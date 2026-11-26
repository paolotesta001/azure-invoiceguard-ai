"""PostgreSQL implementation of ``Repository`` (SQLAlchemy 2).

Uniqueness is enforced by the database, so duplicate detection holds under concurrency:
two workers inserting the same (supplier_id, invoice_number) cannot both succeed.
"""

from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from invoiceguard.db import tables as t
from invoiceguard.domain.enums import InvoiceStatus
from invoiceguard.domain.models import (
    Anomaly,
    ApprovalDecision,
    AuditEvent,
    Contract,
    ContractPriceItem,
    ExtractedInvoice,
    ExtractedInvoiceLine,
    GoodsReceipt,
    GoodsReceiptLine,
    Invoice,
    InvoiceSubmission,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierEmailDraft,
    ValidationRun,
)
from invoiceguard.persistence.repository import (
    DuplicateInvoiceError,
    DuplicateSubmissionError,
    NotFoundError,
)


def _aware(value: datetime) -> datetime:
    """Some drivers (e.g. SQLite) return naive datetimes; values are always stored as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _aware_opt(value: datetime | None) -> datetime | None:
    return _aware(value) if value is not None else None


class SqlRepository:
    """Implements ``Repository`` on top of SQLAlchemy sessions (one transaction per call)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str) -> "SqlRepository":
        """Create a repository from a SQLAlchemy URL."""
        return cls(create_engine(url, pool_pre_ping=True))

    @contextmanager
    def _tx(self) -> Iterator[Session]:
        with self._sessions.begin() as session:
            yield session

    # master data ---------------------------------------------------------------------------
    def add_supplier(self, supplier: Supplier) -> None:
        with self._tx() as s:
            s.add(t.SupplierRow(**supplier.model_dump(mode="python")))

    @staticmethod
    def _supplier(row: t.SupplierRow) -> Supplier:
        return Supplier.model_validate(
            {c.key: getattr(row, c.key) for c in t.SupplierRow.__table__.columns}
        )

    def get_supplier(self, supplier_id: str) -> Supplier | None:
        with self._tx() as s:
            row = s.get(t.SupplierRow, supplier_id)
            return self._supplier(row) if row else None

    def find_supplier_by_vat(self, vat_id: str) -> Supplier | None:
        with self._tx() as s:
            row = s.scalars(select(t.SupplierRow).where(t.SupplierRow.vat_id == vat_id)).first()
            return self._supplier(row) if row else None

    def list_suppliers(self) -> list[Supplier]:
        with self._tx() as s:
            rows = s.scalars(select(t.SupplierRow).order_by(t.SupplierRow.id))
            return [self._supplier(r) for r in rows]

    def add_contract(self, contract: Contract) -> None:
        with self._tx() as s:
            s.add(t.ContractRow(**contract.model_dump(mode="python")))

    def list_contracts(self, supplier_id: str) -> list[Contract]:
        with self._tx() as s:
            rows = s.scalars(
                select(t.ContractRow)
                .where(t.ContractRow.supplier_id == supplier_id)
                .order_by(t.ContractRow.version)
            )
            return [
                Contract.model_validate(
                    {c.key: getattr(r, c.key) for c in t.ContractRow.__table__.columns}
                )
                for r in rows
            ]

    def add_price_items(self, items: Sequence[ContractPriceItem]) -> None:
        with self._tx() as s:
            s.add_all(t.ContractPriceItemRow(**i.model_dump(mode="python")) for i in items)

    def list_price_items(self, contract_id: str) -> list[ContractPriceItem]:
        with self._tx() as s:
            rows = s.scalars(
                select(t.ContractPriceItemRow).where(
                    t.ContractPriceItemRow.contract_id == contract_id
                )
            )
            return [
                ContractPriceItem(
                    contract_id=r.contract_id,
                    sku=r.sku,
                    description=r.description,
                    unit_price=r.unit_price,
                    currency=r.currency,
                    unit=r.unit,
                )
                for r in rows
            ]

    def add_purchase_order(self, po: PurchaseOrder) -> None:
        with self._tx() as s:
            s.add(
                t.PurchaseOrderRow(
                    po_number=po.po_number,
                    supplier_id=po.supplier_id,
                    status=po.status.value,
                    lines=[
                        t.PurchaseOrderLineRow(
                            sku=line.sku, quantity=line.quantity, unit_price=line.unit_price
                        )
                        for line in po.lines
                    ],
                )
            )

    def get_purchase_order(self, po_number: str) -> PurchaseOrder | None:
        with self._tx() as s:
            row = s.get(t.PurchaseOrderRow, po_number)
            if row is None:
                return None
            return PurchaseOrder.model_validate({
                "po_number": row.po_number,
                "supplier_id": row.supplier_id,
                "status": row.status,
                "lines": tuple(
                    PurchaseOrderLine(sku=ln.sku, quantity=ln.quantity, unit_price=ln.unit_price)
                    for ln in row.lines
                ),
            })

    def add_goods_receipt(self, receipt: GoodsReceipt) -> None:
        with self._tx() as s:
            s.add(
                t.GoodsReceiptRow(
                    id=receipt.id,
                    po_number=receipt.po_number,
                    received_at=receipt.received_at,
                    lines=[
                        t.GoodsReceiptLineRow(sku=ln.sku, quantity_received=ln.quantity_received)
                        for ln in receipt.lines
                    ],
                )
            )

    def list_goods_receipts(self, po_number: str) -> list[GoodsReceipt]:
        with self._tx() as s:
            rows = s.scalars(
                select(t.GoodsReceiptRow).where(t.GoodsReceiptRow.po_number == po_number)
            )
            return [
                GoodsReceipt(
                    id=r.id,
                    po_number=r.po_number,
                    received_at=r.received_at,
                    lines=tuple(
                        GoodsReceiptLine(sku=ln.sku, quantity_received=ln.quantity_received)
                        for ln in r.lines
                    ),
                )
                for r in rows
            ]

    # submissions -----------------------------------------------------------------------------
    @staticmethod
    def _submission(row: t.SubmissionRow) -> InvoiceSubmission:
        values = {c.key: getattr(row, c.key) for c in t.SubmissionRow.__table__.columns}
        values["uploaded_at"] = _aware(row.uploaded_at)
        return InvoiceSubmission.model_validate(values)

    def add_submission(self, submission: InvoiceSubmission) -> None:
        try:
            with self._tx() as s:
                s.add(t.SubmissionRow(**submission.model_dump(mode="python")))
        except IntegrityError as exc:
            existing = self.find_submission_by_sha(submission.file_sha256)
            if existing is None:
                raise
            raise DuplicateSubmissionError(existing.id) from exc

    def get_submission(self, submission_id: str) -> InvoiceSubmission | None:
        with self._tx() as s:
            row = s.get(t.SubmissionRow, submission_id)
            return self._submission(row) if row else None

    def find_submission_by_sha(self, sha256: str) -> InvoiceSubmission | None:
        with self._tx() as s:
            row = s.scalars(
                select(t.SubmissionRow).where(t.SubmissionRow.file_sha256 == sha256)
            ).first()
            return self._submission(row) if row else None

    def update_submission(self, submission: InvoiceSubmission) -> None:
        with self._tx() as s:
            row = s.get(t.SubmissionRow, submission.id)
            if row is None:
                raise NotFoundError(submission.id)
            row.status = submission.status.value
            row.invoice_id = submission.invoice_id
            row.duplicate_of_invoice_id = submission.duplicate_of_invoice_id
            row.failure_reason = submission.failure_reason
            row.retry_count = submission.retry_count

    def list_submissions(self) -> list[InvoiceSubmission]:
        with self._tx() as s:
            rows = s.scalars(select(t.SubmissionRow).order_by(t.SubmissionRow.uploaded_at.desc()))
            return [self._submission(r) for r in rows]

    # invoices ------------------------------------------------------------------------------
    @staticmethod
    def _invoice(row: t.InvoiceRow) -> Invoice:
        data = ExtractedInvoice.model_validate({
            "source_type": row.source_type,
            "supplier_vat_id": row.supplier_vat_id,
            "supplier_name": row.supplier_name,
            "invoice_number": row.invoice_number,
            "invoice_date": row.invoice_date,
            "due_date": row.due_date,
            "currency": row.currency,
            "subtotal": row.subtotal,
            "vat_amount": row.vat_amount,
            "total": row.total,
            "iban": row.iban,
            "po_number": row.po_number,
            "lines": tuple(
                ExtractedInvoiceLine(
                    line_no=ln.line_no,
                    sku=ln.sku,
                    description=ln.description,
                    quantity=ln.quantity,
                    unit_price=ln.unit_price,
                    vat_rate=ln.vat_rate,
                    line_total=ln.line_total,
                )
                for ln in row.lines
            ),
            "field_confidence": dict(row.field_confidence),
        })
        return Invoice.model_validate({
            "id": row.id,
            "submission_id": row.submission_id,
            "supplier_id": row.supplier_id,
            "status": row.status,
            "data": data,
            "needs_review_fields": tuple(row.needs_review_fields),
            "created_at": _aware(row.created_at),
            "status_changed_at": _aware(row.status_changed_at),
            "reminder_sent_at": _aware_opt(row.reminder_sent_at),
        })

    def _find_invoice_id(self, supplier_id: str, invoice_number: str) -> str | None:
        with self._tx() as s:
            return s.scalars(
                select(t.InvoiceRow.id).where(
                    t.InvoiceRow.supplier_id == supplier_id,
                    t.InvoiceRow.invoice_number == invoice_number,
                )
            ).first()

    def add_invoice(self, invoice: Invoice) -> None:
        d = invoice.data
        row = t.InvoiceRow(
            id=invoice.id,
            submission_id=invoice.submission_id,
            supplier_id=invoice.supplier_id,
            status=invoice.status.value,
            source_type=d.source_type.value,
            supplier_vat_id=d.supplier_vat_id,
            supplier_name=d.supplier_name,
            invoice_number=d.invoice_number,
            invoice_date=d.invoice_date,
            due_date=d.due_date,
            currency=d.currency,
            subtotal=d.subtotal,
            vat_amount=d.vat_amount,
            total=d.total,
            iban=d.iban,
            po_number=d.po_number,
            field_confidence=dict(d.field_confidence),
            needs_review_fields=list(invoice.needs_review_fields),
            created_at=invoice.created_at,
            status_changed_at=invoice.status_changed_at,
            reminder_sent_at=invoice.reminder_sent_at,
            lines=[
                t.InvoiceLineRow(
                    line_no=ln.line_no,
                    sku=ln.sku,
                    description=ln.description,
                    quantity=ln.quantity,
                    unit_price=ln.unit_price,
                    vat_rate=ln.vat_rate,
                    line_total=ln.line_total,
                )
                for ln in d.lines
            ],
        )
        try:
            with self._tx() as s:
                s.add(row)
        except IntegrityError as exc:
            existing = self._find_invoice_id(invoice.supplier_id, d.invoice_number)
            if existing is None:
                raise
            raise DuplicateInvoiceError(existing) from exc

    def get_invoice(self, invoice_id: str) -> Invoice | None:
        with self._tx() as s:
            row = s.get(t.InvoiceRow, invoice_id)
            return self._invoice(row) if row else None

    def update_invoice(self, invoice: Invoice) -> None:
        with self._tx() as s:
            row = s.get(t.InvoiceRow, invoice.id)
            if row is None:
                raise NotFoundError(invoice.id)
            row.status = invoice.status.value
            row.needs_review_fields = list(invoice.needs_review_fields)
            row.status_changed_at = invoice.status_changed_at
            row.reminder_sent_at = invoice.reminder_sent_at

    def list_invoices(self, statuses: Collection[InvoiceStatus] | None = None) -> list[Invoice]:
        with self._tx() as s:
            query = select(t.InvoiceRow).order_by(t.InvoiceRow.created_at.desc())
            if statuses is not None:
                query = query.where(t.InvoiceRow.status.in_([st.value for st in statuses]))
            return [self._invoice(r) for r in s.scalars(query)]

    # validation results --------------------------------------------------------------------
    def add_anomalies(self, anomalies: Sequence[Anomaly]) -> None:
        with self._tx() as s:
            s.add_all(
                t.AnomalyRow(
                    id=a.id,
                    submission_id=a.submission_id,
                    invoice_id=a.invoice_id,
                    type=a.type.value,
                    severity=a.severity.value,
                    message=a.message,
                    monetary_impact=a.monetary_impact,
                    evidence=dict(a.evidence),
                    explanation=a.explanation,
                    detected_by=a.detected_by.value,
                )
                for a in anomalies
            )

    def list_anomalies(self, submission_id: str) -> list[Anomaly]:
        with self._tx() as s:
            rows = s.scalars(
                select(t.AnomalyRow).where(t.AnomalyRow.submission_id == submission_id)
            )
            return [
                Anomaly.model_validate(
                    {c.key: getattr(r, c.key) for c in t.AnomalyRow.__table__.columns}
                )
                for r in rows
            ]

    def save_run(self, run: ValidationRun) -> None:
        with self._tx() as s:
            s.merge(t.ValidationRunRow(**run.model_dump(mode="python")))

    def get_run(self, run_id: str) -> ValidationRun | None:
        with self._tx() as s:
            r = s.get(t.ValidationRunRow, run_id)
            if r is None:
                return None
            values = {c.key: getattr(r, c.key) for c in t.ValidationRunRow.__table__.columns}
            values["started_at"] = _aware(r.started_at)
            values["finished_at"] = _aware_opt(r.finished_at)
            return ValidationRun.model_validate(values)

    def save_email_draft(self, draft: SupplierEmailDraft) -> None:
        with self._tx() as s:
            row = s.scalars(
                select(t.SupplierEmailDraftRow).where(
                    t.SupplierEmailDraftRow.invoice_id == draft.invoice_id
                )
            ).first()
            if row is None:
                s.add(t.SupplierEmailDraftRow(**draft.model_dump(mode="python")))
                return
            row.subject = draft.subject
            row.body = draft.body
            row.generated_by = draft.generated_by
            row.updated_by = draft.updated_by
            row.updated_at = draft.updated_at

    def get_email_draft(self, invoice_id: str) -> SupplierEmailDraft | None:
        with self._tx() as s:
            row = s.scalars(
                select(t.SupplierEmailDraftRow).where(
                    t.SupplierEmailDraftRow.invoice_id == invoice_id
                )
            ).first()
            if row is None:
                return None
            values = {
                c.key: getattr(row, c.key) for c in t.SupplierEmailDraftRow.__table__.columns
            }
            values["updated_at"] = _aware(row.updated_at)
            return SupplierEmailDraft.model_validate(values)

    # decisions and audit -------------------------------------------------------------------
    def add_decision(self, decision: ApprovalDecision) -> None:
        with self._tx() as s:
            s.add(t.ApprovalDecisionRow(**decision.model_dump(mode="python")))

    def list_decisions(self, invoice_id: str) -> list[ApprovalDecision]:
        with self._tx() as s:
            rows = s.scalars(
                select(t.ApprovalDecisionRow)
                .where(t.ApprovalDecisionRow.invoice_id == invoice_id)
                .order_by(t.ApprovalDecisionRow.decided_at)
            )
            result = []
            for r in rows:
                values = {
                    c.key: getattr(r, c.key) for c in t.ApprovalDecisionRow.__table__.columns
                }
                values["decided_at"] = _aware(r.decided_at)
                result.append(ApprovalDecision.model_validate(values))
            return result

    def append_audit(self, event: AuditEvent) -> None:
        with self._tx() as s:
            s.add(
                t.AuditEventRow(
                    **event.model_dump(mode="json", exclude={"timestamp"}),
                    timestamp=event.timestamp,
                )
            )

    def list_audit(
        self, submission_id: str | None = None, invoice_id: str | None = None
    ) -> list[AuditEvent]:
        with self._tx() as s:
            query = select(t.AuditEventRow).order_by(t.AuditEventRow.timestamp)
            if submission_id is not None:
                query = query.where(t.AuditEventRow.submission_id == submission_id)
            if invoice_id is not None:
                query = query.where(t.AuditEventRow.invoice_id == invoice_id)
            return [
                AuditEvent(
                    id=r.id,
                    timestamp=_aware(r.timestamp),
                    actor=r.actor,
                    event_type=r.event_type,
                    submission_id=r.submission_id,
                    invoice_id=r.invoice_id,
                    payload=dict(r.payload),
                )
                for r in s.scalars(query)
            ]

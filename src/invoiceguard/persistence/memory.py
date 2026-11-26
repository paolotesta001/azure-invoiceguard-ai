"""Thread-safe in-memory repository. Mirrors the SQL uniqueness rules exactly."""

import threading
from collections.abc import Collection, Sequence

from invoiceguard.domain.enums import InvoiceStatus
from invoiceguard.domain.models import (
    Anomaly,
    ApprovalDecision,
    AuditEvent,
    Contract,
    ContractPriceItem,
    GoodsReceipt,
    Invoice,
    InvoiceSubmission,
    PurchaseOrder,
    Supplier,
    SupplierEmailDraft,
    ValidationRun,
)
from invoiceguard.persistence.repository import (
    DuplicateInvoiceError,
    DuplicateSubmissionError,
    NotFoundError,
)


class InMemoryRepository:
    """Implements ``Repository`` with dictionaries guarded by a lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._suppliers: dict[str, Supplier] = {}
        self._contracts: dict[str, Contract] = {}
        self._price_items: dict[str, list[ContractPriceItem]] = {}
        self._pos: dict[str, PurchaseOrder] = {}
        self._receipts: dict[str, list[GoodsReceipt]] = {}
        self._submissions: dict[str, InvoiceSubmission] = {}
        self._sha_index: dict[str, str] = {}
        self._invoices: dict[str, Invoice] = {}
        self._invoice_key_index: dict[tuple[str, str], str] = {}
        self._anomalies: list[Anomaly] = []
        self._runs: dict[str, ValidationRun] = {}
        self._drafts: dict[str, SupplierEmailDraft] = {}
        self._decisions: list[ApprovalDecision] = []
        self._audit: list[AuditEvent] = []

    # master data ---------------------------------------------------------------------------
    def add_supplier(self, supplier: Supplier) -> None:
        with self._lock:
            self._suppliers[supplier.id] = supplier

    def get_supplier(self, supplier_id: str) -> Supplier | None:
        with self._lock:
            return self._suppliers.get(supplier_id)

    def find_supplier_by_vat(self, vat_id: str) -> Supplier | None:
        with self._lock:
            return next((s for s in self._suppliers.values() if s.vat_id == vat_id), None)

    def list_suppliers(self) -> list[Supplier]:
        with self._lock:
            return sorted(self._suppliers.values(), key=lambda s: s.id)

    def add_contract(self, contract: Contract) -> None:
        with self._lock:
            self._contracts[contract.id] = contract

    def list_contracts(self, supplier_id: str) -> list[Contract]:
        with self._lock:
            return sorted(
                (c for c in self._contracts.values() if c.supplier_id == supplier_id),
                key=lambda c: c.version,
            )

    def add_price_items(self, items: Sequence[ContractPriceItem]) -> None:
        with self._lock:
            for item in items:
                self._price_items.setdefault(item.contract_id, []).append(item)

    def list_price_items(self, contract_id: str) -> list[ContractPriceItem]:
        with self._lock:
            return list(self._price_items.get(contract_id, []))

    def add_purchase_order(self, po: PurchaseOrder) -> None:
        with self._lock:
            self._pos[po.po_number] = po

    def get_purchase_order(self, po_number: str) -> PurchaseOrder | None:
        with self._lock:
            return self._pos.get(po_number)

    def add_goods_receipt(self, receipt: GoodsReceipt) -> None:
        with self._lock:
            self._receipts.setdefault(receipt.po_number, []).append(receipt)

    def list_goods_receipts(self, po_number: str) -> list[GoodsReceipt]:
        with self._lock:
            return list(self._receipts.get(po_number, []))

    # submissions and invoices --------------------------------------------------------------
    def add_submission(self, submission: InvoiceSubmission) -> None:
        with self._lock:
            existing = self._sha_index.get(submission.file_sha256)
            if existing is not None:
                raise DuplicateSubmissionError(existing)
            self._submissions[submission.id] = submission
            self._sha_index[submission.file_sha256] = submission.id

    def get_submission(self, submission_id: str) -> InvoiceSubmission | None:
        with self._lock:
            return self._submissions.get(submission_id)

    def find_submission_by_sha(self, sha256: str) -> InvoiceSubmission | None:
        with self._lock:
            sub_id = self._sha_index.get(sha256)
            return self._submissions.get(sub_id) if sub_id else None

    def update_submission(self, submission: InvoiceSubmission) -> None:
        with self._lock:
            if submission.id not in self._submissions:
                raise NotFoundError(submission.id)
            self._submissions[submission.id] = submission

    def list_submissions(self) -> list[InvoiceSubmission]:
        with self._lock:
            return sorted(self._submissions.values(), key=lambda s: s.uploaded_at, reverse=True)

    def add_invoice(self, invoice: Invoice) -> None:
        key = (invoice.supplier_id, invoice.data.invoice_number)
        with self._lock:
            existing = self._invoice_key_index.get(key)
            if existing is not None:
                raise DuplicateInvoiceError(existing)
            self._invoices[invoice.id] = invoice
            self._invoice_key_index[key] = invoice.id

    def get_invoice(self, invoice_id: str) -> Invoice | None:
        with self._lock:
            return self._invoices.get(invoice_id)

    def update_invoice(self, invoice: Invoice) -> None:
        with self._lock:
            if invoice.id not in self._invoices:
                raise NotFoundError(invoice.id)
            self._invoices[invoice.id] = invoice

    def list_invoices(self, statuses: Collection[InvoiceStatus] | None = None) -> list[Invoice]:
        with self._lock:
            items = [i for i in self._invoices.values() if statuses is None or i.status in statuses]
            return sorted(items, key=lambda i: i.created_at, reverse=True)

    # validation results --------------------------------------------------------------------
    def add_anomalies(self, anomalies: Sequence[Anomaly]) -> None:
        with self._lock:
            self._anomalies.extend(anomalies)

    def list_anomalies(self, submission_id: str) -> list[Anomaly]:
        with self._lock:
            return [a for a in self._anomalies if a.submission_id == submission_id]

    def save_run(self, run: ValidationRun) -> None:
        with self._lock:
            self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> ValidationRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def save_email_draft(self, draft: SupplierEmailDraft) -> None:
        with self._lock:
            self._drafts[draft.invoice_id] = draft

    def get_email_draft(self, invoice_id: str) -> SupplierEmailDraft | None:
        with self._lock:
            return self._drafts.get(invoice_id)

    # decisions and audit -------------------------------------------------------------------
    def add_decision(self, decision: ApprovalDecision) -> None:
        with self._lock:
            self._decisions.append(decision)

    def list_decisions(self, invoice_id: str) -> list[ApprovalDecision]:
        with self._lock:
            return [d for d in self._decisions if d.invoice_id == invoice_id]

    def append_audit(self, event: AuditEvent) -> None:
        with self._lock:
            self._audit.append(event)

    def list_audit(
        self, submission_id: str | None = None, invoice_id: str | None = None
    ) -> list[AuditEvent]:
        with self._lock:
            return [
                e
                for e in self._audit
                if (submission_id is None or e.submission_id == submission_id)
                and (invoice_id is None or e.invoice_id == invoice_id)
            ]

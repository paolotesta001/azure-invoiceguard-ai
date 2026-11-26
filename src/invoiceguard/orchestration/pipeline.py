"""Validation pipeline: ingest → extract → persist (duplicate-safe) → checks → LLM
explanations → policy. Deterministic results are final; the LLM only adds explanations."""

import hashlib
import logging
import time
from collections.abc import Sequence
from decimal import Decimal

from invoiceguard.adapters.file_store import FileStore
from invoiceguard.adapters.payments import PaymentGateway, PaymentGatewayError
from invoiceguard.adapters.retry import TransientError, call_with_retry
from invoiceguard.agent.explainer import ExplanationService
from invoiceguard.checks.base import CheckContext, Finding
from invoiceguard.checks.contract import select_contract
from invoiceguard.checks.runner import run_checks
from invoiceguard.config import ValidationSettings
from invoiceguard.domain.clock import Clock, new_id, utc_now
from invoiceguard.domain.enums import (
    AnomalyType,
    InvoiceStatus,
    Mode,
    RunStatus,
    Severity,
    SubmissionStatus,
)
from invoiceguard.domain.models import (
    Anomaly,
    ExtractedInvoice,
    Invoice,
    InvoiceSubmission,
    Supplier,
    SupplierEmailDraft,
    ValidationRun,
)
from invoiceguard.ingestion.errors import ExtractionError
from invoiceguard.ingestion.extract import InvoiceExtractor
from invoiceguard.persistence.audit import AuditLog
from invoiceguard.persistence.repository import (
    DuplicateInvoiceError,
    DuplicateSubmissionError,
    NotFoundError,
    Repository,
)
from invoiceguard.policy.auto_approve import evaluate_auto_approval

logger = logging.getLogger(__name__)
SYSTEM = "system"
POLICY_ACTOR = "policy:auto-approve"


def file_sha256(content: bytes) -> str:
    """Hex SHA-256 of file bytes; also used as the idempotent run id."""
    return hashlib.sha256(content).hexdigest()


class ValidationPipeline:
    """Processing of one submission. Safe to call concurrently."""

    def __init__(
        self,
        repo: Repository,
        file_store: FileStore,
        payments: PaymentGateway,
        settings: ValidationSettings,
        mode: Mode,
        clock: Clock = utc_now,
        extractor: InvoiceExtractor | None = None,
        explainer: ExplanationService | None = None,
    ) -> None:
        self._repo = repo
        self._files = file_store
        self._payments = payments
        self._settings = settings
        self._mode = mode
        self._clock = clock
        self._extractor = extractor or InvoiceExtractor()
        self._explainer = explainer
        self._audit = AuditLog(repo, clock)

    # ---------------------------------------------------------------------------------------
    def ingest(self, content: bytes, filename: str,
               uploaded_by: str) -> tuple[InvoiceSubmission, bool]:
        """Store the file and create a submission. Returns ``(submission, created)``.
        Re-uploading identical bytes returns the existing submission (idempotency)."""
        if not uploaded_by.strip():
            raise ValueError("uploaded_by is required")
        sha = file_sha256(content)
        existing = self._repo.find_submission_by_sha(sha)
        if existing is not None:
            self._audit.record(uploaded_by, "SUBMISSION_REPLAYED", submission_id=existing.id,
                               payload={"file_sha256": sha})
            return existing, False

        submission = InvoiceSubmission(
            id=new_id(),
            file_sha256=sha,
            filename=filename,
            file_uri=self._files.save(sha, filename, content),
            uploaded_by=uploaded_by,
            uploaded_at=self._clock(),
            status=SubmissionStatus.RECEIVED,
        )
        try:
            self._repo.add_submission(submission)
        except DuplicateSubmissionError as exc:  # concurrent upload of the same bytes
            winner = self._repo.get_submission(exc.existing_submission_id)
            if winner is None:  # pragma: no cover - cannot happen with a consistent store
                raise
            return winner, False
        self._audit.record(uploaded_by, "SUBMISSION_RECEIVED", submission_id=submission.id,
                           payload={"filename": filename, "file_sha256": sha})
        return submission, True

    # ---------------------------------------------------------------------------------------
    def process(self, submission_id: str) -> InvoiceSubmission:
        """Validate a received submission end to end and return its final state."""
        submission = self._repo.get_submission(submission_id)
        if submission is None:
            raise NotFoundError(submission_id)
        if submission.status is not SubmissionStatus.RECEIVED:
            return submission  # already processed: idempotent

        t0 = time.perf_counter()
        run = ValidationRun(run_id=submission.file_sha256, submission_id=submission.id,
                            status=RunStatus.RUNNING, mode=self._mode, started_at=self._clock())
        self._repo.save_run(run)
        submission = self._set_submission(submission, status=SubmissionStatus.PROCESSING)

        try:
            extracted, source = self._extractor.extract(self._files.load(submission.file_uri))
        except ExtractionError as exc:
            return self._fail(submission, run, t0, f"Extraction failed: {exc}")
        self._audit.record(SYSTEM, "INVOICE_EXTRACTED", submission_id=submission.id, payload={
            "extraction_source": source,
            "source_type": extracted.source_type.value,
            "invoice_number": extracted.invoice_number,
            "supplier_vat_id": extracted.supplier_vat_id,
            "total": str(extracted.total),
            "currency": extracted.currency,
            "iban": extracted.iban,
            "line_count": len(extracted.lines),
            "low_confidence_fields": list(
                extracted.low_confidence_fields(self._settings.confidence_threshold)),
        })

        supplier = self._repo.find_supplier_by_vat(extracted.supplier_vat_id)
        if supplier is None:
            return self._fail(submission, run, t0,
                              f"Unknown supplier VAT id {extracted.supplier_vat_id}: "
                              "add the supplier to master data, then re-upload.")

        now = self._clock()
        invoice = Invoice(
            id=new_id(),
            submission_id=submission.id,
            supplier_id=supplier.id,
            status=InvoiceStatus.PROCESSING,
            data=extracted,
            needs_review_fields=extracted.low_confidence_fields(self._settings.confidence_threshold),
            created_at=now,
            status_changed_at=now,
        )
        try:
            self._repo.add_invoice(invoice)
        except DuplicateInvoiceError as exc:
            return self._reject_duplicate(submission, run, t0, extracted, supplier.id,
                                          exc.existing_invoice_id)
        submission = self._set_submission(submission, invoice_id=invoice.id)

        contract = select_contract(self._repo.list_contracts(supplier.id), extracted.invoice_date)
        price_items = (
            {p.sku: p for p in self._repo.list_price_items(contract.id)} if contract else {}
        )
        ctx = CheckContext(invoice=extracted, supplier=supplier, contract=contract,
                           price_items=price_items, settings=self._settings)
        anomalies = [self._to_anomaly(f, submission.id, invoice.id) for f in run_checks(ctx)]
        self._audit.record(SYSTEM, "CHECKS_COMPLETED", submission_id=submission.id,
                           invoice_id=invoice.id, payload={
                               "contract_id": contract.id if contract else None,
                               "contract_version": contract.version if contract else None,
                               "anomalies": [a.type.value for a in anomalies],
                           })
        anomalies, run = self._explain(invoice, supplier, anomalies, run)
        self._repo.add_anomalies(anomalies)

        policy = evaluate_auto_approval(extracted, supplier, anomalies,
                                        invoice.needs_review_fields, self._settings)
        self._audit.record(SYSTEM, "POLICY_EVALUATED", submission_id=submission.id,
                           invoice_id=invoice.id, payload={
                               "auto_approve": policy.auto_approve,
                               "reasons": list(policy.reasons),
                           })

        if policy.auto_approve:
            status = self._auto_approve(invoice)
        else:
            status = InvoiceStatus.FLAGGED if anomalies else InvoiceStatus.PENDING_REVIEW
        self._repo.update_invoice(invoice.model_copy(update={"status": status,
                                                             "status_changed_at": self._clock()}))
        submission = self._set_submission(submission, status=SubmissionStatus.ACCEPTED)
        self._finish_run(run, t0, RunStatus.SUCCEEDED)
        self._audit.record(SYSTEM, "RUN_COMPLETED", submission_id=submission.id,
                           invoice_id=invoice.id, payload={"invoice_status": status.value})
        return submission

    # helpers -----------------------------------------------------------------------------
    def _explain(self, invoice: Invoice, supplier: Supplier, anomalies: Sequence[Anomaly],
                 run: ValidationRun) -> tuple[list[Anomaly], ValidationRun]:
        """Attach LLM explanations and store a supplier email draft (if any)."""
        if self._explainer is None or not anomalies:
            return list(anomalies), run
        outcome = self._explainer.explain(invoice.data, supplier.name, anomalies)
        explained = [a.model_copy(update={"explanation": outcome.explanations.get(a.id)})
                     for a in anomalies]
        if outcome.email is not None:
            self._repo.save_email_draft(SupplierEmailDraft(
                id=new_id(), invoice_id=invoice.id, subject=outcome.email.subject,
                body=outcome.email.body, generated_by=f"llm:{outcome.model}",
                updated_at=self._clock()))
        cost = self._settings.llm_pricing.cost(outcome.usage.prompt_tokens,
                                               outcome.usage.completion_tokens)
        run = run.model_copy(update={
            "model_deployment": outcome.model,
            "prompt_tokens": run.prompt_tokens + outcome.usage.prompt_tokens,
            "completion_tokens": run.completion_tokens + outcome.usage.completion_tokens,
            "estimated_cost": run.estimated_cost + cost.quantize(Decimal("0.000001")),
        })
        self._audit.record(f"llm:{outcome.model}", "LLM_EXPLANATIONS", invoice_id=invoice.id,
                           submission_id=invoice.submission_id, payload={
                               "model": outcome.model,
                               "attempts": outcome.attempts,
                               "fallback": outcome.fallback,
                               "problems": outcome.problems,
                               "prompt_tokens": outcome.usage.prompt_tokens,
                               "completion_tokens": outcome.usage.completion_tokens,
                               "email_drafted": outcome.email is not None,
                           })
        return explained, run

    def _auto_approve(self, invoice: Invoice) -> InvoiceStatus:
        """Fail closed: if the ERP call fails, route the invoice to a human."""
        try:
            reference = call_with_retry(
                lambda: self._payments.approve_payment(invoice.id, POLICY_ACTOR)
            )
        except (TransientError, PaymentGatewayError) as exc:
            logger.warning("auto-approval call failed for %s: %s", invoice.id, exc)
            self._audit.record(SYSTEM, "PAYMENT_APPROVAL_FAILED",
                               submission_id=invoice.submission_id, invoice_id=invoice.id,
                               payload={"error": str(exc)})
            return InvoiceStatus.PENDING_REVIEW
        self._audit.record(POLICY_ACTOR, "PAYMENT_APPROVED", submission_id=invoice.submission_id,
                           invoice_id=invoice.id, payload={"payment_reference": reference})
        return InvoiceStatus.AUTO_APPROVED

    def _reject_duplicate(self, submission: InvoiceSubmission, run: ValidationRun, t0: float,
                          extracted: ExtractedInvoice, supplier_id: str,
                          original_id: str) -> InvoiceSubmission:
        original = self._repo.get_invoice(original_id)
        anomaly = Anomaly(
            id=new_id(),
            submission_id=submission.id,
            invoice_id=None,
            type=AnomalyType.DUPLICATE,
            severity=Severity.CRITICAL,
            message=(f"Invoice {extracted.invoice_number} from this supplier was already received "
                     "and was not processed again."),
            monetary_impact=extracted.total,
            evidence={
                "invoice_number": extracted.invoice_number,
                "supplier_id": supplier_id,
                "duplicate_of_invoice_id": original_id,
                "original_submission_id": original.submission_id if original else None,
            },
        )
        self._repo.add_anomalies([anomaly])
        submission = self._set_submission(submission, status=SubmissionStatus.DUPLICATE_REJECTED,
                                          duplicate_of_invoice_id=original_id)
        self._finish_run(run, t0, RunStatus.SUCCEEDED)
        self._audit.record(SYSTEM, "DUPLICATE_REJECTED", submission_id=submission.id,
                           invoice_id=original_id,
                           payload={"invoice_number": extracted.invoice_number})
        return submission

    def _fail(self, submission: InvoiceSubmission, run: ValidationRun, t0: float,
              reason: str) -> InvoiceSubmission:
        submission = self._set_submission(submission, status=SubmissionStatus.FAILED,
                                          failure_reason=reason)
        self._finish_run(run, t0, RunStatus.FAILED)
        self._audit.record(SYSTEM, "SUBMISSION_FAILED", submission_id=submission.id,
                           payload={"reason": reason})
        return submission

    def _set_submission(self, submission: InvoiceSubmission,
                        **changes: object) -> InvoiceSubmission:
        updated = submission.model_copy(update=changes)
        self._repo.update_submission(updated)
        return updated

    def _finish_run(self, run: ValidationRun, t0: float, status: RunStatus) -> None:
        self._repo.save_run(run.model_copy(update={
            "status": status,
            "finished_at": self._clock(),
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }))

    @staticmethod
    def _to_anomaly(finding: Finding, submission_id: str, invoice_id: str) -> Anomaly:
        return Anomaly(
            id=new_id(),
            submission_id=submission_id,
            invoice_id=invoice_id,
            type=finding.type,
            severity=finding.severity,
            message=finding.message,
            monetary_impact=finding.monetary_impact,
            evidence=dict(finding.evidence),
        )

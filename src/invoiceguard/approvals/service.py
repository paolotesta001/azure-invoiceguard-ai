"""Human approval: decisions, segregation of duties, reminders, email-draft edits.
All rules are enforced in the backend, not only in the UI."""

from datetime import timedelta

from invoiceguard.adapters.payments import PaymentGateway
from invoiceguard.adapters.retry import call_with_retry
from invoiceguard.config import ValidationSettings
from invoiceguard.domain.clock import Clock, new_id, utc_now
from invoiceguard.domain.enums import DecisionType, InvoiceStatus
from invoiceguard.domain.models import ApprovalDecision, SupplierEmailDraft
from invoiceguard.persistence.audit import AuditLog
from invoiceguard.persistence.repository import Repository

REVIEWABLE_STATUSES = frozenset(
    {InvoiceStatus.FLAGGED, InvoiceStatus.PENDING_REVIEW, InvoiceStatus.CLARIFICATION_REQUESTED}
)
AWAITING_DECISION = frozenset({InvoiceStatus.FLAGGED, InvoiceStatus.PENDING_REVIEW})
_RESULT_STATUS = {
    DecisionType.APPROVE: InvoiceStatus.APPROVED,
    DecisionType.REJECT: InvoiceStatus.REJECTED,
    DecisionType.REQUEST_CLARIFICATION: InvoiceStatus.CLARIFICATION_REQUESTED,
}


class ApprovalError(Exception):
    """Base class for decision errors shown to the reviewer."""


class InvoiceNotFoundError(ApprovalError):
    """The invoice does not exist."""


class InvalidInvoiceStateError(ApprovalError):
    """The invoice is not awaiting a decision."""


class SegregationOfDutiesError(ApprovalError):
    """The uploader tried to decide on their own invoice."""


class CommentRequiredError(ApprovalError):
    """A comment is mandatory for this decision."""


class ApprovalService:
    """Records human decisions and triggers payment approval only after an approve decision."""

    def __init__(self, repo: Repository, payments: PaymentGateway, settings: ValidationSettings,
                 clock: Clock = utc_now) -> None:
        self._repo = repo
        self._payments = payments
        self._settings = settings
        self._clock = clock
        self._audit = AuditLog(repo, clock)

    def decide(self, invoice_id: str, reviewer_id: str, decision: DecisionType,
               comment: str | None = None) -> ApprovalDecision:
        """Validate and record a decision. Raises an ``ApprovalError`` subclass if not allowed."""
        reviewer_id = reviewer_id.strip()
        if not reviewer_id:
            raise ApprovalError("reviewer_id is required")
        invoice = self._repo.get_invoice(invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError(f"invoice {invoice_id} not found")
        if invoice.status not in REVIEWABLE_STATUSES:
            raise InvalidInvoiceStateError(
                f"invoice is '{invoice.status.value}' and cannot be decided"
            )
        submission = self._repo.get_submission(invoice.submission_id)
        if submission is None or submission.uploaded_by == reviewer_id:
            self._audit.record(reviewer_id, "DECISION_BLOCKED_SOD", invoice_id=invoice.id,
                               submission_id=invoice.submission_id,
                               payload={"decision": decision.value})
            raise SegregationOfDutiesError("the uploader of an invoice cannot decide on it")
        clean_comment = (comment or "").strip() or None
        if decision is not DecisionType.APPROVE and clean_comment is None:
            raise CommentRequiredError(f"a comment is required to {decision.value.replace('_', ' ')}")

        payment_reference = None
        if decision is DecisionType.APPROVE:
            payment_reference = call_with_retry(
                lambda: self._payments.approve_payment(invoice.id, reviewer_id)
            )

        now = self._clock()
        record = ApprovalDecision(id=new_id(), invoice_id=invoice.id, decision=decision,
                                  reviewer_id=reviewer_id, comment=clean_comment,
                                  payment_reference=payment_reference, decided_at=now)
        self._repo.add_decision(record)
        self._repo.update_invoice(invoice.model_copy(update={
            "status": _RESULT_STATUS[decision], "status_changed_at": now,
        }))
        self._audit.record(reviewer_id, "HUMAN_DECISION", invoice_id=invoice.id,
                           submission_id=invoice.submission_id, payload={
                               "decision": decision.value,
                               "comment": clean_comment,
                               "payment_reference": payment_reference,
                           })
        return record

    def update_email_draft(self, invoice_id: str, user_id: str, subject: str,
                           body: str) -> SupplierEmailDraft:
        """Save a reviewer's edit of the supplier email draft (it is never sent)."""
        invoice = self._repo.get_invoice(invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError(f"invoice {invoice_id} not found")
        if not subject.strip() or not body.strip():
            raise ApprovalError("subject and body are required")
        existing = self._repo.get_email_draft(invoice_id)
        draft = SupplierEmailDraft(
            id=existing.id if existing else new_id(), invoice_id=invoice_id,
            subject=subject.strip(), body=body.strip(),
            generated_by=existing.generated_by if existing else f"user:{user_id}",
            updated_by=user_id, updated_at=self._clock())
        self._repo.save_email_draft(draft)
        self._audit.record(user_id, "EMAIL_DRAFT_EDITED", invoice_id=invoice_id,
                           submission_id=invoice.submission_id,
                           payload={"subject": draft.subject})
        return draft

    def send_reminders(self) -> list[str]:
        """Escalate invoices waiting longer than the timeout (once per invoice)."""
        now = self._clock()
        timeout = timedelta(hours=self._settings.approval_timeout_hours)
        reminded: list[str] = []
        for invoice in self._repo.list_invoices(AWAITING_DECISION):
            if invoice.reminder_sent_at is None and now - invoice.status_changed_at >= timeout:
                self._repo.update_invoice(invoice.model_copy(update={"reminder_sent_at": now}))
                self._audit.record("system", "APPROVAL_REMINDER", invoice_id=invoice.id,
                                   submission_id=invoice.submission_id,
                                   payload={"waiting_hours": int((now - invoice.status_changed_at)
                                                                 .total_seconds() // 3600)})
                reminded.append(invoice.id)
        return reminded

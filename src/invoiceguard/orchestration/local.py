"""Synchronous orchestrator with state persisted in the repository (survives restarts)."""

import logging

from invoiceguard.approvals.service import ApprovalService
from invoiceguard.domain.enums import DecisionType, SubmissionStatus
from invoiceguard.domain.models import ApprovalDecision, InvoiceSubmission, SupplierEmailDraft
from invoiceguard.orchestration.pipeline import ValidationPipeline
from invoiceguard.persistence.repository import Repository

logger = logging.getLogger(__name__)


class LocalOrchestrator:
    """Implements ``Orchestrator`` without any Azure runtime."""

    def __init__(self, repo: Repository, pipeline: ValidationPipeline,
                 approvals: ApprovalService) -> None:
        self._repo = repo
        self._pipeline = pipeline
        self._approvals = approvals

    def submit(self, content: bytes, filename: str, uploaded_by: str) -> InvoiceSubmission:
        """Ingest and process a file. Unexpected errors mark the submission as failed
        ("Failed – needs attention") instead of losing it."""
        submission, created = self._pipeline.ingest(content, filename, uploaded_by)
        if not created:
            return submission
        try:
            return self._pipeline.process(submission.id)
        except Exception as exc:
            logger.exception("processing failed for submission %s", submission.id)
            current = self._repo.get_submission(submission.id) or submission
            failed = current.model_copy(update={
                "status": SubmissionStatus.FAILED,
                "failure_reason": f"Unexpected error: {type(exc).__name__}",
                "retry_count": current.retry_count + 1,
            })
            self._repo.update_submission(failed)
            return failed

    def record_decision(self, invoice_id: str, reviewer_id: str, decision: DecisionType,
                        comment: str | None = None) -> ApprovalDecision:
        return self._approvals.decide(invoice_id, reviewer_id, decision, comment)

    def update_email_draft(self, invoice_id: str, user_id: str, subject: str,
                           body: str) -> SupplierEmailDraft:
        return self._approvals.update_email_draft(invoice_id, user_id, subject, body)

    def check_timeouts(self) -> list[str]:
        return self._approvals.send_reminders()

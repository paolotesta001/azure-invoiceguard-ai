"""Orchestrator interface. ``LocalOrchestrator`` runs in-process (mock mode, v1–v2);
a Durable Functions implementation is added in v3 for Azure."""

from typing import Protocol

from invoiceguard.domain.enums import DecisionType
from invoiceguard.domain.models import ApprovalDecision, InvoiceSubmission


class Orchestrator(Protocol):
    def submit(self, content: bytes, filename: str, uploaded_by: str) -> InvoiceSubmission: ...
    def record_decision(self, invoice_id: str, reviewer_id: str, decision: DecisionType,
                        comment: str | None = None) -> ApprovalDecision: ...
    def check_timeouts(self) -> list[str]: ...

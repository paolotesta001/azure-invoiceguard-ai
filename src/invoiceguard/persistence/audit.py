"""Audit logging helper. Payloads are masked before they are stored."""

from collections.abc import Mapping

from pydantic import JsonValue

from invoiceguard.domain.clock import Clock, new_id
from invoiceguard.domain.models import AuditEvent
from invoiceguard.persistence.repository import Repository
from invoiceguard.safety.masking import mask_payload


class AuditLog:
    """Writes append-only ``AuditEvent`` records."""

    def __init__(self, repo: Repository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    def record(
        self,
        actor: str,
        event_type: str,
        *,
        submission_id: str | None = None,
        invoice_id: str | None = None,
        payload: Mapping[str, JsonValue] | None = None,
    ) -> AuditEvent:
        """Store one event and return it."""
        event = AuditEvent(
            id=new_id(),
            timestamp=self._clock(),
            actor=actor,
            event_type=event_type,
            submission_id=submission_id,
            invoice_id=invoice_id,
            payload=mask_payload(payload or {}),
        )
        self._repo.append_audit(event)
        return event

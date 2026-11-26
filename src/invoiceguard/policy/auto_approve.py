"""Auto-approval policy. Coded rules only; the LLM never decides on payments."""

from collections.abc import Sequence
from dataclasses import dataclass

from invoiceguard.config import ValidationSettings
from invoiceguard.domain.enums import SupplierStatus
from invoiceguard.domain.models import Anomaly, ExtractedInvoice, Supplier


@dataclass(frozen=True)
class PolicyResult:
    auto_approve: bool
    reasons: tuple[str, ...]


def evaluate_auto_approval(
    invoice: ExtractedInvoice,
    supplier: Supplier,
    anomalies: Sequence[Anomaly],
    needs_review_fields: Sequence[str],
    settings: ValidationSettings,
) -> PolicyResult:
    """Auto-approve only if there are no anomalies, no low-confidence fields, the total is
    below the threshold for the invoice currency, and the supplier is active.
    Every reason that blocks auto-approval is returned, so reviewers see all of them."""
    reasons: list[str] = []
    if anomalies:
        reasons.append(f"{len(anomalies)} anomal{'y' if len(anomalies) == 1 else 'ies'} detected")
    if needs_review_fields:
        reasons.append(f"low-confidence fields: {', '.join(needs_review_fields)}")
    threshold = settings.auto_approve_threshold.get(invoice.currency)
    if threshold is None:
        reasons.append(f"no auto-approve threshold configured for {invoice.currency}")
    elif invoice.total >= threshold:
        reasons.append(
            f"total {invoice.total} {invoice.currency} is not below the auto-approve "
            f"threshold {threshold} {invoice.currency}"
        )
    if supplier.status is not SupplierStatus.ACTIVE:
        reasons.append(f"supplier status is {supplier.status.value}")
    return PolicyResult(auto_approve=not reasons, reasons=tuple(reasons))

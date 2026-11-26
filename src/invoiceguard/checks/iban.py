"""IBAN: missing, invalid, different from master data, or recently changed (fraud signal)."""

from invoiceguard.checks.base import CheckContext, Finding
from invoiceguard.domain.enums import AnomalyType, Severity
from invoiceguard.domain.iban import is_valid_iban, normalize_iban
from invoiceguard.safety.masking import mask_iban


def check_iban(ctx: CheckContext) -> list[Finding]:
    """Evidence contains masked IBANs only."""
    inv, supplier = ctx.invoice, ctx.supplier
    if not inv.iban:
        return [
            Finding(
                type=AnomalyType.IBAN_MISSING,
                severity=Severity.MEDIUM,
                message="The invoice does not state a bank account (IBAN).",
                evidence={"supplier_id": supplier.id},
            )
        ]

    invoice_iban = normalize_iban(inv.iban)
    if not is_valid_iban(invoice_iban):
        return [
            Finding(
                type=AnomalyType.IBAN_INVALID,
                severity=Severity.CRITICAL,
                message="The IBAN on the invoice fails the ISO 13616 checksum.",
                monetary_impact=inv.total,
                evidence={"invoice_iban": mask_iban(invoice_iban)},
            )
        ]

    findings: list[Finding] = []
    if invoice_iban != normalize_iban(supplier.iban_on_file):
        findings.append(
            Finding(
                type=AnomalyType.IBAN_MISMATCH,
                severity=Severity.CRITICAL,
                message=(
                    f"Invoice IBAN {mask_iban(invoice_iban)} differs from the IBAN on file "
                    f"{mask_iban(supplier.iban_on_file)}. Verify with the supplier through a "
                    "known contact before paying."
                ),
                monetary_impact=inv.total,
                evidence={
                    "invoice_iban": mask_iban(invoice_iban),
                    "iban_on_file": mask_iban(supplier.iban_on_file),
                    "supplier_id": supplier.id,
                },
            )
        )

    changed = supplier.iban_last_changed_at
    if changed is not None:
        days = (inv.invoice_date - changed).days
        if 0 <= days <= ctx.settings.iban_recent_change_days:
            findings.append(
                Finding(
                    type=AnomalyType.IBAN_RECENTLY_CHANGED,
                    severity=Severity.CRITICAL,
                    message=(
                        f"The supplier's bank account was changed {days} day(s) before this "
                        "invoice. Confirm the change independently before paying."
                    ),
                    monetary_impact=inv.total,
                    evidence={
                        "iban_last_changed_at": changed.isoformat(),
                        "invoice_date": inv.invoice_date.isoformat(),
                        "window_days": ctx.settings.iban_recent_change_days,
                    },
                )
            )
    return findings

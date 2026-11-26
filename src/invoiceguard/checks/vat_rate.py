"""VAT_RATE: every VAT rate must be valid for the supplier's country."""

from invoiceguard.checks.base import CheckContext, Finding
from invoiceguard.domain.enums import AnomalyType, Severity


def check_vat_rate(ctx: CheckContext) -> list[Finding]:
    """Flag lines whose VAT rate is not in the configured list for the supplier country."""
    allowed = ctx.settings.vat_rates.get(ctx.supplier.country)
    if allowed is None:
        return []
    findings: list[Finding] = []
    for line in ctx.invoice.lines:
        if line.vat_rate not in allowed:
            findings.append(
                Finding(
                    type=AnomalyType.VAT_RATE,
                    severity=Severity.MEDIUM,
                    message=(
                        f"Line {line.line_no}: VAT rate {line.vat_rate}% is not valid in "
                        f"{ctx.supplier.country.value} (allowed: "
                        f"{', '.join(str(r) for r in allowed)})."
                    ),
                    evidence={
                        "invoice_line": line.line_no,
                        "vat_rate": str(line.vat_rate),
                        "country": ctx.supplier.country.value,
                        "allowed_rates": [str(r) for r in allowed],
                    },
                )
            )
    return findings

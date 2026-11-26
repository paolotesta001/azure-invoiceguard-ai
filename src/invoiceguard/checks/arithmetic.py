"""ARITHMETIC: line totals, subtotal, VAT and total must be internally consistent."""

from collections import defaultdict
from decimal import Decimal

from invoiceguard.checks.base import CheckContext, Finding
from invoiceguard.domain.enums import AnomalyType, Severity
from invoiceguard.domain.money import line_amount, round_money, vat_amount, within_tolerance


def _finding(what: str, expected: Decimal, actual: Decimal, **extra: str | int) -> Finding:
    return Finding(
        type=AnomalyType.ARITHMETIC,
        severity=Severity.HIGH,
        message=f"{what}: expected {expected}, invoice states {actual}.",
        monetary_impact=round_money(actual - expected),
        evidence={"check": what, "expected": str(expected), "actual": str(actual), **extra},
    )


def check_arithmetic(ctx: CheckContext) -> list[Finding]:
    """Recompute every amount and compare with the declared one (tolerance from settings)."""
    inv = ctx.invoice
    tol = ctx.settings.arithmetic_tolerance
    findings: list[Finding] = []

    base_by_rate: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    for line in inv.lines:
        expected_line = line_amount(line.quantity, line.unit_price)
        if not within_tolerance(expected_line, line.line_total, tol):
            findings.append(
                _finding(
                    f"Line {line.line_no} total",
                    expected_line,
                    line.line_total,
                    invoice_line=line.line_no,
                )
            )
        base_by_rate[line.vat_rate] += line.line_total

    expected_subtotal = round_money(sum(base_by_rate.values(), Decimal("0")))
    if not within_tolerance(expected_subtotal, inv.subtotal, tol):
        findings.append(_finding("Subtotal", expected_subtotal, inv.subtotal))

    expected_vat = sum(
        (vat_amount(base, rate) for rate, base in base_by_rate.items()), Decimal("0")
    )
    if not within_tolerance(expected_vat, inv.vat_amount, tol):
        findings.append(_finding("VAT amount", expected_vat, inv.vat_amount))

    expected_total = round_money(inv.subtotal + inv.vat_amount)
    if not within_tolerance(expected_total, inv.total, tol):
        findings.append(_finding("Total", expected_total, inv.total))

    return findings

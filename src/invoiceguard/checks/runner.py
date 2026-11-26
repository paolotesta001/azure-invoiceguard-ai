"""Runs all deterministic checks in a fixed order."""

from collections.abc import Sequence

from invoiceguard.checks.arithmetic import check_arithmetic
from invoiceguard.checks.base import Check, CheckContext, Finding
from invoiceguard.checks.contract import check_contract_validity, check_currency
from invoiceguard.checks.iban import check_iban
from invoiceguard.checks.price import check_price
from invoiceguard.checks.vat_rate import check_vat_rate

DEFAULT_CHECKS: tuple[Check, ...] = (
    check_arithmetic,
    check_vat_rate,
    check_contract_validity,
    check_currency,
    check_price,
    check_iban,
)


def run_checks(ctx: CheckContext, checks: Sequence[Check] = DEFAULT_CHECKS) -> list[Finding]:
    """Run every check and return all findings, most severe first (stable order)."""
    findings = [finding for check in checks for finding in check(ctx)]
    return sorted(findings, key=lambda f: -f.severity.rank)

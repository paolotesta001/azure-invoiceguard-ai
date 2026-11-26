"""Contract selection and NO_VALID_CONTRACT / CURRENCY checks."""

from collections.abc import Iterable
from datetime import date

from invoiceguard.checks.base import CheckContext, Finding
from invoiceguard.domain.enums import AnomalyType, Severity
from invoiceguard.domain.models import Contract


def select_contract(contracts: Iterable[Contract], invoice_date: date) -> Contract | None:
    """Return the highest-version contract in force on ``invoice_date``, if any."""
    valid = [c for c in contracts if c.is_valid_on(invoice_date)]
    return max(valid, key=lambda c: c.version) if valid else None


def check_contract_validity(ctx: CheckContext) -> list[Finding]:
    """Flag invoices dated outside every contract's validity period."""
    if ctx.contract is not None:
        return []
    return [
        Finding(
            type=AnomalyType.NO_VALID_CONTRACT,
            severity=Severity.HIGH,
            message=(
                f"No contract with {ctx.supplier.name} is valid on "
                f"{ctx.invoice.invoice_date.isoformat()}."
            ),
            evidence={
                "supplier_id": ctx.supplier.id,
                "invoice_date": ctx.invoice.invoice_date.isoformat(),
            },
        )
    ]


def check_currency(ctx: CheckContext) -> list[Finding]:
    """Flag invoices not issued in the contract currency (no conversion is performed)."""
    if ctx.contract is None or ctx.invoice.currency == ctx.contract.currency:
        return []
    return [
        Finding(
            type=AnomalyType.CURRENCY,
            severity=Severity.MEDIUM,
            message=(
                f"Invoice currency {ctx.invoice.currency} differs from contract currency "
                f"{ctx.contract.currency}. Prices were not compared."
            ),
            evidence={
                "invoice_currency": ctx.invoice.currency,
                "contract_currency": ctx.contract.currency,
                "contract_id": ctx.contract.id,
            },
        )
    ]

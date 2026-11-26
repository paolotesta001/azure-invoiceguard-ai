"""Money helpers. Money is always ``Decimal``; rounding happens only here.

Rounding rule: ``ROUND_HALF_UP`` to 2 decimals, applied to line amounts, VAT amounts
and totals. Intermediate values (unit prices, quantities, percentages) are never rounded.
"""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal(100)


def to_decimal(value: str | int | float | Decimal) -> Decimal:
    """Convert to ``Decimal``. Floats (e.g. from JSON SDK payloads) go through ``str`` so the
    shortest decimal representation is used instead of the binary float value."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def round_money(value: Decimal) -> Decimal:
    """Round to 2 decimals with ROUND_HALF_UP."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Expected line total: quantity × unit price, rounded."""
    return round_money(quantity * unit_price)


def vat_amount(taxable_base: Decimal, rate_pct: Decimal) -> Decimal:
    """VAT for a taxable base at a percentage rate, rounded."""
    return round_money(taxable_base * rate_pct / HUNDRED)


def within_tolerance(expected: Decimal, actual: Decimal, tolerance: Decimal) -> bool:
    """True if two amounts differ by at most ``tolerance``."""
    return abs(expected - actual) <= tolerance


def pct_change(reference: Decimal, observed: Decimal) -> Decimal:
    """Percentage change from ``reference`` to ``observed`` (not rounded)."""
    if reference == 0:
        raise ValueError("reference must be non-zero")
    return (observed - reference) / reference * HUNDRED

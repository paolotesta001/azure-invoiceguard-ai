"""PRICE: invoiced unit prices vs. structured contract prices (never retrieved via search)."""

from decimal import Decimal

from invoiceguard.checks.base import CheckContext, Finding
from invoiceguard.domain.enums import AnomalyType, Severity
from invoiceguard.domain.money import pct_change, round_money

_PCT = Decimal("0.01")


def check_price(ctx: CheckContext) -> list[Finding]:
    """Compare each line with ``ContractPriceItem``.

    * price at or below contract price → no finding
    * increase within ``max_price_increase_pct`` → LOW (a human confirms the adjustment)
    * increase above the cap → HIGH
    * SKU missing or not in the contract → HIGH
    Skipped when there is no valid contract or the currencies differ (flagged elsewhere).
    """
    contract = ctx.contract
    if contract is None or ctx.invoice.currency != contract.currency:
        return []

    findings: list[Finding] = []
    for line in ctx.invoice.lines:
        item = ctx.price_items.get(line.sku) if line.sku else None
        if item is None:
            findings.append(
                Finding(
                    type=AnomalyType.SKU_NOT_IN_CONTRACT,
                    severity=Severity.HIGH,
                    message=(
                        f"Line {line.line_no}: item '{line.sku or line.description}' is not "
                        f"priced in contract {contract.id} v{contract.version}."
                    ),
                    monetary_impact=line.line_total,
                    evidence={
                        "invoice_line": line.line_no,
                        "sku": line.sku,
                        "contract_id": contract.id,
                        "contract_version": contract.version,
                    },
                )
            )
            continue

        if line.unit_price <= item.unit_price:
            continue

        increase = pct_change(item.unit_price, line.unit_price)
        above_cap = increase > contract.max_price_increase_pct
        findings.append(
            Finding(
                type=AnomalyType.PRICE_ABOVE_CAP if above_cap else AnomalyType.PRICE_INCREASE_WITHIN_CAP,
                severity=Severity.HIGH if above_cap else Severity.LOW,
                message=(
                    f"Line {line.line_no} ({item.sku}): unit price {line.unit_price} vs. contract "
                    f"{item.unit_price} (+{increase.quantize(_PCT)}%, cap "
                    f"{contract.max_price_increase_pct}%)."
                ),
                monetary_impact=round_money((line.unit_price - item.unit_price) * line.quantity),
                evidence={
                    "invoice_line": line.line_no,
                    "sku": item.sku,
                    "invoice_unit_price": str(line.unit_price),
                    "contract_unit_price": str(item.unit_price),
                    "increase_pct": str(increase.quantize(_PCT)),
                    "max_price_increase_pct": str(contract.max_price_increase_pct),
                    "contract_id": contract.id,
                    "contract_version": contract.version,
                },
            )
        )
    return findings

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from invoiceguard.checks.arithmetic import check_arithmetic
from invoiceguard.checks.base import CheckContext, Finding
from invoiceguard.checks.contract import check_contract_validity, check_currency, select_contract
from invoiceguard.checks.iban import check_iban
from invoiceguard.checks.price import check_price
from invoiceguard.checks.runner import run_checks
from invoiceguard.checks.vat_rate import check_vat_rate
from invoiceguard.domain.enums import AnomalyType, Country, Severity
from invoiceguard.domain.iban import build_iban
from invoiceguard.domain.models import Contract, Supplier
from tests.conftest import make_invoice

MakeCtx = Callable[..., CheckContext]


def types(findings: list[Finding]) -> list[AnomalyType]:
    return [f.type for f in findings]


def test_clean_invoice_has_no_findings(make_ctx: MakeCtx) -> None:
    assert run_checks(make_ctx()) == []


def test_arithmetic_wrong_total(make_ctx: MakeCtx) -> None:
    inv = make_invoice()
    bad = inv.model_copy(update={"total": inv.total + Decimal("10.00")})
    findings = check_arithmetic(make_ctx(bad))
    assert types(findings) == [AnomalyType.ARITHMETIC]
    assert findings[0].monetary_impact == Decimal("10.00")
    assert findings[0].severity is Severity.HIGH


def test_arithmetic_wrong_line_subtotal_and_vat(make_ctx: MakeCtx) -> None:
    inv = make_invoice()
    line = inv.lines[0].model_copy(update={"line_total": Decimal("175.00")})
    bad = inv.model_copy(update={"lines": (line,)})
    checks = [f.evidence["check"] for f in check_arithmetic(make_ctx(bad))]
    assert checks == ["Line 1 total", "Subtotal", "VAT amount"]


def test_arithmetic_within_tolerance(make_ctx: MakeCtx) -> None:
    inv = make_invoice()
    ok = inv.model_copy(update={"total": inv.total + Decimal("0.01")})
    assert check_arithmetic(make_ctx(ok)) == []


def test_vat_rate_invalid_for_italy(make_ctx: MakeCtx) -> None:
    findings = check_vat_rate(make_ctx(make_invoice([("CHAIR", "1", "85.00", "21")])))
    assert types(findings) == [AnomalyType.VAT_RATE]
    assert findings[0].severity is Severity.MEDIUM


def test_vat_rate_unknown_country_is_not_checked(make_ctx: MakeCtx, supplier: Supplier) -> None:
    other = supplier.model_copy(update={"country": Country.OTHER})
    assert check_vat_rate(make_ctx(make_invoice([("CHAIR", "1", "85", "19")]),
                                   supplier=other)) == []


def test_select_contract_picks_highest_valid_version(contract: Contract) -> None:
    v2 = contract.model_copy(update={"id": "C2", "version": 2, "valid_from": date(2026, 7, 1)})
    assert select_contract([contract, v2], date(2026, 6, 30)) == contract
    assert select_contract([contract, v2], date(2026, 7, 1)) == v2
    assert select_contract([contract, v2], date(2027, 1, 1)) is None


def test_no_valid_contract(make_ctx: MakeCtx) -> None:
    assert types(check_contract_validity(make_ctx(contract=None))) == [
        AnomalyType.NO_VALID_CONTRACT]


def test_currency_mismatch_skips_price_check(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(make_invoice([("CHAIR", "1", "99.00", "22")], currency="USD"))
    assert types(check_currency(ctx)) == [AnomalyType.CURRENCY]
    assert check_price(ctx) == []


def test_price_above_cap(make_ctx: MakeCtx) -> None:
    findings = check_price(make_ctx(make_invoice([("CHAIR", "2", "95.20", "22")])))
    assert types(findings) == [AnomalyType.PRICE_ABOVE_CAP]
    assert findings[0].monetary_impact == Decimal("20.40")
    assert findings[0].evidence["increase_pct"] == "12.00"


def test_price_within_cap_is_low(make_ctx: MakeCtx) -> None:
    findings = check_price(make_ctx(make_invoice([("CHAIR", "1", "87.55", "22")])))  # +3.00%
    assert types(findings) == [AnomalyType.PRICE_INCREASE_WITHIN_CAP]
    assert findings[0].severity is Severity.LOW


def test_price_lower_than_contract_is_fine(make_ctx: MakeCtx) -> None:
    assert check_price(make_ctx(make_invoice([("CHAIR", "1", "80.00", "22")]))) == []


def test_sku_not_in_contract_and_missing_sku(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(make_invoice([("SOFA", "1", "390", "22"), (None, "1", "5", "22")]))
    assert types(check_price(ctx)) == [AnomalyType.SKU_NOT_IN_CONTRACT] * 2


def test_iban_mismatch_is_critical_and_masked(make_ctx: MakeCtx) -> None:
    other = build_iban("IT", "Z0306909606100000012345")
    findings = check_iban(make_ctx(make_invoice(iban=other)))
    assert types(findings) == [AnomalyType.IBAN_MISMATCH]
    assert findings[0].severity is Severity.CRITICAL
    assert "****" in str(findings[0].evidence["invoice_iban"])
    assert other not in findings[0].message


def test_iban_invalid_and_missing(make_ctx: MakeCtx) -> None:
    assert types(check_iban(make_ctx(make_invoice(iban="IT00X0542811101000000123456")))) == [
        AnomalyType.IBAN_INVALID]
    assert types(check_iban(make_ctx(make_invoice(iban=None)))) == [AnomalyType.IBAN_MISSING]


def test_iban_recently_changed_window(make_ctx: MakeCtx, supplier: Supplier) -> None:
    recent = supplier.model_copy(update={"iban_last_changed_at": date(2026, 9, 5)})  # 30 days
    assert types(check_iban(make_ctx(supplier=recent))) == [AnomalyType.IBAN_RECENTLY_CHANGED]
    older = supplier.model_copy(update={"iban_last_changed_at": date(2026, 9, 4)})  # 31 days
    assert check_iban(make_ctx(supplier=older)) == []


def test_runner_sorts_by_severity(make_ctx: MakeCtx) -> None:
    other = build_iban("IT", "Z0306909606100000012345")
    findings = run_checks(make_ctx(make_invoice([("CHAIR", "1", "87.00", "22")], iban=other)))
    assert findings[0].severity is Severity.CRITICAL
    assert findings[-1].severity is Severity.LOW

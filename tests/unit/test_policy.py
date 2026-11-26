from decimal import Decimal

from invoiceguard.config import ValidationSettings
from invoiceguard.domain.enums import AnomalyType, Severity, SupplierStatus
from invoiceguard.domain.models import Anomaly, Supplier
from invoiceguard.policy.auto_approve import evaluate_auto_approval
from tests.conftest import make_invoice

ANOMALY = Anomaly(id="a", submission_id="s", invoice_id="i",
                  type=AnomalyType.PRICE_INCREASE_WITHIN_CAP, severity=Severity.LOW, message="m")


def test_clean_small_invoice_is_auto_approved(supplier: Supplier,
                                              rules: ValidationSettings) -> None:
    result = evaluate_auto_approval(make_invoice(), supplier, [], [], rules)
    assert result.auto_approve and result.reasons == ()


def test_any_anomaly_blocks(supplier: Supplier, rules: ValidationSettings) -> None:
    assert not evaluate_auto_approval(make_invoice(), supplier, [ANOMALY], [], rules).auto_approve


def test_low_confidence_field_blocks(supplier: Supplier, rules: ValidationSettings) -> None:
    result = evaluate_auto_approval(make_invoice(), supplier, [], ["total"], rules)
    assert not result.auto_approve and "low-confidence" in result.reasons[0]


def test_threshold_is_exclusive(supplier: Supplier, rules: ValidationSettings) -> None:
    inv = make_invoice().model_copy(update={"total": Decimal("1000.00")})
    result = evaluate_auto_approval(inv, supplier, [], [], rules)
    assert not result.auto_approve and "threshold" in result.reasons[0]


def test_unknown_currency_and_blocked_supplier(supplier: Supplier,
                                               rules: ValidationSettings) -> None:
    blocked = supplier.model_copy(update={"status": SupplierStatus.BLOCKED})
    result = evaluate_auto_approval(make_invoice(currency="CHF"), blocked, [], ["total"], rules)
    assert len(result.reasons) == 3


def test_llm_pricing_cost(rules: ValidationSettings) -> None:
    pricing = rules.llm_pricing.model_copy(update={"input_per_1k_tokens": Decimal("0.002"),
                                                   "output_per_1k_tokens": Decimal("0.008")})
    assert pricing.cost(1000, 500) == Decimal("0.006")

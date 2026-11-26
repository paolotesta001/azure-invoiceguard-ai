from decimal import Decimal

import pytest

from invoiceguard.domain.iban import build_iban, is_valid_iban, normalize_iban
from invoiceguard.domain.money import line_amount, pct_change, round_money, to_decimal, vat_amount
from invoiceguard.safety.masking import mask_iban, mask_payload


def test_round_half_up() -> None:
    assert round_money(Decimal("2.345")) == Decimal("2.35")
    assert round_money(Decimal("2.344")) == Decimal("2.34")
    assert round_money(Decimal("-2.345")) == Decimal("-2.35")


def test_to_decimal_uses_shortest_float_repr() -> None:
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal("12.50") == Decimal("12.50")


def test_line_and_vat_amounts() -> None:
    assert line_amount(Decimal("3"), Decimal("33.335")) == Decimal("100.01")
    assert vat_amount(Decimal("202.50"), Decimal("22")) == Decimal("44.55")


def test_pct_change_and_zero_reference() -> None:
    assert pct_change(Decimal("100"), Decimal("112")) == Decimal("12")
    with pytest.raises(ValueError, match="non-zero"):
        pct_change(Decimal("0"), Decimal("1"))


def test_known_valid_iban() -> None:
    # Public example IBAN from the ISO 13616 / ECBS documentation
    assert is_valid_iban("GB82 WEST 1234 5698 7654 32")
    assert not is_valid_iban("GB83 WEST 1234 5698 7654 32")
    assert not is_valid_iban("not an iban")


def test_build_iban_round_trip() -> None:
    iban = build_iban("IT", "X0542811101000000123456")
    assert is_valid_iban(iban) and iban.startswith("IT")
    assert normalize_iban(" it60 x054 ") == "IT60X054"


def test_masking() -> None:
    assert mask_iban("IT60X0542811101000000123456") == "IT60 **** **** 3456"
    assert mask_iban(None) is None
    payload = {"iban": "IT60X0542811101000000123456",
               "nested": {"invoice_iban": "GB82WEST12345698765432"},
               "items": [{"iban_on_file": "GB82WEST12345698765432"}], "total": "10.00"}
    masked = mask_payload(payload)
    assert masked["iban"] == "IT60 **** **** 3456"
    assert masked["nested"] == {"invoice_iban": "GB82 **** **** 5432"}
    assert masked["items"] == [{"iban_on_file": "GB82 **** **** 5432"}]
    assert masked["total"] == "10.00"

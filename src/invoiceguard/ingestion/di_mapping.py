"""Map a Document Intelligence ``prebuilt-invoice`` result (REST JSON shape, API 2024-11-30)
to ``ExtractedInvoice``. Pure function: testable without the Azure SDK.

Field names are isolated in ``FIELD_MAP``; verify them against the prebuilt-invoice field list
for the API version you use (see docs/sdk-notes.md). Query fields ``PurchaseOrderNumber`` and
``IBAN`` are used when the standard fields are missing or less confident.

Rules:
* Missing *key* fields (supplier VAT id, invoice number, date, total with currency, line items)
  → ``ExtractionError`` ("needs manual entry"): without them duplicate detection cannot work.
* Any other missing field gets confidence 0.0, so it lands in ``needs_review_fields`` and the
  invoice cannot be auto-approved. Nothing is silently trusted.
"""

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from invoiceguard.domain.enums import SourceType
from invoiceguard.domain.models import ExtractedInvoice, ExtractedInvoiceLine
from invoiceguard.domain.money import round_money, to_decimal
from invoiceguard.ingestion.errors import ExtractionError

FIELD_MAP = {
    "supplier_name": "VendorName",
    "supplier_vat_id": "VendorTaxId",
    "invoice_number": "InvoiceId",
    "invoice_date": "InvoiceDate",
    "due_date": "DueDate",
    "po_number": "PurchaseOrder",
    "subtotal": "SubTotal",
    "vat_amount": "TotalTax",
    "total": "InvoiceTotal",
    "items": "Items",
    "payment_details": "PaymentDetails",
}
ITEM_FIELD_MAP = {
    "sku": "ProductCode",
    "description": "Description",
    "quantity": "Quantity",
    "unit_price": "UnitPrice",
    "line_total": "Amount",
    "vat_rate": "TaxRate",
}
QUERY_FIELDS = ("PurchaseOrderNumber", "IBAN")
Field = Mapping[str, Any]


def _confidence(field: Field | None) -> float:
    if not field:
        return 0.0
    value = field.get("confidence")
    return float(value) if isinstance(value, int | float | Decimal) else 0.0


def _string(field: Field | None) -> str | None:
    if not field:
        return None
    value = field.get("valueString", field.get("content"))
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date(field: Field | None) -> date | None:
    if not field or not field.get("valueDate"):
        return None
    try:
        return date.fromisoformat(str(field["valueDate"]))
    except ValueError:
        return None


def _amount(field: Field | None) -> tuple[Decimal | None, str | None]:
    """Return (amount, currency code) from a currency or number field."""
    if not field:
        return None, None
    currency = field.get("valueCurrency")
    if isinstance(currency, Mapping) and currency.get("amount") is not None:
        code = currency.get("currencyCode")
        return to_decimal(currency["amount"]), str(code) if code else None
    if field.get("valueNumber") is not None:
        return to_decimal(field["valueNumber"]), None
    return None, None


def _rate(field: Field | None) -> Decimal | None:
    raw = _string(field)
    if raw is None:
        number, _ = _amount(field)
        return number
    match = re.search(r"\d+(?:[.,]\d+)?", raw)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", "."))
    except InvalidOperation:
        return None


def _pick(primary: Field | None, query: Field | None) -> tuple[str | None, float]:
    """Choose between a standard field and a query field by confidence."""
    candidates = [(f, _confidence(f)) for f in (primary, query) if _string(f)]
    if not candidates:
        return None, 0.0
    best, conf = max(candidates, key=lambda c: c[1])
    return _string(best), conf


def map_invoice_result(result: Mapping[str, Any]) -> ExtractedInvoice:
    """Convert an analyze result (dict) into an ``ExtractedInvoice`` with per-field confidence."""
    documents = result.get("documents") or []
    if not documents:
        raise ExtractionError("needs manual entry: Document Intelligence found no invoice")
    fields: Mapping[str, Field] = documents[0].get("fields") or {}

    def get(name: str) -> Field | None:
        value = fields.get(FIELD_MAP.get(name, name))
        return value if isinstance(value, Mapping) else None

    conf: dict[str, float] = {}
    missing: list[str] = []

    vat_raw = _string(get("supplier_vat_id"))
    supplier_vat_id = re.sub(r"[\s.\-]", "", vat_raw).upper() if vat_raw else None
    invoice_number = _string(get("invoice_number"))
    invoice_date = _date(get("invoice_date"))
    total, currency = _amount(get("total"))
    for name, value in (("supplier_vat_id", supplier_vat_id), ("invoice_number", invoice_number),
                        ("invoice_date", invoice_date), ("total", total), ("currency", currency)):
        if value is None:
            missing.append(name)

    items_field = get("items")
    raw_items = items_field.get("valueArray", []) if items_field else []
    if not raw_items:
        missing.append("line items")
    if missing:
        raise ExtractionError(f"needs manual entry: could not read {', '.join(missing)}")
    assert supplier_vat_id and invoice_number and invoice_date and total is not None and currency

    for name in ("supplier_vat_id", "invoice_number", "invoice_date", "total"):
        conf[name] = _confidence(get(name))
    conf["currency"] = conf["total"]
    supplier_name = _string(get("supplier_name")) or supplier_vat_id
    conf["supplier_name"] = _confidence(get("supplier_name"))
    due_date = _date(get("due_date"))
    conf["due_date"] = _confidence(get("due_date")) if due_date else 0.0

    po_number, conf["po_number"] = _pick(get("po_number"), fields.get("PurchaseOrderNumber"))
    payment = get("payment_details")
    payment_items = payment.get("valueArray", []) if payment else []
    first_payment = (payment_items[0].get("valueObject") or {}) if payment_items else {}
    iban_value, conf["iban"] = _pick(first_payment.get("IBAN"), fields.get("IBAN"))
    iban = re.sub(r"\s+", "", iban_value).upper() if iban_value else None

    raw_lines: list[dict[str, Any]] = []
    line_conf: dict[str, list[float]] = {key: [] for key in ITEM_FIELD_MAP}
    known_rates: list[Decimal] = []
    for index, item in enumerate(raw_items, start=1):
        obj: Mapping[str, Field] = item.get("valueObject") or {}
        sub = {key: obj.get(name) for key, name in ITEM_FIELD_MAP.items()}
        quantity, _ = _amount(sub["quantity"])
        unit_price, _ = _amount(sub["unit_price"])
        line_total, _ = _amount(sub["line_total"])
        rate = _rate(sub["vat_rate"])
        if line_total is None and quantity is not None and unit_price is not None:
            line_total = round_money(quantity * unit_price)
            sub["line_total"] = None  # derived, not read → confidence 0
        if unit_price is None and line_total is not None and quantity:
            unit_price = line_total / quantity
            sub["unit_price"] = None
        if line_total is None or unit_price is None:
            raise ExtractionError(f"needs manual entry: line {index} has no readable amount")
        if rate is not None:
            known_rates.append(rate)
        for key, field in sub.items():
            if key == "sku" and field is None:
                continue
            line_conf[key].append(_confidence(field) if field else 0.0)
        raw_lines.append({
            "line_no": index,
            "sku": _string(sub["sku"]),
            "description": _string(sub["description"]) or f"Line {index}",
            "quantity": quantity if quantity is not None else Decimal("1"),
            "unit_price": unit_price,
            "vat_rate": rate,
            "line_total": line_total,
        })

    subtotal, _ = _amount(get("subtotal"))
    vat_amount, _ = _amount(get("vat_amount"))
    lines_net = round_money(sum((ln["line_total"] for ln in raw_lines), Decimal("0")))
    conf["subtotal"] = _confidence(get("subtotal")) if subtotal is not None else 0.0
    subtotal = subtotal if subtotal is not None else lines_net
    conf["vat_amount"] = _confidence(get("vat_amount")) if vat_amount is not None else 0.0
    vat_amount = vat_amount if vat_amount is not None else round_money(total - subtotal)

    # Lines without a readable VAT rate: use the single rate found on other lines, or the
    # overall effective rate. Either way the field is marked for review (confidence 0).
    fallback_rate = (known_rates[0] if len(set(known_rates)) == 1 else
                     (round_money(vat_amount / subtotal * 100) if subtotal else Decimal("0")))
    lines = tuple(
        ExtractedInvoiceLine.model_validate(
            {**ln, "vat_rate": ln["vat_rate"] if ln["vat_rate"] is not None else fallback_rate}
        )
        for ln in raw_lines
    )

    for key, values in line_conf.items():
        if values:
            conf[f"lines.{key}"] = min(values)

    return ExtractedInvoice(
        source_type=SourceType.OCR,
        supplier_vat_id=supplier_vat_id,
        supplier_name=supplier_name,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        currency=currency,
        subtotal=subtotal,
        vat_amount=vat_amount,
        total=total,
        iban=iban,
        po_number=po_number,
        lines=lines,
        field_confidence={k: round(v, 3) for k, v in conf.items()},
    )

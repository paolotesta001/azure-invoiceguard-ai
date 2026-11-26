import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from invoiceguard.adapters.document_intelligence import RecordedAnalyzer
from invoiceguard.ingestion.di_mapping import map_invoice_result
from invoiceguard.ingestion.errors import ExtractionError


def _recording(dataset: Path, name: str) -> dict[str, Any]:
    content = (dataset / "invoices" / name).read_bytes()
    return RecordedAnalyzer(dataset / "recorded" / "document_intelligence").analyze_invoice(content)


def test_maps_clean_pdf_with_confidences(dataset: Path) -> None:
    inv = map_invoice_result(_recording(dataset, "13_pdf_clean_layout_a.pdf"))
    assert inv.supplier_vat_id == "IT02000000022"
    assert inv.invoice_number == "CF-26-0470"
    assert (inv.subtotal, inv.vat_amount, inv.total) == (
        Decimal("146.30"), Decimal("32.19"), Decimal("178.49"))
    assert [ln.sku for ln in inv.lines] == ["CON-PAPER", "CON-BINDER"]
    assert inv.lines[0].vat_rate == Decimal("22")
    assert inv.low_confidence_fields(0.8) == ()
    assert {"total", "iban", "lines.unit_price"} <= set(inv.field_confidence)


def test_query_fields_fill_missing_standard_fields(dataset: Path) -> None:
    layout_b = map_invoice_result(_recording(dataset, "14_pdf_wrong_price_layout_b.pdf"))
    assert layout_b.iban is not None  # only present as query field "IBAN"
    layout_c = map_invoice_result(_recording(dataset, "15_pdf_clean_layout_c.pdf"))
    assert layout_c.po_number == "PO-S-IT-03-001"  # only present as "PurchaseOrderNumber"


def test_noisy_scan_has_low_confidence_fields(dataset: Path) -> None:
    inv = map_invoice_result(_recording(dataset, "16_scan_low_quality.jpg"))
    assert inv.low_confidence_fields(0.8) == ("currency", "iban", "total")


def test_missing_key_field_needs_manual_entry(dataset: Path) -> None:
    result = copy.deepcopy(_recording(dataset, "13_pdf_clean_layout_a.pdf"))
    del result["documents"][0]["fields"]["InvoiceId"]
    with pytest.raises(ExtractionError, match="needs manual entry: could not read invoice_number"):
        map_invoice_result(result)
    with pytest.raises(ExtractionError, match="no invoice"):
        map_invoice_result({"documents": []})


def test_missing_optional_fields_get_zero_confidence(dataset: Path) -> None:
    result = copy.deepcopy(_recording(dataset, "13_pdf_clean_layout_a.pdf"))
    fields = result["documents"][0]["fields"]
    for name in ("SubTotal", "TotalTax", "DueDate"):
        del fields[name]
    for item in fields["Items"]["valueArray"]:
        del item["valueObject"]["TaxRate"]
    inv = map_invoice_result(result)
    assert inv.subtotal == Decimal("146.30")  # derived from lines
    assert inv.vat_amount == Decimal("32.19")  # total - subtotal
    assert inv.lines[0].vat_rate == Decimal("22.00")  # effective rate
    assert {"subtotal", "vat_amount", "due_date", "lines.vat_rate"} <= set(
        inv.low_confidence_fields(0.8))


def test_live_style_float_amounts(dataset: Path) -> None:
    raw = json.loads(json.dumps(_recording(dataset, "13_pdf_clean_layout_a.pdf"),
                                default=float))  # floats, like SDK as_dict()
    assert map_invoice_result(raw).total == Decimal("178.49")

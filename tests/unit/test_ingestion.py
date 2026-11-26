from decimal import Decimal
from pathlib import Path

import pytest

from invoiceguard.adapters.document_intelligence import RecordedAnalyzer
from invoiceguard.domain.enums import SourceType
from invoiceguard.ingestion.detect import InvoiceFormat, detect_format
from invoiceguard.ingestion.errors import ExtractionError, UnsupportedFormatError
from invoiceguard.ingestion.extract import InvoiceExtractor
from invoiceguard.ingestion.fatturapa import parse_fatturapa
from invoiceguard.ingestion.ksef import parse_ksef


def test_parse_clean_fatturapa(dataset: Path) -> None:
    inv = parse_fatturapa((dataset / "invoices" / "01_clean_small.xml").read_bytes())
    assert inv.source_type is SourceType.XML_FATTURAPA
    assert inv.supplier_vat_id == "IT01000000011"
    assert inv.invoice_number == "FA-2026-0101"
    assert (inv.subtotal, inv.vat_amount, inv.total) == (
        Decimal("202.50"), Decimal("44.55"), Decimal("247.05"))
    assert inv.po_number == "PO-S-IT-01-001"
    assert [ln.sku for ln in inv.lines] == ["FAB-CHAIR", "FAB-LAMP"]
    assert inv.due_date is not None and (inv.due_date - inv.invoice_date).days == 30
    assert set(inv.field_confidence.values()) == {1.0}


def test_parse_ksef(dataset: Path) -> None:
    inv = parse_ksef((dataset / "invoices" / "17_ksef_clean.xml").read_bytes())
    assert inv.source_type is SourceType.XML_KSEF
    assert inv.supplier_vat_id == "PL1000000011"
    assert inv.invoice_number == "WT/2026/10/015"
    assert inv.currency == "PLN"
    assert (inv.subtotal, inv.vat_amount, inv.total) == (
        Decimal("1300.00"), Decimal("299.00"), Decimal("1599.00"))
    assert inv.iban and inv.iban.startswith("PL") and len(inv.iban) == 28
    assert inv.po_number == "PO-S-PL-01-001"
    [line] = inv.lines
    assert (line.sku, line.quantity, line.unit_price, line.vat_rate) == (
        "WT-BOX", Decimal("200.00"), Decimal("6.50"), Decimal("23"))


def test_ksef_rejects_unsupported_vat_marker(dataset: Path) -> None:
    xml = (dataset / "invoices" / "17_ksef_clean.xml").read_bytes().replace(
        b"<P_12>23</P_12>", b"<P_12>zw</P_12>")
    with pytest.raises(ExtractionError, match="VAT marker"):
        parse_ksef(xml)


def test_ksef_ignores_pln_conversion_fields(dataset: Path) -> None:
    xml = (dataset / "invoices" / "17_ksef_clean.xml").read_bytes().replace(
        b"<P_15>", b"<P_14_1W>299.00</P_14_1W><P_15>")
    assert parse_ksef(xml).vat_amount == Decimal("299.00")


def test_detect_formats(dataset: Path) -> None:
    inv = dataset / "invoices"
    assert detect_format((inv / "01_clean_small.xml").read_bytes()) is InvoiceFormat.FATTURAPA
    assert detect_format((inv / "17_ksef_clean.xml").read_bytes()) is InvoiceFormat.KSEF
    assert detect_format((inv / "13_pdf_clean_layout_a.pdf").read_bytes()) is InvoiceFormat.PDF
    assert detect_format((inv / "16_scan_low_quality.jpg").read_bytes()) is InvoiceFormat.IMAGE
    with pytest.raises(UnsupportedFormatError):
        detect_format(b"<Other/>")
    with pytest.raises(UnsupportedFormatError):
        detect_format(b"hello")


def test_extractor_routes_formats(dataset: Path) -> None:
    extractor = InvoiceExtractor(RecordedAnalyzer(dataset / "recorded" / "document_intelligence"))
    inv = dataset / "invoices"
    assert extractor.extract((inv / "17_ksef_clean.xml").read_bytes())[1] == "xml:ksef"
    data, source = extractor.extract((inv / "13_pdf_clean_layout_a.pdf").read_bytes())
    assert source == "document_intelligence:recorded"
    assert data.source_type is SourceType.OCR
    with pytest.raises(UnsupportedFormatError, match="not configured"):
        InvoiceExtractor().extract(b"%PDF-1.7")
    with pytest.raises(ExtractionError, match="no recorded"):
        extractor.extract(b"%PDF-1.7 unknown file")


def test_invalid_xml_and_missing_fields() -> None:
    with pytest.raises(ExtractionError, match="invalid XML"):
        parse_fatturapa(b"<FatturaElettronica><broken>")
    with pytest.raises(ExtractionError, match="exactly one header"):
        parse_fatturapa(b"<FatturaElettronica/>")
    with pytest.raises(ExtractionError, match="exactly one Fa"):
        parse_ksef(b"<Faktura/>")


def test_xxe_is_not_resolved(dataset: Path) -> None:
    xml = (dataset / "invoices" / "01_clean_small.xml").read_text(encoding="utf-8")
    evil = xml.replace("<?xml version='1.0' encoding='UTF-8'?>",
                       "<?xml version='1.0'?><!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]>")
    evil = evil.replace("Fabrikam Arredi S.r.l.", "&e;")
    try:
        inv = parse_fatturapa(evil.encode())
    except ExtractionError:
        return  # rejecting the document is also safe
    assert "root:" not in inv.supplier_name

"""Parser for Italian FatturaPA e-invoices (FPR12, namespace .../fatture/v1.2).

Elements are matched by local name, so the parser does not depend on namespace prefixes.
Structured XML is authoritative, so every extracted field gets confidence 1.0.
Only single-body files are supported (batch files with several bodies are rejected).
"""

from decimal import Decimal

from lxml import etree

from invoiceguard.domain.enums import SourceType
from invoiceguard.domain.models import ExtractedInvoice, ExtractedInvoiceLine
from invoiceguard.domain.money import round_money
from invoiceguard.ingestion.errors import ExtractionError
from invoiceguard.ingestion.parsing import parse_date, parse_decimal
from invoiceguard.ingestion.xml_safety import find_all, find_text, local_name, parse_xml

HEADER_FIELDS = (
    "supplier_vat_id",
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "vat_amount",
    "total",
    "iban",
    "po_number",
)


def _required(element: etree._Element, path: str) -> str:
    value = find_text(element, path)
    if value is None:
        raise ExtractionError(f"FatturaPA: missing required element {path}")
    return value


def _parse_line(line: etree._Element) -> ExtractedInvoiceLine:
    return ExtractedInvoiceLine(
        line_no=int(_required(line, "NumeroLinea")),
        sku=find_text(line, "CodiceArticolo/CodiceValore"),
        description=_required(line, "Descrizione"),
        quantity=parse_decimal(find_text(line, "Quantita") or "1", "FatturaPA Quantita"),
        unit_price=parse_decimal(_required(line, "PrezzoUnitario"), "FatturaPA PrezzoUnitario"),
        vat_rate=parse_decimal(_required(line, "AliquotaIVA"), "FatturaPA AliquotaIVA"),
        line_total=parse_decimal(_required(line, "PrezzoTotale"), "FatturaPA PrezzoTotale"),
    )


def parse_fatturapa(content: bytes) -> ExtractedInvoice:
    """Parse a FatturaPA XML document into an ``ExtractedInvoice``."""
    root = parse_xml(content)
    if local_name(root) != "FatturaElettronica":
        raise ExtractionError("not a FatturaPA document")

    headers = find_all(root, "FatturaElettronicaHeader")
    bodies = find_all(root, "FatturaElettronicaBody")
    if len(headers) != 1 or len(bodies) != 1:
        raise ExtractionError("FatturaPA: exactly one header and one body are supported")
    header, body = headers[0], bodies[0]

    supplier = "CedentePrestatore/DatiAnagrafici"
    vat_id = _required(header, f"{supplier}/IdFiscaleIVA/IdPaese") + _required(
        header, f"{supplier}/IdFiscaleIVA/IdCodice"
    )
    name = find_text(header, f"{supplier}/Anagrafica/Denominazione") or " ".join(
        part
        for part in (
            find_text(header, f"{supplier}/Anagrafica/Nome"),
            find_text(header, f"{supplier}/Anagrafica/Cognome"),
        )
        if part
    )
    if not name:
        raise ExtractionError("FatturaPA: supplier name (Denominazione or Nome/Cognome) missing")

    doc = "DatiGenerali/DatiGeneraliDocumento"
    lines = tuple(_parse_line(node) for node in find_all(body, "DatiBeniServizi/DettaglioLinee"))
    if not lines:
        raise ExtractionError("FatturaPA: no DettaglioLinee found")

    summaries = find_all(body, "DatiBeniServizi/DatiRiepilogo")
    if not summaries:
        raise ExtractionError("FatturaPA: no DatiRiepilogo found")
    subtotal = sum(
        (parse_decimal(_required(s, "ImponibileImporto"), "ImponibileImporto") for s in summaries),
        Decimal("0"),
    )
    vat = sum(
        (parse_decimal(_required(s, "Imposta"), "Imposta") for s in summaries),
        Decimal("0"),
    )
    declared_total = find_text(body, f"{doc}/ImportoTotaleDocumento")
    total = (
        parse_decimal(declared_total, "ImportoTotaleDocumento")
        if declared_total is not None
        else round_money(subtotal + vat)
    )

    payment = "DatiPagamento/DettaglioPagamento"
    due_raw = find_text(body, f"{payment}/DataScadenzaPagamento")

    return ExtractedInvoice(
        source_type=SourceType.XML_FATTURAPA,
        supplier_vat_id=vat_id,
        supplier_name=name,
        invoice_number=_required(body, f"{doc}/Numero"),
        invoice_date=parse_date(_required(body, f"{doc}/Data"), "FatturaPA Data"),
        due_date=parse_date(due_raw, "DataScadenzaPagamento") if due_raw else None,
        currency=_required(body, f"{doc}/Divisa"),
        subtotal=subtotal,
        vat_amount=vat,
        total=total,
        iban=find_text(body, f"{payment}/IBAN"),
        po_number=find_text(body, "DatiGenerali/DatiOrdineAcquisto/IdDocumento"),
        lines=lines,
        field_confidence={field: 1.0 for field in HEADER_FIELDS},
    )

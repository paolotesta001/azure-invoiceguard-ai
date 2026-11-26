"""Parser for Polish KSeF structured invoices (logical structure FA(3)).

Element names follow the Ministry of Finance information sheet for FA(3)
(Naglowek, Podmiot1 = seller, Podmiot2 = buyer, Fa, FaWiersz, Platnosc, WarunkiTransakcji).
Elements are matched by local name; the namespace is not checked.
Field codes used (see docs/sdk-notes.md, to be verified against the official XSD/sample):

* Podmiot1/PrefiksPodatnika, Podmiot1/DaneIdentyfikacyjne/NIP, .../Nazwa
* Fa/KodWaluty, Fa/P_1 (issue date), Fa/P_2 (invoice number), Fa/P_15 (gross total)
* Fa/P_13_* (net amount per rate), Fa/P_14_* (VAT per rate; ``P_14_*W`` = PLN conversion, ignored)
* FaWiersz: NrWierszaFa, Indeks (seller item code), P_7 (name), P_8B (qty),
  P_9A (unit net price), P_11 (line net value), P_12 (VAT rate)
* Platnosc/TerminPlatnosci/Termin, Platnosc/RachunekBankowy/NrRB
* WarunkiTransakcji/Zamowienia/NrZamowienia (purchase order number)
"""

import re
from decimal import Decimal

from lxml import etree

from invoiceguard.domain.enums import SourceType
from invoiceguard.domain.models import ExtractedInvoice, ExtractedInvoiceLine
from invoiceguard.ingestion.errors import ExtractionError
from invoiceguard.ingestion.parsing import parse_date, parse_decimal
from invoiceguard.ingestion.xml_safety import find_all, find_text, local_name, parse_xml

_NET_PER_RATE = re.compile(r"^P_13_\d+(_\d+)?$")
_VAT_PER_RATE = re.compile(r"^P_14_\d+$")
_NRB = re.compile(r"^\d{26}$")

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
        raise ExtractionError(f"KSeF: missing required element {path}")
    return value


def _vat_rate(raw: str, line_no: int) -> Decimal:
    if not re.fullmatch(r"\d+(\.\d+)?", raw.strip()):
        raise ExtractionError(
            f"KSeF: line {line_no} uses VAT marker {raw!r}, which is not supported yet"
        )
    return Decimal(raw.strip())


def _parse_line(line: etree._Element) -> ExtractedInvoiceLine:
    line_no = int(_required(line, "NrWierszaFa"))
    return ExtractedInvoiceLine(
        line_no=line_no,
        sku=find_text(line, "Indeks"),
        description=_required(line, "P_7"),
        quantity=parse_decimal(find_text(line, "P_8B") or "1", "KSeF P_8B"),
        unit_price=parse_decimal(_required(line, "P_9A"), "KSeF P_9A"),
        vat_rate=_vat_rate(_required(line, "P_12"), line_no),
        line_total=parse_decimal(_required(line, "P_11"), "KSeF P_11"),
    )


def _normalize_account(raw: str | None) -> str | None:
    """Polish NRB (26 digits) → IBAN with ``PL`` prefix; other values are kept."""
    if raw is None:
        return None
    compact = re.sub(r"\s+", "", raw).upper()
    return f"PL{compact}" if _NRB.match(compact) else compact


def parse_ksef(content: bytes) -> ExtractedInvoice:
    """Parse a KSeF FA(3) XML document into an ``ExtractedInvoice``."""
    root = parse_xml(content)
    if local_name(root) != "Faktura":
        raise ExtractionError("not a KSeF document")
    fa_nodes = find_all(root, "Fa")
    if len(fa_nodes) != 1:
        raise ExtractionError("KSeF: exactly one Fa element is required")
    fa = fa_nodes[0]

    prefix = find_text(root, "Podmiot1/PrefiksPodatnika") or "PL"
    nip = _required(root, "Podmiot1/DaneIdentyfikacyjne/NIP")
    lines = tuple(_parse_line(node) for node in find_all(fa, "FaWiersz"))
    if not lines:
        raise ExtractionError("KSeF: no FaWiersz found")

    children = [child for child in fa if isinstance(child.tag, str)]
    subtotal = sum(
        (parse_decimal(c.text or "0", local_name(c)) for c in children
         if _NET_PER_RATE.match(local_name(c))),
        Decimal("0"),
    )
    vat = sum(
        (parse_decimal(c.text or "0", local_name(c)) for c in children
         if _VAT_PER_RATE.match(local_name(c))),
        Decimal("0"),
    )
    due_raw = find_text(fa, "Platnosc/TerminPlatnosci/Termin")

    return ExtractedInvoice(
        source_type=SourceType.XML_KSEF,
        supplier_vat_id=f"{prefix}{nip}",
        supplier_name=_required(root, "Podmiot1/DaneIdentyfikacyjne/Nazwa"),
        invoice_number=_required(fa, "P_2"),
        invoice_date=parse_date(_required(fa, "P_1"), "KSeF P_1"),
        due_date=parse_date(due_raw, "KSeF Termin") if due_raw else None,
        currency=_required(fa, "KodWaluty"),
        subtotal=subtotal,
        vat_amount=vat,
        total=parse_decimal(_required(fa, "P_15"), "KSeF P_15"),
        iban=_normalize_account(find_text(fa, "Platnosc/RachunekBankowy/NrRB")),
        po_number=find_text(fa, "WarunkiTransakcji/Zamowienia/NrZamowienia"),
        lines=lines,
        field_confidence={field: 1.0 for field in HEADER_FIELDS},
    )

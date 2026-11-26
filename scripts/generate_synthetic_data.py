"""Generate reproducible synthetic data: suppliers, contracts, prices, POs, goods receipts,
FatturaPA + KSeF XML invoices, PDF invoices (3 layouts), a noisy scan, simulated Document
Intelligence recordings and JSON labels. All names, VAT ids and IBANs are fictional.

Usage: python scripts/generate_synthetic_data.py --seed 42 --out data
Requires the ``data`` extra (reportlab, Pillow).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from lxml import etree

from invoiceguard.domain.iban import build_iban
from invoiceguard.domain.money import line_amount, round_money, vat_amount

NS_FATTURAPA = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
# KSeF FA(3) namespace: verify against the official XSD (docs/sdk-notes.md). The parser
# matches elements by local name, so a different namespace does not break parsing.
NS_KSEF = "http://crd.gov.pl/wzor/2025/06/25/13775/"
BUYER_IT = {"vat": ("IT", "09999999990"), "name": "Demo Buyer S.r.l. (synthetic)"}
BUYER_PL = {"nip": "9999999999", "name": "Demo Buyer Polska Sp. z o.o. (synthetic)"}


@dataclass
class SupplierSpec:
    id: str
    name: str
    country: str
    vat_code: str
    currency: str
    iban_changed: str | None
    contract_from: str
    contract_to: str
    terms_days: int
    prices: dict[str, tuple[str, str, str]]  # sku -> (description, unit price, unit)
    iban: str = ""


SUPPLIERS = [
    SupplierSpec("S-IT-01", "Fabrikam Arredi S.r.l.", "IT", "01000000011", "EUR", "2025-03-01",
                 "2026-01-01", "2026-12-31", 30,
                 {"FAB-CHAIR": ("Ergonomic office chair", "85.00", "pz"),
                  "FAB-DESK": ("Standing desk 160x80", "240.00", "pz"),
                  "FAB-LAMP": ("LED desk lamp", "32.50", "pz")}),
    SupplierSpec("S-IT-02", "Contoso Forniture Ufficio S.p.A.", "IT", "02000000022", "EUR", None,
                 "2026-01-01", "2026-12-31", 60,
                 {"CON-PAPER": ("A4 paper box (5 reams)", "21.90", "box"),
                  "CON-TONER": ("Toner cartridge black", "64.00", "pz"),
                  "CON-BINDER": ("Ring binder pack (10)", "18.40", "pack")}),
    SupplierSpec("S-IT-03", "Northwind Logistica S.r.l.", "IT", "03000000033", "EUR", "2024-06-15",
                 "2026-01-01", "2026-12-31", 30,
                 {"NW-PALLET": ("Pallet transport Milano-Torino", "145.00", "pallet"),
                  "NW-STORAGE": ("Warehouse storage per pallet/month", "12.00", "pallet")}),
    SupplierSpec("S-IT-04", "Tailspin Elettronica S.r.l.", "IT", "04000000044", "EUR", "2026-09-28",
                 "2026-01-01", "2026-12-31", 30,
                 {"TS-CABLE": ("USB-C cable 2m", "9.90", "pz"),
                  "TS-DOCK": ("USB-C docking station", "129.00", "pz")}),
    SupplierSpec("S-IT-05", "Adatum Servizi S.r.l.", "IT", "05000000055", "EUR", None,
                 "2025-01-01", "2025-12-31", 30,
                 {"AD-CLEAN": ("Office cleaning (monthly)", "450.00", "month")}),
    SupplierSpec("S-PL-01", "Wingtip Dostawy Sp. z o.o.", "PL", "1000000011", "PLN", None,
                 "2026-01-01", "2026-12-31", 30,
                 {"WT-BOX": ("Shipping box large", "6.50", "szt")}),
    SupplierSpec("S-PL-02", "Litware Polska Sp. z o.o.", "PL", "2000000022", "PLN", None,
                 "2026-01-01", "2026-12-31", 45,
                 {"LW-LIC": ("Software licence (annual)", "1200.00", "szt")}),
]


def _bban(rng: random.Random, country: str) -> str:
    if country == "IT":
        cin = rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        return cin + "".join(rng.choice("0123456789") for _ in range(22))
    return "".join(rng.choice("0123456789") for _ in range(24))


@dataclass
class InvoiceSpec:
    file: str
    supplier: str
    number: str
    day: str
    lines: list[tuple[str, str, str, str]]  # sku, qty, unit price, vat rate
    description: str
    expected_submission_status: str
    expected_invoice_status: str | None
    expected_anomalies: list[str]
    currency: str | None = None
    iban: str | None = None  # override
    total_delta: str = "0"
    transmission_no: str = "00001"
    layout: str = "xml"  # xml | ksef | pdf_a | pdf_b | pdf_c | scan
    expected_needs_review: list[str] = field(default_factory=list)


def _invoice_specs(alt_iban: str) -> list[InvoiceSpec]:
    return [
        InvoiceSpec("01_clean_small.xml", "S-IT-01", "FA-2026-0101", "2026-10-05",
                    [("FAB-CHAIR", "2", "85.00", "22"), ("FAB-LAMP", "1", "32.50", "22")],
                    "Clean invoice below the auto-approve threshold",
                    "accepted", "auto_approved", []),
        InvoiceSpec("02_wrong_price.xml", "S-IT-02", "CF-26-0442", "2026-10-06",
                    [("CON-TONER", "3", "71.70", "22"), ("CON-PAPER", "2", "21.90", "22")],
                    "Toner unit price +12% vs contract (cap 3%)",
                    "accepted", "flagged", ["PRICE_ABOVE_CAP"]),
        InvoiceSpec("03_duplicate_of_01.xml", "S-IT-01", "FA-2026-0101", "2026-10-05",
                    [("FAB-CHAIR", "2", "85.00", "22"), ("FAB-LAMP", "1", "32.50", "22")],
                    "Same invoice number as 01, re-sent (different file bytes)",
                    "duplicate_rejected", None, ["DUPLICATE"], transmission_no="00002"),
        InvoiceSpec("04_iban_mismatch.xml", "S-IT-03", "NWL-2026-311", "2026-10-07",
                    [("NW-PALLET", "4", "145.00", "22")],
                    "Bank account differs from supplier master data",
                    "accepted", "flagged", ["IBAN_MISMATCH"], iban=alt_iban),
        InvoiceSpec("05_arithmetic_error.xml", "S-IT-02", "CF-26-0450", "2026-10-08",
                    [("CON-BINDER", "5", "18.40", "22")],
                    "Declared total is 10.00 higher than subtotal + VAT",
                    "accepted", "flagged", ["ARITHMETIC"], total_delta="10.00"),
        InvoiceSpec("06_invalid_vat_rate.xml", "S-IT-03", "NWL-2026-315", "2026-10-09",
                    [("NW-STORAGE", "20", "12.00", "21")],
                    "VAT rate 21% is not an Italian rate",
                    "accepted", "flagged", ["VAT_RATE"]),
        InvoiceSpec("07_currency_mismatch.xml", "S-IT-01", "FA-2026-0107", "2026-10-10",
                    [("FAB-LAMP", "4", "35.00", "22")],
                    "Invoice in USD, contract in EUR",
                    "accepted", "flagged", ["CURRENCY"], currency="USD"),
        InvoiceSpec("08_price_within_cap.xml", "S-IT-02", "CF-26-0461", "2026-10-12",
                    [("CON-PAPER", "10", "22.30", "22")],
                    "Paper price +1.83%, within the 3% cap: human confirms the adjustment",
                    "accepted", "flagged", ["PRICE_INCREASE_WITHIN_CAP"]),
        InvoiceSpec("09_clean_above_threshold.xml", "S-IT-03", "NWL-2026-320", "2026-10-13",
                    [("NW-PALLET", "8", "145.00", "22")],
                    "Clean, but total is above the auto-approve threshold",
                    "accepted", "pending_review", []),
        InvoiceSpec("10_iban_recently_changed.xml", "S-IT-04", "TS-10-2026-77", "2026-10-10",
                    [("TS-CABLE", "10", "9.90", "22")],
                    "IBAN matches master data, but it was changed 12 days earlier",
                    "accepted", "flagged", ["IBAN_RECENTLY_CHANGED"]),
        InvoiceSpec("11_unknown_sku.xml", "S-IT-01", "FA-2026-0111", "2026-10-14",
                    [("FAB-SOFA", "1", "390.00", "22")],
                    "Item not priced in the contract",
                    "accepted", "flagged", ["SKU_NOT_IN_CONTRACT"]),
        InvoiceSpec("12_expired_contract.xml", "S-IT-05", "AD-2026-10", "2026-10-15",
                    [("AD-CLEAN", "1", "450.00", "22")],
                    "The only contract with this supplier expired on 2025-12-31",
                    "accepted", "flagged", ["NO_VALID_CONTRACT"]),
        # ---- v1b: PDF (3 layouts), noisy scan, KSeF -------------------------------------
        InvoiceSpec("13_pdf_clean_layout_a.pdf", "S-IT-02", "CF-26-0470", "2026-10-16",
                    [("CON-PAPER", "5", "21.90", "22"), ("CON-BINDER", "2", "18.40", "22")],
                    "PDF (layout A), clean, high OCR confidence",
                    "accepted", "auto_approved", [], layout="pdf_a"),
        InvoiceSpec("14_pdf_wrong_price_layout_b.pdf", "S-IT-01", "FA-2026-0120", "2026-10-17",
                    [("FAB-DESK", "2", "260.00", "22")],
                    "PDF (layout B), desk price +8.3% vs contract; IBAN only via query field",
                    "accepted", "flagged", ["PRICE_ABOVE_CAP"], layout="pdf_b"),
        InvoiceSpec("15_pdf_clean_layout_c.pdf", "S-IT-03", "NWL-2026-330", "2026-10-18",
                    [("NW-STORAGE", "30", "12.00", "22")],
                    "PDF (layout C), clean; PO number only via query field",
                    "accepted", "auto_approved", [], layout="pdf_c"),
        InvoiceSpec("16_scan_low_quality.jpg", "S-IT-02", "CF-26-0475", "2026-10-19",
                    [("CON-TONER", "2", "64.00", "22")],
                    "Noisy scan: total and IBAN read with low confidence → human review",
                    "accepted", "pending_review", [], layout="scan",
                    expected_needs_review=["currency", "iban", "total"]),
        InvoiceSpec("17_ksef_clean.xml", "S-PL-01", "WT/2026/10/015", "2026-10-20",
                    [("WT-BOX", "200", "6.50", "23")],
                    "KSeF FA(3), clean, below the PLN threshold",
                    "accepted", "auto_approved", [], layout="ksef"),
        InvoiceSpec("18_ksef_wrong_price.xml", "S-PL-02", "LW-2026-311", "2026-10-21",
                    [("LW-LIC", "1", "1290.00", "23")],
                    "KSeF FA(3), licence price +7.5% vs contract",
                    "accepted", "flagged", ["PRICE_ABOVE_CAP"], layout="ksef"),
    ]


# ---------------------------------------------------------------------------- amounts
@dataclass
class Computed:
    lines: list[dict[str, Any]]
    base_by_rate: dict[Decimal, Decimal]
    vat_by_rate: dict[Decimal, Decimal]
    subtotal: Decimal
    vat_total: Decimal
    total: Decimal
    due: str


def compute(spec: InvoiceSpec, supplier: SupplierSpec) -> Computed:
    lines: list[dict[str, Any]] = []
    base: dict[Decimal, Decimal] = {}
    for idx, (sku, qty, price, rate) in enumerate(spec.lines, start=1):
        q, p, r = Decimal(qty), Decimal(price), Decimal(rate)
        amount = line_amount(q, p)
        base[r] = base.get(r, Decimal("0")) + amount
        desc, _, unit = supplier.prices.get(sku, ("Item not in price list", "", "pz"))
        lines.append({"no": idx, "sku": sku, "desc": desc, "unit": unit, "qty": q, "price": p,
                      "rate": r, "amount": amount})
    vat = {r: vat_amount(b, r) for r, b in base.items()}
    subtotal = sum(base.values(), Decimal("0"))
    vat_total = sum(vat.values(), Decimal("0"))
    total = round_money(subtotal + vat_total) + Decimal(spec.total_delta)
    due = (date.fromisoformat(spec.day) + timedelta(days=supplier.terms_days)).isoformat()
    return Computed(lines, base, vat, subtotal, vat_total, total, due)


def _sub(parent: etree._Element, tag: str, text: str | None = None,
         **attrs: str) -> etree._Element:
    el = etree.SubElement(parent, tag, **attrs)
    if text is not None:
        el.text = text
    return el


# ---------------------------------------------------------------------------- FatturaPA
def _party(parent: etree._Element, tag: str, country: str, code: str, name: str) -> None:
    party = _sub(parent, tag)
    anag = _sub(party, "DatiAnagrafici")
    vat = _sub(anag, "IdFiscaleIVA")
    _sub(vat, "IdPaese", country)
    _sub(vat, "IdCodice", code)
    _sub(_sub(anag, "Anagrafica"), "Denominazione", name)
    if tag == "CedentePrestatore":
        _sub(anag, "RegimeFiscale", "RF01")
    sede = _sub(party, "Sede")
    _sub(sede, "Indirizzo", "Via Esempio 1")
    _sub(sede, "CAP", "20100")
    _sub(sede, "Comune", "Milano")
    _sub(sede, "Nazione", "IT")


def build_fatturapa(spec: InvoiceSpec, supplier: SupplierSpec, c: Computed) -> bytes:
    root = etree.Element(f"{{{NS_FATTURAPA}}}FatturaElettronica", nsmap={"p": NS_FATTURAPA},
                         versione="FPR12")
    header = _sub(root, "FatturaElettronicaHeader")
    trasm = _sub(header, "DatiTrasmissione")
    tid = _sub(trasm, "IdTrasmittente")
    _sub(tid, "IdPaese", "IT")
    _sub(tid, "IdCodice", supplier.vat_code)
    _sub(trasm, "ProgressivoInvio", spec.transmission_no)
    _sub(trasm, "FormatoTrasmissione", "FPR12")
    _sub(trasm, "CodiceDestinatario", "0000000")
    _party(header, "CedentePrestatore", "IT", supplier.vat_code, supplier.name)
    _party(header, "CessionarioCommittente", BUYER_IT["vat"][0], BUYER_IT["vat"][1],
           str(BUYER_IT["name"]))

    body = _sub(root, "FatturaElettronicaBody")
    generali = _sub(body, "DatiGenerali")
    doc = _sub(generali, "DatiGeneraliDocumento")
    _sub(doc, "TipoDocumento", "TD01")
    _sub(doc, "Divisa", spec.currency or supplier.currency)
    _sub(doc, "Data", spec.day)
    _sub(doc, "Numero", spec.number)
    _sub(doc, "ImportoTotaleDocumento", f"{c.total:.2f}")
    _sub(_sub(generali, "DatiOrdineAcquisto"), "IdDocumento", f"PO-{supplier.id}-001")

    beni = _sub(body, "DatiBeniServizi")
    for ln in c.lines:
        line = _sub(beni, "DettaglioLinee")
        _sub(line, "NumeroLinea", str(ln["no"]))
        code = _sub(line, "CodiceArticolo")
        _sub(code, "CodiceTipo", "SKU")
        _sub(code, "CodiceValore", ln["sku"])
        _sub(line, "Descrizione", ln["desc"])
        _sub(line, "Quantita", f"{ln['qty']:.2f}")
        _sub(line, "UnitaMisura", ln["unit"])
        _sub(line, "PrezzoUnitario", f"{ln['price']:.2f}")
        _sub(line, "PrezzoTotale", f"{ln['amount']:.2f}")
        _sub(line, "AliquotaIVA", f"{ln['rate']:.2f}")
    for rate, base in sorted(c.base_by_rate.items()):
        riep = _sub(beni, "DatiRiepilogo")
        _sub(riep, "AliquotaIVA", f"{rate:.2f}")
        _sub(riep, "ImponibileImporto", f"{base:.2f}")
        _sub(riep, "Imposta", f"{c.vat_by_rate[rate]:.2f}")
        _sub(riep, "EsigibilitaIVA", "I")

    pagamento = _sub(body, "DatiPagamento")
    _sub(pagamento, "CondizioniPagamento", "TP02")
    dett = _sub(pagamento, "DettaglioPagamento")
    _sub(dett, "ModalitaPagamento", "MP05")
    _sub(dett, "DataScadenzaPagamento", c.due)
    _sub(dett, "ImportoPagamento", f"{c.total:.2f}")
    _sub(dett, "IBAN", spec.iban or supplier.iban)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ---------------------------------------------------------------------------- KSeF FA(3)
_PL_RATE_SLOT = {Decimal("23"): "1", Decimal("8"): "2", Decimal("5"): "3"}


def build_ksef(spec: InvoiceSpec, supplier: SupplierSpec, c: Computed) -> bytes:
    root = etree.Element(f"{{{NS_KSEF}}}Faktura", nsmap={None: NS_KSEF})
    nag = _sub(root, f"{{{NS_KSEF}}}Naglowek")
    _sub(nag, f"{{{NS_KSEF}}}KodFormularza", "FA", kodSystemowy="FA (3)", wersjaSchemy="1-0E")
    _sub(nag, f"{{{NS_KSEF}}}WariantFormularza", "3")
    _sub(nag, f"{{{NS_KSEF}}}DataWytworzeniaFa", f"{spec.day}T09:00:00Z")
    _sub(nag, f"{{{NS_KSEF}}}SystemInfo", "InvoiceGuard synthetic generator")

    def party(tag: str, nip: str, name: str, prefix: bool) -> None:
        p = _sub(root, f"{{{NS_KSEF}}}{tag}")
        if prefix:
            _sub(p, f"{{{NS_KSEF}}}PrefiksPodatnika", "PL")
        ids = _sub(p, f"{{{NS_KSEF}}}DaneIdentyfikacyjne")
        _sub(ids, f"{{{NS_KSEF}}}NIP", nip)
        _sub(ids, f"{{{NS_KSEF}}}Nazwa", name)
        adr = _sub(p, f"{{{NS_KSEF}}}Adres")
        _sub(adr, f"{{{NS_KSEF}}}KodKraju", "PL")
        _sub(adr, f"{{{NS_KSEF}}}AdresL1", "ul. Przykładowa 1, 00-001 Warszawa")

    party("Podmiot1", supplier.vat_code, supplier.name, prefix=True)
    party("Podmiot2", BUYER_PL["nip"], BUYER_PL["name"], prefix=False)

    fa = _sub(root, f"{{{NS_KSEF}}}Fa")
    _sub(fa, f"{{{NS_KSEF}}}KodWaluty", spec.currency or supplier.currency)
    _sub(fa, f"{{{NS_KSEF}}}P_1", spec.day)
    _sub(fa, f"{{{NS_KSEF}}}P_1M", "Warszawa")
    _sub(fa, f"{{{NS_KSEF}}}P_2", spec.number)
    for rate, base in sorted(c.base_by_rate.items(), reverse=True):
        slot = _PL_RATE_SLOT[rate]
        _sub(fa, f"{{{NS_KSEF}}}P_13_{slot}", f"{base:.2f}")
        _sub(fa, f"{{{NS_KSEF}}}P_14_{slot}", f"{c.vat_by_rate[rate]:.2f}")
    _sub(fa, f"{{{NS_KSEF}}}P_15", f"{c.total:.2f}")
    _sub(fa, f"{{{NS_KSEF}}}RodzajFaktury", "VAT")
    for ln in c.lines:
        row = _sub(fa, f"{{{NS_KSEF}}}FaWiersz")
        _sub(row, f"{{{NS_KSEF}}}NrWierszaFa", str(ln["no"]))
        _sub(row, f"{{{NS_KSEF}}}Indeks", ln["sku"])
        _sub(row, f"{{{NS_KSEF}}}P_7", ln["desc"])
        _sub(row, f"{{{NS_KSEF}}}P_8A", ln["unit"])
        _sub(row, f"{{{NS_KSEF}}}P_8B", f"{ln['qty']:.2f}")
        _sub(row, f"{{{NS_KSEF}}}P_9A", f"{ln['price']:.2f}")
        _sub(row, f"{{{NS_KSEF}}}P_11", f"{ln['amount']:.2f}")
        _sub(row, f"{{{NS_KSEF}}}P_12", f"{ln['rate']:.0f}")
    pay = _sub(fa, f"{{{NS_KSEF}}}Platnosc")
    _sub(_sub(pay, f"{{{NS_KSEF}}}TerminPlatnosci"), f"{{{NS_KSEF}}}Termin", c.due)
    _sub(pay, f"{{{NS_KSEF}}}FormaPlatnosci", "6")
    _sub(_sub(pay, f"{{{NS_KSEF}}}RachunekBankowy"), f"{{{NS_KSEF}}}NrRB",
         (spec.iban or supplier.iban)[2:])
    zam = _sub(_sub(fa, f"{{{NS_KSEF}}}WarunkiTransakcji"), f"{{{NS_KSEF}}}Zamowienia")
    _sub(zam, f"{{{NS_KSEF}}}DataZamowienia", "2026-09-15")
    _sub(zam, f"{{{NS_KSEF}}}NrZamowienia", f"PO-{supplier.id}-001")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ---------------------------------------------------------------------------- PDF / scan
def _text_block(spec: InvoiceSpec, supplier: SupplierSpec, c: Computed) -> dict[str, Any]:
    cur = spec.currency or supplier.currency
    return {
        "supplier": supplier.name, "vat": f"IT{supplier.vat_code}",
        "number": spec.number, "date": spec.day, "due": c.due, "po": f"PO-{supplier.id}-001",
        "buyer": BUYER_IT["name"], "iban": spec.iban or supplier.iban, "cur": cur,
        "rows": [(ln["sku"], ln["desc"], f"{ln['qty']:.2f}", f"{ln['price']:.2f}",
                  f"{ln['rate']:.0f}%", f"{ln['amount']:.2f}") for ln in c.lines],
        "subtotal": f"{c.subtotal:.2f}", "vat_total": f"{c.vat_total:.2f}",
        "total": f"{c.total:.2f}",
    }


def build_pdf(layout: str, block: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4, invariant=1)  # invariant → reproducible bytes
    width, height = A4
    y = height - 60
    if layout == "pdf_a":  # classic
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(50, y, block["supplier"])
        pdf.setFont("Helvetica", 10)
        pdf.drawString(50, y - 16, f"VAT ID: {block['vat']}")
        pdf.drawRightString(width - 50, y, f"INVOICE {block['number']}")
        pdf.drawRightString(width - 50, y - 16, f"Date: {block['date']}  Due: {block['due']}")
        pdf.drawString(50, y - 40, f"Bill to: {block['buyer']}")
        pdf.drawString(50, y - 56, f"Purchase order: {block['po']}")
        y -= 90
    elif layout == "pdf_b":  # header band
        pdf.setFillColor(colors.HexColor("#1F3A5F"))
        pdf.rect(0, height - 100, width, 100, stroke=0, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 20)
        pdf.drawString(40, height - 55, block["supplier"])
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, height - 75, f"P.IVA {block['vat']}")
        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, height - 125, f"Fattura n. {block['number']} del {block['date']}")
        pdf.drawString(40, height - 140, f"Scadenza: {block['due']}  |  Ordine: {block['po']}")
        y = height - 175
    else:  # pdf_c: compact two-column
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(40, y, block["supplier"])
        pdf.setFont("Helvetica", 8)
        pdf.drawString(40, y - 12, f"Tax ID {block['vat']}")
        pdf.drawString(320, y, f"Invoice: {block['number']}")
        pdf.drawString(320, y - 12, f"Issued: {block['date']}")
        pdf.drawString(320, y - 24, f"Payable by: {block['due']}")
        pdf.drawString(320, y - 36, f"Your order ref: {block['po']}")
        y -= 70
    pdf.setFont("Helvetica-Bold", 9)
    cols = (40, 110, 330, 380, 450, 500)
    for x, title in zip(cols, ("SKU", "Description", "Qty", "Unit", "VAT", "Amount"), strict=True):
        pdf.drawString(x, y, title)
    pdf.setFont("Helvetica", 9)
    for row in block["rows"]:
        y -= 16
        for x, value in zip(cols, row, strict=True):
            pdf.drawString(x, y, str(value))
    y -= 30
    for label, key in (("Subtotal", "subtotal"), ("VAT", "vat_total"), ("TOTAL", "total")):
        pdf.drawRightString(width - 60, y, f"{label}: {block[key]} {block['cur']}")
        y -= 14
    pdf.drawString(40, 80, f"Bank transfer to IBAN {block['iban']}")
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


def build_scan(block: dict[str, Any], rng: random.Random) -> bytes:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    img = Image.new("L", (1240, 1754), color=250)
    draw = ImageDraw.Draw(img)
    big, small = ImageFont.load_default(size=40), ImageFont.load_default(size=24)
    y = 80
    draw.text((80, y), block["supplier"], fill=20, font=big)
    for line in (f"VAT ID {block['vat']}", f"Invoice {block['number']}  Date {block['date']}",
                 f"Due {block['due']}  PO {block['po']}", ""):
        y += 50
        draw.text((80, y), line, fill=30, font=small)
    for row in block["rows"]:
        y += 40
        draw.text((80, y), "   ".join(str(v) for v in row), fill=30, font=small)
    y += 80
    for label, key in (("Subtotal", "subtotal"), ("VAT", "vat_total"), ("TOTAL", "total")):
        draw.text((700, y), f"{label}: {block[key]} {block['cur']}", fill=40, font=small)
        y += 36
    draw.text((80, 1600), f"IBAN {block['iban']}", fill=60, font=small)
    for _ in range(4000):  # speckle noise
        draw.point((rng.randrange(1240), rng.randrange(1754)), fill=rng.randrange(0, 160))
    img = img.rotate(rng.uniform(-2.5, 2.5), resample=Image.Resampling.BILINEAR, fillcolor=250)
    img = img.filter(ImageFilter.GaussianBlur(radius=1.2))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=35)
    return out.getvalue()


# ---------------------------------------------------------------------------- DI recordings
def _f(value: Decimal) -> float:
    return float(value)


def simulated_recording(spec: InvoiceSpec, supplier: SupplierSpec, c: Computed,
                        rng: random.Random) -> dict[str, Any]:
    """REST-shaped prebuilt-invoice result (API 2024-11-30) with simulated confidences."""
    scan = spec.layout == "scan"
    low = {"InvoiceTotal": 0.61, "IBAN": 0.58, "PaymentIBAN": 0.55} if scan else {}

    def conf(name: str) -> float:
        if name in low:
            return low[name]
        return round(rng.uniform(0.82, 0.9) if scan else rng.uniform(0.9, 0.99), 3)

    cur = spec.currency or supplier.currency

    def money(value: Decimal, name: str) -> dict[str, Any]:
        return {"type": "currency", "valueCurrency": {"amount": _f(value), "currencyCode": cur},
                "content": f"{value:.2f}", "confidence": conf(name)}

    def text(value: str, name: str) -> dict[str, Any]:
        return {"type": "string", "valueString": value, "content": value, "confidence": conf(name)}

    def day(value: str, name: str) -> dict[str, Any]:
        return {"type": "date", "valueDate": value, "content": value, "confidence": conf(name)}

    iban = spec.iban or supplier.iban
    fields: dict[str, Any] = {
        "VendorName": text(supplier.name, "VendorName"),
        "VendorTaxId": text(f"IT{supplier.vat_code}", "VendorTaxId"),
        "CustomerName": text(str(BUYER_IT["name"]), "CustomerName"),
        "InvoiceId": text(spec.number, "InvoiceId"),
        "InvoiceDate": day(spec.day, "InvoiceDate"),
        "DueDate": day(c.due, "DueDate"),
        "SubTotal": money(c.subtotal, "SubTotal"),
        "TotalTax": money(c.vat_total, "TotalTax"),
        "InvoiceTotal": money(c.total, "InvoiceTotal"),
        "Items": {"type": "array", "valueArray": [
            {"type": "object", "confidence": conf("Item"), "valueObject": {
                "ProductCode": text(ln["sku"], "ProductCode"),
                "Description": text(ln["desc"], "Description"),
                "Quantity": {"type": "number", "valueNumber": _f(ln["qty"]),
                             "content": f"{ln['qty']:.2f}", "confidence": conf("Quantity")},
                "UnitPrice": money(ln["price"], "UnitPrice"),
                "Amount": money(ln["amount"], "Amount"),
                "TaxRate": text(f"{ln['rate']:.0f}%", "TaxRate"),
            }} for ln in c.lines]},
    }
    if spec.layout != "pdf_c":
        fields["PurchaseOrder"] = text(f"PO-{supplier.id}-001", "PurchaseOrder")
    if spec.layout not in ("pdf_b",):
        fields["PaymentDetails"] = {"type": "array", "valueArray": [
            {"type": "object", "valueObject": {"IBAN": text(iban, "PaymentIBAN")}}]}
    # query fields (features=queryFields)
    fields["PurchaseOrderNumber"] = text(f"PO-{supplier.id}-001", "PurchaseOrderNumber")
    fields["IBAN"] = text(iban, "IBAN")
    return {
        "_recording": {"source": "simulated",
                       "note": "Generated from synthetic ground truth; replace with a live "
                               "recording via `make record` (scripts/record_responses.py)."},
        "apiVersion": "2024-11-30",
        "modelId": "prebuilt-invoice",
        "documents": [{"docType": "invoice", "confidence": conf("doc"), "fields": fields}],
    }


# ---------------------------------------------------------------------------- main
def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def generate(out: Path, seed: int = 42) -> dict[str, int]:
    """Generate the full synthetic dataset into ``out`` (overwrites generated folders)."""
    rng = random.Random(seed)
    for spec in SUPPLIERS:
        spec.iban = build_iban(spec.country, _bban(rng, spec.country))
    alt_iban = build_iban("IT", _bban(rng, "IT"))
    by_id = {s.id: s for s in SUPPLIERS}

    for sub in ("seed", "invoices", "labels", "recorded/document_intelligence"):
        shutil.rmtree(out / sub, ignore_errors=True)
        (out / sub).mkdir(parents=True)

    suppliers, contracts, prices, pos, receipts = [], [], [], [], []
    for s in SUPPLIERS:
        suppliers.append({"id": s.id, "name": s.name, "vat_id": f"{s.country}{s.vat_code}",
                          "country": s.country, "currency": s.currency, "iban_on_file": s.iban,
                          "iban_last_changed_at": s.iban_changed, "status": "active"})
        contract_id = f"C-{s.id}-v1"
        contracts.append({"id": contract_id, "supplier_id": s.id, "version": 1,
                          "valid_from": s.contract_from, "valid_to": s.contract_to,
                          "supersedes_contract_id": None, "payment_terms_days": s.terms_days,
                          "early_payment_discount_pct": "2.0", "late_penalty_pct": "1.5",
                          "max_price_increase_pct": "3.0", "currency": s.currency,
                          "source_document_uri": f"contracts/{contract_id}.pdf"})
        for sku, (desc, price, unit) in s.prices.items():
            prices.append({"contract_id": contract_id, "sku": sku, "description": desc,
                           "unit_price": price, "currency": s.currency, "unit": unit})
        po_number = f"PO-{s.id}-001"
        po_lines = [{"sku": sku, "quantity": "300", "unit_price": price}
                    for sku, (_, price, _) in s.prices.items()]
        pos.append({"po_number": po_number, "supplier_id": s.id, "status": "open",
                    "lines": po_lines})
        receipts.append({"id": f"GR-{s.id}-001", "po_number": po_number,
                         "received_at": "2026-09-30",
                         "lines": [{"sku": ln["sku"], "quantity_received": "300"}
                                   for ln in po_lines]})

    seed_dir = out / "seed"
    _write_json(seed_dir / "suppliers.json", suppliers)
    _write_json(seed_dir / "contracts.json", contracts)
    _write_json(seed_dir / "contract_price_items.json", prices)
    _write_json(seed_dir / "purchase_orders.json", pos)
    _write_json(seed_dir / "goods_receipts.json", receipts)

    specs = _invoice_specs(alt_iban)
    for spec in specs:
        supplier = by_id[spec.supplier]
        c = compute(spec, supplier)
        if spec.layout == "xml":
            content = build_fatturapa(spec, supplier, c)
        elif spec.layout == "ksef":
            content = build_ksef(spec, supplier, c)
        elif spec.layout == "scan":
            content = build_scan(_text_block(spec, supplier, c), rng)
        else:
            content = build_pdf(spec.layout, _text_block(spec, supplier, c))
        (out / "invoices" / spec.file).write_bytes(content)
        if spec.layout.startswith(("pdf", "scan")):
            _write_json(out / "recorded" / "document_intelligence"
                        / f"{hashlib.sha256(content).hexdigest()}.json",
                        simulated_recording(spec, supplier, c, rng))
        _write_json(out / "labels" / f"{Path(spec.file).stem}.json", {
            "file": spec.file,
            "description": spec.description,
            "format": spec.layout,
            "supplier_id": spec.supplier,
            "invoice_number": spec.number,
            "expected_fields": {"invoice_date": spec.day,
                                "currency": spec.currency or supplier.currency,
                                "subtotal": f"{c.subtotal:.2f}",
                                "vat_amount": f"{c.vat_total:.2f}",
                                "total": f"{c.total:.2f}"},
            "expected_submission_status": spec.expected_submission_status,
            "expected_invoice_status": spec.expected_invoice_status,
            "expected_anomalies": sorted(spec.expected_anomalies),
            "expected_needs_review": sorted(spec.expected_needs_review),
        })
    return {"suppliers": len(suppliers), "contracts": len(contracts), "invoices": len(specs)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(generate(args.out, args.seed))  # noqa: T201


if __name__ == "__main__":
    main()

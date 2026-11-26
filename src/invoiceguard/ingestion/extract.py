"""Extraction service: route by detected format.

* FatturaPA / KSeF XML → parsed directly (preferred: structured, confidence 1.0)
* PDF / image → Document Intelligence adapter (real in Azure mode, recorded in mock mode)
"""

from invoiceguard.adapters.document_intelligence import InvoiceAnalyzer
from invoiceguard.domain.models import ExtractedInvoice
from invoiceguard.ingestion.detect import InvoiceFormat, detect_format
from invoiceguard.ingestion.di_mapping import map_invoice_result
from invoiceguard.ingestion.errors import UnsupportedFormatError
from invoiceguard.ingestion.fatturapa import parse_fatturapa
from invoiceguard.ingestion.ksef import parse_ksef


class InvoiceExtractor:
    """Turns file bytes into an ``ExtractedInvoice`` or raises ``ExtractionError``."""

    def __init__(self, analyzer: InvoiceAnalyzer | None = None) -> None:
        self._analyzer = analyzer

    def extract(self, content: bytes) -> tuple[ExtractedInvoice, str]:
        """Return the invoice and a short description of the extraction source."""
        detected = detect_format(content)
        if detected is InvoiceFormat.FATTURAPA:
            return parse_fatturapa(content), "xml:fatturapa"
        if detected is InvoiceFormat.KSEF:
            return parse_ksef(content), "xml:ksef"
        if self._analyzer is None:
            raise UnsupportedFormatError(
                f"format '{detected.value}' needs Document Intelligence, which is not configured"
            )
        result = self._analyzer.analyze_invoice(content)
        return map_invoice_result(result), f"document_intelligence:{self._analyzer.source_label}"

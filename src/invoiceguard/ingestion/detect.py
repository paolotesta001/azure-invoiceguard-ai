"""Detect the invoice file format from its bytes (never trust the file extension)."""

from enum import StrEnum

from invoiceguard.ingestion.errors import UnsupportedFormatError
from invoiceguard.ingestion.xml_safety import local_name, parse_xml


class InvoiceFormat(StrEnum):
    FATTURAPA = "fatturapa_xml"
    KSEF = "ksef_xml"
    PDF = "pdf"
    IMAGE = "image"


_IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*")


def detect_format(content: bytes) -> InvoiceFormat:
    """Return the detected format or raise ``UnsupportedFormatError``."""
    head = content.lstrip(b"\xef\xbb\xbf \t\r\n")[:8]
    if head.startswith(b"%PDF"):
        return InvoiceFormat.PDF
    if any(head.startswith(magic) for magic in _IMAGE_MAGIC):
        return InvoiceFormat.IMAGE
    if head.startswith(b"<"):
        root_name = local_name(parse_xml(content))
        if root_name == "FatturaElettronica":
            return InvoiceFormat.FATTURAPA
        if root_name == "Faktura":
            return InvoiceFormat.KSEF
        raise UnsupportedFormatError(f"unknown XML document type <{root_name}>")
    raise UnsupportedFormatError("unrecognised file format (expected XML, PDF or image)")

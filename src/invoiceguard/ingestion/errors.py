"""Extraction errors. All are permanent: retrying the same bytes gives the same result."""


class ExtractionError(Exception):
    """The file could not be turned into an ``ExtractedInvoice``."""


class UnsupportedFormatError(ExtractionError):
    """The file format is recognised but not handled in this configuration, or unknown."""

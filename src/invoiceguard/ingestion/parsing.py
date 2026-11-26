"""Small typed helpers shared by the XML parsers."""

from datetime import date
from decimal import Decimal, InvalidOperation

from invoiceguard.ingestion.errors import ExtractionError


def parse_decimal(raw: str, label: str) -> Decimal:
    """Parse a decimal string or raise ``ExtractionError`` naming the element."""
    try:
        return Decimal(raw.strip().replace(",", "."))
    except InvalidOperation as exc:
        raise ExtractionError(f"{label} is not a number: {raw!r}") from exc


def parse_date(raw: str, label: str) -> date:
    """Parse an ISO date (YYYY-MM-DD) or raise ``ExtractionError``."""
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ExtractionError(f"{label} is not an ISO date: {raw!r}") from exc

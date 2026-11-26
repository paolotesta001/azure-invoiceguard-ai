"""IBAN utilities (ISO 13616 mod-97 checksum)."""

import re

_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{8,30}$")


def normalize_iban(value: str) -> str:
    """Remove spaces and upper-case the IBAN."""
    return re.sub(r"\s+", "", value).upper()


def _to_digits(text: str) -> str:
    return "".join(str(int(ch, 36)) for ch in text)


def is_valid_iban(value: str) -> bool:
    """Validate format and mod-97 checksum."""
    iban = normalize_iban(value)
    if not _IBAN_RE.match(iban):
        return False
    rearranged = iban[4:] + iban[:4]
    return int(_to_digits(rearranged)) % 97 == 1


def build_iban(country: str, bban: str) -> str:
    """Build a valid IBAN from a country code and BBAN (used for synthetic data)."""
    country = country.upper()
    bban = normalize_iban(bban)
    remainder = int(_to_digits(bban + country + "00")) % 97
    return f"{country}{98 - remainder:02d}{bban}"

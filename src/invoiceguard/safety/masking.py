"""Data minimisation: mask IBANs and personal data before logging or auditing."""

from collections.abc import Mapping

from pydantic import JsonValue

from invoiceguard.domain.iban import normalize_iban

_SENSITIVE_KEY_FRAGMENTS = ("iban",)


def mask_iban(value: str | None) -> str | None:
    """Keep the first 4 and last 4 characters, e.g. ``IT60 **** **** 3456``."""
    if value is None:
        return None
    iban = normalize_iban(value)
    if len(iban) <= 8:
        return "****"
    return f"{iban[:4]} **** **** {iban[-4:]}"


def mask_payload(payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Recursively mask values whose key looks sensitive (e.g. contains ``iban``)."""
    masked: dict[str, JsonValue] = {}
    for key, value in payload.items():
        if any(fragment in key.lower() for fragment in _SENSITIVE_KEY_FRAGMENTS):
            masked[key] = mask_iban(value) if isinstance(value, str) else value
        elif isinstance(value, Mapping):
            masked[key] = mask_payload(value)
        elif isinstance(value, list):
            masked[key] = [mask_payload(v) if isinstance(v, Mapping) else v for v in value]
        else:
            masked[key] = value
    return masked

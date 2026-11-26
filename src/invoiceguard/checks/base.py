"""Shared types for deterministic checks. Checks are pure functions: context in, findings out."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import JsonValue

from invoiceguard.config import ValidationSettings
from invoiceguard.domain.enums import AnomalyType, Severity
from invoiceguard.domain.models import Contract, ContractPriceItem, ExtractedInvoice, Supplier


@dataclass(frozen=True)
class CheckContext:
    """Everything a check may look at. Built once per validation run."""

    invoice: ExtractedInvoice
    supplier: Supplier
    contract: Contract | None
    price_items: Mapping[str, ContractPriceItem]
    settings: ValidationSettings


@dataclass(frozen=True)
class Finding:
    """A rule violation. Becomes an ``Anomaly`` when persisted."""

    type: AnomalyType
    severity: Severity
    message: str
    monetary_impact: Decimal | None = None
    evidence: Mapping[str, JsonValue] = field(default_factory=dict)


Check = Callable[[CheckContext], list[Finding]]

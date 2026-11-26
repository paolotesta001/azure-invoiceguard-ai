"""Pydantic v2 domain models. Money and quantities are ``Decimal``, never ``float``."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from invoiceguard.domain.enums import (
    AnomalyType,
    Country,
    DecisionType,
    DetectedBy,
    InvoiceStatus,
    Mode,
    PurchaseOrderStatus,
    RunStatus,
    Severity,
    SourceType,
    SubmissionStatus,
    SupplierStatus,
)

CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DomainModel(BaseModel):
    """Base class: immutable, strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Master data -------------------------------------------------------------------------


class Supplier(DomainModel):
    id: str
    name: str
    vat_id: str
    country: Country
    currency: CurrencyCode
    iban_on_file: str
    iban_last_changed_at: date | None = None
    status: SupplierStatus = SupplierStatus.ACTIVE


class Contract(DomainModel):
    id: str
    supplier_id: str
    version: int = Field(ge=1)
    valid_from: date
    valid_to: date
    supersedes_contract_id: str | None = None
    payment_terms_days: int = Field(ge=0)
    early_payment_discount_pct: Decimal = Decimal("0")
    late_penalty_pct: Decimal = Decimal("0")
    max_price_increase_pct: Decimal = Field(ge=0)
    currency: CurrencyCode
    source_document_uri: str | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> "Contract":
        if self.valid_to < self.valid_from:
            raise ValueError("valid_to must be on or after valid_from")
        return self

    def is_valid_on(self, day: date) -> bool:
        """True if the contract is in force on ``day`` (inclusive bounds)."""
        return self.valid_from <= day <= self.valid_to


class ContractPriceItem(DomainModel):
    contract_id: str
    sku: str
    description: str
    unit_price: Decimal = Field(gt=0)
    currency: CurrencyCode
    unit: str


class PurchaseOrderLine(DomainModel):
    sku: str
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(gt=0)


class PurchaseOrder(DomainModel):
    po_number: str
    supplier_id: str
    status: PurchaseOrderStatus
    lines: tuple[PurchaseOrderLine, ...]


class GoodsReceiptLine(DomainModel):
    sku: str
    quantity_received: Decimal = Field(ge=0)


class GoodsReceipt(DomainModel):
    id: str
    po_number: str
    received_at: date
    lines: tuple[GoodsReceiptLine, ...]


# --- Invoices ----------------------------------------------------------------------------


class ExtractedInvoiceLine(DomainModel):
    line_no: int = Field(ge=1)
    sku: str | None
    description: str
    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal = Field(ge=0)
    line_total: Decimal


class ExtractedInvoice(DomainModel):
    """Invoice data as extracted from XML or OCR, before validation.

    ``field_confidence`` maps header fields (e.g. ``total``) and aggregated line fields
    (e.g. ``lines.unit_price`` = lowest confidence across lines) to a score in [0, 1].
    """

    source_type: SourceType
    supplier_vat_id: str
    supplier_name: str
    invoice_number: str
    invoice_date: date
    due_date: date | None = None
    currency: CurrencyCode
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    iban: str | None = None
    po_number: str | None = None
    lines: tuple[ExtractedInvoiceLine, ...] = Field(min_length=1)
    field_confidence: dict[str, float] = Field(default_factory=dict)

    def low_confidence_fields(self, threshold: float) -> tuple[str, ...]:
        """Fields whose confidence is below ``threshold`` (sorted)."""
        return tuple(sorted(k for k, v in self.field_confidence.items() if v < threshold))


class InvoiceSubmission(DomainModel):
    """Every uploaded file, including duplicates and failures."""

    id: str
    file_sha256: Sha256Hex
    filename: str
    file_uri: str
    uploaded_by: str
    uploaded_at: datetime
    status: SubmissionStatus
    invoice_id: str | None = None
    duplicate_of_invoice_id: str | None = None
    failure_reason: str | None = None
    retry_count: int = Field(default=0, ge=0)


class Invoice(DomainModel):
    """An accepted invoice. Unique on (supplier_id, data.invoice_number)."""

    id: str
    submission_id: str
    supplier_id: str
    status: InvoiceStatus
    data: ExtractedInvoice
    needs_review_fields: tuple[str, ...] = ()
    created_at: datetime
    status_changed_at: datetime
    reminder_sent_at: datetime | None = None


class Anomaly(DomainModel):
    id: str
    submission_id: str
    invoice_id: str | None
    type: AnomalyType
    severity: Severity
    message: str
    monetary_impact: Decimal | None = None
    evidence: dict[str, JsonValue] = Field(default_factory=dict)
    explanation: str | None = None
    detected_by: DetectedBy = DetectedBy.RULE


class SupplierEmailDraft(DomainModel):
    """Clarification email for a flagged invoice. Draft only: it is never sent by the system."""

    id: str
    invoice_id: str
    subject: str
    body: str
    generated_by: str
    updated_by: str | None = None
    updated_at: datetime


class ValidationRun(DomainModel):
    run_id: Sha256Hex
    submission_id: str
    status: RunStatus
    mode: Mode
    started_at: datetime
    finished_at: datetime | None = None
    latency_ms: int | None = None
    model_deployment: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: Decimal = Decimal("0")


class ApprovalDecision(DomainModel):
    id: str
    invoice_id: str
    decision: DecisionType
    reviewer_id: str
    comment: str | None = None
    signed_token_id: str | None = None
    payment_reference: str | None = None
    decided_at: datetime


class AuditEvent(DomainModel):
    """Append-only record of every step, tool call and human action."""

    id: str
    timestamp: datetime
    actor: str
    event_type: str
    submission_id: str | None = None
    invoice_id: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)

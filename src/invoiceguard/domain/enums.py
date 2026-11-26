"""Enumerations shared across the domain."""

from enum import StrEnum


class Country(StrEnum):
    """Supplier country, used to pick the valid VAT rates."""

    IT = "IT"
    PL = "PL"
    OTHER = "OTHER"


class SupplierStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class PurchaseOrderStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class SourceType(StrEnum):
    XML_FATTURAPA = "xml_fatturapa"
    XML_KSEF = "xml_ksef"
    OCR = "ocr"


class SubmissionStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    ACCEPTED = "accepted"
    DUPLICATE_REJECTED = "duplicate_rejected"
    FAILED = "failed"


class InvoiceStatus(StrEnum):
    PROCESSING = "processing"
    AUTO_APPROVED = "auto_approved"
    FLAGGED = "flagged"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CLARIFICATION_REQUESTED = "clarification_requested"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Numeric rank for sorting (higher is more severe)."""
        return ("low", "medium", "high", "critical").index(self.value)


class AnomalyType(StrEnum):
    ARITHMETIC = "ARITHMETIC"
    VAT_RATE = "VAT_RATE"
    CURRENCY = "CURRENCY"
    NO_VALID_CONTRACT = "NO_VALID_CONTRACT"
    PRICE_ABOVE_CAP = "PRICE_ABOVE_CAP"
    PRICE_INCREASE_WITHIN_CAP = "PRICE_INCREASE_WITHIN_CAP"
    SKU_NOT_IN_CONTRACT = "SKU_NOT_IN_CONTRACT"
    DUPLICATE = "DUPLICATE"
    IBAN_MISSING = "IBAN_MISSING"
    IBAN_INVALID = "IBAN_INVALID"
    IBAN_MISMATCH = "IBAN_MISMATCH"
    IBAN_RECENTLY_CHANGED = "IBAN_RECENTLY_CHANGED"


class DetectedBy(StrEnum):
    RULE = "rule"
    LLM = "llm"


class DecisionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CLARIFICATION = "request_clarification"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Mode(StrEnum):
    MOCK = "mock"
    AZURE = "azure"

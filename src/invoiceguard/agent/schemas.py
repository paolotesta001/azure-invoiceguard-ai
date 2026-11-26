"""Structured-output schemas for the LLM. Strict mode: every field required, no extras."""

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnomalyExplanation(_Strict):
    anomaly_id: str = Field(description="Exactly one of the anomaly ids given in the input.")
    explanation: str = Field(description="2-4 sentences in plain business English for an AP reviewer.")
    cited_evidence: list[str] = Field(
        description="References used, e.g. 'invoice line 1', 'contract C-S-IT-01-v1', 'supplier master data'."
    )


class EmailDraft(_Strict):
    subject: str
    body: str


class InvoiceAnalysis(_Strict):
    explanations: list[AnomalyExplanation]
    supplier_email: EmailDraft | None = Field(
        description="Clarification email to the supplier, or null if nothing needs clarifying."
    )

"""Deterministic mock LLM for mock mode and tests.

It does not call any model: it builds template explanations from the rule messages, clearly
prefixed with "[mock]". Recorded replays are not used for the LLM because prompts contain
run-specific anomaly ids; live quality is measured with Foundry evaluators in v3.
"""

from collections.abc import Mapping
from typing import TypeVar, cast

from pydantic import BaseModel

from invoiceguard.adapters.llm import LlmError, LlmResult, LlmUsage
from invoiceguard.agent.instructions import extract_payload
from invoiceguard.agent.schemas import AnomalyExplanation, EmailDraft, InvoiceAnalysis

T = TypeVar("T", bound=BaseModel)
_NEEDS_SUPPLIER = {"PRICE_ABOVE_CAP", "PRICE_INCREASE_WITHIN_CAP", "SKU_NOT_IN_CONTRACT",
                   "ARITHMETIC", "VAT_RATE", "CURRENCY", "IBAN_MISMATCH"}
_ADVICE = {
    "IBAN_MISMATCH": "Confirm the bank details by calling the supplier on a number from the "
                     "master data, not from the invoice.",
    "IBAN_RECENTLY_CHANGED": "Confirm the bank-account change independently before paying.",
    "PRICE_ABOVE_CAP": "Ask the supplier to justify the price or issue a credit note.",
    "PRICE_INCREASE_WITHIN_CAP": "Check that the supplier gave the required notice for the "
                                 "price adjustment.",
}


class MockLlmClient:
    """Implements ``LlmClient`` deterministically. ``bad_outputs`` simulates N invalid answers."""

    def __init__(self, deployment: str = "mock-llm", bad_outputs: int = 0) -> None:
        self.deployment = deployment
        self._bad_outputs = bad_outputs
        self.calls = 0

    def complete_structured(self, system: str, user: str, schema: type[T]) -> LlmResult[T]:
        self.calls += 1
        if schema is not InvoiceAnalysis:
            raise LlmError(f"mock LLM does not support schema {schema.__name__}")
        usage = LlmUsage(prompt_tokens=(len(system) + len(user)) // 4, completion_tokens=0)
        if self._bad_outputs > 0:
            self._bad_outputs -= 1
            bad = InvoiceAnalysis(explanations=[], supplier_email=None)
            return LlmResult(parsed=cast(T, bad), usage=usage, model=self.deployment)

        payload = extract_payload(user)
        anomalies = cast(list[Mapping[str, object]], payload.get("anomalies") or [])
        explanations = []
        for anomaly in anomalies:
            kind = str(anomaly["type"])
            text = f"[mock] {anomaly['rule_message']}"
            if kind in _ADVICE:
                text += f" {_ADVICE[kind]}"
            explanations.append(AnomalyExplanation(
                anomaly_id=str(anomaly["anomaly_id"]), explanation=text,
                cited_evidence=[f"rule {kind}"]))
        needs_email = any(str(a["type"]) in _NEEDS_SUPPLIER for a in anomalies)
        email = EmailDraft(
            subject=f"[mock] Clarification needed: invoice {payload.get('invoice_number')}",
            body=("[mock] Dear supplier,\n\nwhile checking the invoice above we found the following "
                  "points that need clarification:\n"
                  + "\n".join(f"- {a['rule_message']}" for a in anomalies
                              if str(a["type"]) in _NEEDS_SUPPLIER)
                  + "\n\nCould you please confirm or send a corrected invoice?\n\nKind regards,\n"
                  "Accounts Payable"),
        ) if needs_email else None
        result = InvoiceAnalysis(explanations=explanations, supplier_email=email)
        completion_tokens = len(result.model_dump_json()) // 4
        return LlmResult(parsed=cast(T, result),
                         usage=LlmUsage(usage.prompt_tokens, completion_tokens),
                         model=self.deployment)

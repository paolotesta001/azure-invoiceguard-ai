"""Explains anomalies and drafts supplier emails with one structured LLM call per invoice.

Output is validated beyond the JSON schema: every anomaly id must be explained exactly once and
no unknown ids may appear. Invalid output → one retry → fallback ("explanation unavailable").
Failures never block the pipeline: the deterministic result stands on its own.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from invoiceguard.adapters.llm import LlmClient, LlmError, LlmUsage
from invoiceguard.adapters.retry import TransientError, call_with_retry
from invoiceguard.agent.instructions import SYSTEM_PROMPT, build_user_message
from invoiceguard.agent.schemas import EmailDraft, InvoiceAnalysis
from invoiceguard.domain.models import Anomaly, ExtractedInvoice

logger = logging.getLogger(__name__)
FALLBACK_TEXT = "Explanation unavailable – review the rule message and evidence."
MAX_EXPLANATION_CHARS = 1200


@dataclass(frozen=True)
class ExplanationOutcome:
    explanations: dict[str, str]
    email: EmailDraft | None
    usage: LlmUsage
    model: str
    attempts: int
    fallback: bool
    problems: list[str] = field(default_factory=list)


def validate_analysis(analysis: InvoiceAnalysis | None, anomaly_ids: set[str]) -> list[str]:
    """Return a list of problems; empty means the output is usable."""
    if analysis is None:
        return ["no parsed output (refusal or schema mismatch)"]
    problems: list[str] = []
    seen = [e.anomaly_id for e in analysis.explanations]
    if missing := anomaly_ids - set(seen):
        problems.append(f"missing explanations for {len(missing)} anomaly id(s)")
    if unknown := set(seen) - anomaly_ids:
        problems.append(f"unknown anomaly id(s): {sorted(unknown)}")
    if len(seen) != len(set(seen)):
        problems.append("duplicate anomaly ids")
    if any(not e.explanation.strip() for e in analysis.explanations):
        problems.append("empty explanation")
    return problems


class ExplanationService:
    """Wraps an ``LlmClient`` with validation, retry and fallback."""

    def __init__(self, llm: LlmClient, max_attempts: int = 2) -> None:
        self._llm = llm
        self._max_attempts = max_attempts

    @property
    def deployment(self) -> str:
        return self._llm.deployment

    def explain(self, invoice: ExtractedInvoice, supplier_name: str,
                anomalies: Sequence[Anomaly]) -> ExplanationOutcome:
        """Explain ``anomalies``; never raises for model problems."""
        ids = {a.id for a in anomalies}
        user = build_user_message(invoice, supplier_name, anomalies)
        usage = LlmUsage()
        problems: list[str] = []
        model = self._llm.deployment
        for attempt in range(1, self._max_attempts + 1):
            try:
                result = call_with_retry(
                    lambda: self._llm.complete_structured(SYSTEM_PROMPT, user, InvoiceAnalysis)
                )
            except (TransientError, LlmError) as exc:
                logger.warning("LLM call failed: %s", exc)
                problems.append(str(exc))
                break
            usage = usage + result.usage
            model = result.model
            issues = validate_analysis(result.parsed, ids)
            if not issues and result.parsed is not None:
                texts = {e.anomaly_id: e.explanation.strip()[:MAX_EXPLANATION_CHARS]
                         for e in result.parsed.explanations}
                return ExplanationOutcome(texts, result.parsed.supplier_email, usage, model,
                                          attempt, fallback=False, problems=problems)
            problems.extend(f"attempt {attempt}: {p}" for p in issues)
        return ExplanationOutcome({i: FALLBACK_TEXT for i in ids}, None, usage, model,
                                  len([p for p in problems if p.startswith("attempt")]) or 1,
                                  fallback=True, problems=problems)

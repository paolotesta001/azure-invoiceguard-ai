"""LLM adapter + explanation service, tested without the openai package (fake client)."""

from types import SimpleNamespace
from typing import Any

import pytest

from invoiceguard.adapters.llm import AzureOpenAIClient, LlmError, LlmResult, LlmUsage
from invoiceguard.adapters.retry import TransientError
from invoiceguard.agent.explainer import FALLBACK_TEXT, ExplanationService, validate_analysis
from invoiceguard.agent.instructions import (
    CLOSE_TAG,
    OPEN_TAG,
    SYSTEM_PROMPT,
    build_user_message,
    extract_payload,
)
from invoiceguard.agent.mock_llm import MockLlmClient
from invoiceguard.agent.schemas import AnomalyExplanation, InvoiceAnalysis
from invoiceguard.domain.enums import AnomalyType, Severity
from invoiceguard.domain.models import Anomaly
from tests.conftest import IBAN, make_invoice

ANOMALIES = [
    Anomaly(id="a1", submission_id="s", invoice_id="i", type=AnomalyType.PRICE_ABOVE_CAP,
            severity=Severity.HIGH, message="Line 1: unit price too high.",
            evidence={"invoice_iban": "IT60 **** **** 3456"}),
    Anomaly(id="a2", submission_id="s", invoice_id="i", type=AnomalyType.IBAN_RECENTLY_CHANGED,
            severity=Severity.CRITICAL, message="IBAN changed recently."),
]


class FakeCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.kwargs: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.kwargs.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def fake_client(outcomes: list[Any]) -> tuple[Any, FakeCompletions]:
    completions = FakeCompletions(outcomes)
    return SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=completions))), \
        completions


def completion(parsed: InvoiceAnalysis | None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=None))],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=40), model="gpt-test")


class RateLimitError(Exception):  # same class name as openai.RateLimitError
    response = SimpleNamespace(headers={"retry-after": "0"})


def test_prompt_marks_data_untrusted_and_masks_iban() -> None:
    user = build_user_message(make_invoice(), "Fabrikam", ANOMALIES)
    assert OPEN_TAG in user and CLOSE_TAG in user and "untrusted" in SYSTEM_PROMPT
    assert IBAN not in user and "****" in user
    assert extract_payload(user)["anomalies"][0]["anomaly_id"] == "a1"  # type: ignore[index]


def test_azure_client_parses_structured_output() -> None:
    good = InvoiceAnalysis(explanations=[], supplier_email=None)
    client, calls = fake_client([completion(good)])
    result = AzureOpenAIClient("https://x", "dep", client=client).complete_structured(
        "sys", "user", InvoiceAnalysis)
    assert result.parsed == good and result.usage == LlmUsage(120, 40) and result.model == "gpt-test"
    assert calls.kwargs[0]["response_format"] is InvoiceAnalysis
    assert calls.kwargs[0]["temperature"] == 0


def test_azure_client_maps_errors() -> None:
    client, _ = fake_client([RateLimitError("slow down")])
    with pytest.raises(TransientError):
        AzureOpenAIClient("https://x", "dep", client=client).complete_structured(
            "s", "u", InvoiceAnalysis)
    client, _ = fake_client([ValueError("bad request")])
    with pytest.raises(LlmError):
        AzureOpenAIClient("https://x", "dep", client=client).complete_structured(
            "s", "u", InvoiceAnalysis)


def test_validate_analysis_catches_id_problems() -> None:
    ids = {"a1", "a2"}
    ok = InvoiceAnalysis(explanations=[
        AnomalyExplanation(anomaly_id=i, explanation="x", cited_evidence=[]) for i in ids],
        supplier_email=None)
    assert validate_analysis(ok, ids) == []
    wrong = InvoiceAnalysis(explanations=[
        AnomalyExplanation(anomaly_id="zz", explanation="x", cited_evidence=[])],
        supplier_email=None)
    problems = validate_analysis(wrong, ids)
    assert any("missing" in p for p in problems) and any("unknown" in p for p in problems)
    assert validate_analysis(None, ids)


def test_mock_explains_every_anomaly_and_drafts_email() -> None:
    outcome = ExplanationService(MockLlmClient()).explain(make_invoice(), "Fabrikam", ANOMALIES)
    assert not outcome.fallback and outcome.attempts == 1
    assert set(outcome.explanations) == {"a1", "a2"}
    assert all(text.startswith("[mock]") for text in outcome.explanations.values())
    assert outcome.email is not None and "unit price too high" in outcome.email.body
    assert outcome.usage.prompt_tokens > 0


def test_invalid_output_is_retried_once_then_succeeds() -> None:
    llm = MockLlmClient(bad_outputs=1)
    outcome = ExplanationService(llm).explain(make_invoice(), "Fabrikam", ANOMALIES)
    assert not outcome.fallback and outcome.attempts == 2 and llm.calls == 2


def test_invalid_output_twice_falls_back() -> None:
    llm = MockLlmClient(bad_outputs=2)
    outcome = ExplanationService(llm).explain(make_invoice(), "Fabrikam", ANOMALIES)
    assert outcome.fallback and llm.calls == 2
    assert set(outcome.explanations.values()) == {FALLBACK_TEXT}
    assert outcome.email is None


def test_llm_error_falls_back_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("invoiceguard.adapters.retry.time.sleep", lambda _s: None)

    class Broken:
        deployment = "broken"

        def complete_structured(self, *_: Any) -> LlmResult[InvoiceAnalysis]:
            raise TransientError("down")

    outcome = ExplanationService(Broken()).explain(make_invoice(), "Fabrikam", ANOMALIES)
    assert outcome.fallback and "down" in outcome.problems[0]

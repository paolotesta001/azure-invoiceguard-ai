import random
from pathlib import Path

import httpx
import pytest

from invoiceguard.adapters.file_store import LocalFileStore
from invoiceguard.adapters.payments import HttpPaymentGateway, PaymentGatewayError
from invoiceguard.adapters.retry import TransientError, call_with_retry
from invoiceguard.bootstrap import ConfigurationError, build_analyzer, build_llm
from invoiceguard.config import AppSettings
from invoiceguard.domain.enums import Mode


def test_retry_backoff_respects_retry_after() -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("429", retry_after=5.0)
        return "ok"

    assert call_with_retry(flaky, attempts=3, sleep=sleeps.append, rng=random.Random(1)) == "ok"
    assert sleeps == [5.0, 5.0]


def test_retry_gives_up() -> None:
    def always() -> str:
        raise TransientError("down")

    with pytest.raises(TransientError):
        call_with_retry(always, attempts=2, sleep=lambda _s: None)


def test_file_store_round_trip_and_path_guard(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path / "store")
    uri = store.save("ab" * 32, "inv.XML", b"<x/>")
    assert store.load(uri) == b"<x/>" and uri.endswith(".xml")
    with pytest.raises(ValueError, match="outside"):
        store.load((tmp_path / "other.txt").as_uri())


def _gateway(handler: object) -> HttpPaymentGateway:
    client = httpx.Client(base_url="http://erp", transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return HttpPaymentGateway("http://erp", client=client)


def test_http_gateway_maps_status_codes() -> None:
    ok = _gateway(lambda r: httpx.Response(200, json={"approval_reference": "ERP-1"}))
    assert ok.approve_payment("i", "bob") == "ERP-1"
    with pytest.raises(TransientError) as exc:
        _gateway(lambda r: httpx.Response(429, headers={"retry-after": "2"})).approve_payment(
            "i", "b")
    assert exc.value.retry_after == 2.0
    with pytest.raises(PaymentGatewayError):
        _gateway(lambda r: httpx.Response(403)).approve_payment("i", "b")


def test_azure_mode_requires_endpoints() -> None:
    settings = AppSettings(mode=Mode.AZURE, document_intelligence_endpoint=None,
                           openai_endpoint=None, llm_deployment=None, _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(ConfigurationError, match="DOCUMENT_INTELLIGENCE"):
        build_analyzer(settings)
    with pytest.raises(ConfigurationError, match="OPENAI_ENDPOINT"):
        build_llm(settings)
    assert build_llm(settings.model_copy(update={"llm_enabled": False})) is None

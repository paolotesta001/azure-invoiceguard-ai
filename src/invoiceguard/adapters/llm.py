"""LLM client interface + Azure OpenAI (Microsoft Foundry) implementation.

Real client follows the Microsoft Learn "structured outputs" sample: ``openai.OpenAI`` with
``base_url=<endpoint>/openai/v1/``, a Microsoft Entra token provider for scope
``https://ai.azure.com/.default`` and ``client.beta.chat.completions.parse(response_format=
<Pydantic model>)``. The openai/azure-identity imports are lazy (mock mode never needs them).
"""

from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

from invoiceguard.adapters.retry import TransientError

T = TypeVar("T", bound=BaseModel)
TOKEN_SCOPE = "https://ai.azure.com/.default"
_TRANSIENT_ERRORS = {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"}


class LlmError(Exception):
    """Permanent LLM failure (bad request, auth, content filter...)."""


@dataclass(frozen=True)
class LlmUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(self, other: "LlmUsage") -> "LlmUsage":
        return LlmUsage(self.prompt_tokens + other.prompt_tokens,
                        self.completion_tokens + other.completion_tokens)


@dataclass(frozen=True)
class LlmResult(Generic[T]):
    """``parsed`` is ``None`` when the model refused or returned unparseable output."""

    parsed: T | None
    usage: LlmUsage
    model: str
    refusal: str | None = None


class LlmClient(Protocol):
    deployment: str

    def complete_structured(self, system: str, user: str, schema: type[T]) -> LlmResult[T]: ...


class AzureOpenAIClient:
    """Structured-output chat completions against a Foundry / Azure OpenAI deployment."""

    def __init__(self, endpoint: str, deployment: str, client: Any | None = None) -> None:
        self.deployment = deployment
        if client is None:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            from openai import OpenAI

            token_provider = get_bearer_token_provider(DefaultAzureCredential(), TOKEN_SCOPE)
            client = OpenAI(base_url=f"{endpoint.rstrip('/')}/openai/v1/", api_key=token_provider)
        self._client = client

    def complete_structured(self, system: str, user: str, schema: type[T]) -> LlmResult[T]:
        try:
            completion = self._client.beta.chat.completions.parse(
                model=self.deployment,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format=schema,
                temperature=0,
            )
        except Exception as exc:
            if type(exc).__name__ in _TRANSIENT_ERRORS:
                retry_after = None
                response = getattr(exc, "response", None)
                header = response.headers.get("retry-after") if response is not None else None
                if header and str(header).isdigit():
                    retry_after = float(header)
                raise TransientError(f"LLM call failed: {type(exc).__name__}", retry_after) from exc
            if type(exc).__name__ == "ValidationError":  # schema mismatch while parsing
                return LlmResult(parsed=None, usage=LlmUsage(), model=self.deployment)
            raise LlmError(f"LLM call failed: {type(exc).__name__}: {exc}") from exc
        message = completion.choices[0].message
        usage = completion.usage
        return LlmResult(
            parsed=message.parsed,
            usage=LlmUsage(
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            ),
            model=str(getattr(completion, "model", self.deployment)),
            refusal=getattr(message, "refusal", None),
        )

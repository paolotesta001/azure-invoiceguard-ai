"""Composition root: wires settings, repository, adapters and services together."""

from dataclasses import dataclass

from invoiceguard.adapters.document_intelligence import (
    DocumentIntelligenceAnalyzer,
    InvoiceAnalyzer,
    RecordedAnalyzer,
)
from invoiceguard.adapters.file_store import LocalFileStore
from invoiceguard.adapters.llm import AzureOpenAIClient, LlmClient
from invoiceguard.adapters.payments import (
    HttpPaymentGateway,
    InMemoryPaymentGateway,
    PaymentGateway,
)
from invoiceguard.agent.explainer import ExplanationService
from invoiceguard.agent.mock_llm import MockLlmClient
from invoiceguard.approvals.service import ApprovalService
from invoiceguard.config import AppSettings, ValidationSettings, load_validation_settings
from invoiceguard.domain.clock import Clock, utc_now
from invoiceguard.domain.enums import Mode
from invoiceguard.ingestion.extract import InvoiceExtractor
from invoiceguard.orchestration.local import LocalOrchestrator
from invoiceguard.orchestration.pipeline import ValidationPipeline
from invoiceguard.persistence.memory import InMemoryRepository
from invoiceguard.persistence.repository import Repository


class ConfigurationError(Exception):
    """Required settings for the selected mode are missing."""


@dataclass(frozen=True)
class AppContext:
    settings: AppSettings
    rules: ValidationSettings
    repo: Repository
    payments: PaymentGateway
    orchestrator: LocalOrchestrator
    llm_label: str


def build_repository(settings: AppSettings) -> Repository:
    """In-memory store or PostgreSQL, depending on ``INVOICEGUARD_STORAGE``."""
    if settings.storage == "memory":
        return InMemoryRepository()
    from invoiceguard.db.sql_repository import SqlRepository  # optional heavy import

    return SqlRepository.from_url(settings.database_url)


def build_analyzer(settings: AppSettings) -> InvoiceAnalyzer:
    """Recorded responses in mock mode; the real service in Azure mode."""
    if settings.mode is Mode.MOCK:
        return RecordedAnalyzer(settings.recordings_dir / "document_intelligence")
    if not settings.document_intelligence_endpoint:
        raise ConfigurationError("INVOICEGUARD_DOCUMENT_INTELLIGENCE_ENDPOINT is required in azure mode")
    return DocumentIntelligenceAnalyzer(settings.document_intelligence_endpoint)


def build_llm(settings: AppSettings) -> LlmClient | None:
    """Deterministic mock in mock mode; Azure OpenAI in Azure mode; None if disabled."""
    if not settings.llm_enabled:
        return None
    if settings.mode is Mode.MOCK:
        return MockLlmClient()
    if not settings.openai_endpoint or not settings.llm_deployment:
        raise ConfigurationError(
            "INVOICEGUARD_OPENAI_ENDPOINT and INVOICEGUARD_LLM_DEPLOYMENT are required in azure mode"
        )
    return AzureOpenAIClient(settings.openai_endpoint, settings.llm_deployment)


def build_context(settings: AppSettings | None = None, clock: Clock = utc_now) -> AppContext:
    """Create the full application graph."""
    settings = settings or AppSettings()
    rules = load_validation_settings(settings.config_path)
    repo = build_repository(settings)
    payments: PaymentGateway = (
        HttpPaymentGateway(settings.erp_base_url) if settings.erp_base_url
        else InMemoryPaymentGateway()
    )
    llm = build_llm(settings)
    explainer = ExplanationService(llm) if llm is not None else None
    pipeline = ValidationPipeline(
        repo, LocalFileStore(settings.file_store_dir), payments, rules, settings.mode, clock,
        extractor=InvoiceExtractor(build_analyzer(settings)), explainer=explainer,
    )
    approvals = ApprovalService(repo, payments, rules, clock)
    label = "disabled" if llm is None else f"{settings.mode.value}:{llm.deployment}"
    return AppContext(settings, rules, repo, payments,
                      LocalOrchestrator(repo, pipeline, approvals), label)

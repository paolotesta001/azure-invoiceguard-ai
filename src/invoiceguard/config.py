"""Application settings (environment) and validation rules (YAML)."""

from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from invoiceguard.domain.enums import Country, Mode


class LlmPricing(BaseModel):
    """Token prices used for the cost estimate of each run (configured, never hard-coded)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: str = "EUR"
    input_per_1k_tokens: Decimal = Decimal("0")
    output_per_1k_tokens: Decimal = Decimal("0")

    def cost(self, prompt_tokens: int, completion_tokens: int) -> Decimal:
        """Estimated cost of one call."""
        return (
            Decimal(prompt_tokens) * self.input_per_1k_tokens
            + Decimal(completion_tokens) * self.output_per_1k_tokens
        ) / Decimal(1000)


class ValidationSettings(BaseModel):
    """Business rules loaded from ``config/settings.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arithmetic_tolerance: Decimal = Decimal("0.01")
    confidence_threshold: float = Field(default=0.80, ge=0, le=1)
    iban_recent_change_days: int = Field(default=30, ge=0)
    approval_timeout_hours: int = Field(default=72, ge=1)
    auto_approve_threshold: dict[str, Decimal] = Field(
        default_factory=lambda: {"EUR": Decimal("1000.00")}
    )
    vat_rates: dict[Country, tuple[Decimal, ...]] = Field(default_factory=dict)
    llm_pricing: LlmPricing = Field(default_factory=LlmPricing)


class AppSettings(BaseSettings):
    """Runtime settings from environment variables (prefix ``INVOICEGUARD_``) or ``.env``."""

    model_config = SettingsConfigDict(env_prefix="INVOICEGUARD_", env_file=".env", extra="ignore")

    mode: Mode = Mode.MOCK
    storage: Literal["memory", "sql"] = "sql"
    database_url: str = "postgresql+psycopg://invoiceguard:invoiceguard@localhost:5432/invoiceguard"
    erp_base_url: str | None = None
    file_store_dir: Path = Path(".data/files")
    config_path: Path = Path("config/settings.yaml")
    seed_dir: Path = Path("data/seed")
    invoices_dir: Path = Path("data/invoices")
    recordings_dir: Path = Path("data/recorded")
    document_intelligence_endpoint: str | None = None
    openai_endpoint: str | None = None
    llm_deployment: str | None = None
    llm_enabled: bool = True


def load_validation_settings(path: Path) -> ValidationSettings:
    """Load and validate business rules from a YAML file."""
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return ValidationSettings.model_validate(raw)

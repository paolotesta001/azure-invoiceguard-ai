"""Shared fixtures."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from invoiceguard.adapters.document_intelligence import RecordedAnalyzer
from invoiceguard.adapters.file_store import LocalFileStore
from invoiceguard.adapters.llm import LlmClient
from invoiceguard.adapters.payments import InMemoryPaymentGateway
from invoiceguard.agent.explainer import ExplanationService
from invoiceguard.agent.mock_llm import MockLlmClient
from invoiceguard.approvals.service import ApprovalService
from invoiceguard.checks.base import CheckContext
from invoiceguard.config import ValidationSettings, load_validation_settings
from invoiceguard.domain.enums import Country, Mode, SourceType
from invoiceguard.domain.iban import build_iban
from invoiceguard.domain.models import (
    Contract,
    ContractPriceItem,
    ExtractedInvoice,
    ExtractedInvoiceLine,
    Supplier,
)
from invoiceguard.ingestion.extract import InvoiceExtractor
from invoiceguard.orchestration.local import LocalOrchestrator
from invoiceguard.orchestration.pipeline import ValidationPipeline
from invoiceguard.persistence.memory import InMemoryRepository
from invoiceguard.persistence.repository import Repository
from invoiceguard.seed import load_master_data
from scripts.generate_synthetic_data import generate

ROOT = Path(__file__).resolve().parents[1]
IBAN = build_iban("IT", "X0542811101000000123456")


@pytest.fixture(scope="session")
def rules() -> ValidationSettings:
    return load_validation_settings(ROOT / "config" / "settings.yaml")


@pytest.fixture(scope="session")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("data")
    generate(out, seed=42)
    return out


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def supplier() -> Supplier:
    return Supplier(id="S1", name="Fabrikam Arredi S.r.l.", vat_id="IT01000000011",
                    country=Country.IT, currency="EUR", iban_on_file=IBAN,
                    iban_last_changed_at=date(2025, 1, 1))


@pytest.fixture
def contract() -> Contract:
    return Contract(id="C1", supplier_id="S1", version=1, valid_from=date(2026, 1, 1),
                    valid_to=date(2026, 12, 31), payment_terms_days=30,
                    max_price_increase_pct=Decimal("3.0"), currency="EUR")


@pytest.fixture
def price_items() -> dict[str, ContractPriceItem]:
    return {"CHAIR": ContractPriceItem(contract_id="C1", sku="CHAIR", description="Chair",
                                       unit_price=Decimal("85.00"), currency="EUR", unit="pz")}


def make_invoice(lines: list[tuple[str | None, str, str, str]] | None = None,
                 **overrides: object) -> ExtractedInvoice:
    """Build a consistent invoice; lines are (sku, qty, unit_price, vat_rate)."""
    from invoiceguard.domain.money import line_amount, round_money, vat_amount

    raw = lines or [("CHAIR", "2", "85.00", "22")]
    built = []
    subtotal = vat = Decimal("0")
    for i, (sku, q, p, r) in enumerate(raw, start=1):
        total = line_amount(Decimal(q), Decimal(p))
        built.append(ExtractedInvoiceLine(line_no=i, sku=sku, description=sku or "item",
                                          quantity=Decimal(q), unit_price=Decimal(p),
                                          vat_rate=Decimal(r), line_total=total))
        subtotal += total
        vat += vat_amount(total, Decimal(r))
    data: dict[str, object] = {
        "source_type": SourceType.XML_FATTURAPA, "supplier_vat_id": "IT01000000011",
        "supplier_name": "Fabrikam Arredi S.r.l.", "invoice_number": "INV-1",
        "invoice_date": date(2026, 10, 5), "currency": "EUR", "subtotal": subtotal,
        "vat_amount": vat, "total": round_money(subtotal + vat), "iban": IBAN,
        "lines": tuple(built), "field_confidence": {"total": 1.0},
    }
    data.update(overrides)
    return ExtractedInvoice.model_validate(data)


@pytest.fixture
def make_ctx(supplier: Supplier, contract: Contract, price_items: dict[str, ContractPriceItem],
             rules: ValidationSettings) -> Callable[..., CheckContext]:
    def _make(invoice: ExtractedInvoice | None = None, **overrides: object) -> CheckContext:
        values: dict[str, object] = {"invoice": invoice or make_invoice(), "supplier": supplier,
                                     "contract": contract, "price_items": price_items,
                                     "settings": rules}
        values.update(overrides)
        return CheckContext(**values)  # type: ignore[arg-type]
    return _make


class Stack:
    def __init__(self, repo: Repository, orchestrator: LocalOrchestrator,
                 payments: InMemoryPaymentGateway, pipeline: ValidationPipeline) -> None:
        self.repo, self.orchestrator = repo, orchestrator
        self.payments, self.pipeline = payments, pipeline


def build_stack(repo: Repository, tmp_path: Path, dataset: Path, rules: ValidationSettings,
                clock: FakeClock, payments: InMemoryPaymentGateway | None = None,
                llm: LlmClient | None = None, with_llm: bool = True) -> Stack:
    payments = payments or InMemoryPaymentGateway()
    load_master_data(repo, dataset / "seed")
    explainer = ExplanationService(llm or MockLlmClient()) if with_llm else None
    pipeline = ValidationPipeline(
        repo, LocalFileStore(tmp_path / "files"), payments, rules, Mode.MOCK, clock,
        extractor=InvoiceExtractor(RecordedAnalyzer(dataset / "recorded" / "document_intelligence")),
        explainer=explainer,
    )
    approvals = ApprovalService(repo, payments, rules, clock)
    return Stack(repo, LocalOrchestrator(repo, pipeline, approvals), payments, pipeline)


@pytest.fixture
def stack(tmp_path: Path, dataset: Path, rules: ValidationSettings, clock: FakeClock) -> Stack:
    return build_stack(InMemoryRepository(), tmp_path, dataset, rules, clock)

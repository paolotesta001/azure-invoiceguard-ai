"""SQL repository tests. SQLite by default; set INVOICEGUARD_TEST_DATABASE_URL to a PostgreSQL
URL to run against Postgres (CI does this, including the append-only audit trigger)."""

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")

from alembic import command  # noqa: E402
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from invoiceguard.config import ValidationSettings  # noqa: E402
from invoiceguard.db.sql_repository import SqlRepository  # noqa: E402
from invoiceguard.db.tables import Base  # noqa: E402
from invoiceguard.domain.models import InvoiceSubmission, SupplierEmailDraft  # noqa: E402
from invoiceguard.seed import process_demo_invoices  # noqa: E402
from tests.conftest import FakeClock, build_stack  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PG_URL = os.environ.get("INVOICEGUARD_TEST_DATABASE_URL")


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    url = PG_URL or f"sqlite:///{tmp_path / 'test.db'}"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    if PG_URL:
        command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return url


def test_migrations_match_models(db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], diff


def test_demo_dataset_on_sql(db_url: str, tmp_path: Path, dataset: Path,
                             rules: ValidationSettings) -> None:
    stack = build_stack(SqlRepository.from_url(db_url), tmp_path, dataset, rules, FakeClock())
    process_demo_invoices(stack.orchestrator, dataset / "invoices")
    by_name = {s.filename: s for s in stack.repo.list_submissions()}
    for label_path in sorted((dataset / "labels").glob("*.json")):
        label = json.loads(label_path.read_text(encoding="utf-8"))
        sub = by_name[label["file"]]
        assert sub.status.value == label["expected_submission_status"], label["file"]
        assert sorted(a.type.value for a in stack.repo.list_anomalies(sub.id)) == \
            label["expected_anomalies"]
        if sub.invoice_id:
            invoice = stack.repo.get_invoice(sub.invoice_id)
            assert invoice and list(invoice.needs_review_fields) == label["expected_needs_review"]


def test_email_draft_upsert(db_url: str, tmp_path: Path, dataset: Path,
                            rules: ValidationSettings) -> None:
    stack = build_stack(SqlRepository.from_url(db_url), tmp_path, dataset, rules, FakeClock())
    sub: InvoiceSubmission = stack.orchestrator.submit(
        (dataset / "invoices" / "02_wrong_price.xml").read_bytes(), "02.xml", "alice.uploader")
    assert sub.invoice_id
    first = stack.repo.get_email_draft(sub.invoice_id)
    assert first is not None
    edited = SupplierEmailDraft(id=first.id, invoice_id=sub.invoice_id, subject="S", body="B",
                                generated_by=first.generated_by, updated_by="bob.reviewer",
                                updated_at=datetime(2026, 11, 1, tzinfo=UTC))
    stack.repo.save_email_draft(edited)
    assert stack.repo.get_email_draft(sub.invoice_id) == edited


@pytest.mark.postgres
@pytest.mark.skipif(PG_URL is None, reason="needs PostgreSQL")
def test_concurrent_duplicates_and_append_only_audit(db_url: str, tmp_path: Path,
                                                      dataset: Path,
                                                      rules: ValidationSettings) -> None:
    stack = build_stack(SqlRepository.from_url(db_url), tmp_path, dataset, rules, FakeClock())
    base = (dataset / "invoices" / "01_clean_small.xml").read_bytes()
    variants = [base.replace(b"00001</ProgressivoInvio>", f"{i:05d}</ProgressivoInvio>".encode())
                for i in range(20, 28)]
    barrier = threading.Barrier(len(variants))
    results: list[InvoiceSubmission] = []

    def worker(content: bytes) -> None:
        barrier.wait()
        results.append(stack.orchestrator.submit(content, "x.xml", "alice.uploader"))

    threads = [threading.Thread(target=worker, args=(v,)) for v in variants]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.status.value for r in results).count("accepted") == 1

    engine = create_engine(db_url)
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))

"""v1a + v1b acceptance: every labelled demo invoice (XML, KSeF, PDF, scan) ends in the
expected state with the expected anomaly types and review fields (mock mode, in-memory)."""

import json
from pathlib import Path

from invoiceguard.agent.explainer import FALLBACK_TEXT
from invoiceguard.seed import process_demo_invoices
from tests.conftest import Stack


def test_generator_is_reproducible(tmp_path: Path, dataset: Path) -> None:
    from scripts.generate_synthetic_data import generate

    generate(tmp_path / "again", seed=42)
    for sub in ("seed", "invoices", "labels", "recorded/document_intelligence"):
        for path in sorted((dataset / sub).iterdir()):
            assert path.read_bytes() == (tmp_path / "again" / sub / path.name).read_bytes(), \
                path.name


def test_all_demo_invoices_match_labels(stack: Stack, dataset: Path) -> None:
    assert process_demo_invoices(stack.orchestrator, dataset / "invoices") == 18
    by_name = {s.filename: s for s in stack.repo.list_submissions()}
    for label_path in sorted((dataset / "labels").glob("*.json")):
        label = json.loads(label_path.read_text(encoding="utf-8"))
        sub = by_name[label["file"]]
        assert sub.status.value == label["expected_submission_status"], label["file"]
        anomalies = stack.repo.list_anomalies(sub.id)
        assert sorted(a.type.value for a in anomalies) == label["expected_anomalies"], label["file"]
        if label["expected_invoice_status"] is None:
            continue
        invoice = stack.repo.get_invoice(sub.invoice_id or "")
        assert invoice is not None
        assert invoice.status.value == label["expected_invoice_status"], label["file"]
        assert list(invoice.needs_review_fields) == label["expected_needs_review"], label["file"]
        for key in ("subtotal", "vat_amount", "total"):
            assert getattr(invoice.data, key) == __import__("decimal").Decimal(
                label["expected_fields"][key]), (label["file"], key)
        # v1b acceptance: every flagged anomaly carries a labelled AI explanation
        for anomaly in anomalies:
            assert anomaly.explanation and anomaly.explanation != FALLBACK_TEXT, label["file"]

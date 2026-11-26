"""Smoke test of the Streamlit app in memory mode (no Docker, no database, no Azure)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def app(dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("INVOICEGUARD_STORAGE", "memory")
    monkeypatch.setenv("INVOICEGUARD_MODE", "mock")
    monkeypatch.delenv("INVOICEGUARD_ERP_BASE_URL", raising=False)
    monkeypatch.setenv("INVOICEGUARD_SEED_DIR", str(dataset / "seed"))
    monkeypatch.setenv("INVOICEGUARD_INVOICES_DIR", str(dataset / "invoices"))
    monkeypatch.setenv("INVOICEGUARD_RECORDINGS_DIR", str(dataset / "recorded"))
    monkeypatch.setenv("INVOICEGUARD_FILE_STORE_DIR", str(tmp_path / "files"))
    at = AppTest.from_file(str(ROOT / "ui" / "app.py"), default_timeout=60)
    at.run()
    return at


def test_dashboard_renders_with_mock_banner(app: AppTest) -> None:
    assert not app.exception
    assert any("MOCK MODE" in w.value for w in app.warning)
    assert app.dataframe and len(app.dataframe[0].value) == 18


def test_inbox_blocks_uploader_and_allows_reviewer(app: AppTest) -> None:
    app.sidebar.radio[0].set_value("Approval inbox").run()
    assert not app.exception
    assert any("segregation of duties" in i.value for i in app.info)
    assert any("AI-generated" in i.value for i in app.info)
    app.sidebar.selectbox[0].set_value("bob.reviewer").run()
    assert not app.exception
    assert app.button


def test_detail_page_renders(app: AppTest) -> None:
    app.sidebar.radio[0].set_value("Invoice detail").run()
    assert not app.exception

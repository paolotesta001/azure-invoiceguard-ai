from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from mock_erp.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_read_endpoints(dataset: Path) -> None:
    client = TestClient(create_app(dataset / "seed"))
    assert client.get("/suppliers/S-IT-01").json()["name"] == "Fabrikam Arredi S.r.l."
    assert client.get("/suppliers/nope").status_code == 404
    po = client.get("/purchase-orders/PO-S-IT-01-001").json()
    assert po["supplier_id"] == "S-IT-01" and po["lines"]
    assert client.get("/purchase-orders/PO-S-IT-01-001/goods-receipts").json()[0]["lines"]
    contract = client.get("/contracts/C-S-IT-01-v1").json()
    assert {p["sku"] for p in contract["price_items"]} == {"FAB-CHAIR", "FAB-DESK", "FAB-LAMP"}


def test_payment_approval_is_idempotent_and_hidden_from_schema(dataset: Path) -> None:
    client = TestClient(create_app(dataset / "seed"))
    body = {"invoice_id": "i1", "approved_by": "bob"}
    first = client.post("/payments/approvals", json=body).json()
    second = client.post("/payments/approvals", json=body).json()
    assert first["approval_reference"] == second["approval_reference"]
    assert second["already_approved"]
    assert "/payments/approvals" not in client.get("/openapi.json").json()["paths"]


def test_static_openapi_matches_app_and_is_read_only(dataset: Path) -> None:
    spec = yaml.safe_load((ROOT / "mock_erp" / "openapi.yaml").read_text(encoding="utf-8"))
    assert spec["openapi"].startswith("3.0")
    app_paths = set(TestClient(create_app(dataset / "seed")).get("/openapi.json").json()["paths"])
    assert set(spec["paths"]) <= app_paths
    assert {m for path in spec["paths"].values() for m in path} == {"get"}
    ops = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert ops == {"get_supplier", "get_purchase_order", "get_goods_receipt", "get_contract"}

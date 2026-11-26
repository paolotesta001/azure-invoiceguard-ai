"""Load synthetic master data (JSON produced by scripts/generate_synthetic_data.py)."""

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from invoiceguard.domain.models import (
    Contract,
    ContractPriceItem,
    GoodsReceipt,
    PurchaseOrder,
    Supplier,
)
from invoiceguard.orchestration.base import Orchestrator
from invoiceguard.persistence.repository import Repository

DEMO_UPLOADER = "alice.uploader"
INVOICE_SUFFIXES = {".xml", ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def _read(seed_dir: Path, name: str) -> Any:
    return json.loads((seed_dir / name).read_text(encoding="utf-8"))


def load_master_data(repo: Repository, seed_dir: Path) -> dict[str, int]:
    """Insert suppliers, contracts, prices, POs and goods receipts. Idempotent."""
    if repo.list_suppliers():
        return {"suppliers": 0}
    suppliers = TypeAdapter(list[Supplier]).validate_python(_read(seed_dir, "suppliers.json"))
    contracts = TypeAdapter(list[Contract]).validate_python(_read(seed_dir, "contracts.json"))
    prices = TypeAdapter(list[ContractPriceItem]).validate_python(
        _read(seed_dir, "contract_price_items.json")
    )
    pos = TypeAdapter(list[PurchaseOrder]).validate_python(_read(seed_dir, "purchase_orders.json"))
    receipts = TypeAdapter(list[GoodsReceipt]).validate_python(
        _read(seed_dir, "goods_receipts.json")
    )
    for supplier in suppliers:
        repo.add_supplier(supplier)
    for contract in sorted(contracts, key=lambda c: c.version):
        repo.add_contract(contract)
    repo.add_price_items(prices)
    for po in pos:
        repo.add_purchase_order(po)
    for receipt in receipts:
        repo.add_goods_receipt(receipt)
    return {"suppliers": len(suppliers), "contracts": len(contracts), "price_items": len(prices),
            "purchase_orders": len(pos), "goods_receipts": len(receipts)}


def process_demo_invoices(orchestrator: Orchestrator, invoices_dir: Path,
                          uploaded_by: str = DEMO_UPLOADER) -> int:
    """Submit every demo invoice in file-name order. Re-running is a no-op (idempotent)."""
    files = sorted(p for p in invoices_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in INVOICE_SUFFIXES)
    for path in files:
        orchestrator.submit(path.read_bytes(), path.name, uploaded_by)
    return len(files)

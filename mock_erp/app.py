"""Mock ERP exposing read-only master data and a backend-only payment approval endpoint.

Read endpoints are described in ``mock_erp/openapi.yaml`` (OpenAPI 3.0) for the Foundry
OpenAPI tool in v2. ``POST /payments/approvals`` is deliberately NOT in that spec: the agent
must never be able to approve payments. In v4 it will also require a signed approval token.
"""

import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, TypeAdapter

from invoiceguard.domain.models import (
    Contract,
    ContractPriceItem,
    GoodsReceipt,
    PurchaseOrder,
    Supplier,
)


class ContractOut(BaseModel):
    contract: Contract
    price_items: list[ContractPriceItem]


class PaymentApprovalIn(BaseModel):
    invoice_id: str
    approved_by: str


class PaymentApprovalOut(BaseModel):
    approval_reference: str
    invoice_id: str
    approved_by: str
    already_approved: bool


def _load(seed_dir: Path, name: str) -> object:
    return json.loads((seed_dir / name).read_text(encoding="utf-8"))


def create_app(seed_dir: Path | None = None) -> FastAPI:
    """Build the FastAPI app from seed JSON files."""
    seed_dir = seed_dir or Path(os.environ.get("INVOICEGUARD_SEED_DIR", "data/seed"))
    suppliers = {s.id: s for s in TypeAdapter(list[Supplier]).validate_python(
        _load(seed_dir, "suppliers.json"))}
    contracts = {c.id: c for c in TypeAdapter(list[Contract]).validate_python(
        _load(seed_dir, "contracts.json"))}
    prices = TypeAdapter(list[ContractPriceItem]).validate_python(
        _load(seed_dir, "contract_price_items.json"))
    pos = {p.po_number: p for p in TypeAdapter(list[PurchaseOrder]).validate_python(
        _load(seed_dir, "purchase_orders.json"))}
    receipts = TypeAdapter(list[GoodsReceipt]).validate_python(
        _load(seed_dir, "goods_receipts.json"))
    approvals: dict[str, PaymentApprovalOut] = {}
    lock = threading.Lock()

    app = FastAPI(title="InvoiceGuard Mock ERP", version="0.2.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/suppliers/{supplier_id}", operation_id="get_supplier")
    def get_supplier(supplier_id: str) -> Supplier:
        if supplier_id not in suppliers:
            raise HTTPException(404, "supplier not found")
        return suppliers[supplier_id]

    @app.get("/purchase-orders/{po_number}", operation_id="get_purchase_order")
    def get_purchase_order(po_number: str) -> PurchaseOrder:
        if po_number not in pos:
            raise HTTPException(404, "purchase order not found")
        return pos[po_number]

    @app.get("/purchase-orders/{po_number}/goods-receipts", operation_id="get_goods_receipt")
    def get_goods_receipts(po_number: str) -> list[GoodsReceipt]:
        if po_number not in pos:
            raise HTTPException(404, "purchase order not found")
        return [r for r in receipts if r.po_number == po_number]

    @app.get("/contracts/{contract_id}", operation_id="get_contract")
    def get_contract(contract_id: str) -> ContractOut:
        if contract_id not in contracts:
            raise HTTPException(404, "contract not found")
        return ContractOut(contract=contracts[contract_id],
                           price_items=[p for p in prices if p.contract_id == contract_id])

    @app.post("/payments/approvals", operation_id="approve_payment", include_in_schema=False)
    def approve_payment(body: PaymentApprovalIn) -> PaymentApprovalOut:
        with lock:
            if body.invoice_id in approvals:
                return approvals[body.invoice_id].model_copy(update={"already_approved": True})
            result = PaymentApprovalOut(approval_reference=f"ERP-PAY-{len(approvals) + 1:06d}",
                                        invoice_id=body.invoice_id, approved_by=body.approved_by,
                                        already_approved=False)
            approvals[body.invoice_id] = result
            return result

    return app


_DEFAULT_SEED = Path(os.environ.get("INVOICEGUARD_SEED_DIR", "data/seed"))
app = create_app(_DEFAULT_SEED) if _DEFAULT_SEED.exists() else FastAPI(title="Mock ERP (no data)")

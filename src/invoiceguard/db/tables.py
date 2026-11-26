"""SQLAlchemy 2 table definitions. Keep in sync with ``migrations/versions``;
``tests/integration/test_sql_repository.py`` fails if the migrations and the models drift."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(18, 2)
AMOUNT = Numeric(20, 8)  # unit prices and quantities (FatturaPA allows up to 8 decimals)
PCT = Numeric(7, 3)
TZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    """Declarative base for all tables."""


class SupplierRow(Base):
    __tablename__ = "suppliers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    vat_id: Mapped[str] = mapped_column(String(32), unique=True)
    country: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(3))
    iban_on_file: Mapped[str] = mapped_column(String(34))
    iban_last_changed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16))


class ContractRow(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("supplier_id", "version", name="uq_contracts_supplier_version"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    supersedes_contract_id: Mapped[str | None] = mapped_column(
        ForeignKey("contracts.id"), nullable=True
    )
    payment_terms_days: Mapped[int] = mapped_column(Integer)
    early_payment_discount_pct: Mapped[Decimal] = mapped_column(PCT)
    late_penalty_pct: Mapped[Decimal] = mapped_column(PCT)
    max_price_increase_pct: Mapped[Decimal] = mapped_column(PCT)
    currency: Mapped[str] = mapped_column(String(3))
    source_document_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ContractPriceItemRow(Base):
    __tablename__ = "contract_price_items"
    __table_args__ = (UniqueConstraint("contract_id", "sku", name="uq_price_items_contract_sku"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(300))
    unit_price: Mapped[Decimal] = mapped_column(AMOUNT)
    currency: Mapped[str] = mapped_column(String(3))
    unit: Mapped[str] = mapped_column(String(16))


class PurchaseOrderRow(Base):
    __tablename__ = "purchase_orders"
    po_number: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    lines: Mapped[list["PurchaseOrderLineRow"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="PurchaseOrderLineRow.id"
    )


class PurchaseOrderLineRow(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_number: Mapped[str] = mapped_column(ForeignKey("purchase_orders.po_number"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[Decimal] = mapped_column(AMOUNT)
    unit_price: Mapped[Decimal] = mapped_column(AMOUNT)


class GoodsReceiptRow(Base):
    __tablename__ = "goods_receipts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    po_number: Mapped[str] = mapped_column(ForeignKey("purchase_orders.po_number"), index=True)
    received_at: Mapped[date] = mapped_column(Date)
    lines: Mapped[list["GoodsReceiptLineRow"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="GoodsReceiptLineRow.id"
    )


class GoodsReceiptLineRow(Base):
    __tablename__ = "goods_receipt_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goods_receipt_id: Mapped[str] = mapped_column(ForeignKey("goods_receipts.id"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    quantity_received: Mapped[Decimal] = mapped_column(AMOUNT)


class SubmissionRow(Base):
    __tablename__ = "invoice_submissions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(String(300))
    file_uri: Mapped[str] = mapped_column(String(1000))
    uploaded_by: Mapped[str] = mapped_column(String(128))
    uploaded_at: Mapped[datetime] = mapped_column(TZ, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    invoice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duplicate_of_invoice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class InvoiceRow(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("supplier_id", "invoice_number", name="uq_invoices_supplier_number"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("invoice_submissions.id"), unique=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    source_type: Mapped[str] = mapped_column(String(32))
    supplier_vat_id: Mapped[str] = mapped_column(String(32))
    supplier_name: Mapped[str] = mapped_column(String(200))
    invoice_number: Mapped[str] = mapped_column(String(64))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    subtotal: Mapped[Decimal] = mapped_column(MONEY)
    vat_amount: Mapped[Decimal] = mapped_column(MONEY)
    total: Mapped[Decimal] = mapped_column(MONEY)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    po_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    field_confidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    needs_review_fields: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZ)
    status_changed_at: Mapped[datetime] = mapped_column(TZ)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(TZ, nullable=True)
    lines: Mapped[list["InvoiceLineRow"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="InvoiceLineRow.line_no"
    )


class InvoiceLineRow(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(AMOUNT)
    unit_price: Mapped[Decimal] = mapped_column(AMOUNT)
    vat_rate: Mapped[Decimal] = mapped_column(PCT)
    line_total: Mapped[Decimal] = mapped_column(MONEY)


class AnomalyRow(Base):
    __tablename__ = "anomalies"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("invoice_submissions.id"), index=True)
    invoice_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    monetary_impact: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_by: Mapped[str] = mapped_column(String(8))


class SupplierEmailDraftRow(Base):
    __tablename__ = "supplier_email_drafts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), unique=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(128))
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZ)


class ValidationRunRow(Base):
    __tablename__ = "validation_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("invoice_submissions.id"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(8))
    started_at: Mapped[datetime] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_deployment: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6))


class ApprovalDecisionRow(Base):
    __tablename__ = "approval_decisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    reviewer_id: Mapped[str] = mapped_column(String(128))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_token_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(TZ)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(TZ, index=True)
    actor: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(64))
    submission_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    invoice_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)

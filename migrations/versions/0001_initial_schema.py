"""Initial schema (v1a).

Revision ID: 0001
Revises:
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 2)
AMOUNT = sa.Numeric(20, 8)
PCT = sa.Numeric(7, 3)
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("vat_id", sa.String(32), nullable=False, unique=True),
        sa.Column("country", sa.String(8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("iban_on_file", sa.String(34), nullable=False),
        sa.Column("iban_last_changed_at", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
    )
    op.create_table(
        "contracts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("supplier_id", sa.String(64), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("supersedes_contract_id", sa.String(64), sa.ForeignKey("contracts.id"), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False),
        sa.Column("early_payment_discount_pct", PCT, nullable=False),
        sa.Column("late_penalty_pct", PCT, nullable=False),
        sa.Column("max_price_increase_pct", PCT, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source_document_uri", sa.String(500), nullable=True),
        sa.UniqueConstraint("supplier_id", "version", name="uq_contracts_supplier_version"),
    )
    op.create_index("ix_contracts_supplier_id", "contracts", ["supplier_id"])
    op.create_table(
        "contract_price_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contract_id", sa.String(64), sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("unit_price", AMOUNT, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.UniqueConstraint("contract_id", "sku", name="uq_price_items_contract_sku"),
    )
    op.create_index("ix_contract_price_items_contract_id", "contract_price_items", ["contract_id"])
    op.create_table(
        "purchase_orders",
        sa.Column("po_number", sa.String(64), primary_key=True),
        sa.Column("supplier_id", sa.String(64), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
    )
    op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"])
    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("po_number", sa.String(64), sa.ForeignKey("purchase_orders.po_number"), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("quantity", AMOUNT, nullable=False),
        sa.Column("unit_price", AMOUNT, nullable=False),
    )
    op.create_index("ix_purchase_order_lines_po_number", "purchase_order_lines", ["po_number"])
    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("po_number", sa.String(64), sa.ForeignKey("purchase_orders.po_number"), nullable=False),
        sa.Column("received_at", sa.Date(), nullable=False),
    )
    op.create_index("ix_goods_receipts_po_number", "goods_receipts", ["po_number"])
    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("goods_receipt_id", sa.String(64), sa.ForeignKey("goods_receipts.id"), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("quantity_received", AMOUNT, nullable=False),
    )
    op.create_index("ix_goods_receipt_lines_goods_receipt_id", "goods_receipt_lines", ["goods_receipt_id"])
    op.create_table(
        "invoice_submissions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("file_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("file_uri", sa.String(1000), nullable=False),
        sa.Column("uploaded_by", sa.String(128), nullable=False),
        sa.Column("uploaded_at", TZ, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("invoice_id", sa.String(64), nullable=True),
        sa.Column("duplicate_of_invoice_id", sa.String(64), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_invoice_submissions_uploaded_at", "invoice_submissions", ["uploaded_at"])
    op.create_index("ix_invoice_submissions_status", "invoice_submissions", ["status"])
    op.create_table(
        "invoices",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("submission_id", sa.String(64), sa.ForeignKey("invoice_submissions.id"),
                  nullable=False, unique=True),
        sa.Column("supplier_id", sa.String(64), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("supplier_vat_id", sa.String(32), nullable=False),
        sa.Column("supplier_name", sa.String(200), nullable=False),
        sa.Column("invoice_number", sa.String(64), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", MONEY, nullable=False),
        sa.Column("vat_amount", MONEY, nullable=False),
        sa.Column("total", MONEY, nullable=False),
        sa.Column("iban", sa.String(34), nullable=True),
        sa.Column("po_number", sa.String(64), nullable=True),
        sa.Column("field_confidence", sa.JSON(), nullable=False),
        sa.Column("needs_review_fields", sa.JSON(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("status_changed_at", TZ, nullable=False),
        sa.Column("reminder_sent_at", TZ, nullable=True),
        sa.UniqueConstraint("supplier_id", "invoice_number", name="uq_invoices_supplier_number"),
    )
    op.create_index("ix_invoices_supplier_id", "invoices", ["supplier_id"])
    op.create_index("ix_invoices_status", "invoices", ["status"])
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("invoice_id", sa.String(64), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(64), nullable=True),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", AMOUNT, nullable=False),
        sa.Column("unit_price", AMOUNT, nullable=False),
        sa.Column("vat_rate", PCT, nullable=False),
        sa.Column("line_total", MONEY, nullable=False),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])
    op.create_table(
        "anomalies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("submission_id", sa.String(64), sa.ForeignKey("invoice_submissions.id"), nullable=False),
        sa.Column("invoice_id", sa.String(64), nullable=True),
        sa.Column("type", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("monetary_impact", MONEY, nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("detected_by", sa.String(8), nullable=False),
    )
    op.create_index("ix_anomalies_submission_id", "anomalies", ["submission_id"])
    op.create_index("ix_anomalies_invoice_id", "anomalies", ["invoice_id"])
    op.create_table(
        "validation_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("submission_id", sa.String(64), sa.ForeignKey("invoice_submissions.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("finished_at", TZ, nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model_deployment", sa.String(128), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(12, 6), nullable=False),
    )
    op.create_index("ix_validation_runs_submission_id", "validation_runs", ["submission_id"])
    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("invoice_id", sa.String(64), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reviewer_id", sa.String(128), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("signed_token_id", sa.String(128), nullable=True),
        sa.Column("payment_reference", sa.String(128), nullable=True),
        sa.Column("decided_at", TZ, nullable=False),
    )
    op.create_index("ix_approval_decisions_invoice_id", "approval_decisions", ["invoice_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("timestamp", TZ, nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("submission_id", sa.String(64), nullable=True),
        sa.Column("invoice_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"])
    op.create_index("ix_audit_events_submission_id", "audit_events", ["submission_id"])
    op.create_index("ix_audit_events_invoice_id", "audit_events", ["invoice_id"])

    if op.get_bind().dialect.name == "postgresql":
        # Append-only audit log: block UPDATE and DELETE at the database level.
        op.execute(
            """
            CREATE FUNCTION audit_events_append_only() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'audit_events is append-only';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER audit_events_no_update_delete
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events")
        op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    for table in ("audit_events", "approval_decisions", "validation_runs", "anomalies",
                  "invoice_lines", "invoices", "invoice_submissions", "goods_receipt_lines",
                  "goods_receipts", "purchase_order_lines", "purchase_orders",
                  "contract_price_items", "contracts", "suppliers"):
        op.drop_table(table)

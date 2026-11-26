"""Supplier email drafts (v1b).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_email_drafts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("invoice_id", sa.String(64), sa.ForeignKey("invoices.id"), nullable=False,
                  unique=True),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("supplier_email_drafts")

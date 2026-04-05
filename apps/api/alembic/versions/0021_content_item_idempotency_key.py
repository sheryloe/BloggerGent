"""content item idempotency key

Revision ID: 0021_content_item_idempotency
Revises: 0020_analytics_fact_perf_indexes
Create Date: 2026-04-04 00:00:02.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_content_item_idempotency"
down_revision = "0020_analytics_fact_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("idempotency_key", sa.String(length=120), nullable=False, server_default=""),
    )
    op.create_index(op.f("ix_content_items_idempotency_key"), "content_items", ["idempotency_key"], unique=False)
    op.create_index(
        "ix_content_items_managed_channel_idempotency_key",
        "content_items",
        ["managed_channel_id", "idempotency_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_managed_channel_idempotency_key", table_name="content_items")
    op.drop_index(op.f("ix_content_items_idempotency_key"), table_name="content_items")
    op.drop_column("content_items", "idempotency_key")

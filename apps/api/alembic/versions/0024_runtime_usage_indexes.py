"""Add runtime usage indexes.

Revision ID: 0024_runtime_usage_indexes
Revises: 0023_synced_cloudflare_posts
Create Date: 2026-04-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0024_runtime_usage_indexes"
down_revision = "0023_synced_cloudflare_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f("ix_ai_usage_events_created_at"), "ai_usage_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_agent_runs_created_at"), "agent_runs", ["created_at"], unique=False)
    op.create_index(op.f("ix_content_items_created_at"), "content_items", ["created_at"], unique=False)
    op.create_index(op.f("ix_agent_workers_created_at"), "agent_workers", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_workers_created_at"), table_name="agent_workers")
    op.drop_index(op.f("ix_content_items_created_at"), table_name="content_items")
    op.drop_index(op.f("ix_agent_runs_created_at"), table_name="agent_runs")
    op.drop_index(op.f("ix_ai_usage_events_created_at"), table_name="ai_usage_events")

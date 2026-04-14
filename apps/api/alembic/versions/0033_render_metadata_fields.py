"""add render metadata fields to articles and synced cloudflare posts

Revision ID: 0033_render_metadata_fields
Revises: 0032_live_image_count_breakdown_fields
Create Date: 2026-04-12 12:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0033_render_metadata_fields"
down_revision = "0032_live_image_count_breakdown_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("render_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.add_column(
        "synced_cloudflare_posts",
        sa.Column("render_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.alter_column("articles", "render_metadata", server_default=None)
    op.alter_column("synced_cloudflare_posts", "render_metadata", server_default=None)


def downgrade() -> None:
    op.drop_column("synced_cloudflare_posts", "render_metadata")
    op.drop_column("articles", "render_metadata")

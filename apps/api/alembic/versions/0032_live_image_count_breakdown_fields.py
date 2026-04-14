"""add live image unique and duplicate count fields

Revision ID: 0032_live_image_count_breakdown_fields
Revises: 0031_cloudflare_lighthouse_detail_fields
Create Date: 2026-04-12 00:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0032_live_image_count_breakdown_fields"
down_revision = "0031_cloudflare_lighthouse_detail_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("synced_blogger_posts", sa.Column("live_unique_image_count", sa.Integer(), nullable=True))
    op.add_column("synced_blogger_posts", sa.Column("live_duplicate_image_count", sa.Integer(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("live_unique_image_count", sa.Integer(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("live_duplicate_image_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("synced_cloudflare_posts", "live_duplicate_image_count")
    op.drop_column("synced_cloudflare_posts", "live_unique_image_count")
    op.drop_column("synced_blogger_posts", "live_duplicate_image_count")
    op.drop_column("synced_blogger_posts", "live_unique_image_count")

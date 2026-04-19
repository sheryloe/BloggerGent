"""add cloudflare image health status

Revision ID: 0035_cloudflare_image_health_status
Revises: 0034_travel_translation_state_fields
Create Date: 2026-04-19 21:50:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0035_cloudflare_image_health_status"
down_revision = "0034_travel_translation_state_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("synced_cloudflare_posts", sa.Column("image_health_status", sa.String(length=30), nullable=True))
    op.create_index(
        op.f("ix_synced_cloudflare_posts_image_health_status"),
        "synced_cloudflare_posts",
        ["image_health_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_synced_cloudflare_posts_image_health_status"), table_name="synced_cloudflare_posts")
    op.drop_column("synced_cloudflare_posts", "image_health_status")

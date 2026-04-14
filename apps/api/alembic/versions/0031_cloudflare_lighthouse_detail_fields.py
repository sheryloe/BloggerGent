"""add cloudflare lighthouse detail fields

Revision ID: 0031_cloudflare_lighthouse_detail_fields
Revises: 0030_performance_pattern_and_image_breakdown
Create Date: 2026-04-12 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0031_cloudflare_lighthouse_detail_fields"
down_revision = "0030_performance_pattern_and_image_breakdown"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("synced_cloudflare_posts", sa.Column("lighthouse_accessibility_score", sa.Float(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("lighthouse_best_practices_score", sa.Float(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("lighthouse_seo_score", sa.Float(), nullable=True))
    op.add_column(
        "synced_cloudflare_posts",
        sa.Column("lighthouse_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.add_column("synced_cloudflare_posts", sa.Column("lighthouse_last_audited_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_synced_cloudflare_posts_lighthouse_last_audited_at",
        "synced_cloudflare_posts",
        ["lighthouse_last_audited_at"],
        unique=False,
    )
    op.alter_column("synced_cloudflare_posts", "lighthouse_payload", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_synced_cloudflare_posts_lighthouse_last_audited_at", table_name="synced_cloudflare_posts")
    op.drop_column("synced_cloudflare_posts", "lighthouse_last_audited_at")
    op.drop_column("synced_cloudflare_posts", "lighthouse_payload")
    op.drop_column("synced_cloudflare_posts", "lighthouse_seo_score")
    op.drop_column("synced_cloudflare_posts", "lighthouse_best_practices_score")
    op.drop_column("synced_cloudflare_posts", "lighthouse_accessibility_score")

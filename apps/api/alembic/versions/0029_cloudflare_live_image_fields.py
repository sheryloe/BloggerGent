"""Add live image audit fields to synced_cloudflare_posts.

Revision ID: 0029_cloudflare_live_image_fields
Revises: 0028_telegram_ops_tables
Create Date: 2026-04-11 09:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_cloudflare_live_image_fields"
down_revision = "0028_telegram_ops_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("synced_cloudflare_posts", sa.Column("live_image_count", sa.Integer(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("live_image_issue", sa.String(length=255), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("live_image_audited_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f("ix_synced_cloudflare_posts_live_image_audited_at"),
        "synced_cloudflare_posts",
        ["live_image_audited_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_synced_cloudflare_posts_live_image_audited_at"), table_name="synced_cloudflare_posts")
    op.drop_column("synced_cloudflare_posts", "live_image_audited_at")
    op.drop_column("synced_cloudflare_posts", "live_image_issue")
    op.drop_column("synced_cloudflare_posts", "live_image_count")

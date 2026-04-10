"""Add live Blogger image audit fields and Cloudflare canonical category scores.

Revision ID: 0027_live_audit_and_cloudflare_canonical_fields
Revises: 0026_lighthouse_scores, 0026_r2_asset_relayout_mappings
Create Date: 2026-04-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_live_audit_and_cloudflare_canonical_fields"
down_revision = ("0026_lighthouse_scores", "0026_r2_asset_relayout_mappings")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("synced_blogger_posts", sa.Column("live_image_count", sa.Integer(), nullable=True))
    op.add_column("synced_blogger_posts", sa.Column("live_cover_present", sa.Boolean(), nullable=True))
    op.add_column("synced_blogger_posts", sa.Column("live_inline_present", sa.Boolean(), nullable=True))
    op.add_column("synced_blogger_posts", sa.Column("live_image_issue", sa.String(length=255), nullable=True))
    op.add_column("synced_blogger_posts", sa.Column("live_image_audited_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f("ix_synced_blogger_posts_live_image_audited_at"),
        "synced_blogger_posts",
        ["live_image_audited_at"],
        unique=False,
    )

    op.add_column("synced_cloudflare_posts", sa.Column("canonical_category_name", sa.String(length=255), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("canonical_category_slug", sa.String(length=255), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("lighthouse_score", sa.Float(), nullable=True))
    op.create_index(
        op.f("ix_synced_cloudflare_posts_canonical_category_slug"),
        "synced_cloudflare_posts",
        ["canonical_category_slug"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_synced_cloudflare_posts_canonical_category_slug"),
        table_name="synced_cloudflare_posts",
    )
    op.drop_column("synced_cloudflare_posts", "lighthouse_score")
    op.drop_column("synced_cloudflare_posts", "canonical_category_slug")
    op.drop_column("synced_cloudflare_posts", "canonical_category_name")

    op.drop_index(
        op.f("ix_synced_blogger_posts_live_image_audited_at"),
        table_name="synced_blogger_posts",
    )
    op.drop_column("synced_blogger_posts", "live_image_audited_at")
    op.drop_column("synced_blogger_posts", "live_image_issue")
    op.drop_column("synced_blogger_posts", "live_inline_present")
    op.drop_column("synced_blogger_posts", "live_cover_present")
    op.drop_column("synced_blogger_posts", "live_image_count")

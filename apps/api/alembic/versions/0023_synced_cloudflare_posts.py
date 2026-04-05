"""Add synced Cloudflare posts table.

Revision ID: 0023_synced_cloudflare_posts
Revises: 0022_content_item_pub_errors
Create Date: 2026-04-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_synced_cloudflare_posts"
down_revision = "0022_content_item_pub_errors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "synced_cloudflare_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("managed_channel_id", sa.Integer(), nullable=False),
        sa.Column("remote_post_id", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at_remote", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_remote", sa.DateTime(timezone=True), nullable=True),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("category_name", sa.String(length=255), nullable=True),
        sa.Column("category_slug", sa.String(length=255), nullable=True),
        sa.Column("excerpt_text", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=1000), nullable=True),
        sa.Column("seo_score", sa.Float(), nullable=True),
        sa.Column("geo_score", sa.Float(), nullable=True),
        sa.Column("ctr", sa.Float(), nullable=True),
        sa.Column("index_status", sa.String(length=50), nullable=True),
        sa.Column("quality_status", sa.String(length=50), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["managed_channel_id"], ["managed_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "managed_channel_id",
            "remote_post_id",
            name="uq_synced_cloudflare_posts_channel_remote_post",
        ),
    )
    op.create_index(op.f("ix_synced_cloudflare_posts_id"), "synced_cloudflare_posts", ["id"], unique=False)
    op.create_index(
        op.f("ix_synced_cloudflare_posts_managed_channel_id"),
        "synced_cloudflare_posts",
        ["managed_channel_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_synced_cloudflare_posts_remote_post_id"),
        "synced_cloudflare_posts",
        ["remote_post_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_synced_cloudflare_posts_published_at"),
        "synced_cloudflare_posts",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_synced_cloudflare_posts_created_at_remote"),
        "synced_cloudflare_posts",
        ["created_at_remote"],
        unique=False,
    )
    op.create_index(
        op.f("ix_synced_cloudflare_posts_updated_at_remote"),
        "synced_cloudflare_posts",
        ["updated_at_remote"],
        unique=False,
    )
    op.create_index(
        op.f("ix_synced_cloudflare_posts_synced_at"),
        "synced_cloudflare_posts",
        ["synced_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_synced_cloudflare_posts_category_slug"),
        "synced_cloudflare_posts",
        ["category_slug"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_synced_cloudflare_posts_category_slug"), table_name="synced_cloudflare_posts")
    op.drop_index(op.f("ix_synced_cloudflare_posts_synced_at"), table_name="synced_cloudflare_posts")
    op.drop_index(op.f("ix_synced_cloudflare_posts_updated_at_remote"), table_name="synced_cloudflare_posts")
    op.drop_index(op.f("ix_synced_cloudflare_posts_created_at_remote"), table_name="synced_cloudflare_posts")
    op.drop_index(op.f("ix_synced_cloudflare_posts_published_at"), table_name="synced_cloudflare_posts")
    op.drop_index(op.f("ix_synced_cloudflare_posts_remote_post_id"), table_name="synced_cloudflare_posts")
    op.drop_index(op.f("ix_synced_cloudflare_posts_managed_channel_id"), table_name="synced_cloudflare_posts")
    op.drop_index(op.f("ix_synced_cloudflare_posts_id"), table_name="synced_cloudflare_posts")
    op.drop_table("synced_cloudflare_posts")

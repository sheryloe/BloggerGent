"""add Cloudflare persona packs

Revision ID: 0039_cloudflare_persona_packs
Revises: 0038_travel_pattern_keys
Create Date: 2026-04-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0039_cloudflare_persona_packs"
down_revision = "0038_travel_pattern_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloudflare_category_persona_packs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("managed_channel_id", sa.Integer(), nullable=False),
        sa.Column("category_slug", sa.String(length=120), nullable=False),
        sa.Column("category_id", sa.String(length=120), nullable=True),
        sa.Column("pack_key", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("primary_reader", sa.Text(), nullable=True),
        sa.Column("reader_problem", sa.Text(), nullable=True),
        sa.Column("tone_summary", sa.Text(), nullable=True),
        sa.Column("trust_style", sa.Text(), nullable=True),
        sa.Column("topic_guidance", sa.JSON(), nullable=False),
        sa.Column("title_rules", sa.JSON(), nullable=False),
        sa.Column("ctr_rules", sa.JSON(), nullable=False),
        sa.Column("category_emphasis", sa.JSON(), nullable=False),
        sa.Column("sanitized_profiles", sa.JSON(), nullable=False),
        sa.Column("source_manifest_ref", sa.String(length=1000), nullable=True),
        sa.Column("attribution", sa.String(length=500), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["managed_channel_id"], ["managed_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("managed_channel_id", "category_slug", "pack_key", name="uq_cloudflare_category_persona_pack"),
    )
    op.create_index(op.f("ix_cloudflare_category_persona_packs_id"), "cloudflare_category_persona_packs", ["id"], unique=False)
    op.create_index(op.f("ix_cloudflare_category_persona_packs_managed_channel_id"), "cloudflare_category_persona_packs", ["managed_channel_id"], unique=False)
    op.create_index(op.f("ix_cloudflare_category_persona_packs_category_slug"), "cloudflare_category_persona_packs", ["category_slug"], unique=False)
    op.create_index(op.f("ix_cloudflare_category_persona_packs_pack_key"), "cloudflare_category_persona_packs", ["pack_key"], unique=False)
    op.create_index(op.f("ix_cloudflare_category_persona_packs_is_active"), "cloudflare_category_persona_packs", ["is_active"], unique=False)
    op.create_index(op.f("ix_cloudflare_category_persona_packs_is_default"), "cloudflare_category_persona_packs", ["is_default"], unique=False)
    op.create_index(
        "ix_cloudflare_category_persona_packs_channel_category_active",
        "cloudflare_category_persona_packs",
        ["managed_channel_id", "category_slug", "is_active"],
        unique=False,
    )

    op.add_column("content_items", sa.Column("persona_pack_key", sa.String(length=120), nullable=True))
    op.add_column("content_items", sa.Column("persona_pack_version", sa.Integer(), nullable=True))
    op.add_column("content_items", sa.Column("persona_fit_score", sa.Float(), nullable=True))
    op.add_column("content_items", sa.Column("persona_fit_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.create_index(op.f("ix_content_items_persona_pack_key"), "content_items", ["persona_pack_key"], unique=False)
    op.alter_column("content_items", "persona_fit_payload", server_default=None)

    op.add_column("synced_cloudflare_posts", sa.Column("persona_pack_key", sa.String(length=120), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("persona_pack_version", sa.Integer(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("persona_fit_score", sa.Float(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("persona_fit_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.create_index(op.f("ix_synced_cloudflare_posts_persona_pack_key"), "synced_cloudflare_posts", ["persona_pack_key"], unique=False)
    op.alter_column("synced_cloudflare_posts", "persona_fit_payload", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_synced_cloudflare_posts_persona_pack_key"), table_name="synced_cloudflare_posts")
    op.drop_column("synced_cloudflare_posts", "persona_fit_payload")
    op.drop_column("synced_cloudflare_posts", "persona_fit_score")
    op.drop_column("synced_cloudflare_posts", "persona_pack_version")
    op.drop_column("synced_cloudflare_posts", "persona_pack_key")

    op.drop_index(op.f("ix_content_items_persona_pack_key"), table_name="content_items")
    op.drop_column("content_items", "persona_fit_payload")
    op.drop_column("content_items", "persona_fit_score")
    op.drop_column("content_items", "persona_pack_version")
    op.drop_column("content_items", "persona_pack_key")

    op.drop_index("ix_cloudflare_category_persona_packs_channel_category_active", table_name="cloudflare_category_persona_packs")
    op.drop_index(op.f("ix_cloudflare_category_persona_packs_is_default"), table_name="cloudflare_category_persona_packs")
    op.drop_index(op.f("ix_cloudflare_category_persona_packs_is_active"), table_name="cloudflare_category_persona_packs")
    op.drop_index(op.f("ix_cloudflare_category_persona_packs_pack_key"), table_name="cloudflare_category_persona_packs")
    op.drop_index(op.f("ix_cloudflare_category_persona_packs_category_slug"), table_name="cloudflare_category_persona_packs")
    op.drop_index(op.f("ix_cloudflare_category_persona_packs_managed_channel_id"), table_name="cloudflare_category_persona_packs")
    op.drop_index(op.f("ix_cloudflare_category_persona_packs_id"), table_name="cloudflare_category_persona_packs")
    op.drop_table("cloudflare_category_persona_packs")

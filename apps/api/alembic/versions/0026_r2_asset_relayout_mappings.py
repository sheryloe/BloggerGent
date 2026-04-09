"""Add R2 asset relayout mapping table for WebP migration tracking.

Revision ID: 0026_r2_asset_relayout_mappings
Revises: 0025_planner_brief_runs
Create Date: 2026-04-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_r2_asset_relayout_mappings"
down_revision = "0025_planner_brief_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "r2_asset_relayout_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_blog_id", sa.Integer(), nullable=True),
        sa.Column("source_post_id", sa.String(length=255), nullable=False),
        sa.Column("source_post_url", sa.String(length=1000), nullable=True),
        sa.Column("legacy_url", sa.String(length=1500), nullable=True),
        sa.Column("legacy_key", sa.String(length=1024), nullable=True),
        sa.Column("migrated_url", sa.String(length=1500), nullable=True),
        sa.Column("migrated_key", sa.String(length=1024), nullable=True),
        sa.Column("blog_group", sa.String(length=80), nullable=True),
        sa.Column("category_key", sa.String(length=80), nullable=True),
        sa.Column("asset_role", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'mapped'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_blog_id"], ["blogs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type",
            "source_post_id",
            "legacy_key",
            "migrated_key",
            name="uq_r2_asset_relayout_source_post_legacy_migrated",
        ),
    )
    op.create_index(op.f("ix_r2_asset_relayout_mappings_id"), "r2_asset_relayout_mappings", ["id"], unique=False)
    op.create_index(
        op.f("ix_r2_asset_relayout_mappings_source_type"),
        "r2_asset_relayout_mappings",
        ["source_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_r2_asset_relayout_mappings_source_blog_id"),
        "r2_asset_relayout_mappings",
        ["source_blog_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_r2_asset_relayout_mappings_source_post_id"),
        "r2_asset_relayout_mappings",
        ["source_post_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_r2_asset_relayout_mappings_legacy_key"),
        "r2_asset_relayout_mappings",
        ["legacy_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_r2_asset_relayout_mappings_migrated_key"),
        "r2_asset_relayout_mappings",
        ["migrated_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_r2_asset_relayout_mappings_blog_group"),
        "r2_asset_relayout_mappings",
        ["blog_group"],
        unique=False,
    )
    op.create_index(
        op.f("ix_r2_asset_relayout_mappings_category_key"),
        "r2_asset_relayout_mappings",
        ["category_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_r2_asset_relayout_mappings_status"),
        "r2_asset_relayout_mappings",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_r2_asset_relayout_mappings_cleaned_at"),
        "r2_asset_relayout_mappings",
        ["cleaned_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_r2_asset_relayout_mappings_created_at"),
        "r2_asset_relayout_mappings",
        ["created_at"],
        unique=False,
    )

    with op.batch_alter_table("r2_asset_relayout_mappings") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=30), server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_created_at"), table_name="r2_asset_relayout_mappings")
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_cleaned_at"), table_name="r2_asset_relayout_mappings")
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_status"), table_name="r2_asset_relayout_mappings")
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_category_key"), table_name="r2_asset_relayout_mappings")
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_blog_group"), table_name="r2_asset_relayout_mappings")
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_migrated_key"), table_name="r2_asset_relayout_mappings")
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_legacy_key"), table_name="r2_asset_relayout_mappings")
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_source_post_id"), table_name="r2_asset_relayout_mappings")
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_source_blog_id"), table_name="r2_asset_relayout_mappings")
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_source_type"), table_name="r2_asset_relayout_mappings")
    op.drop_index(op.f("ix_r2_asset_relayout_mappings_id"), table_name="r2_asset_relayout_mappings")
    op.drop_table("r2_asset_relayout_mappings")

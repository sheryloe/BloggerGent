"""add manual image slots

Revision ID: 0037_manual_image_slots
Revises: 0036_travel_image_migration_status
Create Date: 2026-04-22 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0037_manual_image_slots"
down_revision = "0036_travel_image_migration_status"
branch_labels = None
depends_on = None


manual_image_slot_status = postgresql.ENUM(
    "pending",
    "applied",
    "failed",
    "cancelled",
    name="manual_image_slot_status",
    create_type=False,
)


def upgrade() -> None:
    manual_image_slot_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "manual_image_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("serial_code", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("blog_id", sa.Integer(), sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=True),
        sa.Column("blogger_post_id", sa.Integer(), sa.ForeignKey("blogger_posts.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "managed_channel_id",
            sa.Integer(),
            sa.ForeignKey("managed_channels.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "synced_cloudflare_post_id",
            sa.Integer(),
            sa.ForeignKey("synced_cloudflare_posts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("remote_post_id", sa.String(length=255), nullable=True),
        sa.Column("slot_role", sa.String(length=40), nullable=False, server_default="hero"),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", manual_image_slot_status, nullable=False, server_default="pending"),
        sa.Column("file_path", sa.String(length=1000), nullable=True),
        sa.Column("public_url", sa.String(length=1000), nullable=True),
        sa.Column("object_key", sa.String(length=1000), nullable=True),
        sa.Column("batch_key", sa.String(length=120), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("serial_code", name="uq_manual_image_slots_serial_code"),
        sa.UniqueConstraint("provider", "remote_post_id", "slot_role", name="uq_manual_image_slots_provider_remote_slot"),
    )
    op.create_index(op.f("ix_manual_image_slots_id"), "manual_image_slots", ["id"], unique=False)
    op.create_index(op.f("ix_manual_image_slots_serial_code"), "manual_image_slots", ["serial_code"], unique=False)
    op.create_index(op.f("ix_manual_image_slots_provider"), "manual_image_slots", ["provider"], unique=False)
    op.create_index(op.f("ix_manual_image_slots_blog_id"), "manual_image_slots", ["blog_id"], unique=False)
    op.create_index(op.f("ix_manual_image_slots_job_id"), "manual_image_slots", ["job_id"], unique=False)
    op.create_index(op.f("ix_manual_image_slots_article_id"), "manual_image_slots", ["article_id"], unique=False)
    op.create_index(op.f("ix_manual_image_slots_blogger_post_id"), "manual_image_slots", ["blogger_post_id"], unique=False)
    op.create_index(op.f("ix_manual_image_slots_managed_channel_id"), "manual_image_slots", ["managed_channel_id"], unique=False)
    op.create_index(
        op.f("ix_manual_image_slots_synced_cloudflare_post_id"),
        "manual_image_slots",
        ["synced_cloudflare_post_id"],
        unique=False,
    )
    op.create_index(op.f("ix_manual_image_slots_remote_post_id"), "manual_image_slots", ["remote_post_id"], unique=False)
    op.create_index(op.f("ix_manual_image_slots_slot_role"), "manual_image_slots", ["slot_role"], unique=False)
    op.create_index(op.f("ix_manual_image_slots_status"), "manual_image_slots", ["status"], unique=False)
    op.create_index(op.f("ix_manual_image_slots_batch_key"), "manual_image_slots", ["batch_key"], unique=False)
    op.create_index(
        "ix_manual_image_slots_provider_status",
        "manual_image_slots",
        ["provider", "status"],
        unique=False,
    )
    op.create_index(
        "ix_manual_image_slots_blog_status",
        "manual_image_slots",
        ["blog_id", "status"],
        unique=False,
    )
    op.alter_column("manual_image_slots", "slot_role", server_default=None)
    op.alter_column("manual_image_slots", "prompt", server_default=None)
    op.alter_column("manual_image_slots", "status", server_default=None)
    op.alter_column("manual_image_slots", "metadata", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_manual_image_slots_blog_status", table_name="manual_image_slots")
    op.drop_index("ix_manual_image_slots_provider_status", table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_batch_key"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_status"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_slot_role"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_remote_post_id"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_synced_cloudflare_post_id"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_managed_channel_id"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_blogger_post_id"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_article_id"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_job_id"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_blog_id"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_provider"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_serial_code"), table_name="manual_image_slots")
    op.drop_index(op.f("ix_manual_image_slots_id"), table_name="manual_image_slots")
    op.drop_table("manual_image_slots")
    manual_image_slot_status.drop(op.get_bind(), checkfirst=True)

"""add travel image migration status to synced blogger posts

Revision ID: 0036_travel_image_migration_status
Revises: 0035_cloudflare_image_health_status
Create Date: 2026-04-20 14:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0036_travel_image_migration_status"
down_revision = "0035_cloudflare_image_health_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "synced_blogger_posts",
        sa.Column(
            "travel_image_migration_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.create_index(
        op.f("ix_synced_blogger_posts_travel_image_migration_status"),
        "synced_blogger_posts",
        ["travel_image_migration_status"],
        unique=False,
    )
    op.alter_column(
        "synced_blogger_posts",
        "travel_image_migration_status",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_synced_blogger_posts_travel_image_migration_status"),
        table_name="synced_blogger_posts",
    )
    op.drop_column("synced_blogger_posts", "travel_image_migration_status")

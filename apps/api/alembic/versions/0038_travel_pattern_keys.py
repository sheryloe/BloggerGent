"""add travel pattern key fields

Revision ID: 0038_travel_pattern_keys
Revises: 0037_manual_image_slots
Create Date: 2026-04-27 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0038_travel_pattern_keys"
down_revision = "0037_manual_image_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DO $$ BEGIN "
            "ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'FAILED_TEMP'; "
            "EXCEPTION WHEN undefined_object THEN NULL; "
            "END $$;"
        )
    op.add_column("articles", sa.Column("article_pattern_key", sa.String(length=100), nullable=True))
    op.add_column("articles", sa.Column("article_pattern_version_key", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_articles_article_pattern_key"), "articles", ["article_pattern_key"], unique=False)
    op.add_column("analytics_article_facts", sa.Column("article_pattern_key", sa.String(length=100), nullable=True))
    op.add_column("analytics_article_facts", sa.Column("article_pattern_version_key", sa.String(length=100), nullable=True))
    op.create_index(
        op.f("ix_analytics_article_facts_article_pattern_key"),
        "analytics_article_facts",
        ["article_pattern_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_analytics_article_facts_article_pattern_key"), table_name="analytics_article_facts")
    op.drop_column("analytics_article_facts", "article_pattern_version_key")
    op.drop_column("analytics_article_facts", "article_pattern_key")
    op.drop_index(op.f("ix_articles_article_pattern_key"), table_name="articles")
    op.drop_column("articles", "article_pattern_version_key")
    op.drop_column("articles", "article_pattern_key")

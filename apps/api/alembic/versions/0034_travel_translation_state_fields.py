"""add travel translation state fields to articles

Revision ID: 0034_travel_translation_state_fields
Revises: 0033_render_metadata_fields
Create Date: 2026-04-19 11:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0034_travel_translation_state_fields"
down_revision = "0033_render_metadata_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("travel_sync_group_key", sa.String(length=120), nullable=True))
    op.add_column("articles", sa.Column("travel_sync_role", sa.String(length=30), nullable=True))
    op.add_column("articles", sa.Column("travel_sync_source_article_id", sa.Integer(), nullable=True))
    op.add_column("articles", sa.Column("travel_sync_es_article_id", sa.Integer(), nullable=True))
    op.add_column("articles", sa.Column("travel_sync_ja_article_id", sa.Integer(), nullable=True))
    op.add_column("articles", sa.Column("travel_sync_es_status", sa.String(length=30), nullable=True))
    op.add_column("articles", sa.Column("travel_sync_ja_status", sa.String(length=30), nullable=True))
    op.add_column("articles", sa.Column("travel_sync_last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "articles",
        sa.Column("travel_all_languages_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_index(op.f("ix_articles_travel_sync_group_key"), "articles", ["travel_sync_group_key"], unique=False)
    op.create_index(op.f("ix_articles_travel_sync_role"), "articles", ["travel_sync_role"], unique=False)
    op.create_index(
        op.f("ix_articles_travel_sync_source_article_id"),
        "articles",
        ["travel_sync_source_article_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_articles_travel_sync_es_article_id"),
        "articles",
        ["travel_sync_es_article_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_articles_travel_sync_ja_article_id"),
        "articles",
        ["travel_sync_ja_article_id"],
        unique=False,
    )
    op.create_index(op.f("ix_articles_travel_sync_es_status"), "articles", ["travel_sync_es_status"], unique=False)
    op.create_index(op.f("ix_articles_travel_sync_ja_status"), "articles", ["travel_sync_ja_status"], unique=False)
    op.create_index(
        op.f("ix_articles_travel_sync_last_checked_at"),
        "articles",
        ["travel_sync_last_checked_at"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_articles_travel_sync_source_article_id",
        "articles",
        "articles",
        ["travel_sync_source_article_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_articles_travel_sync_es_article_id",
        "articles",
        "articles",
        ["travel_sync_es_article_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_articles_travel_sync_ja_article_id",
        "articles",
        "articles",
        ["travel_sync_ja_article_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("articles", "travel_all_languages_ready", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_articles_travel_sync_ja_article_id", "articles", type_="foreignkey")
    op.drop_constraint("fk_articles_travel_sync_es_article_id", "articles", type_="foreignkey")
    op.drop_constraint("fk_articles_travel_sync_source_article_id", "articles", type_="foreignkey")

    op.drop_index(op.f("ix_articles_travel_sync_last_checked_at"), table_name="articles")
    op.drop_index(op.f("ix_articles_travel_sync_ja_status"), table_name="articles")
    op.drop_index(op.f("ix_articles_travel_sync_es_status"), table_name="articles")
    op.drop_index(op.f("ix_articles_travel_sync_ja_article_id"), table_name="articles")
    op.drop_index(op.f("ix_articles_travel_sync_es_article_id"), table_name="articles")
    op.drop_index(op.f("ix_articles_travel_sync_source_article_id"), table_name="articles")
    op.drop_index(op.f("ix_articles_travel_sync_role"), table_name="articles")
    op.drop_index(op.f("ix_articles_travel_sync_group_key"), table_name="articles")

    op.drop_column("articles", "travel_all_languages_ready")
    op.drop_column("articles", "travel_sync_last_checked_at")
    op.drop_column("articles", "travel_sync_ja_status")
    op.drop_column("articles", "travel_sync_es_status")
    op.drop_column("articles", "travel_sync_ja_article_id")
    op.drop_column("articles", "travel_sync_es_article_id")
    op.drop_column("articles", "travel_sync_source_article_id")
    op.drop_column("articles", "travel_sync_role")
    op.drop_column("articles", "travel_sync_group_key")

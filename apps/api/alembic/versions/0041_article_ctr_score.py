"""add Article CTR quality cache

Revision ID: 0041_article_ctr_score
Revises: 0040_cloudflare_prn_title_rerank
Create Date: 2026-04-29 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0041_article_ctr_score"
down_revision = "0040_cloudflare_prn_title_rerank"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("articles")}
    if "quality_ctr_score" not in columns:
        op.add_column("articles", sa.Column("quality_ctr_score", sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("articles")}
    if "quality_ctr_score" in columns:
        op.drop_column("articles", "quality_ctr_score")

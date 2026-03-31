"""Add article quality cache fields."""

from alembic import op
import sqlalchemy as sa


revision = "0015_article_quality_cache"
down_revision = "0014_editorial_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("quality_similarity_score", sa.Float(), nullable=True))
    op.add_column("articles", sa.Column("quality_most_similar_url", sa.String(length=1000), nullable=True))
    op.add_column("articles", sa.Column("quality_seo_score", sa.Integer(), nullable=True))
    op.add_column("articles", sa.Column("quality_geo_score", sa.Integer(), nullable=True))
    op.add_column("articles", sa.Column("quality_status", sa.String(length=50), nullable=True))
    op.add_column(
        "articles",
        sa.Column("quality_rewrite_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("articles", sa.Column("quality_last_audited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "quality_last_audited_at")
    op.drop_column("articles", "quality_rewrite_attempts")
    op.drop_column("articles", "quality_status")
    op.drop_column("articles", "quality_geo_score")
    op.drop_column("articles", "quality_seo_score")
    op.drop_column("articles", "quality_most_similar_url")
    op.drop_column("articles", "quality_similarity_score")

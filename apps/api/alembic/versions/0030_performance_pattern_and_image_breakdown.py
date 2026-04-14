"""Add performance detail, article pattern, and image breakdown fields.

Revision ID: 0030_performance_pattern_and_image_breakdown
Revises: 0029_cloudflare_live_image_fields
Create Date: 2026-04-11 16:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_performance_pattern_and_image_breakdown"
down_revision = "0029_cloudflare_live_image_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("article_pattern_id", sa.String(length=100), nullable=True))
    op.add_column("articles", sa.Column("article_pattern_version", sa.Integer(), nullable=True))
    op.add_column("articles", sa.Column("quality_lighthouse_accessibility_score", sa.Float(), nullable=True))
    op.add_column("articles", sa.Column("quality_lighthouse_best_practices_score", sa.Float(), nullable=True))
    op.add_column("articles", sa.Column("quality_lighthouse_seo_score", sa.Float(), nullable=True))

    op.add_column("synced_blogger_posts", sa.Column("live_webp_count", sa.Integer(), nullable=True))
    op.add_column("synced_blogger_posts", sa.Column("live_png_count", sa.Integer(), nullable=True))
    op.add_column("synced_blogger_posts", sa.Column("live_other_image_count", sa.Integer(), nullable=True))

    op.add_column("synced_cloudflare_posts", sa.Column("live_webp_count", sa.Integer(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("live_png_count", sa.Integer(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("live_other_image_count", sa.Integer(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("article_pattern_id", sa.String(length=100), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("article_pattern_version", sa.Integer(), nullable=True))

    op.add_column("analytics_article_facts", sa.Column("lighthouse_accessibility_score", sa.Float(), nullable=True))
    op.add_column("analytics_article_facts", sa.Column("lighthouse_best_practices_score", sa.Float(), nullable=True))
    op.add_column("analytics_article_facts", sa.Column("lighthouse_seo_score", sa.Float(), nullable=True))
    op.add_column("analytics_article_facts", sa.Column("article_pattern_id", sa.String(length=100), nullable=True))
    op.add_column("analytics_article_facts", sa.Column("article_pattern_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("analytics_article_facts", "article_pattern_version")
    op.drop_column("analytics_article_facts", "article_pattern_id")
    op.drop_column("analytics_article_facts", "lighthouse_seo_score")
    op.drop_column("analytics_article_facts", "lighthouse_best_practices_score")
    op.drop_column("analytics_article_facts", "lighthouse_accessibility_score")

    op.drop_column("synced_cloudflare_posts", "article_pattern_version")
    op.drop_column("synced_cloudflare_posts", "article_pattern_id")
    op.drop_column("synced_cloudflare_posts", "live_other_image_count")
    op.drop_column("synced_cloudflare_posts", "live_png_count")
    op.drop_column("synced_cloudflare_posts", "live_webp_count")

    op.drop_column("synced_blogger_posts", "live_other_image_count")
    op.drop_column("synced_blogger_posts", "live_png_count")
    op.drop_column("synced_blogger_posts", "live_webp_count")

    op.drop_column("articles", "quality_lighthouse_seo_score")
    op.drop_column("articles", "quality_lighthouse_best_practices_score")
    op.drop_column("articles", "quality_lighthouse_accessibility_score")
    op.drop_column("articles", "article_pattern_version")
    op.drop_column("articles", "article_pattern_id")

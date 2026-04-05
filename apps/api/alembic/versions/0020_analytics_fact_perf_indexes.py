"""analytics fact perf indexes

Revision ID: 0020_analytics_fact_perf_indexes
Revises: 0019_google_indexing_analytics
Create Date: 2026-04-04 00:00:01.000000
"""

from alembic import op


revision = "0020_analytics_fact_perf_indexes"
down_revision = "0019_google_indexing_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_analytics_article_facts_blog_month_published_at",
        "analytics_article_facts",
        ["blog_id", "month", "published_at"],
        unique=False,
    )
    op.create_index(
        "ix_analytics_article_facts_blog_month_source_status",
        "analytics_article_facts",
        ["blog_id", "month", "source_type", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_article_facts_blog_month_source_status", table_name="analytics_article_facts")
    op.drop_index("ix_analytics_article_facts_blog_month_published_at", table_name="analytics_article_facts")

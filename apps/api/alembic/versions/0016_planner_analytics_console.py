"""planner analytics console

Revision ID: 0016_planner_analytics_console
Revises: 0015_article_quality_cache
Create Date: 2026-03-31 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_planner_analytics_console"
down_revision = "0015_article_quality_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blog_themes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blog_id", "key", name="uq_blog_themes_blog_id_key"),
    )
    op.create_index(op.f("ix_blog_themes_id"), "blog_themes", ["id"], unique=False)

    op.create_table(
        "content_plan_days",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("target_post_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="planned"),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blog_id", "plan_date", name="uq_content_plan_days_blog_date"),
    )
    op.create_index(op.f("ix_content_plan_days_id"), "content_plan_days", ["id"], unique=False)
    op.create_index(op.f("ix_content_plan_days_plan_date"), "content_plan_days", ["plan_date"], unique=False)

    op.create_table(
        "content_plan_slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("plan_day_id", sa.Integer(), nullable=False),
        sa.Column("theme_id", sa.Integer(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slot_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="planned"),
        sa.Column("brief_topic", sa.Text(), nullable=True),
        sa.Column("brief_audience", sa.Text(), nullable=True),
        sa.Column("brief_information_level", sa.Text(), nullable=True),
        sa.Column("brief_extra_context", sa.Text(), nullable=True),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_day_id"], ["content_plan_days.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["theme_id"], ["blog_themes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_content_plan_slots_id"), "content_plan_slots", ["id"], unique=False)
    op.create_index(op.f("ix_content_plan_slots_plan_day_id"), "content_plan_slots", ["plan_day_id"], unique=False)
    op.create_index(op.f("ix_content_plan_slots_theme_id"), "content_plan_slots", ["theme_id"], unique=False)
    op.create_index(op.f("ix_content_plan_slots_scheduled_for"), "content_plan_slots", ["scheduled_for"], unique=False)

    op.create_table(
        "analytics_article_facts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("synced_post_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("theme_key", sa.String(length=100), nullable=True),
        sa.Column("theme_name", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("seo_score", sa.Float(), nullable=True),
        sa.Column("geo_score", sa.Float(), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("most_similar_url", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("actual_url", sa.String(length=1000), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="generated"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["synced_post_id"], ["synced_blogger_posts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analytics_article_facts_id"), "analytics_article_facts", ["id"], unique=False)
    op.create_index(op.f("ix_analytics_article_facts_blog_id"), "analytics_article_facts", ["blog_id"], unique=False)
    op.create_index(op.f("ix_analytics_article_facts_month"), "analytics_article_facts", ["month"], unique=False)
    op.create_index(op.f("ix_analytics_article_facts_published_at"), "analytics_article_facts", ["published_at"], unique=False)

    op.create_table(
        "analytics_theme_monthly_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("theme_key", sa.String(length=100), nullable=False),
        sa.Column("theme_name", sa.String(length=255), nullable=False),
        sa.Column("planned_posts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_posts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planned_share", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_share", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gap_share", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_seo_score", sa.Float(), nullable=True),
        sa.Column("avg_geo_score", sa.Float(), nullable=True),
        sa.Column("avg_similarity_score", sa.Float(), nullable=True),
        sa.Column("coverage_gap_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("next_month_weight_suggestion", sa.Integer(), nullable=False, server_default="10"),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analytics_theme_monthly_stats_id"), "analytics_theme_monthly_stats", ["id"], unique=False)
    op.create_index(op.f("ix_analytics_theme_monthly_stats_blog_id"), "analytics_theme_monthly_stats", ["blog_id"], unique=False)
    op.create_index(op.f("ix_analytics_theme_monthly_stats_month"), "analytics_theme_monthly_stats", ["month"], unique=False)

    op.create_table(
        "analytics_blog_monthly_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("total_posts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_seo_score", sa.Float(), nullable=True),
        sa.Column("avg_geo_score", sa.Float(), nullable=True),
        sa.Column("avg_similarity_score", sa.Float(), nullable=True),
        sa.Column("most_underused_theme_key", sa.String(length=100), nullable=True),
        sa.Column("most_underused_theme_name", sa.String(length=255), nullable=True),
        sa.Column("most_overused_theme_key", sa.String(length=100), nullable=True),
        sa.Column("most_overused_theme_name", sa.String(length=255), nullable=True),
        sa.Column("next_month_focus", sa.Text(), nullable=True),
        sa.Column("report_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blog_id", "month", name="uq_analytics_blog_monthly_reports_blog_month"),
    )
    op.create_index(op.f("ix_analytics_blog_monthly_reports_id"), "analytics_blog_monthly_reports", ["id"], unique=False)
    op.create_index(op.f("ix_analytics_blog_monthly_reports_blog_id"), "analytics_blog_monthly_reports", ["blog_id"], unique=False)
    op.create_index(op.f("ix_analytics_blog_monthly_reports_month"), "analytics_blog_monthly_reports", ["month"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_analytics_blog_monthly_reports_month"), table_name="analytics_blog_monthly_reports")
    op.drop_index(op.f("ix_analytics_blog_monthly_reports_blog_id"), table_name="analytics_blog_monthly_reports")
    op.drop_index(op.f("ix_analytics_blog_monthly_reports_id"), table_name="analytics_blog_monthly_reports")
    op.drop_table("analytics_blog_monthly_reports")

    op.drop_index(op.f("ix_analytics_theme_monthly_stats_month"), table_name="analytics_theme_monthly_stats")
    op.drop_index(op.f("ix_analytics_theme_monthly_stats_blog_id"), table_name="analytics_theme_monthly_stats")
    op.drop_index(op.f("ix_analytics_theme_monthly_stats_id"), table_name="analytics_theme_monthly_stats")
    op.drop_table("analytics_theme_monthly_stats")

    op.drop_index(op.f("ix_analytics_article_facts_published_at"), table_name="analytics_article_facts")
    op.drop_index(op.f("ix_analytics_article_facts_month"), table_name="analytics_article_facts")
    op.drop_index(op.f("ix_analytics_article_facts_blog_id"), table_name="analytics_article_facts")
    op.drop_index(op.f("ix_analytics_article_facts_id"), table_name="analytics_article_facts")
    op.drop_table("analytics_article_facts")

    op.drop_index(op.f("ix_content_plan_slots_scheduled_for"), table_name="content_plan_slots")
    op.drop_index(op.f("ix_content_plan_slots_theme_id"), table_name="content_plan_slots")
    op.drop_index(op.f("ix_content_plan_slots_plan_day_id"), table_name="content_plan_slots")
    op.drop_index(op.f("ix_content_plan_slots_id"), table_name="content_plan_slots")
    op.drop_table("content_plan_slots")

    op.drop_index(op.f("ix_content_plan_days_plan_date"), table_name="content_plan_days")
    op.drop_index(op.f("ix_content_plan_days_id"), table_name="content_plan_days")
    op.drop_table("content_plan_days")

    op.drop_index(op.f("ix_blog_themes_id"), table_name="blog_themes")
    op.drop_table("blog_themes")

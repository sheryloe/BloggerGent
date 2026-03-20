"""Add AI usage events, publish queue, and reading time targets."""

from alembic import op
import sqlalchemy as sa


revision = "0010_usage_queue_and_reading_targets"
down_revision = "0009_topic_guard_and_scheduling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blogs",
        sa.Column("target_reading_time_min_minutes", sa.Integer(), nullable=False, server_default="6"),
    )
    op.add_column(
        "blogs",
        sa.Column("target_reading_time_max_minutes", sa.Integer(), nullable=False, server_default="8"),
    )

    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("stage_type", sa.String(length=50), nullable=False),
        sa.Column("provider_mode", sa.String(length=20), nullable=False, server_default="mock"),
        sa.Column("provider_name", sa.String(length=50), nullable=False, server_default="mock"),
        sa.Column("provider_model", sa.String(length=100), nullable=True),
        sa.Column("endpoint", sa.String(length=100), nullable=False, server_default="unknown"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_usage", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_events_id", "ai_usage_events", ["id"])
    op.create_index("ix_ai_usage_events_blog_id", "ai_usage_events", ["blog_id"])
    op.create_index("ix_ai_usage_events_job_id", "ai_usage_events", ["job_id"])
    op.create_index("ix_ai_usage_events_article_id", "ai_usage_events", ["article_id"])
    op.create_index("ix_ai_usage_events_stage_type", "ai_usage_events", ["stage_type"])

    op.create_table(
        "publish_queue_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("requested_mode", sa.String(length=20), nullable=False, server_default="publish"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("response_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_publish_queue_items_id", "publish_queue_items", ["id"])
    op.create_index("ix_publish_queue_items_article_id", "publish_queue_items", ["article_id"])
    op.create_index("ix_publish_queue_items_blog_id", "publish_queue_items", ["blog_id"])
    op.create_index("ix_publish_queue_items_not_before", "publish_queue_items", ["not_before"])
    op.create_index("ix_publish_queue_items_status", "publish_queue_items", ["status"])


def downgrade() -> None:
    op.drop_index("ix_publish_queue_items_status", table_name="publish_queue_items")
    op.drop_index("ix_publish_queue_items_not_before", table_name="publish_queue_items")
    op.drop_index("ix_publish_queue_items_blog_id", table_name="publish_queue_items")
    op.drop_index("ix_publish_queue_items_article_id", table_name="publish_queue_items")
    op.drop_index("ix_publish_queue_items_id", table_name="publish_queue_items")
    op.drop_table("publish_queue_items")

    op.drop_index("ix_ai_usage_events_stage_type", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_article_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_job_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_blog_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_id", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")

    op.drop_column("blogs", "target_reading_time_max_minutes")
    op.drop_column("blogs", "target_reading_time_min_minutes")

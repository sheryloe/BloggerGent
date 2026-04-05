"""google indexing analytics

Revision ID: 0019_google_indexing_analytics
Revises: 0018_multiplatform_foundation
Create Date: 2026-04-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_google_indexing_analytics"
down_revision = "0018_multiplatform_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_index_url_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("canonical_url", sa.String(length=1000), nullable=True),
        sa.Column("index_status", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("index_coverage_state", sa.String(length=255), nullable=True),
        sa.Column("index_state", sa.String(length=255), nullable=True),
        sa.Column("verdict", sa.String(length=30), nullable=True),
        sa.Column("last_crawl_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notify_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_inspection_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_eligible_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_publish_success", sa.Boolean(), nullable=True),
        sa.Column("last_publish_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("inspection_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("metadata_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("publish_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blog_id", "url", name="uq_google_index_url_states_blog_url"),
    )
    op.create_index(op.f("ix_google_index_url_states_id"), "google_index_url_states", ["id"], unique=False)
    op.create_index(op.f("ix_google_index_url_states_blog_id"), "google_index_url_states", ["blog_id"], unique=False)
    op.create_index(op.f("ix_google_index_url_states_url"), "google_index_url_states", ["url"], unique=False)
    op.create_index(op.f("ix_google_index_url_states_index_status"), "google_index_url_states", ["index_status"], unique=False)
    op.create_index(op.f("ix_google_index_url_states_last_crawl_time"), "google_index_url_states", ["last_crawl_time"], unique=False)
    op.create_index(op.f("ix_google_index_url_states_last_notify_time"), "google_index_url_states", ["last_notify_time"], unique=False)
    op.create_index(op.f("ix_google_index_url_states_last_checked_at"), "google_index_url_states", ["last_checked_at"], unique=False)
    op.create_index(op.f("ix_google_index_url_states_last_publish_at"), "google_index_url_states", ["last_publish_at"], unique=False)
    op.create_index(op.f("ix_google_index_url_states_next_eligible_at"), "google_index_url_states", ["next_eligible_at"], unique=False)

    op.create_table(
        "google_index_request_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("request_type", sa.String(length=30), nullable=False),
        sa.Column("trigger_mode", sa.String(length=20), nullable=False),
        sa.Column("is_force", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("response_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_google_index_request_logs_id"), "google_index_request_logs", ["id"], unique=False)
    op.create_index(op.f("ix_google_index_request_logs_blog_id"), "google_index_request_logs", ["blog_id"], unique=False)
    op.create_index(op.f("ix_google_index_request_logs_url"), "google_index_request_logs", ["url"], unique=False)
    op.create_index(op.f("ix_google_index_request_logs_request_type"), "google_index_request_logs", ["request_type"], unique=False)
    op.create_index(op.f("ix_google_index_request_logs_trigger_mode"), "google_index_request_logs", ["trigger_mode"], unique=False)
    op.create_index(op.f("ix_google_index_request_logs_success"), "google_index_request_logs", ["success"], unique=False)
    op.create_index(op.f("ix_google_index_request_logs_created_at"), "google_index_request_logs", ["created_at"], unique=False)

    op.create_table(
        "search_console_page_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("clicks", sa.Float(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Float(), nullable=True),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blog_id", "url", name="uq_search_console_page_metrics_blog_url"),
    )
    op.create_index(op.f("ix_search_console_page_metrics_id"), "search_console_page_metrics", ["id"], unique=False)
    op.create_index(op.f("ix_search_console_page_metrics_blog_id"), "search_console_page_metrics", ["blog_id"], unique=False)
    op.create_index(op.f("ix_search_console_page_metrics_url"), "search_console_page_metrics", ["url"], unique=False)
    op.create_index(op.f("ix_search_console_page_metrics_fetched_at"), "search_console_page_metrics", ["fetched_at"], unique=False)



def downgrade() -> None:
    op.drop_index(op.f("ix_search_console_page_metrics_fetched_at"), table_name="search_console_page_metrics")
    op.drop_index(op.f("ix_search_console_page_metrics_url"), table_name="search_console_page_metrics")
    op.drop_index(op.f("ix_search_console_page_metrics_blog_id"), table_name="search_console_page_metrics")
    op.drop_index(op.f("ix_search_console_page_metrics_id"), table_name="search_console_page_metrics")
    op.drop_table("search_console_page_metrics")

    op.drop_index(op.f("ix_google_index_request_logs_created_at"), table_name="google_index_request_logs")
    op.drop_index(op.f("ix_google_index_request_logs_success"), table_name="google_index_request_logs")
    op.drop_index(op.f("ix_google_index_request_logs_trigger_mode"), table_name="google_index_request_logs")
    op.drop_index(op.f("ix_google_index_request_logs_request_type"), table_name="google_index_request_logs")
    op.drop_index(op.f("ix_google_index_request_logs_url"), table_name="google_index_request_logs")
    op.drop_index(op.f("ix_google_index_request_logs_blog_id"), table_name="google_index_request_logs")
    op.drop_index(op.f("ix_google_index_request_logs_id"), table_name="google_index_request_logs")
    op.drop_table("google_index_request_logs")

    op.drop_index(op.f("ix_google_index_url_states_next_eligible_at"), table_name="google_index_url_states")
    op.drop_index(op.f("ix_google_index_url_states_last_publish_at"), table_name="google_index_url_states")
    op.drop_index(op.f("ix_google_index_url_states_last_checked_at"), table_name="google_index_url_states")
    op.drop_index(op.f("ix_google_index_url_states_last_notify_time"), table_name="google_index_url_states")
    op.drop_index(op.f("ix_google_index_url_states_last_crawl_time"), table_name="google_index_url_states")
    op.drop_index(op.f("ix_google_index_url_states_index_status"), table_name="google_index_url_states")
    op.drop_index(op.f("ix_google_index_url_states_url"), table_name="google_index_url_states")
    op.drop_index(op.f("ix_google_index_url_states_blog_id"), table_name="google_index_url_states")
    op.drop_index(op.f("ix_google_index_url_states_id"), table_name="google_index_url_states")
    op.drop_table("google_index_url_states")

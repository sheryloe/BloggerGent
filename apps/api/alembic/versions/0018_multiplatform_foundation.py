"""multi platform foundation

Revision ID: 0018_multiplatform_foundation
Revises: 0017_channel_planner_refactor
Create Date: 2026-04-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_multiplatform_foundation"
down_revision = "0017_channel_planner_refactor"
branch_labels = None
depends_on = None

NEW_WORKFLOW_STAGE_VALUES = (
    "thumbnail_generation",
    "video_metadata_generation",
    "reel_packaging",
    "platform_publish",
    "performance_review",
    "seo_rewrite",
    "indexing_check",
)


def _add_enum_value(enum_name: str, value: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_enum
                WHERE enumlabel = '{value}'
                  AND enumtypid = (
                    SELECT oid FROM pg_type WHERE typname = '{enum_name}'
                  )
            ) THEN
                ALTER TYPE {enum_name} ADD VALUE '{value}';
            END IF;
        END$$;
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for value in NEW_WORKFLOW_STAGE_VALUES:
            _add_enum_value("workflow_stage_type", value)

    op.create_table(
        "managed_channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("channel_id", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("remote_resource_id", sa.String(length=255), nullable=True),
        sa.Column("linked_blog_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="attention"),
        sa.Column("base_url", sa.String(length=1000), nullable=True),
        sa.Column("primary_category", sa.String(length=100), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("oauth_state", sa.String(length=30), nullable=False, server_default="not_configured"),
        sa.Column("quota_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["linked_blog_id"], ["blogs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id", name="uq_managed_channels_channel_id"),
    )
    op.create_index(op.f("ix_managed_channels_id"), "managed_channels", ["id"], unique=False)
    op.create_index(op.f("ix_managed_channels_provider"), "managed_channels", ["provider"], unique=False)
    op.create_index(op.f("ix_managed_channels_channel_id"), "managed_channels", ["channel_id"], unique=False)
    op.create_index(op.f("ix_managed_channels_remote_resource_id"), "managed_channels", ["remote_resource_id"], unique=False)
    op.create_index(op.f("ix_managed_channels_linked_blog_id"), "managed_channels", ["linked_blog_id"], unique=False)
    op.create_index(op.f("ix_managed_channels_status"), "managed_channels", ["status"], unique=False)

    op.create_table(
        "platform_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("managed_channel_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("credential_key", sa.String(length=120), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("token_type", sa.String(length=30), nullable=False, server_default="Bearer"),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_valid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["managed_channel_id"], ["managed_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "credential_key", name="uq_platform_credentials_provider_key"),
    )
    op.create_index(op.f("ix_platform_credentials_id"), "platform_credentials", ["id"], unique=False)
    op.create_index(op.f("ix_platform_credentials_managed_channel_id"), "platform_credentials", ["managed_channel_id"], unique=False)
    op.create_index(op.f("ix_platform_credentials_provider"), "platform_credentials", ["provider"], unique=False)
    op.create_index(op.f("ix_platform_credentials_credential_key"), "platform_credentials", ["credential_key"], unique=False)

    op.create_table(
        "content_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("managed_channel_id", sa.Integer(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("source_article_id", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("asset_manifest", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("brief", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("review_notes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("approval_status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_feedback", sa.Text(), nullable=True),
        sa.Column("last_score", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by_agent", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["managed_channel_id"], ["managed_channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_article_id"], ["articles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_content_items_id"), "content_items", ["id"], unique=False)
    op.create_index(op.f("ix_content_items_managed_channel_id"), "content_items", ["managed_channel_id"], unique=False)
    op.create_index(op.f("ix_content_items_blog_id"), "content_items", ["blog_id"], unique=False)
    op.create_index(op.f("ix_content_items_job_id"), "content_items", ["job_id"], unique=False)
    op.create_index(op.f("ix_content_items_source_article_id"), "content_items", ["source_article_id"], unique=False)
    op.create_index(op.f("ix_content_items_content_type"), "content_items", ["content_type"], unique=False)
    op.create_index(op.f("ix_content_items_lifecycle_status"), "content_items", ["lifecycle_status"], unique=False)
    op.create_index(op.f("ix_content_items_approval_status"), "content_items", ["approval_status"], unique=False)
    op.create_index(op.f("ix_content_items_scheduled_for"), "content_items", ["scheduled_for"], unique=False)

    op.create_table(
        "publication_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_item_id", sa.Integer(), nullable=False),
        sa.Column("managed_channel_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("remote_id", sa.String(length=255), nullable=True),
        sa.Column("remote_url", sa.String(length=1000), nullable=True),
        sa.Column("publish_status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["managed_channel_id"], ["managed_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_publication_records_id"), "publication_records", ["id"], unique=False)
    op.create_index(op.f("ix_publication_records_content_item_id"), "publication_records", ["content_item_id"], unique=False)
    op.create_index(op.f("ix_publication_records_managed_channel_id"), "publication_records", ["managed_channel_id"], unique=False)
    op.create_index(op.f("ix_publication_records_provider"), "publication_records", ["provider"], unique=False)
    op.create_index(op.f("ix_publication_records_remote_id"), "publication_records", ["remote_id"], unique=False)
    op.create_index(op.f("ix_publication_records_publish_status"), "publication_records", ["publish_status"], unique=False)

    op.create_table(
        "metric_facts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("managed_channel_id", sa.Integer(), nullable=False),
        sa.Column("content_item_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("metric_scope", sa.String(length=30), nullable=False, server_default="content"),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("normalized_score", sa.Float(), nullable=True),
        sa.Column("dimension_key", sa.String(length=100), nullable=True),
        sa.Column("dimension_value", sa.String(length=255), nullable=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["managed_channel_id"], ["managed_channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_metric_facts_id"), "metric_facts", ["id"], unique=False)
    op.create_index(op.f("ix_metric_facts_managed_channel_id"), "metric_facts", ["managed_channel_id"], unique=False)
    op.create_index(op.f("ix_metric_facts_content_item_id"), "metric_facts", ["content_item_id"], unique=False)
    op.create_index(op.f("ix_metric_facts_provider"), "metric_facts", ["provider"], unique=False)
    op.create_index(op.f("ix_metric_facts_metric_scope"), "metric_facts", ["metric_scope"], unique=False)
    op.create_index(op.f("ix_metric_facts_metric_name"), "metric_facts", ["metric_name"], unique=False)
    op.create_index(op.f("ix_metric_facts_snapshot_at"), "metric_facts", ["snapshot_at"], unique=False)

    op.create_table(
        "agent_workers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("managed_channel_id", sa.Integer(), nullable=True),
        sa.Column("worker_key", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("role_name", sa.String(length=120), nullable=False),
        sa.Column("runtime_kind", sa.String(length=30), nullable=False),
        sa.Column("queue_name", sa.String(length=120), nullable=False, server_default="default"),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="idle"),
        sa.Column("config_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["managed_channel_id"], ["managed_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker_key", name="uq_agent_workers_worker_key"),
    )
    op.create_index(op.f("ix_agent_workers_id"), "agent_workers", ["id"], unique=False)
    op.create_index(op.f("ix_agent_workers_managed_channel_id"), "agent_workers", ["managed_channel_id"], unique=False)
    op.create_index(op.f("ix_agent_workers_worker_key"), "agent_workers", ["worker_key"], unique=False)
    op.create_index(op.f("ix_agent_workers_role_name"), "agent_workers", ["role_name"], unique=False)
    op.create_index(op.f("ix_agent_workers_runtime_kind"), "agent_workers", ["runtime_kind"], unique=False)
    op.create_index(op.f("ix_agent_workers_status"), "agent_workers", ["status"], unique=False)

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("managed_channel_id", sa.Integer(), nullable=True),
        sa.Column("content_item_id", sa.Integer(), nullable=True),
        sa.Column("worker_id", sa.Integer(), nullable=True),
        sa.Column("run_key", sa.String(length=120), nullable=False),
        sa.Column("runtime_kind", sa.String(length=30), nullable=False),
        sa.Column("assigned_role", sa.String(length=120), nullable=False),
        sa.Column("provider_model", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_snapshot", sa.Text(), nullable=False, server_default=""),
        sa.Column("response_snapshot", sa.Text(), nullable=False, server_default=""),
        sa.Column("log_lines", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["managed_channel_id"], ["managed_channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["worker_id"], ["agent_workers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uq_agent_runs_run_key"),
    )
    op.create_index(op.f("ix_agent_runs_id"), "agent_runs", ["id"], unique=False)
    op.create_index(op.f("ix_agent_runs_managed_channel_id"), "agent_runs", ["managed_channel_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_content_item_id"), "agent_runs", ["content_item_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_worker_id"), "agent_runs", ["worker_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_run_key"), "agent_runs", ["run_key"], unique=False)
    op.create_index(op.f("ix_agent_runs_runtime_kind"), "agent_runs", ["runtime_kind"], unique=False)
    op.create_index(op.f("ix_agent_runs_assigned_role"), "agent_runs", ["assigned_role"], unique=False)
    op.create_index(op.f("ix_agent_runs_status"), "agent_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_runs_status"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_assigned_role"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_runtime_kind"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_run_key"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_worker_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_content_item_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_managed_channel_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_id"), table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index(op.f("ix_agent_workers_status"), table_name="agent_workers")
    op.drop_index(op.f("ix_agent_workers_runtime_kind"), table_name="agent_workers")
    op.drop_index(op.f("ix_agent_workers_role_name"), table_name="agent_workers")
    op.drop_index(op.f("ix_agent_workers_worker_key"), table_name="agent_workers")
    op.drop_index(op.f("ix_agent_workers_managed_channel_id"), table_name="agent_workers")
    op.drop_index(op.f("ix_agent_workers_id"), table_name="agent_workers")
    op.drop_table("agent_workers")

    op.drop_index(op.f("ix_metric_facts_snapshot_at"), table_name="metric_facts")
    op.drop_index(op.f("ix_metric_facts_metric_name"), table_name="metric_facts")
    op.drop_index(op.f("ix_metric_facts_metric_scope"), table_name="metric_facts")
    op.drop_index(op.f("ix_metric_facts_provider"), table_name="metric_facts")
    op.drop_index(op.f("ix_metric_facts_content_item_id"), table_name="metric_facts")
    op.drop_index(op.f("ix_metric_facts_managed_channel_id"), table_name="metric_facts")
    op.drop_index(op.f("ix_metric_facts_id"), table_name="metric_facts")
    op.drop_table("metric_facts")

    op.drop_index(op.f("ix_publication_records_publish_status"), table_name="publication_records")
    op.drop_index(op.f("ix_publication_records_remote_id"), table_name="publication_records")
    op.drop_index(op.f("ix_publication_records_provider"), table_name="publication_records")
    op.drop_index(op.f("ix_publication_records_managed_channel_id"), table_name="publication_records")
    op.drop_index(op.f("ix_publication_records_content_item_id"), table_name="publication_records")
    op.drop_index(op.f("ix_publication_records_id"), table_name="publication_records")
    op.drop_table("publication_records")

    op.drop_index(op.f("ix_content_items_scheduled_for"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_approval_status"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_lifecycle_status"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_content_type"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_source_article_id"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_job_id"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_blog_id"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_managed_channel_id"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_id"), table_name="content_items")
    op.drop_table("content_items")

    op.drop_index(op.f("ix_platform_credentials_credential_key"), table_name="platform_credentials")
    op.drop_index(op.f("ix_platform_credentials_provider"), table_name="platform_credentials")
    op.drop_index(op.f("ix_platform_credentials_managed_channel_id"), table_name="platform_credentials")
    op.drop_index(op.f("ix_platform_credentials_id"), table_name="platform_credentials")
    op.drop_table("platform_credentials")

    op.drop_index(op.f("ix_managed_channels_status"), table_name="managed_channels")
    op.drop_index(op.f("ix_managed_channels_linked_blog_id"), table_name="managed_channels")
    op.drop_index(op.f("ix_managed_channels_remote_resource_id"), table_name="managed_channels")
    op.drop_index(op.f("ix_managed_channels_channel_id"), table_name="managed_channels")
    op.drop_index(op.f("ix_managed_channels_provider"), table_name="managed_channels")
    op.drop_index(op.f("ix_managed_channels_id"), table_name="managed_channels")
    op.drop_table("managed_channels")

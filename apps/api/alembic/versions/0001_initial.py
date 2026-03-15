"""Initial schema for Bloggent."""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


job_status = sa.Enum(
    "PENDING",
    "DISCOVERING_TOPICS",
    "GENERATING_ARTICLE",
    "GENERATING_IMAGE_PROMPT",
    "GENERATING_IMAGE",
    "ASSEMBLING_HTML",
    "FINDING_RELATED_POSTS",
    "PUBLISHING",
    "COMPLETED",
    "FAILED",
    name="job_status",
)

publish_mode = sa.Enum("draft", "publish", name="publish_mode")
log_level = sa.Enum("INFO", "WARNING", "ERROR", name="log_level")


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="gemini"),
        sa.Column("locale", sa.String(length=20), nullable=False, server_default="global"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("keyword"),
    )
    op.create_index("ix_topics_id", "topics", ["id"])
    op.create_index("ix_topics_keyword", "topics", ["keyword"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("keyword_snapshot", sa.String(length=255), nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="PENDING"),
        sa.Column("publish_mode", publish_mode, nullable=False, server_default="draft"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_logs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("raw_prompts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("raw_responses", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_jobs_id", "jobs", ["id"])
    op.create_index("ix_jobs_keyword_snapshot", "jobs", ["keyword_snapshot"])

    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("meta_description", sa.String(length=320), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("html_article", sa.Text(), nullable=False),
        sa.Column("faq_section", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("image_collage_prompt", sa.Text(), nullable=False),
        sa.Column("assembled_html", sa.Text(), nullable=True),
        sa.Column("reading_time_minutes", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_articles_id", "articles", ["id"])
    op.create_index("ix_articles_slug", "articles", ["slug"])

    op.create_table(
        "images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("public_url", sa.String(length=500), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False, server_default="1536"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="mock"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_images_id", "images", ["id"])

    op.create_table(
        "blogger_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("blogger_post_id", sa.String(length=255), nullable=False),
        sa.Column("published_url", sa.String(length=500), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("response_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_blogger_posts_id", "blogger_posts", ["id"])
    op.create_index("ix_blogger_posts_blogger_post_id", "blogger_posts", ["blogger_post_id"])

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_settings_id", "settings", ["id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("level", log_level, nullable=False, server_default="INFO"),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_job_id", "audit_logs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_job_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_settings_id", table_name="settings")
    op.drop_table("settings")

    op.drop_index("ix_blogger_posts_blogger_post_id", table_name="blogger_posts")
    op.drop_index("ix_blogger_posts_id", table_name="blogger_posts")
    op.drop_table("blogger_posts")

    op.drop_index("ix_images_id", table_name="images")
    op.drop_table("images")

    op.drop_index("ix_articles_slug", table_name="articles")
    op.drop_index("ix_articles_id", table_name="articles")
    op.drop_table("articles")

    op.drop_index("ix_jobs_keyword_snapshot", table_name="jobs")
    op.drop_index("ix_jobs_id", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_topics_keyword", table_name="topics")
    op.drop_index("ix_topics_id", table_name="topics")
    op.drop_table("topics")

    bind = op.get_bind()
    log_level.drop(bind, checkfirst=True)
    publish_mode.drop(bind, checkfirst=True)
    job_status.drop(bind, checkfirst=True)

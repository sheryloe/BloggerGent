from __future__ import annotations

import enum
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [item.value for item in enum_cls]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    DISCOVERING_TOPICS = "DISCOVERING_TOPICS"
    GENERATING_ARTICLE = "GENERATING_ARTICLE"
    GENERATING_IMAGE_PROMPT = "GENERATING_IMAGE_PROMPT"
    GENERATING_IMAGE = "GENERATING_IMAGE"
    ASSEMBLING_HTML = "ASSEMBLING_HTML"
    FINDING_RELATED_POSTS = "FINDING_RELATED_POSTS"
    PUBLISHING = "PUBLISHING"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PublishMode(str, enum.Enum):
    DRAFT = "draft"
    PUBLISH = "publish"


class PostStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"


class WorkflowStageType(str, enum.Enum):
    TOPIC_DISCOVERY = "topic_discovery"
    ARTICLE_GENERATION = "article_generation"
    IMAGE_PROMPT_GENERATION = "image_prompt_generation"
    RELATED_POSTS = "related_posts"
    IMAGE_GENERATION = "image_generation"
    HTML_ASSEMBLY = "html_assembly"
    PUBLISHING = "publishing"
    VIDEO_METADATA_GENERATION = "video_metadata_generation"
    THUMBNAIL_GENERATION = "thumbnail_generation"
    REEL_PACKAGING = "reel_packaging"
    PLATFORM_PUBLISH = "platform_publish"
    PERFORMANCE_REVIEW = "performance_review"
    SEO_REWRITE = "seo_rewrite"
    INDEXING_CHECK = "indexing_check"


class LogLevel(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Blog(TimestampMixin, Base):
    __tablename__ = "blogs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    slug: Mapped[str] = mapped_column(sa.String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    content_category: Mapped[str] = mapped_column(sa.String(50), default="custom", nullable=False)
    primary_language: Mapped[str] = mapped_column(sa.String(20), default="en", nullable=False)
    profile_key: Mapped[str] = mapped_column(sa.String(50), default="custom", nullable=False)
    target_audience: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    content_brief: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    blogger_blog_id: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    blogger_url: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    search_console_site_url: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    ga4_property_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    seo_theme_patch_installed: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    seo_theme_patch_verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    target_reading_time_min_minutes: Mapped[int] = mapped_column(sa.Integer, default=6, nullable=False)
    target_reading_time_max_minutes: Mapped[int] = mapped_column(sa.Integer, default=8, nullable=False)
    publish_mode: Mapped[PublishMode] = mapped_column(
        sa.Enum(PublishMode, name="publish_mode", values_callable=_enum_values),
        default=PublishMode.DRAFT,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)

    topics: Mapped[list["Topic"]] = relationship(back_populates="blog")
    jobs: Mapped[list["Job"]] = relationship(back_populates="blog")
    articles: Mapped[list["Article"]] = relationship(back_populates="blog")
    blogger_posts: Mapped[list["BloggerPost"]] = relationship(back_populates="blog")
    synced_blogger_posts: Mapped[list["SyncedBloggerPost"]] = relationship(
        back_populates="blog",
        cascade="all, delete-orphan",
        order_by="SyncedBloggerPost.id.desc()",
    )
    ai_usage_events: Mapped[list["AIUsageEvent"]] = relationship(
        back_populates="blog",
        cascade="all, delete-orphan",
        order_by="AIUsageEvent.created_at.asc()",
    )
    publish_queue_items: Mapped[list["PublishQueueItem"]] = relationship(
        back_populates="blog",
        cascade="all, delete-orphan",
        order_by="PublishQueueItem.created_at.desc()",
    )
    agent_configs: Mapped[list["BlogAgentConfig"]] = relationship(
        back_populates="blog",
        cascade="all, delete-orphan",
        order_by="BlogAgentConfig.sort_order.asc()",
    )
    content_review_items: Mapped[list["ContentReviewItem"]] = relationship(
        back_populates="blog",
        cascade="all, delete-orphan",
        order_by="ContentReviewItem.updated_at.desc()",
    )
    managed_channels: Mapped[list["ManagedChannel"]] = relationship(
        back_populates="linked_blog",
        cascade="all, delete-orphan",
        order_by="ManagedChannel.created_at.asc()",
    )
    content_items: Mapped[list["ContentItem"]] = relationship(
        back_populates="blog",
        order_by="ContentItem.created_at.desc()",
    )


class BlogAgentConfig(TimestampMixin, Base):
    __tablename__ = "blog_agent_configs"
    __table_args__ = (
        sa.UniqueConstraint("blog_id", "agent_key", name="uq_blog_agent_configs_blog_agent"),
        sa.UniqueConstraint("blog_id", "stage_type", name="uq_blog_agent_configs_blog_stage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_key: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    stage_type: Mapped[WorkflowStageType] = mapped_column(
        sa.Enum(WorkflowStageType, name="workflow_stage_type", values_callable=_enum_values),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    role_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    objective: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    prompt_template: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    provider_hint: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    provider_model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    is_required: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    blog: Mapped[Blog] = relationship(back_populates="agent_configs")


class Topic(TimestampMixin, Base):
    __tablename__ = "topics"
    __table_args__ = (sa.UniqueConstraint("blog_id", "keyword", name="uq_topics_blog_keyword"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    trend_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    source: Mapped[str] = mapped_column(sa.String(50), default="gemini", nullable=False)
    locale: Mapped[str] = mapped_column(sa.String(20), default="global", nullable=False)
    topic_cluster_label: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    topic_angle_label: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    editorial_category_key: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    editorial_category_label: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    distinct_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    blog: Mapped[Blog] = relationship(back_populates="topics")
    jobs: Mapped[list["Job"]] = relationship(back_populates="topic")
    articles: Mapped[list["Article"]] = relationship(back_populates="topic")


class TopicDiscoveryRun(TimestampMixin, Base):
    __tablename__ = "topic_discovery_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="")
    model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    prompt: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    raw_response: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    items: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)
    queued_topics: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    skipped_topics: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    total_topics: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    job_ids: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id: Mapped[int | None] = mapped_column(sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    keyword_snapshot: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(sa.Enum(JobStatus, name="job_status"), default=JobStatus.PENDING, nullable=False)
    publish_mode: Mapped[PublishMode] = mapped_column(
        sa.Enum(PublishMode, name="publish_mode", values_callable=_enum_values),
        default=PublishMode.DRAFT,
        nullable=False,
    )
    start_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    error_logs: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)
    raw_prompts: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    raw_responses: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    attempt_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(sa.Integer, default=3, nullable=False)

    blog: Mapped[Blog] = relationship(back_populates="jobs")
    topic: Mapped[Topic | None] = relationship(back_populates="jobs")
    article: Mapped["Article | None"] = relationship(back_populates="job", uselist=False)
    image: Mapped["Image | None"] = relationship(back_populates="job", uselist=False)
    blogger_post: Mapped["BloggerPost | None"] = relationship(back_populates="job", uselist=False)
    ai_usage_events: Mapped[list["AIUsageEvent"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="AIUsageEvent.created_at.asc()",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    content_items: Mapped[list["ContentItem"]] = relationship(back_populates="job")


class Article(TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        sa.UniqueConstraint("job_id", name="uq_articles_job_id"),
        sa.UniqueConstraint("blog_id", "slug", name="uq_articles_blog_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id: Mapped[int | None] = mapped_column(sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    meta_description: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    labels: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    excerpt: Mapped[str] = mapped_column(sa.Text, nullable=False)
    html_article: Mapped[str] = mapped_column(sa.Text, nullable=False)
    faq_section: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)
    image_collage_prompt: Mapped[str] = mapped_column(sa.Text, nullable=False)
    editorial_category_key: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    editorial_category_label: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    inline_media: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)
    assembled_html: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    article_pattern_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    article_pattern_version: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    render_metadata: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    reading_time_minutes: Mapped[int] = mapped_column(sa.Integer, default=4, nullable=False)
    quality_similarity_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    quality_most_similar_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    quality_seo_score: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    quality_geo_score: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    quality_lighthouse_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    quality_lighthouse_accessibility_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    quality_lighthouse_best_practices_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    quality_lighthouse_seo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    quality_lighthouse_payload: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    quality_lighthouse_last_audited_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    quality_status: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    quality_rewrite_attempts: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    quality_last_audited_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    travel_sync_group_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True, index=True)
    travel_sync_role: Mapped[str | None] = mapped_column(sa.String(30), nullable=True, index=True)
    travel_sync_source_article_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("articles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    travel_sync_es_article_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("articles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    travel_sync_ja_article_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("articles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    travel_sync_es_status: Mapped[str | None] = mapped_column(sa.String(30), nullable=True, index=True)
    travel_sync_ja_status: Mapped[str | None] = mapped_column(sa.String(30), nullable=True, index=True)
    travel_sync_last_checked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    travel_all_languages_ready: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    job: Mapped[Job] = relationship(back_populates="article")
    blog: Mapped[Blog] = relationship(back_populates="articles")
    topic: Mapped[Topic | None] = relationship(back_populates="articles")
    image: Mapped["Image | None"] = relationship(back_populates="article", uselist=False)
    blogger_post: Mapped["BloggerPost | None"] = relationship(back_populates="article", uselist=False)
    ai_usage_events: Mapped[list["AIUsageEvent"]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
        order_by="AIUsageEvent.created_at.asc()",
    )
    publish_queue_items: Mapped[list["PublishQueueItem"]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
        order_by="PublishQueueItem.created_at.desc()",
    )
    content_items: Mapped[list["ContentItem"]] = relationship(back_populates="source_article")

    @property
    def usage_events(self) -> list["AIUsageEvent"]:
        return sorted(self.ai_usage_events or [], key=lambda item: (item.created_at, item.id or 0))

    @property
    def usage_summary(self) -> dict:
        events = self.usage_events
        total_input_tokens = sum(int(item.input_tokens or 0) for item in events)
        total_output_tokens = sum(int(item.output_tokens or 0) for item in events)
        total_tokens = sum(int(item.total_tokens or 0) for item in events)
        total_requests = sum(int(item.request_count or 0) for item in events)
        known_costs = [float(item.estimated_cost_usd) for item in events if item.estimated_cost_usd is not None]
        by_stage: dict[str, dict[str, int | float | None]] = {}
        for item in events:
            stage_bucket = by_stage.setdefault(
                item.stage_type,
                {
                    "event_count": 0,
                    "request_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                },
            )
            stage_bucket["event_count"] = int(stage_bucket["event_count"]) + 1
            stage_bucket["request_count"] = int(stage_bucket["request_count"]) + int(item.request_count or 0)
            stage_bucket["input_tokens"] = int(stage_bucket["input_tokens"]) + int(item.input_tokens or 0)
            stage_bucket["output_tokens"] = int(stage_bucket["output_tokens"]) + int(item.output_tokens or 0)
            stage_bucket["total_tokens"] = int(stage_bucket["total_tokens"]) + int(item.total_tokens or 0)
            if item.estimated_cost_usd is not None:
                stage_bucket["estimated_cost_usd"] = float(stage_bucket["estimated_cost_usd"]) + float(item.estimated_cost_usd)
        return {
            "event_count": len(events),
            "total_requests": total_requests,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(sum(known_costs), 6) if known_costs else None,
            "by_stage": by_stage,
        }

    @property
    def publish_queue(self) -> "PublishQueueItem | None":
        items = list(self.publish_queue_items or [])
        if not items:
            return None
        active_statuses = {"queued", "scheduled", "processing"}
        for item in items:
            if item.status in active_statuses:
                return item
        return items[0]


class Image(TimestampMixin, Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(sa.ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    article_id: Mapped[int | None] = mapped_column(sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True)
    prompt: Mapped[str] = mapped_column(sa.Text, nullable=False)
    file_path: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    public_url: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    width: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1536)
    height: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1024)
    provider: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="mock")
    image_metadata: Mapped[dict] = mapped_column("metadata", sa.JSON, default=dict, nullable=False)

    job: Mapped[Job] = relationship(back_populates="image")
    article: Mapped[Article | None] = relationship(back_populates="image")


class BloggerPost(TimestampMixin, Base):
    __tablename__ = "blogger_posts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(sa.ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    article_id: Mapped[int | None] = mapped_column(sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True)
    blogger_post_id: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    published_url: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    is_draft: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    post_status: Mapped[PostStatus] = mapped_column(
        sa.Enum(PostStatus, name="post_status", values_callable=_enum_values),
        default=PostStatus.DRAFT,
        nullable=False,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    response_payload: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)

    job: Mapped[Job] = relationship(back_populates="blogger_post")
    blog: Mapped[Blog] = relationship(back_populates="blogger_posts")
    article: Mapped[Article | None] = relationship(back_populates="blogger_post")


class AIUsageEvent(TimestampMixin, Base):
    __tablename__ = "ai_usage_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[int | None] = mapped_column(sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    article_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=True, index=True
    )
    stage_type: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    provider_mode: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="mock")
    provider_name: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="mock")
    provider_model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    endpoint: Mapped[str] = mapped_column(sa.String(100), nullable=False, default="unknown")
    input_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    request_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    image_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    image_width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    success: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    raw_usage: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)

    blog: Mapped[Blog] = relationship(back_populates="ai_usage_events")
    job: Mapped[Job | None] = relationship(back_populates="ai_usage_events")
    article: Mapped[Article | None] = relationship(back_populates="ai_usage_events")


class PublishQueueItem(TimestampMixin, Base):
    __tablename__ = "publish_queue_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    article_id: Mapped[int] = mapped_column(sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_mode: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="publish")
    scheduled_for: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    not_before: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    response_payload: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    article: Mapped[Article] = relationship(back_populates="publish_queue_items")
    blog: Mapped[Blog] = relationship(back_populates="publish_queue_items")


class SyncedBloggerPost(TimestampMixin, Base):
    __tablename__ = "synced_blogger_posts"
    __table_args__ = (
        sa.UniqueConstraint("blog_id", "remote_post_id", name="uq_synced_blogger_posts_blog_remote_post"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    remote_post_id: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="live")
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    updated_at_remote: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    labels: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)
    author_display_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    replies_total_items: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    content_html: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    thumbnail_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    excerpt_text: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    live_image_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_unique_image_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_duplicate_image_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_webp_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_png_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_other_image_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_cover_present: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    live_inline_present: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    travel_image_migration_status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="pending")
    live_image_issue: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    live_image_audited_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True)

    blog: Mapped[Blog] = relationship(back_populates="synced_blogger_posts")


class SyncedCloudflarePost(TimestampMixin, Base):
    __tablename__ = "synced_cloudflare_posts"
    __table_args__ = (
        sa.UniqueConstraint(
            "managed_channel_id",
            "remote_post_id",
            name="uq_synced_cloudflare_posts_channel_remote_post",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    managed_channel_id: Mapped[int] = mapped_column(
        sa.ForeignKey("managed_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    remote_post_id: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    slug: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    title: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="published")
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    created_at_remote: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    updated_at_remote: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    labels: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)
    category_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    category_slug: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    canonical_category_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    canonical_category_slug: Mapped[str | None] = mapped_column(sa.String(255), nullable=True, index=True)
    excerpt_text: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    thumbnail_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    seo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    geo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    ctr: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    lighthouse_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    lighthouse_accessibility_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    lighthouse_best_practices_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    lighthouse_seo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    lighthouse_payload: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    lighthouse_last_audited_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    live_image_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_unique_image_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_duplicate_image_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_webp_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_png_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    live_other_image_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    image_health_status: Mapped[str | None] = mapped_column(sa.String(30), nullable=True, index=True)
    live_image_issue: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    live_image_audited_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    index_status: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    quality_status: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    article_pattern_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    article_pattern_version: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    render_metadata: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        index=True,
    )

    managed_channel: Mapped["ManagedChannel"] = relationship(back_populates="synced_cloudflare_posts")


class R2AssetRelayoutMapping(TimestampMixin, Base):
    __tablename__ = "r2_asset_relayout_mappings"
    __table_args__ = (
        sa.UniqueConstraint(
            "source_type",
            "source_post_id",
            "legacy_key",
            "migrated_key",
            name="uq_r2_asset_relayout_source_post_legacy_migrated",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_type: Mapped[str] = mapped_column(sa.String(20), nullable=False, index=True)
    source_blog_id: Mapped[int | None] = mapped_column(sa.ForeignKey("blogs.id", ondelete="SET NULL"), nullable=True, index=True)
    source_post_id: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    source_post_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    legacy_url: Mapped[str | None] = mapped_column(sa.String(1500), nullable=True)
    legacy_key: Mapped[str | None] = mapped_column(sa.String(1024), nullable=True, index=True)
    migrated_url: Mapped[str | None] = mapped_column(sa.String(1500), nullable=True)
    migrated_key: Mapped[str | None] = mapped_column(sa.String(1024), nullable=True, index=True)
    blog_group: Mapped[str | None] = mapped_column(sa.String(80), nullable=True, index=True)
    category_key: Mapped[str | None] = mapped_column(sa.String(80), nullable=True, index=True)
    asset_role: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="mapped", index=True)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    cleaned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)

    source_blog: Mapped[Blog | None] = relationship(foreign_keys=[source_blog_id])


class GoogleIndexUrlState(TimestampMixin, Base):
    __tablename__ = "google_index_url_states"
    __table_args__ = (sa.UniqueConstraint("blog_id", "url", name="uq_google_index_url_states_blog_url"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(sa.String(1000), nullable=False, index=True)
    canonical_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    index_status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="unknown", index=True)
    index_coverage_state: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    index_state: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    verdict: Mapped[str | None] = mapped_column(sa.String(30), nullable=True)
    last_crawl_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    last_notify_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    last_inspection_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    last_publish_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    next_eligible_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    last_publish_success: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    last_publish_http_status: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    inspection_payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    metadata_payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    publish_payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    blog: Mapped[Blog] = relationship("Blog")


class GoogleIndexRequestLog(Base):
    __tablename__ = "google_index_request_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(sa.String(1000), nullable=False, index=True)
    request_type: Mapped[str] = mapped_column(sa.String(30), nullable=False, index=True)
    trigger_mode: Mapped[str] = mapped_column(sa.String(20), nullable=False, index=True)
    is_force: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    success: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, index=True)
    http_status: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    request_payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    response_payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True)

    blog: Mapped[Blog] = relationship("Blog")


class SearchConsolePageMetric(Base):
    __tablename__ = "search_console_page_metrics"
    __table_args__ = (sa.UniqueConstraint("blog_id", "url", name="uq_search_console_page_metrics_blog_url"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(sa.String(1000), nullable=False, index=True)
    clicks: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0)
    impressions: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0)
    ctr: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    position: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    start_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    blog: Mapped[Blog] = relationship("Blog")


class TopicMemory(TimestampMixin, Base):
    __tablename__ = "topic_memories"
    __table_args__ = (
        sa.UniqueConstraint("blog_id", "source_type", "source_id", name="uq_topic_memories_blog_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(sa.String(20), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(sa.String(500), nullable=False, default="")
    canonical_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    topic_cluster_key: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    topic_cluster_label: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    topic_angle_key: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    topic_angle_label: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    entity_names: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)
    evidence_excerpt: Mapped[str] = mapped_column(sa.Text, default="", nullable=False)

    blog: Mapped[Blog] = relationship()


class TrainingRun(TimestampMixin, Base):
    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    state: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="idle", index=True)
    trigger_source: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="manual")
    task_id: Mapped[str | None] = mapped_column(sa.String(255), nullable=True, index=True)
    session_hours: Mapped[float] = mapped_column(sa.Float, nullable=False, default=4.0)
    save_every_minutes: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=20)
    current_step: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    total_steps: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    loss: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    elapsed_seconds: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    eta_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    dataset_item_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    dataset_manifest_path: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    dataset_jsonl_path: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    last_checkpoint: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    checkpoint_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    last_checkpoint_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    pause_requested: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    session_deadline_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    log_tail: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)


class ContentReviewItem(TimestampMixin, Base):
    __tablename__ = "content_review_items"
    __table_args__ = (
        sa.UniqueConstraint("source_type", "source_id", "review_kind", name="uq_content_review_items_source_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    source_title: Mapped[str] = mapped_column(sa.String(500), nullable=False, default="")
    source_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    review_kind: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="")
    quality_score: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    risk_level: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="medium", index=True)
    issues: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    proposed_patch: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    approval_status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="pending", index=True)
    apply_status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="pending", index=True)
    learning_state: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="pending", index=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_applied_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    blog: Mapped[Blog] = relationship(back_populates="content_review_items")
    actions: Mapped[list["ContentReviewAction"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ContentReviewAction.created_at.desc()",
    )


class ContentReviewAction(Base):
    __tablename__ = "content_review_actions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    item_id: Mapped[int] = mapped_column(sa.ForeignKey("content_review_items.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(sa.String(30), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(sa.String(100), nullable=False, default="system")
    channel: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="system")
    result_payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)

    item: Mapped[ContentReviewItem] = relationship(back_populates="actions")


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    key: Mapped[str] = mapped_column(sa.String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    is_secret: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )


class TelegramChatBinding(TimestampMixin, Base):
    __tablename__ = "telegram_chat_bindings"
    __table_args__ = (sa.UniqueConstraint("chat_id", name="uq_telegram_chat_bindings_chat_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chat_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    channel_id: Mapped[str | None] = mapped_column(sa.String(120), nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    chat_title: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    binding_metadata: Mapped[dict] = mapped_column("metadata", sa.JSON, nullable=False, default=dict)

    subscriptions: Mapped[list["TelegramSubscription"]] = relationship(
        "TelegramSubscription",
        back_populates="chat_binding",
        cascade="all, delete-orphan",
        order_by="TelegramSubscription.event_key.asc()",
    )


class TelegramSubscription(TimestampMixin, Base):
    __tablename__ = "telegram_subscriptions"
    __table_args__ = (
        sa.UniqueConstraint(
            "chat_binding_id",
            "event_key",
            name="uq_telegram_subscriptions_chat_binding_event_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chat_binding_id: Mapped[int] = mapped_column(
        sa.ForeignKey("telegram_chat_bindings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_key: Mapped[str] = mapped_column(sa.String(100), nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    config_payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    chat_binding: Mapped["TelegramChatBinding"] = relationship("TelegramChatBinding", back_populates="subscriptions")


class TelegramCommandEvent(Base):
    __tablename__ = "telegram_command_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chat_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    command: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="ok", index=True)
    detail: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column("payload", sa.JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True)


class TelegramDeliveryEvent(Base):
    __tablename__ = "telegram_delivery_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chat_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    message_type: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="message", index=True)
    dedupe_key: Mapped[str | None] = mapped_column(sa.String(255), nullable=True, unique=True, index=True)
    status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="sent", index=True)
    error_code: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column("payload", sa.JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_id: Mapped[int | None] = mapped_column(sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    level: Mapped[LogLevel] = mapped_column(sa.Enum(LogLevel, name="log_level"), default=LogLevel.INFO, nullable=False)
    stage: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)

    job: Mapped[Job | None] = relationship(back_populates="audit_logs")


class BlogTheme(TimestampMixin, Base):
    __tablename__ = "blog_themes"
    __table_args__ = (sa.UniqueConstraint("blog_id", "key", name="uq_blog_themes_blog_id_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    weight: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=10)
    color: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

    blog: Mapped[Blog] = relationship("Blog")


class ContentPlanDay(TimestampMixin, Base):
    __tablename__ = "content_plan_days"
    __table_args__ = (sa.UniqueConstraint("channel_id", "plan_date", name="uq_content_plan_days_channel_date"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    channel_id: Mapped[str] = mapped_column(sa.String(100), nullable=False, index=True)
    blog_id: Mapped[int | None] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=True, index=True)
    plan_date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    target_post_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="planned")

    blog: Mapped[Blog | None] = relationship("Blog")
    slots: Mapped[list[ContentPlanSlot]] = relationship(
        "ContentPlanSlot",
        back_populates="plan_day",
        cascade="all, delete-orphan",
        order_by="ContentPlanSlot.scheduled_for",
    )
    brief_runs: Mapped[list[PlannerBriefRun]] = relationship(
        "PlannerBriefRun",
        back_populates="plan_day",
        cascade="all, delete-orphan",
        order_by="PlannerBriefRun.created_at.desc()",
    )


class PlannerBriefRun(TimestampMixin, Base):
    __tablename__ = "planner_brief_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    plan_day_id: Mapped[int] = mapped_column(sa.ForeignKey("content_plan_days.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(sa.String(100), nullable=False, index=True)
    blog_id: Mapped[int | None] = mapped_column(sa.ForeignKey("blogs.id", ondelete="SET NULL"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="")
    model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    prompt: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    raw_response: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    slot_suggestions: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="completed")
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    applied_slot_ids: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)

    plan_day: Mapped[ContentPlanDay] = relationship("ContentPlanDay", back_populates="brief_runs")
    blog: Mapped[Blog | None] = relationship("Blog")


class ContentPlanSlot(TimestampMixin, Base):
    __tablename__ = "content_plan_slots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    plan_day_id: Mapped[int] = mapped_column(sa.ForeignKey("content_plan_days.id", ondelete="CASCADE"), nullable=False, index=True)
    theme_id: Mapped[int | None] = mapped_column(sa.ForeignKey("blog_themes.id", ondelete="SET NULL"), nullable=True, index=True)
    category_key: Mapped[str | None] = mapped_column(sa.String(100), nullable=True, index=True)
    category_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    category_color: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    slot_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="planned")
    brief_topic: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    brief_audience: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    brief_information_level: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    brief_extra_context: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    article_id: Mapped[int | None] = mapped_column(sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    result_payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    plan_day: Mapped[ContentPlanDay] = relationship("ContentPlanDay", back_populates="slots")
    theme: Mapped[BlogTheme | None] = relationship("BlogTheme")
    article: Mapped[Article | None] = relationship("Article")
    job: Mapped[Job | None] = relationship("Job")


class AnalyticsArticleFact(TimestampMixin, Base):
    __tablename__ = "analytics_article_facts"
    __table_args__ = (
        sa.Index(
            "ix_analytics_article_facts_blog_month_published_at",
            "blog_id",
            "month",
            "published_at",
        ),
        sa.Index(
            "ix_analytics_article_facts_blog_month_source_status",
            "blog_id",
            "month",
            "source_type",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    month: Mapped[str] = mapped_column(sa.String(7), nullable=False, index=True)
    article_id: Mapped[int | None] = mapped_column(sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, index=True)
    synced_post_id: Mapped[int | None] = mapped_column(sa.ForeignKey("synced_blogger_posts.id", ondelete="SET NULL"), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    title: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    theme_key: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    theme_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    seo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    geo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    lighthouse_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    lighthouse_accessibility_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    lighthouse_best_practices_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    lighthouse_seo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    similarity_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    most_similar_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    article_pattern_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    article_pattern_version: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    actual_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    source_type: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="generated")


class AnalyticsThemeMonthlyStat(TimestampMixin, Base):
    __tablename__ = "analytics_theme_monthly_stats"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    month: Mapped[str] = mapped_column(sa.String(7), nullable=False, index=True)
    theme_key: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    theme_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    planned_posts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    actual_posts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    planned_share: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0)
    actual_share: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0)
    gap_share: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0)
    avg_seo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    avg_geo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    avg_similarity_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    coverage_gap_score: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0)
    next_month_weight_suggestion: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=10)


class AnalyticsBlogMonthlyReport(TimestampMixin, Base):
    __tablename__ = "analytics_blog_monthly_reports"
    __table_args__ = (sa.UniqueConstraint("blog_id", "month", name="uq_analytics_blog_monthly_reports_blog_month"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    blog_id: Mapped[int] = mapped_column(sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False, index=True)
    month: Mapped[str] = mapped_column(sa.String(7), nullable=False, index=True)
    total_posts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    avg_seo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    avg_geo_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    avg_similarity_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    most_underused_theme_key: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    most_underused_theme_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    most_overused_theme_key: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    most_overused_theme_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    next_month_focus: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    report_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class ManagedChannel(TimestampMixin, Base):
    __tablename__ = "managed_channels"
    __table_args__ = (sa.UniqueConstraint("channel_id", name="uq_managed_channels_channel_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(sa.String(30), nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(sa.String(120), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    remote_resource_id: Mapped[str | None] = mapped_column(sa.String(255), nullable=True, index=True)
    linked_blog_id: Mapped[int | None] = mapped_column(sa.ForeignKey("blogs.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="attention", index=True)
    base_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    primary_category: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    purpose: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    capabilities: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    oauth_state: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="not_configured")
    quota_state: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    channel_metadata: Mapped[dict] = mapped_column("metadata", sa.JSON, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

    linked_blog: Mapped[Blog | None] = relationship(back_populates="managed_channels")
    credentials: Mapped[list["PlatformCredential"]] = relationship(
        back_populates="managed_channel",
        cascade="all, delete-orphan",
        order_by="PlatformCredential.created_at.desc()",
    )
    content_items: Mapped[list["ContentItem"]] = relationship(
        back_populates="managed_channel",
        cascade="all, delete-orphan",
        order_by="ContentItem.created_at.desc()",
    )
    synced_cloudflare_posts: Mapped[list["SyncedCloudflarePost"]] = relationship(
        back_populates="managed_channel",
        cascade="all, delete-orphan",
        order_by="SyncedCloudflarePost.id.desc()",
    )
    publication_records: Mapped[list["PublicationRecord"]] = relationship(
        back_populates="managed_channel",
        cascade="all, delete-orphan",
        order_by="PublicationRecord.created_at.desc()",
    )
    metric_facts: Mapped[list["MetricFact"]] = relationship(
        back_populates="managed_channel",
        cascade="all, delete-orphan",
        order_by="MetricFact.snapshot_at.desc()",
    )
    agent_workers: Mapped[list["AgentWorker"]] = relationship(
        back_populates="managed_channel",
        cascade="all, delete-orphan",
        order_by="AgentWorker.created_at.asc()",
    )
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="managed_channel",
        cascade="all, delete-orphan",
        order_by="AgentRun.created_at.desc()",
    )


class PlatformCredential(TimestampMixin, Base):
    __tablename__ = "platform_credentials"
    __table_args__ = (sa.UniqueConstraint("provider", "credential_key", name="uq_platform_credentials_provider_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    managed_channel_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("managed_channels.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(sa.String(30), nullable=False, index=True)
    credential_key: Mapped[str] = mapped_column(sa.String(120), nullable=False, index=True)
    subject: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    token_type: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="Bearer")
    scopes: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    access_token_encrypted: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    refresh_token_encrypted: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    refresh_metadata: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    is_valid: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    managed_channel: Mapped[ManagedChannel | None] = relationship(back_populates="credentials")


class ContentItem(TimestampMixin, Base):
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    managed_channel_id: Mapped[int] = mapped_column(sa.ForeignKey("managed_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(sa.String(120), nullable=False, default="", index=True)
    blog_id: Mapped[int | None] = mapped_column(sa.ForeignKey("blogs.id", ondelete="SET NULL"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    source_article_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("articles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    content_type: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    lifecycle_status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="draft", index=True)
    title: Mapped[str] = mapped_column(sa.String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    body_text: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    asset_manifest: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    brief_payload: Mapped[dict] = mapped_column("brief", sa.JSON, nullable=False, default=dict)
    review_notes: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    approval_status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="pending", index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    last_feedback: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(sa.String(120), nullable=True, index=True)
    last_score: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    created_by_agent: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)

    managed_channel: Mapped[ManagedChannel] = relationship(back_populates="content_items")
    blog: Mapped[Blog | None] = relationship(back_populates="content_items")
    job: Mapped[Job | None] = relationship(back_populates="content_items")
    source_article: Mapped[Article | None] = relationship(back_populates="content_items")
    publication_records: Mapped[list["PublicationRecord"]] = relationship(
        back_populates="content_item",
        cascade="all, delete-orphan",
        order_by="PublicationRecord.created_at.desc()",
    )
    metric_facts: Mapped[list["MetricFact"]] = relationship(
        back_populates="content_item",
        cascade="all, delete-orphan",
        order_by="MetricFact.snapshot_at.desc()",
    )
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="content_item",
        cascade="all, delete-orphan",
        order_by="AgentRun.created_at.desc()",
    )


class PublicationRecord(TimestampMixin, Base):
    __tablename__ = "publication_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    content_item_id: Mapped[int] = mapped_column(sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True)
    managed_channel_id: Mapped[int] = mapped_column(sa.ForeignKey("managed_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(sa.String(30), nullable=False, index=True)
    remote_id: Mapped[str | None] = mapped_column(sa.String(255), nullable=True, index=True)
    remote_url: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    target_state: Mapped[str] = mapped_column(sa.String(40), nullable=False, default="publish", index=True)
    publish_status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="draft", index=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(50), nullable=True, index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    response_payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    content_item: Mapped[ContentItem] = relationship(back_populates="publication_records")
    managed_channel: Mapped[ManagedChannel] = relationship(back_populates="publication_records")


class MetricFact(TimestampMixin, Base):
    __tablename__ = "metric_facts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    managed_channel_id: Mapped[int] = mapped_column(sa.ForeignKey("managed_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    content_item_id: Mapped[int | None] = mapped_column(sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(sa.String(30), nullable=False, index=True)
    metric_scope: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="content", index=True)
    metric_name: Mapped[str] = mapped_column(sa.String(100), nullable=False, index=True)
    value: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0)
    normalized_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    dimension_key: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    dimension_value: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)
    metric_payload: Mapped[dict] = mapped_column("payload", sa.JSON, nullable=False, default=dict)

    managed_channel: Mapped[ManagedChannel] = relationship(back_populates="metric_facts")
    content_item: Mapped[ContentItem | None] = relationship(back_populates="metric_facts")


class AgentWorker(TimestampMixin, Base):
    __tablename__ = "agent_workers"
    __table_args__ = (sa.UniqueConstraint("worker_key", name="uq_agent_workers_worker_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    managed_channel_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("managed_channels.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    worker_key: Mapped[str] = mapped_column(sa.String(120), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role_name: Mapped[str] = mapped_column(sa.String(120), nullable=False, index=True)
    runtime_kind: Mapped[str] = mapped_column(sa.String(30), nullable=False, index=True)
    queue_name: Mapped[str] = mapped_column(sa.String(120), nullable=False, default="default")
    concurrency_limit: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="idle", index=True)
    config_payload: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    managed_channel: Mapped[ManagedChannel | None] = relationship(back_populates="agent_workers")
    runs: Mapped[list["AgentRun"]] = relationship(back_populates="worker", order_by="AgentRun.created_at.desc()")


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (sa.UniqueConstraint("run_key", name="uq_agent_runs_run_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    managed_channel_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("managed_channels.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    content_item_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("content_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    worker_id: Mapped[int | None] = mapped_column(sa.ForeignKey("agent_workers.id", ondelete="SET NULL"), nullable=True, index=True)
    run_key: Mapped[str] = mapped_column(sa.String(120), nullable=False, index=True)
    runtime_kind: Mapped[str] = mapped_column(sa.String(30), nullable=False, index=True)
    assigned_role: Mapped[str] = mapped_column(sa.String(120), nullable=False, index=True)
    provider_model: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(30), nullable=False, default="queued", index=True)
    priority: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=50)
    timeout_seconds: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=900)
    retry_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=3)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    prompt_snapshot: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    response_snapshot: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    log_lines: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    managed_channel: Mapped[ManagedChannel | None] = relationship(back_populates="agent_runs")
    content_item: Mapped[ContentItem | None] = relationship(back_populates="agent_runs")
    worker: Mapped[AgentWorker | None] = relationship(back_populates="runs")

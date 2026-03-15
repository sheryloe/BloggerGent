from __future__ import annotations

import enum
from datetime import datetime

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


class WorkflowStageType(str, enum.Enum):
    TOPIC_DISCOVERY = "topic_discovery"
    ARTICLE_GENERATION = "article_generation"
    IMAGE_PROMPT_GENERATION = "image_prompt_generation"
    RELATED_POSTS = "related_posts"
    IMAGE_GENERATION = "image_generation"
    HTML_ASSEMBLY = "html_assembly"
    PUBLISHING = "publishing"


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
    agent_configs: Mapped[list["BlogAgentConfig"]] = relationship(
        back_populates="blog",
        cascade="all, delete-orphan",
        order_by="BlogAgentConfig.sort_order.asc()",
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

    blog: Mapped[Blog] = relationship(back_populates="topics")
    jobs: Mapped[list["Job"]] = relationship(back_populates="topic")
    articles: Mapped[list["Article"]] = relationship(back_populates="topic")


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
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="job", cascade="all, delete-orphan")


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
    assembled_html: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    reading_time_minutes: Mapped[int] = mapped_column(sa.Integer, default=4, nullable=False)

    job: Mapped[Job] = relationship(back_populates="article")
    blog: Mapped[Blog] = relationship(back_populates="articles")
    topic: Mapped[Topic | None] = relationship(back_populates="articles")
    image: Mapped["Image | None"] = relationship(back_populates="article", uselist=False)
    blogger_post: Mapped["BloggerPost | None"] = relationship(back_populates="article", uselist=False)


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
    response_payload: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)

    job: Mapped[Job] = relationship(back_populates="blogger_post")
    blog: Mapped[Blog] = relationship(back_populates="blogger_posts")
    article: Mapped[Article | None] = relationship(back_populates="blogger_post")


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

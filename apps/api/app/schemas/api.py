from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.entities import JobStatus, LogLevel, PostStatus, PublishMode, WorkflowStageType

ChannelProvider = str
ManagedChannelStatus = str


class ContentItemType(str, enum.Enum):
    BLOG_ARTICLE = "blog_article"
    YOUTUBE_VIDEO = "youtube_video"
    INSTAGRAM_IMAGE = "instagram_image"
    INSTAGRAM_REEL = "instagram_reel"
    ARTICLE = "article"  # legacy compatibility
    BRIEF = "brief"  # legacy compatibility
    ASSET = "asset"  # legacy compatibility


class ContentItemStatus(str, enum.Enum):
    DRAFT = "draft"
    READY_TO_PUBLISH = "ready_to_publish"
    BLOCKED_ASSET = "blocked_asset"
    QUEUED = "queued"
    REVIEW = "review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"
    BLOCKED = "blocked"


class AgentRuntimeKind(str, enum.Enum):
    CLAUDE_CLI = "claude_cli"
    CODEX_CLI = "codex_cli"
    GEMINI_CLI = "gemini_cli"
    OPENAI = "openai"  # legacy compatibility
    INTERNAL = "internal"  # legacy compatibility


class AgentWorkerStatus(str, enum.Enum):
    IDLE = "idle"
    BUSY = "busy"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class AgentRunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class BlogAgentConfigRead(BaseModel):
    id: int
    agent_key: str
    stage_type: WorkflowStageType
    name: str
    role_name: str
    objective: str | None = None
    prompt_template: str
    provider_hint: str | None = None
    provider_model: str | None = None
    is_enabled: bool
    is_required: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime
    stage_label: str | None = None
    prompt_enabled: bool = False
    removable: bool = False

    model_config = {"from_attributes": True}


class BlogConnectionSummaryRead(BaseModel):
    blogger: "BloggerRemoteBlogRead | None" = None
    search_console: "SearchConsoleSiteRead | None" = None
    analytics: "AnalyticsPropertyRead | None" = None


class BlogCompactRead(BaseModel):
    id: int
    name: str
    slug: str
    content_category: str

    model_config = {"from_attributes": True}


class BlogRead(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    content_category: str
    primary_language: str
    profile_key: str
    target_audience: str | None = None
    content_brief: str | None = None
    blogger_blog_id: str | None = None
    blogger_url: str | None = None
    search_console_site_url: str | None = None
    ga4_property_id: str | None = None
    seo_theme_patch_installed: bool = False
    seo_theme_patch_verified_at: datetime | None = None
    target_reading_time_min_minutes: int = 6
    target_reading_time_max_minutes: int = 8
    publish_mode: PublishMode
    is_active: bool
    created_at: datetime
    updated_at: datetime
    workflow_steps: list[BlogAgentConfigRead] = []
    user_visible_steps: list[BlogAgentConfigRead] = []
    system_steps: list[BlogAgentConfigRead] = []
    execution_path_labels: list[str] = []
    selected_connections: BlogConnectionSummaryRead = Field(default_factory=BlogConnectionSummaryRead)
    job_count: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    published_posts: int = 0
    latest_topic_keywords: list[str] = []
    latest_published_url: str | None = None


class BlogUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    content_category: str = Field(min_length=2, max_length=50)
    primary_language: str = Field(min_length=2, max_length=20)
    target_audience: str | None = None
    content_brief: str | None = None
    target_reading_time_min_minutes: int = Field(default=6, ge=1, le=60)
    target_reading_time_max_minutes: int = Field(default=8, ge=1, le=60)
    publish_mode: PublishMode
    is_active: bool = True


class BlogAgentConfigUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    role_name: str = Field(min_length=2, max_length=255)
    objective: str | None = None
    prompt_template: str = ""
    provider_hint: str | None = None
    provider_model: str | None = None
    is_enabled: bool = True


class BlogImportProfileRead(BaseModel):
    key: str
    label: str
    description: str
    content_category: str
    primary_language: str
    target_audience: str


class BlogImportRequest(BaseModel):
    blogger_blog_id: str = Field(min_length=3)
    profile_key: str = Field(min_length=2, max_length=50)


class BlogImportOptionsRead(BaseModel):
    available_blogs: list["BloggerRemoteBlogRead"] = Field(default_factory=list)
    profiles: list[BlogImportProfileRead] = Field(default_factory=list)
    imported_blogger_blog_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BlogConnectionOptionsRead(BaseModel):
    blog_id: int
    blogger_blog: "BloggerRemoteBlogRead | None" = None
    search_console_sites: list["SearchConsoleSiteRead"] = Field(default_factory=list)
    analytics_properties: list["AnalyticsPropertyRead"] = Field(default_factory=list)
    selected_search_console: "SearchConsoleSiteRead | None" = None
    selected_analytics: "AnalyticsPropertyRead | None" = None
    warnings: list[str] = Field(default_factory=list)


class BlogConnectionUpdate(BaseModel):
    search_console_site_url: str | None = None
    ga4_property_id: str | None = None


class BlogPresetApplyRequest(BaseModel):
    overwrite_prompts: bool = True


class SeoMetaStatusRead(BaseModel):
    key: str
    label: str
    status: str
    actual: str | None = None
    expected: str | None = None
    message: str


class BlogSeoMetaRead(BaseModel):
    blog_id: int
    seo_theme_patch_installed: bool = False
    seo_theme_patch_verified: bool = False
    seo_theme_patch_verified_at: datetime | None = None
    verification_target_url: str | None = None
    expected_meta_description: str | None = None
    patch_snippet: str
    patch_steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    head_meta_description_status: SeoMetaStatusRead
    og_description_status: SeoMetaStatusRead
    twitter_description_status: SeoMetaStatusRead


class BlogSeoMetaUpdate(BaseModel):
    seo_theme_patch_installed: bool


class ArticleSeoMetaRead(BaseModel):
    article_id: int
    blog_id: int
    article_title: str
    verification_target_url: str | None = None
    expected_meta_description: str | None = None
    warnings: list[str] = Field(default_factory=list)
    head_meta_description_status: SeoMetaStatusRead
    og_description_status: SeoMetaStatusRead
    twitter_description_status: SeoMetaStatusRead


class ArticleSearchDescriptionSyncRead(BaseModel):
    article_id: int
    blogger_post_id: str
    editor_url: str
    cdp_url: str
    description: str
    status: str
    message: str


class WorkflowStepCreate(BaseModel):
    stage_type: WorkflowStageType


class WorkflowStepReorder(BaseModel):
    ordered_ids: list[int] = Field(min_length=1)


class TopicRead(BaseModel):
    id: int
    blog_id: int
    keyword: str
    reason: str | None = None
    trend_score: float | None = None
    source: str
    locale: str
    topic_cluster_label: str | None = None
    topic_angle_label: str | None = None
    distinct_reason: str | None = None
    created_at: datetime
    blog: BlogCompactRead | None = None

    model_config = {"from_attributes": True}


class TopicDiscoveryRunItem(BaseModel):
    keyword: str
    reason: str | None = None
    trend_score: float | None = None
    status: str
    skip_reasons: list[str] = Field(default_factory=list)
    metadata: dict[str, str | None] = Field(default_factory=dict)


class TopicDiscoveryRunRead(BaseModel):
    id: int
    blog_id: int
    provider: str
    model: str | None = None
    prompt: str
    raw_response: dict
    items: list[TopicDiscoveryRunItem]
    queued_topics: int
    skipped_topics: int
    total_topics: int
    job_ids: list[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogRead(BaseModel):
    id: int
    level: LogLevel
    stage: str
    message: str
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class ImageRead(BaseModel):
    id: int
    prompt: str
    file_path: str
    public_url: str
    width: int
    height: int
    provider: str
    metadata: dict = Field(validation_alias="image_metadata")

    model_config = {"from_attributes": True, "populate_by_name": True}


class BloggerPostRead(BaseModel):
    id: int
    blog_id: int
    blogger_post_id: str
    published_url: str
    published_at: datetime | None = None
    is_draft: bool
    post_status: PostStatus = PostStatus.DRAFT
    scheduled_for: datetime | None = None

    model_config = {"from_attributes": True}


class AIUsageEventRead(BaseModel):
    id: int
    stage_type: str
    provider_mode: str
    provider_name: str
    provider_model: str | None = None
    endpoint: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None
    request_count: int
    latency_ms: int | None = None
    image_count: int
    image_width: int | None = None
    image_height: int | None = None
    success: bool
    error_message: str | None = None
    raw_usage: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class AIUsageSummaryRead(BaseModel):
    event_count: int
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None
    by_stage: dict = Field(default_factory=dict)


class PublishQueueItemRead(BaseModel):
    id: int
    article_id: int
    blog_id: int
    requested_mode: str
    scheduled_for: datetime | None = None
    not_before: datetime
    status: str
    attempt_count: int
    last_error: str | None = None
    response_payload: dict = Field(default_factory=dict)
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PublishQueueSummaryRead(BaseModel):
    id: int
    article_id: int
    blog_id: int
    requested_mode: str
    scheduled_for: datetime | None = None
    not_before: datetime
    status: str
    attempt_count: int
    last_error: str | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImageCompactRead(BaseModel):
    id: int
    public_url: str
    width: int
    height: int

    model_config = {"from_attributes": True}


class ArticleListItemRead(BaseModel):
    id: int
    job_id: int
    blog_id: int
    topic_id: int | None = None
    title: str
    meta_description: str
    labels: list[str]
    slug: str
    excerpt: str
    reading_time_minutes: int
    article_pattern_id: str | None = None
    article_pattern_version: int | None = None
    editorial_category_key: str | None = None
    editorial_category_label: str | None = None
    created_at: datetime
    updated_at: datetime
    blog: BlogCompactRead | None = None
    image: ImageCompactRead | None = None
    blogger_post: BloggerPostRead | None = None
    publish_queue: PublishQueueSummaryRead | None = None

    model_config = {"from_attributes": True}


class ArticleDetailRead(ArticleListItemRead):
    html_article: str
    faq_section: list[dict]
    image_collage_prompt: str
    inline_media: list[dict] = Field(default_factory=list)
    assembled_html: str | None = None
    usage_events: list[AIUsageEventRead] = Field(default_factory=list)
    usage_summary: AIUsageSummaryRead | None = None
    publish_queue: PublishQueueItemRead | None = None

    model_config = {"from_attributes": True}


class JobListItemRead(BaseModel):
    id: int
    blog_id: int
    topic_id: int | None = None
    keyword_snapshot: str
    status: JobStatus
    publish_mode: PublishMode
    start_time: datetime | None = None
    end_time: datetime | None = None
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    blog: BlogCompactRead | None = None
    topic: TopicRead | None = None
    article: ArticleListItemRead | None = None
    image: ImageCompactRead | None = None
    blogger_post: BloggerPostRead | None = None
    publish_status: str = "pending"
    execution_status: str = "PENDING"
    telegram_delivery_status: str | None = None
    telegram_error_message: str | None = None
    telegram_error_code: int | None = None
    telegram_response_text: str | None = None

    model_config = {"from_attributes": True}


class JobDetailRead(JobListItemRead):
    error_logs: list = Field(default_factory=list)
    raw_prompts: dict = Field(default_factory=dict)
    raw_responses: dict = Field(default_factory=dict)
    article: ArticleDetailRead | None = None
    image: ImageRead | None = None
    audit_logs: list[AuditLogRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DashboardTimeseriesPoint(BaseModel):
    date: str
    completed: int
    failed: int


class DashboardBlogSummary(BaseModel):
    blog_id: int
    blog_name: str
    blog_slug: str
    content_category: str
    completed_jobs: int
    failed_jobs: int
    queued_jobs: int
    published_posts: int
    latest_topic_keywords: list[str]
    latest_published_url: str | None = None


class DashboardMetrics(BaseModel):
    today_generated_posts: int
    success_jobs: int
    failed_jobs: int
    avg_processing_seconds: float
    latest_published_links: list[BloggerPostRead]
    jobs_by_status: dict[str, int]
    processing_series: list[DashboardTimeseriesPoint]
    blog_summaries: list[DashboardBlogSummary]
    review_queue_count: int = 0
    high_risk_count: int = 0
    auto_fix_applied_today: int = 0
    learning_snapshot_age: int | None = None


class ContentReviewActionRead(BaseModel):
    id: int
    action: str
    actor: str
    channel: str
    result_payload: dict = Field(default_factory=dict)
    created_at: datetime


class ContentReviewItemRead(BaseModel):
    id: int
    blog_id: int
    source_type: str
    source_id: str
    source_title: str
    source_url: str | None = None
    review_kind: str
    content_hash: str
    quality_score: int
    risk_level: str
    issues: list[dict] = Field(default_factory=list)
    proposed_patch: dict = Field(default_factory=dict)
    approval_status: str
    apply_status: str
    learning_state: str
    source_updated_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    last_applied_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
    actions: list[ContentReviewActionRead] = Field(default_factory=list)


class ContentOpsStatusRead(BaseModel):
    review_queue_count: int
    high_risk_count: int
    auto_fix_applied_today: int
    learning_snapshot_age: int | None = None
    learning_paused: bool = False
    learning_snapshot_path: str = ""
    prompt_memory_path: str = ""
    recent_reviews: list[ContentReviewItemRead] = Field(default_factory=list)


class IntegratedChannelSummaryRead(BaseModel):
    provider: str
    channel_id: str
    channel_name: str
    provider_status: str
    posts_count: int = 0
    categories_count: int = 0
    prompts_count: int = 0
    runs_count: int = 0
    site_title: str | None = None
    base_url: str | None = None
    error: str | None = None


class CloudflareCategoryRead(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None = None
    status: str
    scheduleTime: str
    scheduleTimezone: str
    createdAt: str
    updatedAt: str


class CloudflarePromptRead(BaseModel):
    id: str
    categoryId: str
    categorySlug: str
    categoryName: str
    stage: str
    currentVersion: int
    content: str
    createdAt: str
    updatedAt: str


class CloudflarePromptBundleRead(BaseModel):
    categories: list[CloudflareCategoryRead] = Field(default_factory=list)
    templates: list[CloudflarePromptRead] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)


class CloudflarePromptUpdate(BaseModel):
    content: str = Field(min_length=20)


class CloudflarePromptSyncRequest(BaseModel):
    execute: bool = True


class CloudflarePromptSyncRead(BaseModel):
    status: str
    execute: bool
    updated: int = 0
    skipped: int = 0
    files: list[dict] = Field(default_factory=list)
    failures: list[dict] = Field(default_factory=list)


class CloudflareGenerateRequest(BaseModel):
    per_category: int = Field(default=1, ge=1, le=5)
    category_slugs: list[str] = Field(default_factory=list)
    status: str = Field(default="published", pattern="^(published|draft)$")
    sync_sheet: bool = True


class CloudflareGenerateItemRead(BaseModel):
    status: str
    keyword: str | None = None
    title: str | None = None
    post_id: str | None = None
    slug: str | None = None
    public_url: str | None = None
    category_id: str | None = None
    quality_gate: dict | None = None
    error: str | None = None


class CloudflareGenerateCategoryRead(BaseModel):
    category_id: str
    category_slug: str
    category_name: str
    requested: int = 0
    created: int = 0
    failed: int = 0
    skipped: int = 0
    items: list[CloudflareGenerateItemRead] = Field(default_factory=list)
    topic_reject_breakdown: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class CloudflareGenerateRead(BaseModel):
    status: str
    created_count: int = 0
    failed_count: int = 0
    requested_categories: int = 0
    per_category: int = 0
    categories: list[CloudflareGenerateCategoryRead] = Field(default_factory=list)
    quality_sheet_sync: dict | None = None
    sync_result: dict | None = None
    sheet_sync: dict | None = None


class CloudflareRefactorRequest(BaseModel):
    execute: bool = False
    queue: bool = False
    threshold: float = Field(default=80.0, ge=0.0, le=100.0)
    month: str | None = None
    category_slugs: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=500)
    sync_before: bool = True
    parallel_workers: int = Field(default=1, ge=1, le=8)


class CloudflareRefactorItemRead(BaseModel):
    remote_id: str
    category_slug: str | None = None
    category_name: str | None = None
    title: str
    url: str | None = None
    published_at: str | None = None
    seo_score: float | None = None
    geo_score: float | None = None
    ctr: float | None = None
    lighthouse_score: float | None = None
    refactor_candidate: bool = False
    action: str
    updated_title: str | None = None
    updated_url: str | None = None
    article_pattern_id: str | None = None
    article_pattern_version: int | None = None
    quality_gate: dict | None = None
    error: str | None = None


class CloudflareRefactorRead(BaseModel):
    status: str
    execute: bool
    threshold: float
    month: str
    parallel_workers: int = 1
    task_id: str | None = None
    total_candidates: int = 0
    processed_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    sync_before_result: dict | None = None
    sync_after_result: dict | None = None
    summary_after: dict | None = None
    items: list[CloudflareRefactorItemRead] = Field(default_factory=list)


class BloggerRefactorRequest(BaseModel):
    execute: bool = False
    queue: bool = False
    threshold: float = Field(default=80.0, ge=0.0, le=100.0)
    month: str | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
    sync_before: bool = True
    run_lighthouse: bool = True
    parallel_workers: int = Field(default=1, ge=1, le=8)


class BloggerRefactorItemRead(BaseModel):
    fact_id: int
    synced_post_id: int
    remote_post_id: str
    title: str
    url: str | None = None
    published_at: str | None = None
    seo_score: float | None = None
    geo_score: float | None = None
    ctr: float | None = None
    ctr_score: float | None = None
    lighthouse_score: float | None = None
    refactor_candidate: bool = False
    action: str
    updated_title: str | None = None
    updated_url: str | None = None
    predicted_seo_score: float | None = None
    predicted_geo_score: float | None = None
    predicted_ctr_score: float | None = None
    lighthouse_after: dict | None = None
    article_pattern_id: str | None = None
    article_pattern_version: int | None = None
    quality_gate: dict | None = None
    search_description_sync: dict | None = None
    telegram: dict | None = None
    error: str | None = None


class BloggerRefactorRead(BaseModel):
    status: str
    execute: bool
    blog_id: int
    blog_name: str
    threshold: float
    month: str
    parallel_workers: int = 1
    task_id: str | None = None
    total_candidates: int = 0
    processed_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    sync_before_result: dict | None = None
    sync_after_result: dict | None = None
    summary_after: dict | None = None
    items: list[BloggerRefactorItemRead] = Field(default_factory=list)


class IntegratedArchiveItemRead(BaseModel):
    provider: str
    channel_id: str
    channel_name: str
    category_slug: str | None = None
    remote_id: str
    provider_status: str
    title: str
    excerpt: str | None = None
    published_url: str | None = None
    thumbnail_url: str | None = None
    labels: list[str] = Field(default_factory=list)
    canonical_category_name: str | None = None
    canonical_category_slug: str | None = None
    seo_score: float | None = None
    geo_score: float | None = None
    ctr: float | None = None
    lighthouse_score: float | None = None
    live_image_count: int | None = None
    live_unique_image_count: int | None = None
    live_duplicate_image_count: int | None = None
    live_webp_count: int | None = None
    live_png_count: int | None = None
    live_other_image_count: int | None = None
    live_image_issue: str | None = None
    live_image_audited_at: str | None = None
    index_status: str = "unknown"
    index_coverage_state: str | None = None
    index_last_checked_at: str | None = None
    next_eligible_at: str | None = None
    last_error: str | None = None
    quality_status: str | None = None
    published_at: str | None = None
    updated_at: str | None = None
    status: str


class IntegratedRunItemRead(BaseModel):
    provider: str
    channel_id: str
    channel_name: str
    remote_id: str
    provider_status: str
    title: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None
    summary: str | None = None
    metadata: dict = Field(default_factory=dict)


class JobCreate(BaseModel):
    blog_id: int | None = None
    keyword: str | None = None
    topic_id: int | None = None
    publish_mode: PublishMode | None = None
    stop_after_status: JobStatus | None = None


class DiscoveryRunRequest(BaseModel):
    blog_id: int
    publish_mode: PublishMode | None = None
    stop_after_status: JobStatus | None = None
    topic_count: int | None = Field(default=None, ge=1, le=20)


class DiscoveryRunResponse(BaseModel):
    blog_id: int
    blog_name: str
    queued_topics: int
    job_ids: list[int]
    message: str
    stop_after_status: JobStatus | None = None
    topic_count: int | None = None


class JobRetryResponse(BaseModel):
    job_id: int
    status: str
    message: str


class GeneratedDataResetResponse(BaseModel):
    deleted_jobs: int
    deleted_topics: int
    deleted_articles: int
    deleted_images: int
    deleted_blogger_posts: int
    deleted_ai_usage_events: int
    deleted_publish_queue_items: int
    deleted_audit_logs: int
    deleted_storage_files: int
    message: str


class SettingItem(BaseModel):
    key: str
    value: str
    description: str | None = None
    is_secret: bool = False

    model_config = {"from_attributes": True}


class SettingUpdate(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


class TrainingControlPayload(BaseModel):
    session_hours: float = Field(default=4.0, gt=0, le=24)
    save_every_minutes: int | None = Field(default=None, ge=1, le=180)


class TrainingScheduleRead(BaseModel):
    enabled: bool = False
    time: str = "03:00"
    timezone: str = "Asia/Seoul"


class TrainingScheduleUpdate(BaseModel):
    enabled: bool = False
    time: str = Field(default="03:00", pattern=r"^\d{2}:\d{2}$")
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=100)


class TrainingStatusRead(BaseModel):
    state: str
    current_step: int
    total_steps: int
    loss: float | None = None
    elapsed_seconds: int
    eta_seconds: int | None = None
    last_checkpoint: str | None = None
    next_scheduled_at: str | None = None
    last_error: str | None = None
    session_hours: float = 4.0
    save_every_minutes: int = 20
    pause_requested: bool = False
    run_id: int | None = None
    dataset_item_count: int = 0
    recent_logs: list[str] = Field(default_factory=list)
    schedule: TrainingScheduleRead = Field(default_factory=TrainingScheduleRead)
    model_name: str | None = None
    data_scope: str


class OpenAIFreeUsageBucketRead(BaseModel):
    label: str
    limit_tokens: int
    input_tokens: int = 0
    output_tokens: int = 0
    used_tokens: int
    remaining_tokens: int
    usage_percent: float
    matched_models: list[str] = Field(default_factory=list)


class OpenAIFreeUsageRead(BaseModel):
    date_label: str
    window_start_utc: str
    window_end_utc: str
    key_mode: str
    admin_key_configured: bool
    large: OpenAIFreeUsageBucketRead
    small: OpenAIFreeUsageBucketRead
    warning: str | None = None
    hard_cap_enabled: bool = True
    blocked_due_to_usage_unavailable: bool = False
    blocked_due_to_usage_cap: bool = False
    warning_threshold_percent: float = 80.0
    hard_cap_threshold_percent: float = 100.0
    unexpected_text_api_call_count: int = 0


class TelegramTestRequest(BaseModel):
    message: str | None = None


class TelegramTestRead(BaseModel):
    delivery_status: str
    chat_id: str | None = None
    message_id: int | None = None
    error_code: int | None = None
    error_message: str | None = None
    response_text: str | None = None
    skipped_reason: str | None = None


class TelegramPollNowRead(BaseModel):
    status: str
    processed: int = 0
    ignored: int = 0
    reason: str | None = None


class HelpTopicRead(BaseModel):
    topic_id: str
    title: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    related_screens: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    deep_links: list[str] = Field(default_factory=list)
    runbook: str | None = None


class TelegramSubscriptionsRead(BaseModel):
    chat_id: str
    subscriptions: dict[str, bool] = Field(default_factory=dict)
    updated_at: str | None = None


class TelegramSubscriptionsUpdate(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    subscriptions: dict[str, bool] = Field(default_factory=dict)


class TelegramCommandAggregateRead(BaseModel):
    command: str
    count: int


class TelegramTelemetryRead(BaseModel):
    days: int
    command_events: int = 0
    command_success: int = 0
    command_failed: int = 0
    deliveries_sent: int = 0
    deliveries_failed: int = 0
    top_commands: list[TelegramCommandAggregateRead] = Field(default_factory=list)


class PromptTemplateRead(BaseModel):
    key: str
    title: str
    description: str
    file_name: str
    placeholders: list[str]
    content: str


class PromptTemplateUpdate(BaseModel):
    content: str = Field(min_length=20)


class ArticlePublishRequest(BaseModel):
    mode: str = Field(default="publish", pattern="^(publish|schedule)$")
    scheduled_for: datetime | None = None
    force: bool = False


class CloudflareR2MigrationRequest(BaseModel):
    mode: str = Field(default="dry_run", pattern="^(dry_run|execute)$")
    blog_id: int | None = None
    limit: int = Field(default=20, ge=1, le=200)


class CloudflareR2MigrationItemRead(BaseModel):
    article_id: int
    title: str
    current_provider: str
    current_public_url: str | None = None
    planned_public_url: str | None = None
    status: str
    message: str


class CloudflareR2MigrationRead(BaseModel):
    mode: str
    candidate_count: int
    processable_count: int
    skipped_count: int
    updated_count: int
    failed_count: int
    items: list[CloudflareR2MigrationItemRead] = Field(default_factory=list)


class CloudflareAssetBootstrapRequest(BaseModel):
    channel_id: str = "cloudflare:dongriarchive"
    bucket_name: str = "dongriarchive-cloudflare"
    create_missing_categories: bool = True
    backfill_channel_metadata: bool = True
    verify_bucket: bool = True
    create_if_missing: bool = False


class CloudflareAssetBootstrapRead(BaseModel):
    status: str
    channel_id: str
    generated_at: str
    bucket_name: str
    bucket_created: bool = False
    bucket_verified: bool = False
    created_categories: list[str] = Field(default_factory=list)
    backfilled_metadata: bool = False
    metadata_updated: bool = False
    local_asset_root: str = ""
    sample_uploaded_keys: list[str] = Field(default_factory=list)
    report_path: str | None = None
    manifest_path: str | None = None
    csv_path: str | None = None


class CloudflareAssetRebuildRequest(BaseModel):
    mode: str = Field(default="dry_run", pattern="^(dry_run|execute)$")
    channel_id: str = "cloudflare:dongriarchive"
    category_slugs: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=1000)
    purge_target: bool = True
    use_fallback_heuristic: bool = True
    image_match_strategy: str = Field(default="slug_similarity", pattern="^(slug_similarity)$")
    ignore_filename_patterns: list[str] = Field(default_factory=lambda: ["cover"])
    allow_thumbnail_fallback: bool = False
    bucket_override: str | None = "dongriarchive-cloudflare"
    source_scope: str = Field(default="cloudflare_only_root_pool", pattern="^(cloudflare_only_root_pool)$")
    update_live_posts: bool = False
    allow_remote_thumbnail_fetch: bool = False
    use_legacy_evidence: bool = True
    legacy_evidence_can_auto_accept: bool = False


class CloudflareAssetRebuildItemRead(BaseModel):
    status: str
    remote_post_id: str | None = None
    slug: str | None = None
    title: str | None = None
    category_slug: str | None = None
    match_source: str | None = None
    confidence: float | None = None
    legacy_url_scheme: str | None = None
    url_asset_slug: str | None = None
    legacy_object_slug: str | None = None
    manifest_category_hit: bool = False
    evidence_score: float | None = None
    evidence_sources: list[str] = Field(default_factory=list)
    resolved_local_source: str | None = None
    resolved_target_path: str | None = None
    resolved_object_key: str | None = None
    resolved_public_url: str | None = None
    error: str | None = None
    reason: str | None = None


class CloudflareAssetRebuildRead(BaseModel):
    status: str
    mode: str
    channel_id: str
    generated_at: str
    db_posts: int = 0
    post_count: int = 0
    matched: int = 0
    candidate_count: int = 0
    matched_count: int = 0
    heuristic_matched_count: int = 0
    uploaded: int = 0
    uploaded_count: int = 0
    unresolved_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    purged_categories: list[str] = Field(default_factory=list)
    legacy_scheme_breakdown: dict[str, int] = Field(default_factory=dict)
    evidence_breakdown: dict[str, int] = Field(default_factory=dict)
    url_asset_exact_count: int = 0
    url_asset_prefix_count: int = 0
    manifest_category_hit_count: int = 0
    image_match_strategy: str = "slug_similarity"
    ignore_filename_patterns: list[str] = Field(default_factory=list)
    allow_thumbnail_fallback: bool = False
    bucket_name: str | None = None
    bucket_verified: bool | None = None
    sample_uploaded_keys: list[str] = Field(default_factory=list)
    source_scope: str = "cloudflare_only_root_pool"
    update_live_posts: bool = False
    allow_remote_thumbnail_fetch: bool = False
    remote_fetch_enabled: bool = False
    remote_fetch_attempted_count: int = 0
    remote_fetch_success_count: int = 0
    remote_fetch_preflight_count: int = 0
    remote_fetch_preflight_success_count: int = 0
    remote_fetch_status_breakdown: dict[str, int] = Field(default_factory=dict)
    use_legacy_evidence: bool = True
    legacy_evidence_can_auto_accept: bool = False
    created_categories: list[str] = Field(default_factory=list)
    sync_result: dict | None = None
    report_path: str | None = None
    manifest_path: str | None = None
    csv_path: str | None = None
    items: list[CloudflareAssetRebuildItemRead] = Field(default_factory=list)
    unresolved: list[dict] = Field(default_factory=list)


class CloudflareAssetRebuildReportRead(BaseModel):
    status: str
    channel_id: str
    report_path: str = ""
    manifest_path: str = ""
    report: dict | None = None


class CloudflarePostDedupeRequest(BaseModel):
    mode: str = Field(default="dry_run", pattern="^(dry_run|execute)$")
    channel_id: str = "cloudflare:dongriarchive"
    delete_scope: str = Field(default="remote_and_synced", pattern="^(remote_and_synced|synced_only)$")
    keep_rule: str = Field(default="latest_published", pattern="^(latest_published)$")


class CloudflarePostDedupeItemRead(BaseModel):
    action: str
    id: int | None = None
    remote_post_id: str | None = None
    slug: str | None = None
    title: str | None = None
    category_slug: str | None = None
    status: str | None = None
    url: str | None = None
    published_at: str | datetime | None = None
    normalized_title: str | None = None
    keeper_remote_post_id: str | None = None
    error: str | None = None


class CloudflarePostDedupeRead(BaseModel):
    status: str
    mode: str
    channel_id: str
    delete_scope: str
    keep_rule: str
    generated_at: str
    initial_sync_result: dict | None = None
    final_sync_result: dict | None = None
    total_live_count: int = 0
    duplicate_group_count: int = 0
    keep_count: int = 0
    delete_candidate_count: int = 0
    deleted_count: int = 0
    delete_failed_count: int = 0
    remaining_live_count: int = 0
    report_path: str | None = None
    manifest_path: str | None = None
    csv_path: str | None = None
    keep_items: list[CloudflarePostDedupeItemRead] = Field(default_factory=list)
    delete_candidates: list[CloudflarePostDedupeItemRead] = Field(default_factory=list)
    failed_items: list[CloudflarePostDedupeItemRead] = Field(default_factory=list)


class BloggerEditorialLabelBackfillRequest(BaseModel):
    mode: str = Field(default="dry_run", pattern="^(dry_run|execute)$")
    profile_keys: list[str] = Field(default_factory=lambda: ["korea_travel", "world_mystery"])


class BloggerEditorialLabelBackfillItemRead(BaseModel):
    article_id: int
    blog_id: int
    blog_name: str = ""
    profile_key: str = ""
    title: str
    published_url: str = ""
    blogger_post_id: str = ""
    current_labels: list[str] = Field(default_factory=list)
    target_labels: list[str] = Field(default_factory=list)
    editorial_category_key: str | None = None
    editorial_category_label: str | None = None
    resolved_editorial_category_key: str | None = None
    resolved_editorial_category_label: str | None = None
    status: str
    message: str


class BloggerEditorialLabelBackfillRead(BaseModel):
    status: str
    mode: str
    profile_keys: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    processable_count: int = 0
    skipped_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    task_id: str | None = None
    report_path: str | None = None
    sync_results: list[dict] = Field(default_factory=list)
    sheet_sync: dict | None = None
    items: list[BloggerEditorialLabelBackfillItemRead] = Field(default_factory=list)


class CloudflarePublishedPostBackfillRequest(BaseModel):
    mode: str = Field(default="dry_run", pattern="^(dry_run|execute)$")
    limit: int = Field(default=20, ge=1, le=100)
    only_missing_cover: bool = True


class CloudflarePublishedPostBackfillItemRead(BaseModel):
    post_id: str
    slug: str
    title: str
    category_slug: str | None = None
    current_cover_image: str | None = None
    updated_cover_image: str | None = None
    current_length: int = 0
    updated_length: int | None = None
    status: str
    message: str


class CloudflarePublishedPostBackfillRead(BaseModel):
    mode: str
    candidate_count: int
    processable_count: int
    skipped_count: int
    updated_count: int
    failed_count: int
    items: list[CloudflarePublishedPostBackfillItemRead] = Field(default_factory=list)


class BloggerRemoteBlogRead(BaseModel):
    id: str
    name: str
    description: str | None = None
    url: str | None = None
    published: str | None = None
    updated: str | None = None
    locale: dict | None = None
    posts_total_items: int | None = None
    pages_total_items: int | None = None


class BloggerRemotePostRead(BaseModel):
    id: str
    title: str
    url: str | None = None
    published: str | None = None
    updated: str | None = None
    labels: list[str] = Field(default_factory=list)
    status: str | None = None
    author_display_name: str | None = None
    replies_total_items: int = 0


class SyncedBloggerPostRead(BaseModel):
    id: str
    title: str
    url: str | None = None
    status: str | None = None
    published: str | None = None
    updated: str | None = None
    labels: list[str] = Field(default_factory=list)
    author_display_name: str | None = None
    replies_total_items: int = 0
    content_html: str = ""
    thumbnail_url: str | None = None
    excerpt_text: str = ""
    live_image_count: int | None = None
    live_unique_image_count: int | None = None
    live_duplicate_image_count: int | None = None
    live_webp_count: int | None = None
    live_png_count: int | None = None
    live_other_image_count: int | None = None
    live_cover_present: bool | None = None
    live_inline_present: bool | None = None
    live_image_issue: str | None = None
    live_image_audited_at: str | None = None
    synced_at: str | None = None
    seo_score: float | None = None
    geo_score: float | None = None
    lighthouse_score: float | None = None
    ctr: float | None = None
    index_status: str = "unknown"
    index_coverage_state: str | None = None
    index_last_checked_at: str | None = None
    next_eligible_at: str | None = None
    last_error: str | None = None


class SyncedBloggerPostPageRead(BaseModel):
    items: list[SyncedBloggerPostRead] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    last_synced_at: str | None = None


class SyncedBloggerPostGroupRead(BaseModel):
    blog_id: int
    blog_name: str
    blog_url: str | None = None
    total: int
    last_synced_at: str | None = None
    items: list[SyncedBloggerPostRead] = Field(default_factory=list)


class SyncedBloggerPostGroupPageRead(BaseModel):
    groups: list[SyncedBloggerPostGroupRead] = Field(default_factory=list)
    total_groups: int = 0


class IntegratedArchiveCategoryGroupRead(BaseModel):
    category_slug: str
    category_name: str
    total: int
    last_synced_at: str | None = None
    items: list[IntegratedArchiveItemRead] = Field(default_factory=list)


class BlogArchiveItemRead(BaseModel):
    source: str
    id: str
    blog_id: int
    title: str
    excerpt: str = ""
    thumbnail_url: str | None = None
    labels: list[str] = Field(default_factory=list)
    published_url: str | None = None
    published_at: datetime | None = None
    scheduled_for: datetime | None = None
    updated_at: datetime | None = None
    status: str
    content_html: str | None = None
    has_published_url: bool = False
    clickable: bool = False
    publish_state: str = "pending"
    recovery_available: bool = False
    recovery_block_reason: str | None = None
    queue_status: str | None = None
    last_publish_error: str | None = None
    remote_validation_status: str = "unknown"
    remote_validation_message: str | None = None
    publish_status: str = "pending"
    telegram_delivery_status: str | None = None
    telegram_error_message: str | None = None
    telegram_error_code: int | None = None
    telegram_response_text: str | None = None


class BlogArchivePageRead(BaseModel):
    items: list[BlogArchiveItemRead] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    last_synced_at: datetime | None = None


class ArchiveChannelRead(BaseModel):
    channel_key: str
    channel_label: str
    provider: str
    channel_id: str
    channel_name: str
    provider_status: str


class ArchiveChannelListRead(BaseModel):
    items: list[ArchiveChannelRead] = Field(default_factory=list)


class ArchiveChannelItemRead(BaseModel):
    provider: str
    channel_key: str
    channel_label: str
    channel_id: str
    channel_name: str
    provider_status: str
    source: str
    id: str
    remote_id: str
    blog_id: int | None = None
    title: str
    excerpt: str = ""
    category_slug: str | None = None
    category_name: str | None = None
    thumbnail_url: str | None = None
    labels: list[str] = Field(default_factory=list)
    published_url: str | None = None
    published_at: datetime | None = None
    scheduled_for: datetime | None = None
    updated_at: datetime | None = None
    status: str
    content_html: str | None = None
    has_published_url: bool = False
    clickable: bool = False
    publish_state: str = "pending"
    recovery_available: bool = False
    recovery_block_reason: str | None = None
    queue_status: str | None = None
    last_publish_error: str | None = None
    remote_validation_status: str = "unknown"
    remote_validation_message: str | None = None
    publish_status: str = "pending"
    telegram_delivery_status: str | None = None
    telegram_error_message: str | None = None
    telegram_error_code: int | None = None
    telegram_response_text: str | None = None


class ArchiveChannelPageRead(BaseModel):
    channel_key: str
    channel_label: str
    provider: str
    channel_id: str
    channel_name: str
    provider_status: str
    items: list[ArchiveChannelItemRead] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 24
    last_synced_at: datetime | None = None
    available_categories: list[dict[str, str | int]] = Field(default_factory=list)
    selected_category: str | None = None


class SearchConsoleSiteRead(BaseModel):
    site_url: str
    permission_level: str | None = None


class SearchConsoleRowRead(BaseModel):
    keys: list[str] = Field(default_factory=list)
    clicks: float = 0
    impressions: float = 0
    ctr: float = 0
    position: float = 0


class SearchConsolePerformanceRead(BaseModel):
    site_url: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    totals: dict[str, float] = Field(default_factory=dict)
    top_queries: list[SearchConsoleRowRead] = Field(default_factory=list)
    top_pages: list[SearchConsoleRowRead] = Field(default_factory=list)


class AnalyticsPropertyRead(BaseModel):
    property_id: str
    display_name: str
    property_type: str | None = None
    parent_display_name: str | None = None


class AnalyticsOverviewRead(BaseModel):
    property_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    totals: dict[str, float] = Field(default_factory=dict)
    top_pages: list[dict] = Field(default_factory=list)


class BloggerPageviewRead(BaseModel):
    range: str
    count: int


class GoogleBlogOverviewRead(BaseModel):
    blog_id: int
    blog_name: str
    blogger_blog_id: str | None = None
    remote_blog: BloggerRemoteBlogRead | None = None
    pageviews: list[BloggerPageviewRead] = Field(default_factory=list)
    recent_posts: list[BloggerRemotePostRead] = Field(default_factory=list)
    search_console: SearchConsolePerformanceRead | None = None
    analytics: AnalyticsOverviewRead | None = None
    warnings: list[str] = Field(default_factory=list)


class GoogleIntegrationConfigRead(BaseModel):
    oauth_scopes: list[str]
    granted_scopes: list[str]
    search_console_sites: list[SearchConsoleSiteRead] = Field(default_factory=list)
    analytics_properties: list[AnalyticsPropertyRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GoogleBlogIndexingTestRequest(BaseModel):
    urls: list[str] | None = None
    limit: int = Field(default=50, ge=1, le=500)


class GoogleBlogIndexingRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=500)
    urls: list[str] | None = None
    force: bool = False
    run_test: bool = True
    test_limit: int = Field(default=100, ge=1, le=1000)


class GooglePlaywrightIndexingRequest(BaseModel):
    count: int = Field(default=12, ge=1, le=12)
    force: bool = False
    run_test: bool = True
    test_limit: int = Field(default=100, ge=1, le=1000)
    urls: list[str] | None = None
    target_scope: str = "blogger+cloudflare"


class GoogleIndexingStatusRefreshRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)
    force: bool = False
    run_test: bool = False
    target_scope: str = "blogger+cloudflare"


class GoogleBlogIndexingQuotaRead(BaseModel):
    day_key: str
    blog_id: int
    publish_used: int
    publish_limit: int
    publish_remaining: int
    inspection_used: int
    inspection_limit: int
    inspection_remaining: int
    inspection_qpm_limit: int


class GoogleSheetSyncRequest(BaseModel):
    initial: bool = False


class GoogleSheetSyncRead(BaseModel):
    sheet_id: str
    initial: bool
    snapshot_date_kst: str
    travel_blog_id: int
    mystery_blog_id: int
    travel_rows: int
    mystery_rows: int
    travel_tab: str
    mystery_tab: str


class ContentOverviewRowRead(BaseModel):
    article_id: int
    blog_id: int
    profile: str
    blog: str
    title: str
    url: str
    content_category: str | None = None
    category_key: str | None = None
    topic_cluster: str
    topic_angle: str
    similarity_score: float | None = None
    most_similar_url: str
    seo_score: float | None = None
    geo_score: float | None = None
    lighthouse_score: float | None = None
    media_state: str
    quality_status: str
    suggested_action: str
    auto_fixable: bool
    manual_review: bool
    rewrite_attempts: int = 0
    status: str
    published_at: str = ""
    updated_at: str = ""
    last_audited_at: str
    lighthouse_last_audited_at: str = ""


class ContentOverviewResponse(BaseModel):
    rows: list[ContentOverviewRowRead] = Field(default_factory=list)
    total: int
    page: int = 1
    page_size: int = 50
    profile: str | None = None
    published_only: bool = False


class ContentOverviewSyncRequest(BaseModel):
    profile: str | None = None
    published_only: bool = False
    sync_sheet: bool = True


class ContentOverviewSyncRead(BaseModel):
    sheet_id: str
    profile: str | None
    tab: str
    status: str
    rows: int
    columns: int


class ContentOverviewRecalculateRead(BaseModel):
    profile: str | None = None
    published_only: bool = False
    updated_articles: int
    total_articles: int
    status: str = "ok"


class ModelPolicyRead(BaseModel):
    large: list[str]
    small: list[str]
    deprecated: list[str]
    defaults: dict[str, str]
    text_runtime_kind: str
    text_runtime_model: str
    image_runtime_kind: str
    image_runtime_model: str
    openai_usage_hard_cap_enabled: bool
    unexpected_openai_text_calls: int = 0
    banned_text_model_prefixes: list[str] = Field(default_factory=list)


class ManagedChannelRead(BaseModel):
    provider: ChannelProvider | str
    channel_id: str
    name: str
    is_enabled: bool = True
    status: ManagedChannelStatus | str
    base_url: str | None = None
    primary_category: str | None = None
    purpose: str | None = None
    posts_count: int = 0
    categories_count: int = 0
    prompts_count: int = 0
    planner_supported: bool = False
    analytics_supported: bool = False
    prompt_flow_supported: bool = False
    capabilities: list[str] = Field(default_factory=list)
    oauth_state: str = "disconnected"
    quota_state: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    agent_pack_summary: list[dict[str, str | int | bool | None]] = Field(default_factory=list)
    live_worker_count: int = 0
    pending_items: int = 0
    failed_items: int = 0
    linked_blog_id: int | None = None
    credential_state: "PlatformCredentialRead | None" = None


class PlatformCredentialRead(BaseModel):
    id: int
    managed_channel_id: int | None = None
    channel_id: str | None = None
    provider: ChannelProvider | str
    credential_key: str
    subject: str | None = None
    scopes: list[str] = Field(default_factory=list)
    access_token_configured: bool = False
    refresh_token_configured: bool = False
    expires_at: datetime | None = None
    token_type: str = "Bearer"
    is_valid: bool = False
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class PlatformCredentialUpsert(BaseModel):
    channel_id: str = Field(min_length=3)
    provider: ChannelProvider | str
    subject: str | None = None
    display_name: str | None = None
    credential_key: str | None = None
    access_token: str = ""
    refresh_token: str = ""
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    token_type: str = "Bearer"
    refresh_metadata: dict = Field(default_factory=dict)
    is_valid: bool = True
    last_error: str | None = None


class PlatformIntegrationRead(BaseModel):
    provider: ChannelProvider | str
    channel_id: str
    display_name: str
    oauth_state: str
    status: str
    scope_count: int = 0
    expires_at: datetime | None = None
    is_valid: bool = False
    last_error: str | None = None


class SeoTargetRead(BaseModel):
    target_id: str
    provider: ChannelProvider | str
    channel_id: str | None = None
    label: str
    base_url: str | None = None
    linked_blog_id: int | None = None
    search_console_site_url: str | None = None
    ga4_property_id: str | None = None
    oauth_state: str = "unknown"
    is_connected: bool = False


class RuntimeUsageBucketRead(BaseModel):
    key: str
    label: str
    event_count: int = 0
    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    error_count: int = 0
    latest_event_at: datetime | None = None


class RuntimeUsageTotalRead(BaseModel):
    event_count: int = 0
    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    error_count: int = 0


class WorkspaceRuntimeUsageRead(BaseModel):
    generated_at: datetime
    days: int
    totals: RuntimeUsageTotalRead
    providers: list[RuntimeUsageBucketRead] = Field(default_factory=list)


class PublicationRecordRead(BaseModel):
    id: int
    provider: ChannelProvider | str
    remote_id: str | None = None
    remote_url: str | None = None
    target_state: str = "publish"
    publish_status: str
    error_code: str | None = None
    scheduled_for: datetime | None = None
    published_at: datetime | None = None
    response_payload: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MetricFactRead(BaseModel):
    id: int
    managed_channel_id: int
    content_item_id: int | None = None
    provider: ChannelProvider | str
    metric_scope: str
    metric_name: str
    value: float
    normalized_score: float | None = None
    dimension_key: str | None = None
    dimension_value: str | None = None
    snapshot_at: datetime
    payload: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ContentItemRead(BaseModel):
    id: int
    managed_channel_id: int
    idempotency_key: str = ""
    channel_id: str
    provider: ChannelProvider | str
    blog_id: int | None = None
    job_id: int | None = None
    source_article_id: int | None = None
    content_type: ContentItemType | str
    lifecycle_status: ContentItemStatus | str
    title: str
    description: str = ""
    body_text: str = ""
    asset_manifest: dict = Field(default_factory=dict)
    brief_payload: dict = Field(default_factory=dict)
    review_notes: list = Field(default_factory=list)
    approval_status: str = "pending"
    scheduled_for: datetime | None = None
    last_feedback: str | None = None
    blocked_reason: str | None = None
    last_score: dict = Field(default_factory=dict)
    created_by_agent: str | None = None
    latest_publication: PublicationRecordRead | None = None
    metric_count: int = 0
    run_count: int = 0
    created_at: datetime
    updated_at: datetime


class ContentItemCreate(BaseModel):
    channel_id: str = Field(min_length=3)
    idempotency_key: str | None = Field(default=None, min_length=3, max_length=120)
    content_type: ContentItemType | str
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    body_text: str = ""
    asset_manifest: dict = Field(default_factory=dict)
    brief_payload: dict = Field(default_factory=dict)
    scheduled_for: datetime | None = None
    created_by_agent: str | None = None
    job_id: int | None = Field(default=None, ge=1)
    source_article_id: int | None = Field(default=None, ge=1)


class ContentItemUpdate(BaseModel):
    lifecycle_status: ContentItemStatus | str | None = None
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    body_text: str | None = None
    approval_status: str | None = None
    asset_manifest: dict | None = None
    brief_payload: dict | None = None
    review_notes: list | None = None
    scheduled_for: datetime | None = None
    last_feedback: str | None = None
    blocked_reason: str | None = None
    last_score: dict | None = None


class ContentItemReviewRequest(BaseModel):
    review_notes: list = Field(default_factory=list)
    last_feedback: str | None = None


class AgentWorkerRead(BaseModel):
    id: int
    managed_channel_id: int | None = None
    channel_id: str | None = None
    worker_key: str
    runtime_kind: AgentRuntimeKind | str
    display_name: str
    role_name: str
    queue_name: str
    concurrency_limit: int
    status: AgentWorkerStatus | str
    config_payload: dict = Field(default_factory=dict)
    last_heartbeat_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentWorkerCreate(BaseModel):
    channel_id: str | None = None
    worker_key: str = Field(min_length=3, max_length=120)
    display_name: str = Field(min_length=2, max_length=255)
    role_name: str = Field(min_length=2, max_length=120)
    runtime_kind: AgentRuntimeKind | str
    queue_name: str = Field(min_length=3, max_length=120)
    concurrency_limit: int = Field(default=1, ge=1, le=20)
    status: AgentWorkerStatus | str = AgentWorkerStatus.IDLE
    config_payload: dict = Field(default_factory=dict)


class AgentWorkerUpdate(BaseModel):
    status: AgentWorkerStatus | str | None = None
    concurrency_limit: int | None = Field(default=None, ge=1, le=20)
    config_payload: dict | None = None
    last_heartbeat_at: datetime | None = None
    last_error: str | None = None


class AgentRunRead(BaseModel):
    id: int
    managed_channel_id: int | None = None
    channel_id: str | None = None
    content_item_id: int | None = None
    worker_id: int | None = None
    run_key: str
    runtime_kind: AgentRuntimeKind | str
    assigned_role: str
    provider_model: str | None = None
    status: AgentRunStatus | str
    priority: int
    timeout_seconds: int
    retry_count: int
    max_retries: int
    started_at: datetime | None = None
    ended_at: datetime | None = None
    prompt_snapshot: str = ""
    response_snapshot: str = ""
    log_lines: list = Field(default_factory=list)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentRunCreate(BaseModel):
    channel_id: str | None = None
    content_item_id: int | None = Field(default=None, ge=1)
    worker_id: int | None = Field(default=None, ge=1)
    run_key: str = Field(min_length=3, max_length=120)
    runtime_kind: AgentRuntimeKind | str
    assigned_role: str = Field(min_length=2, max_length=120)
    provider_model: str | None = None
    priority: int = Field(default=50, ge=0, le=100)
    timeout_seconds: int = Field(default=900, ge=30, le=3600)
    prompt_snapshot: str = ""
    status: AgentRunStatus | str = AgentRunStatus.QUEUED


class AgentRunUpdate(BaseModel):
    status: AgentRunStatus | str | None = None
    retry_count: int | None = Field(default=None, ge=0, le=20)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    response_snapshot: str | None = None
    log_lines: list | None = None
    error_message: str | None = None


class AgentRuntimeHealthRead(BaseModel):
    worker_count: int
    run_count: int
    worker_status: dict = Field(default_factory=dict)
    run_status: dict = Field(default_factory=dict)
    last_run_at: datetime | None = None
    runtime_kinds: list[str] = Field(default_factory=list)
    healthy: bool = False
    generated_at: datetime


class MissionControlAlertRead(BaseModel):
    key: str
    level: str
    title: str
    message: str


class MissionControlRead(BaseModel):
    workspace_label: str
    channels: list[ManagedChannelRead] = Field(default_factory=list)
    workers: list[AgentWorkerRead] = Field(default_factory=list)
    runs: list[AgentRunRead] = Field(default_factory=list)
    recent_content: list[ContentItemRead] = Field(default_factory=list)
    runtime_health: AgentRuntimeHealthRead
    alerts: list[MissionControlAlertRead] = Field(default_factory=list)


class WorkspaceIntegrationOverviewRead(BaseModel):
    channels: list[ManagedChannelRead] = Field(default_factory=list)
    integrations: list[PlatformIntegrationRead] = Field(default_factory=list)
    credentials: list[PlatformCredentialRead] = Field(default_factory=list)


class WorkspaceRuntimeOverviewRead(BaseModel):
    profiles: list[dict] = Field(default_factory=list)
    workers: list[AgentWorkerRead] = Field(default_factory=list)
    runs: list[AgentRunRead] = Field(default_factory=list)
    runtime_health: AgentRuntimeHealthRead | None = None


class WorkspaceOverviewRead(BaseModel):
    channels: list[ManagedChannelRead] = Field(default_factory=list)
    content_items: list[ContentItemRead] = Field(default_factory=list)
    runtime: WorkspaceRuntimeOverviewRead


class WorkspaceRuntimeUsageBucketRead(BaseModel):
    provider_key: str
    label: str
    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0
    error_count: int = 0
    last_event_at: datetime | None = None
    models: list[str] = Field(default_factory=list)


class WorkspaceRuntimeUsageTotalsRead(BaseModel):
    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0
    error_count: int = 0
    last_event_at: datetime | None = None
    models: list[str] = Field(default_factory=list)


class WorkspaceRuntimeUsageRead(BaseModel):
    generated_at: datetime
    days: int
    providers: list[WorkspaceRuntimeUsageBucketRead] = Field(default_factory=list)
    totals: WorkspaceRuntimeUsageTotalsRead = Field(default_factory=WorkspaceRuntimeUsageTotalsRead)


class SeoTargetRead(BaseModel):
    target_id: str
    provider: ChannelProvider | str
    channel_id: str
    blog_id: int | None = None
    label: str
    base_url: str | None = None
    linked_blog_id: int | None = None
    search_console_site_url: str | None = None
    ga4_property_id: str | None = None
    oauth_state: str = "disconnected"
    is_connected: bool = False


class PromptFlowStepRead(BaseModel):
    id: str
    channel_id: str
    provider: str
    stage_type: str
    stage_label: str
    name: str
    role_name: str | None = None
    objective: str | None = None
    prompt_template: str
    provider_hint: str | None = None
    provider_model: str | None = None
    is_enabled: bool = True
    is_required: bool = False
    removable: bool = False
    prompt_enabled: bool = True
    editable: bool = True
    structure_editable: bool = True
    content_editable: bool = True
    sort_order: int
    backup_relative_path: str | None = None
    backup_exists: bool = False
    planner_provider_hint: str | None = None
    planner_provider_model: str | None = None
    pass_provider_hint: str | None = None
    pass_provider_model: str | None = None
    structure_mode: str | None = None
    structure_segments: int | None = None
    locked_image_model: str | None = None
    image_policy_version: str | None = None
    image_layout_policy: str | None = None
    text_generation_route: str | None = None
    policy_config: dict | None = None


class PromptFlowRead(BaseModel):
    channel_id: str
    channel_name: str
    provider: str
    structure_editable: bool = True
    content_editable: bool = True
    available_stage_types: list[str] = Field(default_factory=list)
    steps: list[PromptFlowStepRead] = Field(default_factory=list)
    backup_directory: str | None = None


class PromptFlowStepUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    role_name: str | None = Field(default=None, min_length=2, max_length=255)
    objective: str | None = None
    prompt_template: str | None = None
    provider_hint: str | None = None
    provider_model: str | None = None
    is_enabled: bool | None = None
    planner_provider_hint: str | None = None
    planner_provider_model: str | None = None
    pass_provider_hint: str | None = None
    pass_provider_model: str | None = None
    structure_mode: str | None = None
    structure_segments: int | None = None
    locked_image_model: str | None = None
    image_policy_version: str | None = None
    image_layout_policy: str | None = None
    text_generation_route: str | None = None
    policy_config: dict | None = None


class PromptFlowReorderRequest(BaseModel):
    ordered_ids: list[str] = Field(min_length=1)


class PlannerCategoryRead(BaseModel):
    key: str
    name: str
    weight: int
    color: str | None = None
    sort_order: int
    is_active: bool
    planning_mode: str = "auto"
    weekly_target: int | None = Field(default=None, ge=1, le=7)
    weekdays: list[int] = Field(default_factory=list)


class PlannerSlotCreate(BaseModel):
    plan_day_id: int
    category_key: str = Field(min_length=1, max_length=100)
    scheduled_for: str
    brief_topic: str | None = None
    brief_audience: str | None = None
    brief_information_level: str | None = None
    brief_extra_context: str | None = None


class PlannerSlotUpdate(BaseModel):
    category_key: str | None = Field(default=None, min_length=1, max_length=100)
    scheduled_for: str | None = None
    slot_order: int | None = None
    brief_topic: str | None = None
    brief_audience: str | None = None
    brief_information_level: str | None = None
    brief_extra_context: str | None = None
    status: str | None = None
    error_message: str | None = None


class PlannerSlotRead(BaseModel):
    id: int
    plan_day_id: int
    channel_id: str
    publish_mode: str | None = None
    theme_id: int | None = None
    theme_key: str | None = None
    theme_name: str | None = None
    category_key: str | None = None
    category_name: str | None = None
    category_color: str | None = None
    scheduled_for: str | None = None
    slot_order: int
    status: str
    brief_topic: str | None = None
    brief_audience: str | None = None
    brief_information_level: str | None = None
    brief_extra_context: str | None = None
    article_id: int | None = None
    job_id: int | None = None
    error_message: str | None = None
    last_run_at: str | None = None
    article_title: str | None = None
    article_seo_score: float | None = None
    article_geo_score: float | None = None
    article_similarity_score: float | None = None
    article_most_similar_url: str | None = None
    article_quality_status: str | None = None
    article_publish_status: str | None = None
    article_published_url: str | None = None
    result_title: str | None = None
    result_url: str | None = None
    result_status: str | None = None
    quality_gate_status: str | None = None


class PlannerDayRead(BaseModel):
    id: int
    channel_id: str
    blog_id: int | None = None
    plan_date: str
    target_post_count: int
    status: str
    slot_count: int
    category_mix: dict[str, int]
    slots: list[PlannerSlotRead]


class PlannerCalendarRead(BaseModel):
    channel_id: str
    channel_name: str
    channel_provider: str
    blog_id: int | None = None
    month: str
    categories: list[PlannerCategoryRead] = Field(default_factory=list)
    days: list[PlannerDayRead]


class PlannerMonthPlanRequest(BaseModel):
    channel_id: str | None = None
    blog_id: int | None = Field(default=None, ge=1)
    month: str
    target_post_count: int | None = None
    overwrite: bool = False


class PlannerCategoryRuleUpdate(BaseModel):
    category_key: str = Field(min_length=1, max_length=100)
    planning_mode: str = Field(default="auto", pattern=r"^(auto|weekly|weekdays)$")
    weekly_target: int | None = Field(default=None, ge=1, le=7)
    weekdays: list[int] = Field(default_factory=list)


class PlannerCategoryRulesUpdateRequest(BaseModel):
    channel_id: str | None = None
    blog_id: int | None = Field(default=None, ge=1)
    rules: list[PlannerCategoryRuleUpdate] = Field(default_factory=list)


class PlannerBriefSuggestionRead(BaseModel):
    slot_id: int
    slot_order: int | None = None
    category_key: str | None = None
    topic: str | None = None
    audience: str | None = None
    information_level: str | None = None
    extra_context: str | None = None
    expected_ctr_lift: str | None = None
    confidence: float | None = None
    signal_source: str | None = None
    reason: str | None = None


class PlannerBriefRunRead(BaseModel):
    id: int
    plan_day_id: int
    channel_id: str
    blog_id: int | None = None
    provider: str
    model: str | None = None
    prompt: str
    raw_response: dict
    slot_suggestions: list[PlannerBriefSuggestionRead] = Field(default_factory=list)
    status: str
    error_message: str | None = None
    applied_slot_ids: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlannerDayBriefAnalysisRequest(BaseModel):
    prompt_override: str | None = None


class PlannerDayBriefAnalysisResponse(BaseModel):
    run: PlannerBriefRunRead


class PlannerBriefSuggestionInput(BaseModel):
    slot_id: int = Field(ge=1)
    topic: str | None = None
    audience: str | None = None
    information_level: str | None = None
    extra_context: str | None = None
    expected_ctr_lift: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    signal_source: str | None = None
    reason: str | None = None


class PlannerDayBriefApplyRequest(BaseModel):
    run_id: int | None = Field(default=None, ge=1)
    slot_suggestions: list[PlannerBriefSuggestionInput] | None = None


class PlannerDayBriefApplyResponse(BaseModel):
    plan_day_id: int
    applied_slot_ids: list[int] = Field(default_factory=list)
    skipped_slot_ids: list[int] = Field(default_factory=list)
    run_id: int | None = None
    status: str = "applied"


class AnalyticsArticleFactRead(BaseModel):
    id: int
    blog_id: int
    article_id: int | None = None
    synced_post_id: int | None = None
    published_at: str | None = None
    title: str
    theme_key: str | None = None
    theme_name: str | None = None
    category: str | None = None
    seo_score: float | None = None
    geo_score: float | None = None
    lighthouse_score: float | None = None
    lighthouse_accessibility_score: float | None = None
    lighthouse_best_practices_score: float | None = None
    lighthouse_seo_score: float | None = None
    similarity_score: float | None = None
    most_similar_url: str | None = None
    article_pattern_id: str | None = None
    article_pattern_version: int | None = None
    status: str | None = None
    actual_url: str | None = None
    source_type: str
    ctr: float | None = None
    ctr_score: float | None = None
    live_image_count: int | None = None
    live_unique_image_count: int | None = None
    live_duplicate_image_count: int | None = None
    live_webp_count: int | None = None
    live_png_count: int | None = None
    live_other_image_count: int | None = None
    live_image_issue: str | None = None
    refactor_candidate: bool = False
    index_status: str = "unknown"
    index_coverage_state: str | None = None
    last_crawl_time: str | None = None
    last_notify_time: str | None = None
    next_eligible_at: str | None = None
    index_last_checked_at: str | None = None
    status_variant: str = "unknown"
    can_manual_delete: bool = False


class AnalyticsThemeMonthlyStatRead(BaseModel):
    id: int
    blog_id: int
    month: str
    theme_key: str
    theme_name: str
    planned_posts: int
    actual_posts: int
    planned_share: float
    actual_share: float
    gap_share: float
    avg_seo_score: float | None = None
    avg_geo_score: float | None = None
    avg_similarity_score: float | None = None
    coverage_gap_score: float
    next_month_weight_suggestion: int


class AnalyticsBlogMonthlySummaryRead(BaseModel):
    blog_id: int
    blog_name: str
    month: str
    total_posts: int
    avg_seo_score: float | None = None
    avg_geo_score: float | None = None
    avg_similarity_score: float | None = None
    most_underused_theme_name: str | None = None
    most_overused_theme_name: str | None = None
    next_month_focus: str | None = None


class AnalyticsBlogMonthlyListResponse(BaseModel):
    month: str
    items: list[AnalyticsBlogMonthlySummaryRead]


class AnalyticsBlogMonthlyReportRead(BaseModel):
    blog_id: int
    blog_name: str
    month: str
    total_posts: int
    avg_seo_score: float | None = None
    avg_geo_score: float | None = None
    avg_similarity_score: float | None = None
    most_underused_theme_name: str | None = None
    most_overused_theme_name: str | None = None
    next_month_focus: str | None = None
    report_summary: str | None = None
    theme_stats: list[AnalyticsThemeMonthlyStatRead]
    article_facts: list[AnalyticsArticleFactRead]


class AnalyticsDailySummaryRead(BaseModel):
    date: str
    total_posts: int
    generated_posts: int
    synced_posts: int
    avg_seo: float | None = None
    avg_geo: float | None = None


class AnalyticsDailySummaryListResponse(BaseModel):
    blog_id: int
    month: str
    items: list[AnalyticsDailySummaryRead] = Field(default_factory=list)


class AnalyticsArticleFactListResponse(BaseModel):
    blog_id: int
    month: str
    total: int = 0
    page: int = 1
    page_size: int = 50
    items: list[AnalyticsArticleFactRead] = Field(default_factory=list)


class AnalyticsIndexingRequest(BaseModel):
    blog_id: int = Field(ge=1)
    url: str = Field(min_length=1, max_length=1000)
    force: bool = False


class AnalyticsIndexingRefreshRequest(BaseModel):
    blog_id: int = Field(ge=1)
    urls: list[str] | None = None
    limit: int = Field(default=50, ge=1, le=500)


class AnalyticsThemeWeightApplyRequest(BaseModel):
    month: str


class AnalyticsThemeWeightApplyResponse(BaseModel):
    blog_id: int
    source_month: str
    target_month: str
    applied_weights: dict[str, int]


class AnalyticsBackfillRead(BaseModel):
    blog_months: int
    generated_facts: int
    synced_facts: int


class AnalyticsIntegratedKpiRead(BaseModel):
    total_posts: int
    avg_seo_score: float | None = None
    avg_geo_score: float | None = None
    avg_similarity_score: float | None = None
    most_underused_theme_name: str | None = None
    most_overused_theme_name: str | None = None
    recent_upload_count: int


class AnalyticsThemeFilterOptionRead(BaseModel):
    key: str
    name: str


class AnalyticsIntegratedRead(BaseModel):
    month: str
    range: str
    selected_blog_id: int | None = None
    kpis: AnalyticsIntegratedKpiRead
    blogs: list[AnalyticsBlogMonthlySummaryRead]
    report: AnalyticsBlogMonthlyReportRead | None = None
    source_type: str
    theme_key: str | None = None
    category: str | None = None
    status: str | None = None
    available_themes: list[AnalyticsThemeFilterOptionRead] = Field(default_factory=list)
    available_categories: list[str] = Field(default_factory=list)


class CloudflarePerformanceCategoryOptionRead(BaseModel):
    slug: str
    name: str
    count: int = 0


class CloudflarePerformanceRowRead(BaseModel):
    channel_id: str
    channel_name: str
    category_slug: str | None = None
    category_name: str | None = None
    canonical_category_slug: str | None = None
    canonical_category_name: str | None = None
    title: str
    url: str | None = None
    published_at: str | None = None
    seo_score: float | None = None
    geo_score: float | None = None
    ctr: float | None = None
    lighthouse_score: float | None = None
    index_status: str = "unknown"
    live_image_count: int | None = None
    live_unique_image_count: int | None = None
    live_duplicate_image_count: int | None = None
    live_webp_count: int | None = None
    live_png_count: int | None = None
    live_other_image_count: int | None = None
    live_image_issue: str | None = None
    live_image_audited_at: str | None = None
    lighthouse_accessibility_score: float | None = None
    lighthouse_best_practices_score: float | None = None
    lighthouse_seo_score: float | None = None
    article_pattern_id: str | None = None
    article_pattern_version: int | None = None
    refactor_candidate: bool = False
    status: str
    quality_status: str | None = None


class CloudflarePerformanceSummaryRead(BaseModel):
    month: str
    channel_id: str
    channel_name: str
    total: int = 0
    low_score_count: int = 0
    refactor_candidate_count: int = 0
    lighthouse_below_70_count: int = 0
    available_categories: list[CloudflarePerformanceCategoryOptionRead] = Field(default_factory=list)
    available_statuses: list[str] = Field(default_factory=list)


class CloudflarePerformancePageRead(BaseModel):
    month: str
    total: int = 0
    page: int = 1
    page_size: int = 50
    summary: CloudflarePerformanceSummaryRead
    items: list[CloudflarePerformanceRowRead] = Field(default_factory=list)

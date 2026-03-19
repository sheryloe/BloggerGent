from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.entities import JobStatus, LogLevel, PostStatus, PublishMode, WorkflowStageType


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


class ArticleRead(BaseModel):
    id: int
    job_id: int
    blog_id: int
    topic_id: int | None = None
    title: str
    meta_description: str
    labels: list[str]
    slug: str
    excerpt: str
    html_article: str
    faq_section: list[dict]
    image_collage_prompt: str
    assembled_html: str | None = None
    reading_time_minutes: int
    created_at: datetime
    blog: BlogCompactRead | None = None
    image: ImageRead | None = None
    blogger_post: BloggerPostRead | None = None

    model_config = {"from_attributes": True}


class JobRead(BaseModel):
    id: int
    blog_id: int
    topic_id: int | None = None
    keyword_snapshot: str
    status: JobStatus
    publish_mode: PublishMode
    start_time: datetime | None = None
    end_time: datetime | None = None
    error_logs: list
    raw_prompts: dict
    raw_responses: dict
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    blog: BlogCompactRead | None = None
    topic: TopicRead | None = None
    article: ArticleRead | None = None
    image: ImageRead | None = None
    blogger_post: BloggerPostRead | None = None
    audit_logs: list[AuditLogRead] = []

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


class DiscoveryRunResponse(BaseModel):
    blog_id: int
    blog_name: str
    queued_topics: int
    job_ids: list[int]
    message: str
    stop_after_status: JobStatus | None = None


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


class OpenAIFreeUsageBucketRead(BaseModel):
    label: str
    limit_tokens: int
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
    synced_at: str | None = None


class SyncedBloggerPostPageRead(BaseModel):
    items: list[SyncedBloggerPostRead] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    last_synced_at: str | None = None


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


class BlogArchivePageRead(BaseModel):
    items: list[BlogArchiveItemRead] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    last_synced_at: datetime | None = None


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

export type JobStatus =
  | "PENDING"
  | "DISCOVERING_TOPICS"
  | "GENERATING_ARTICLE"
  | "GENERATING_IMAGE_PROMPT"
  | "GENERATING_IMAGE"
  | "ASSEMBLING_HTML"
  | "FINDING_RELATED_POSTS"
  | "PUBLISHING"
  | "STOPPED"
  | "COMPLETED"
  | "FAILED";

export type PublishMode = "draft" | "publish";
export type PostStatus = "draft" | "scheduled" | "published";
export type PublishQueueStatus = "queued" | "scheduled" | "processing" | "completed" | "failed" | "cancelled";

export type WorkflowStageType =
  | "topic_discovery"
  | "article_generation"
  | "image_prompt_generation"
  | "related_posts"
  | "image_generation"
  | "html_assembly"
  | "publishing"
  | "video_metadata_generation"
  | "thumbnail_generation"
  | "reel_packaging"
  | "platform_publish"
  | "performance_review"
  | "seo_rewrite"
  | "indexing_check";

export interface BlogCompact {
  id: number;
  name: string;
  slug: string;
  content_category: string;
}

export interface BloggerRemoteBlog {
  id: string;
  name: string;
  description?: string | null;
  url?: string | null;
  published?: string | null;
  updated?: string | null;
  locale?: Record<string, unknown> | null;
  posts_total_items?: number | null;
  pages_total_items?: number | null;
}

export interface BloggerRemotePost {
  id: string;
  title: string;
  url?: string | null;
  published?: string | null;
  updated?: string | null;
  labels: string[];
  status?: string | null;
  author_display_name?: string | null;
  replies_total_items: number;
}

export interface SyncedBloggerPost {
  id: string;
  title: string;
  url?: string | null;
  status?: string | null;
  published?: string | null;
  updated?: string | null;
  labels: string[];
  author_display_name?: string | null;
  replies_total_items: number;
  content_html: string;
  thumbnail_url?: string | null;
  excerpt_text: string;
  live_image_count?: number | null;
  live_unique_image_count?: number | null;
  live_duplicate_image_count?: number | null;
  live_webp_count?: number | null;
  live_png_count?: number | null;
  live_other_image_count?: number | null;
  live_cover_present?: boolean | null;
  live_inline_present?: boolean | null;
  live_image_issue?: string | null;
  live_image_audited_at?: string | null;
  synced_at?: string | null;
  seo_score?: number | null;
  geo_score?: number | null;
  lighthouse_score?: number | null;
  ctr?: number | null;
  index_status: string;
  index_coverage_state?: string | null;
  index_last_checked_at?: string | null;
  next_eligible_at?: string | null;
  last_error?: string | null;
}

export interface SyncedBloggerPostPage {
  items: SyncedBloggerPost[];
  total: number;
  page: number;
  page_size: number;
  last_synced_at?: string | null;
}

export interface SyncedBloggerPostGroup {
  blog_id: number;
  blog_name: string;
  blog_url?: string | null;
  total: number;
  last_synced_at?: string | null;
  items: SyncedBloggerPost[];
}

export interface SyncedBloggerPostGroupPage {
  groups: SyncedBloggerPostGroup[];
  total_groups: number;
}

export interface SearchConsoleSite {
  site_url: string;
  permission_level?: string | null;
}

export interface SearchConsoleRow {
  keys: string[];
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
}

export interface SearchConsolePerformance {
  site_url?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  totals: Record<string, number>;
  top_queries: SearchConsoleRow[];
  top_pages: SearchConsoleRow[];
}

export interface AnalyticsProperty {
  property_id: string;
  display_name: string;
  property_type?: string | null;
  parent_display_name?: string | null;
}

export interface AnalyticsOverview {
  property_id?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  totals: Record<string, number>;
  top_pages: Array<{
    page_path: string;
    screenPageViews: number;
    sessions: number;
  }>;
}

export interface BlogConnectionSummary {
  blogger?: BloggerRemoteBlog | null;
  search_console?: SearchConsoleSite | null;
  analytics?: AnalyticsProperty | null;
}

export interface WorkflowStep {
  id: number;
  agent_key: string;
  stage_type: WorkflowStageType;
  name: string;
  role_name: string;
  objective?: string | null;
  prompt_template: string;
  provider_hint?: string | null;
  provider_model?: string | null;
  is_enabled: boolean;
  is_required: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
  stage_label?: string | null;
  prompt_enabled: boolean;
  removable: boolean;
}

export interface Blog {
  id: number;
  name: string;
  slug: string;
  description?: string | null;
  content_category: string;
  primary_language: string;
  profile_key: string;
  target_audience?: string | null;
  content_brief?: string | null;
  blogger_blog_id?: string | null;
  blogger_url?: string | null;
  search_console_site_url?: string | null;
  ga4_property_id?: string | null;
  seo_theme_patch_installed: boolean;
  seo_theme_patch_verified_at?: string | null;
  target_reading_time_min_minutes: number;
  target_reading_time_max_minutes: number;
  publish_mode: PublishMode;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  workflow_steps: WorkflowStep[];
  user_visible_steps: WorkflowStep[];
  system_steps: WorkflowStep[];
  execution_path_labels: string[];
  selected_connections: BlogConnectionSummary;
  job_count: number;
  completed_jobs: number;
  failed_jobs: number;
  published_posts: number;
  latest_topic_keywords: string[];
  latest_published_url?: string | null;
}

export interface BlogImportProfile {
  key: string;
  label: string;
  description: string;
  content_category: string;
  primary_language: string;
  target_audience: string;
}

export interface BlogImportOptions {
  available_blogs: BloggerRemoteBlog[];
  profiles: BlogImportProfile[];
  imported_blogger_blog_ids: string[];
  warnings: string[];
}

export interface BlogConnectionOptions {
  blog_id: number;
  blogger_blog?: BloggerRemoteBlog | null;
  search_console_sites: SearchConsoleSite[];
  analytics_properties: AnalyticsProperty[];
  selected_search_console?: SearchConsoleSite | null;
  selected_analytics?: AnalyticsProperty | null;
  warnings: string[];
}

export interface Topic {
  id: number;
  blog_id: number;
  keyword: string;
  reason?: string | null;
  trend_score?: number | null;
  source: string;
  locale: string;
  topic_cluster_label?: string | null;
  topic_angle_label?: string | null;
  distinct_reason?: string | null;
  created_at: string;
  blog?: BlogCompact | null;
}

export interface TopicDiscoveryRunItem {
  keyword: string;
  reason?: string | null;
  trend_score?: number | null;
  status: "queued" | "skipped" | string;
  skip_reasons: string[];
  metadata: Record<string, string | null>;
}

export interface TopicDiscoveryRun {
  id: number;
  blog_id: number;
  provider: string;
  model?: string | null;
  prompt: string;
  raw_response: Record<string, unknown>;
  items: TopicDiscoveryRunItem[];
  queued_topics: number;
  skipped_topics: number;
  total_topics: number;
  job_ids: number[];
  created_at: string;
}

export interface AuditLog {
  id: number;
  level: "INFO" | "WARNING" | "ERROR";
  stage: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ImageAsset {
  id: number;
  prompt: string;
  file_path: string;
  public_url: string;
  width: number;
  height: number;
  provider: string;
  metadata: Record<string, unknown>;
}

export interface BloggerPost {
  id: number;
  blog_id: number;
  blogger_post_id: string;
  published_url: string;
  published_at?: string | null;
  is_draft: boolean;
  post_status: PostStatus;
  scheduled_for?: string | null;
}

export interface AIUsageEvent {
  id: number;
  stage_type: string;
  provider_mode: string;
  provider_name: string;
  provider_model?: string | null;
  endpoint: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd?: number | null;
  request_count: number;
  latency_ms?: number | null;
  image_count: number;
  image_width?: number | null;
  image_height?: number | null;
  success: boolean;
  error_message?: string | null;
  raw_usage: Record<string, unknown>;
  created_at: string;
}

export interface AIUsageSummary {
  event_count: number;
  total_requests: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  estimated_cost_usd?: number | null;
  by_stage: Record<string, Record<string, unknown>>;
}

export interface PublishQueueItem {
  id: number;
  article_id: number;
  blog_id: number;
  requested_mode: string;
  scheduled_for?: string | null;
  not_before: string;
  status: PublishQueueStatus;
  attempt_count: number;
  last_error?: string | null;
  response_payload: Record<string, unknown>;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PublishQueueSummary {
  id: number;
  article_id: number;
  blog_id: number;
  requested_mode: string;
  scheduled_for?: string | null;
  not_before: string;
  status: PublishQueueStatus;
  attempt_count: number;
  last_error?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ImageCompact {
  id: number;
  public_url: string;
  width: number;
  height: number;
}

export interface ArticleListItem {
  id: number;
  job_id: number;
  blog_id: number;
  topic_id?: number | null;
  title: string;
  meta_description: string;
  labels: string[];
  slug: string;
  excerpt: string;
  reading_time_minutes: number;
  article_pattern_id?: string | null;
  article_pattern_version?: number | null;
  editorial_category_key?: string | null;
  editorial_category_label?: string | null;
  created_at: string;
  updated_at?: string;
  blog?: BlogCompact | null;
  image?: ImageCompact | null;
  blogger_post?: BloggerPost | null;
  publish_queue?: PublishQueueSummary | null;
}

export interface ArticleDetail extends ArticleListItem {
  html_article: string;
  faq_section: Array<{ question: string; answer: string }>;
  image_collage_prompt: string;
  inline_media: Array<Record<string, unknown>>;
  assembled_html?: string | null;
  usage_events: AIUsageEvent[];
  usage_summary?: AIUsageSummary | null;
  publish_queue?: PublishQueueItem | null;
}

export type Article = ArticleDetail;

export interface BlogArchiveItem {
  source: "generated" | "synced";
  id: string;
  blog_id: number;
  title: string;
  excerpt: string;
  thumbnail_url?: string | null;
  labels: string[];
  published_url?: string | null;
  published_at?: string | null;
  scheduled_for?: string | null;
  updated_at?: string | null;
  status: string;
  content_html?: string | null;
  has_published_url: boolean;
  clickable: boolean;
  publish_state: "pending" | "draft" | "scheduled" | "published" | string;
  recovery_available: boolean;
  recovery_block_reason?: string | null;
  queue_status?: PublishQueueStatus | null;
  last_publish_error?: string | null;
  publish_status: "published" | "queued" | "scheduled" | "stopped" | "failed" | "pending" | string;
  remote_validation_status?: "ok" | "missing" | "error_view" | "feed_fallback" | "unknown" | string;
  remote_validation_message?: string | null;
  telegram_delivery_status?: "sent" | "failed" | "skipped" | string | null;
  telegram_error_message?: string | null;
  telegram_error_code?: number | null;
  telegram_response_text?: string | null;
}

export interface BlogArchivePage {
  items: BlogArchiveItem[];
  total: number;
  page: number;
  page_size: number;
  last_synced_at?: string | null;
}

export interface ArchiveChannel {
  channel_key: string;
  channel_label: string;
  provider: "blogger" | "cloudflare" | string;
  channel_id: string;
  channel_name: string;
  provider_status: string;
}

export interface ArchiveChannelItem {
  provider: "blogger" | "cloudflare" | string;
  channel_key: string;
  channel_label: string;
  channel_id: string;
  channel_name: string;
  provider_status: string;
  source: string;
  id: string;
  remote_id: string;
  blog_id?: number | null;
  title: string;
  excerpt: string;
  category_slug?: string | null;
  category_name?: string | null;
  thumbnail_url?: string | null;
  labels: string[];
  published_url?: string | null;
  published_at?: string | null;
  scheduled_for?: string | null;
  updated_at?: string | null;
  status: string;
  content_html?: string | null;
  has_published_url: boolean;
  clickable: boolean;
  publish_state: string;
  recovery_available: boolean;
  recovery_block_reason?: string | null;
  queue_status?: PublishQueueStatus | null;
  last_publish_error?: string | null;
  publish_status: string;
  remote_validation_status?: string | null;
  remote_validation_message?: string | null;
  telegram_delivery_status?: string | null;
  telegram_error_message?: string | null;
  telegram_error_code?: number | null;
  telegram_response_text?: string | null;
}

export interface ArchiveChannelPage {
  channel_key: string;
  channel_label: string;
  provider: "blogger" | "cloudflare" | string;
  channel_id: string;
  channel_name: string;
  provider_status: string;
  items: ArchiveChannelItem[];
  total: number;
  page: number;
  page_size: number;
  last_synced_at?: string | null;
  available_categories?: Array<{ slug: string; name: string; count: number }>;
  selected_category?: string | null;
}

export interface JobListItem {
  id: number;
  blog_id: number;
  topic_id?: number | null;
  keyword_snapshot: string;
  status: JobStatus;
  publish_mode: PublishMode;
  start_time?: string | null;
  end_time?: string | null;
  attempt_count: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
  blog?: BlogCompact | null;
  topic?: Topic | null;
  article?: ArticleListItem | null;
  image?: ImageCompact | null;
  blogger_post?: BloggerPost | null;
  publish_status: "published" | "queued" | "scheduled" | "stopped" | "failed" | "pending" | string;
  execution_status: JobStatus | string;
  telegram_delivery_status?: "sent" | "failed" | "skipped" | string | null;
  telegram_error_message?: string | null;
  telegram_error_code?: number | null;
  telegram_response_text?: string | null;
}

export interface JobDetail extends JobListItem {
  error_logs: Array<Record<string, unknown>>;
  raw_prompts: Record<string, unknown>;
  raw_responses: Record<string, unknown>;
  article?: ArticleDetail | null;
  image?: ImageAsset | null;
  audit_logs: AuditLog[];
}

export type Job = JobDetail;

export interface TelegramTestResult {
  delivery_status: "sent" | "failed" | "skipped" | string;
  chat_id?: string | null;
  message_id?: number | null;
  error_code?: number | null;
  error_message?: string | null;
  response_text?: string | null;
  skipped_reason?: string | null;
}

export interface TelegramPollNowRead {
  status: string;
  processed: number;
  ignored: number;
  reason?: string | null;
}

export interface TelegramSubscriptionsRead {
  chatId: string;
  subscriptions: Record<string, boolean>;
  updatedAt: string | null;
}

export interface TelegramTelemetryCommand {
  command: string;
  count: number;
}

export interface TelegramTelemetryRead {
  days: number;
  commandEvents: number;
  commandSuccess: number;
  commandFailed: number;
  deliveriesSent: number;
  deliveriesFailed: number;
  topCommands: TelegramTelemetryCommand[];
}

export interface HelpTopicRead {
  topicId: string;
  title: string;
  summary: string;
  tags: string[];
  relatedScreens: string[];
  commands: string[];
  deepLinks: string[];
  runbook: string | null;
}

export interface DashboardPoint {
  date: string;
  completed: number;
  failed: number;
}

export interface DashboardBlogSummary {
  blog_id: number;
  blog_name: string;
  blog_slug: string;
  content_category: string;
  completed_jobs: number;
  failed_jobs: number;
  queued_jobs: number;
  published_posts: number;
  latest_topic_keywords: string[];
  latest_published_url?: string | null;
}

export interface DashboardMetrics {
  today_generated_posts: number;
  success_jobs: number;
  failed_jobs: number;
  avg_processing_seconds: number;
  latest_published_links: BloggerPost[];
  jobs_by_status: Record<string, number>;
  processing_series: DashboardPoint[];
  blog_summaries: DashboardBlogSummary[];
  review_queue_count: number;
  high_risk_count: number;
  auto_fix_applied_today: number;
  learning_snapshot_age?: number | null;
}

export interface OpsHealthTokenBucket {
  used_tokens: number;
  limit_tokens: number;
  usage_percent: number;
  remaining_tokens: number;
  matched_models: string[];
}

export interface OpsHealthCloudflareReport {
  file: string;
  generated_at_utc: string;
  status: string;
  created_count: number;
  failed_count: number;
}

export interface OpsHealthJobItem {
  job_id: number;
  blog_id: number;
  blog_slug: string;
  keyword: string;
  ended_at_utc: string;
}

export interface OpsHealthSheetIssue {
  tab: string;
  columns: string[];
}

export interface OpsHealthReport {
  generated_at_kst: string;
  token_usage?: {
    date_label: string;
    window_start_utc: string;
    window_end_utc: string;
    large: OpsHealthTokenBucket;
    small: OpsHealthTokenBucket;
  } | null;
  token_error?: string;
  failed_jobs_last_24h: OpsHealthJobItem[];
  latest_cloudflare_reports: OpsHealthCloudflareReport[];
  sheet_issues?: {
    configured: boolean;
    sheet_id?: string;
    duplicates: OpsHealthSheetIssue[];
    english_columns: OpsHealthSheetIssue[];
    error?: string;
  };
  overall_status: string;
}

export interface OpsHealthLatestResponse {
  status: string;
  file_path: string;
  report: OpsHealthReport | null;
  recent_files: string[];
}

export interface ContentReviewAction {
  id: number;
  action: string;
  actor: string;
  channel: string;
  result_payload: Record<string, unknown>;
  created_at: string;
}

export interface ContentReviewItem {
  id: number;
  blog_id: number;
  source_type: string;
  source_id: string;
  source_title: string;
  source_url?: string | null;
  review_kind: string;
  content_hash: string;
  quality_score: number;
  risk_level: string;
  issues: Array<Record<string, unknown>>;
  proposed_patch: Record<string, unknown>;
  approval_status: string;
  apply_status: string;
  learning_state: string;
  source_updated_at?: string | null;
  last_reviewed_at?: string | null;
  last_applied_at?: string | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
  actions: ContentReviewAction[];
}

export interface ContentOverviewRow {
  article_id: number;
  blog_id: number;
  profile: string;
  blog: string;
  title: string;
  url: string;
  content_category?: string | null;
  category_key?: string | null;
  topic_cluster: string;
  topic_angle: string;
  similarity_score?: number | null;
  most_similar_url: string;
  seo_score?: number | null;
  geo_score?: number | null;
  media_state: string;
  quality_status: string;
  suggested_action: string;
  auto_fixable: boolean;
  manual_review: boolean;
  rewrite_attempts: number;
  status: string;
  published_at: string;
  updated_at: string;
  last_audited_at: string;
}

export interface ContentOverviewResponse {
  rows: ContentOverviewRow[];
  total: number;
  page: number;
  page_size: number;
  profile: string | null;
  published_only: boolean;
}

export interface ContentOverviewSyncPayload {
  profile?: string | null;
  published_only?: boolean;
  sync_sheet?: boolean;
}

export interface ContentOverviewSyncResult {
  sheet_id: string;
  tab: string;
  status: string;
  rows: number;
  columns: number;
}

export interface ContentOverviewRecalculateResult {
  profile?: string | null;
  published_only: boolean;
  updated_articles: number;
  total_articles: number;
  status: string;
}
export interface ContentOpsStatus {
  review_queue_count: number;
  high_risk_count: number;
  auto_fix_applied_today: number;
  learning_snapshot_age?: number | null;
  learning_paused: boolean;
  learning_snapshot_path: string;
  prompt_memory_path: string;
  recent_reviews: ContentReviewItem[];
}

export interface IntegratedChannelSummary {
  provider: "blogger" | "cloudflare" | string;
  channel_id: string;
  channel_name: string;
  provider_status: string;
  posts_count: number;
  categories_count: number;
  prompts_count: number;
  runs_count: number;
  site_title?: string | null;
  base_url?: string | null;
  error?: string | null;
}

export interface CloudflareCategory {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  status: string;
  scheduleTime: string;
  scheduleTimezone: string;
  createdAt: string;
  updatedAt: string;
}

export interface CloudflarePrompt {
  id: string;
  categoryId: string;
  categorySlug: string;
  categoryName: string;
  stage: string;
  currentVersion: number;
  content: string;
  createdAt: string;
  updatedAt: string;
}

export interface CloudflarePromptBundle {
  categories: CloudflareCategory[];
  templates: CloudflarePrompt[];
  stages: string[];
}

export interface IntegratedArchiveItem {
  provider: "blogger" | "cloudflare" | string;
  channel_id: string;
  channel_name: string;
  category_slug?: string | null;
  remote_id: string;
  provider_status: string;
  title: string;
  excerpt?: string | null;
  published_url?: string | null;
  thumbnail_url?: string | null;
  labels: string[];
  canonical_category_name?: string | null;
  canonical_category_slug?: string | null;
  seo_score?: number | null;
  geo_score?: number | null;
  ctr?: number | null;
  lighthouse_score?: number | null;
  live_image_count?: number | null;
  live_unique_image_count?: number | null;
  live_duplicate_image_count?: number | null;
  live_webp_count?: number | null;
  live_png_count?: number | null;
  live_other_image_count?: number | null;
  live_image_issue?: string | null;
  live_image_audited_at?: string | null;
  index_status?: string;
  index_coverage_state?: string | null;
  index_last_checked_at?: string | null;
  next_eligible_at?: string | null;
  last_error?: string | null;
  quality_status?: string | null;
  published_at?: string | null;
  updated_at?: string | null;
  status: string;
}

export interface IntegratedArchiveCategoryGroup {
  category_slug: string;
  category_name: string;
  total: number;
  last_synced_at?: string | null;
  items: IntegratedArchiveItem[];
}

export interface IntegratedRunItem {
  provider: "blogger" | "cloudflare" | string;
  channel_id: string;
  channel_name: string;
  remote_id: string;
  provider_status: string;
  title: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
  summary?: string | null;
  metadata: Record<string, unknown>;
}

export interface SettingItem {
  key: string;
  value: string;
  description?: string | null;
  is_secret: boolean;
}

export interface EnvSecretMaskedItemRead {
  key: string;
  maskedValue: string;
  sourceFile: string;
}

export interface IntegrationConnectionChannelRead {
  channelId: string;
  name: string;
  provider: string;
  status: string;
  isConnected: boolean;
}

export interface SettingsEnvSecretsStatusRead {
  checkedAt: string;
  envDir: string;
  secrets: EnvSecretMaskedItemRead[];
  connection: {
    state: "connected" | "disconnected";
    connected: number;
    total: number;
    channels: IntegrationConnectionChannelRead[];
  };
}

export interface SettingsEnvSecretSyncRead {
  checkedAt: string;
  updatedCount: number;
  updatedKeys: string[];
}

export interface TrainingSchedule {
  enabled: boolean;
  time: string;
  timezone: string;
}

export interface TrainingControlPayload {
  session_hours: number;
  save_every_minutes?: number | null;
}

export interface TrainingStatus {
  state: string;
  current_step: number;
  total_steps: number;
  loss?: number | null;
  elapsed_seconds: number;
  eta_seconds?: number | null;
  last_checkpoint?: string | null;
  next_scheduled_at?: string | null;
  last_error?: string | null;
  session_hours: number;
  save_every_minutes: number;
  pause_requested: boolean;
  run_id?: number | null;
  dataset_item_count: number;
  recent_logs: string[];
  schedule: TrainingSchedule;
  model_name?: string | null;
  data_scope: string;
}

export interface OpenAIFreeUsageBucket {
  label: string;
  limit_tokens: number;
  input_tokens: number;
  output_tokens: number;
  used_tokens: number;
  remaining_tokens: number;
  usage_percent: number;
  matched_models: string[];
}

export interface OpenAIFreeUsage {
  date_label: string;
  window_start_utc: string;
  window_end_utc: string;
  key_mode: string;
  admin_key_configured: boolean;
  large: OpenAIFreeUsageBucket;
  small: OpenAIFreeUsageBucket;
  warning?: string | null;
  hard_cap_enabled: boolean;
  blocked_due_to_usage_unavailable: boolean;
  blocked_due_to_usage_cap: boolean;
  warning_threshold_percent: number;
  hard_cap_threshold_percent: number;
  unexpected_text_api_call_count: number;
}

export interface PromptTemplate {
  key: string;
  title: string;
  description: string;
  file_name: string;
  placeholders: string[];
  content: string;
}

export interface SeoMetaStatus {
  key: string;
  label: string;
  status: "idle" | "ok" | "warning";
  actual?: string | null;
  expected?: string | null;
  message: string;
}

export interface BlogSeoMeta {
  blog_id: number;
  seo_theme_patch_installed: boolean;
  seo_theme_patch_verified: boolean;
  seo_theme_patch_verified_at?: string | null;
  verification_target_url?: string | null;
  expected_meta_description?: string | null;
  patch_snippet: string;
  patch_steps: string[];
  warnings: string[];
  head_meta_description_status: SeoMetaStatus;
  og_description_status: SeoMetaStatus;
  twitter_description_status: SeoMetaStatus;
}

export interface ArticleSeoMeta {
  article_id: number;
  blog_id: number;
  article_title: string;
  verification_target_url?: string | null;
  expected_meta_description?: string | null;
  warnings: string[];
  head_meta_description_status: SeoMetaStatus;
  og_description_status: SeoMetaStatus;
  twitter_description_status: SeoMetaStatus;
}

export interface ArticleSearchDescriptionSync {
  article_id: number;
  blogger_post_id: string;
  editor_url: string;
  cdp_url: string;
  description: string;
  status: string;
  message: string;
}

export interface BloggerPageview {
  range: string;
  count: number;
}

export interface GoogleBlogOverview {
  blog_id: number;
  blog_name: string;
  blogger_blog_id?: string | null;
  remote_blog?: BloggerRemoteBlog | null;
  pageviews: BloggerPageview[];
  recent_posts: BloggerRemotePost[];
  search_console?: SearchConsolePerformance | null;
  analytics?: AnalyticsOverview | null;
  warnings: string[];
}

export interface GoogleIntegrationConfig {
  oauth_scopes: string[];
  granted_scopes: string[];
  search_console_sites: SearchConsoleSite[];
  analytics_properties: AnalyticsProperty[];
  warnings: string[];
}

export interface GoogleIndexingActionResult {
  status: string;
  reason?: string | null;
  blogId: number;
  url: string;
  source?: string | null;
  siteUrl?: string | null;
  code?: string | null;
  indexStatus: string;
  indexCoverageState?: string | null;
  lastCrawlTime?: string | null;
  lastNotifyTime?: string | null;
  nextEligibleAt?: string | null;
  indexLastCheckedAt?: string | null;
  lastError?: string | null;
}

export interface GoogleBlogIndexingRefreshRead {
  status: string;
  blogId: number;
  requested: number;
  refreshed: number;
  failed: number;
  results: GoogleIndexingActionResult[];
}

export interface GoogleBlogIndexingTestRead {
  status: string;
  blogId: number;
  refresh: GoogleBlogIndexingRefreshRead;
  ctrCache: Record<string, unknown>;
}

export interface GoogleBlogIndexingRequestRead {
  status: string;
  reason?: string | null;
  blogId: number;
  requestedCount: number;
  plannedCount: number;
  candidateCount: number;
  attempted: number;
  success: number;
  failed: number;
  skipped: number;
  dailyQuota: number;
  remainingQuotaBefore: number;
  remainingQuotaAfter: number;
  runTest: boolean;
  test: Record<string, unknown>;
  results: GoogleIndexingActionResult[];
}

export interface GoogleBlogIndexingQuotaRead {
  dayKey: string;
  blogId: number;
  publishUsed: number;
  publishLimit: number;
  publishRemaining: number;
  inspectionUsed: number;
  inspectionLimit: number;
  inspectionRemaining: number;
  inspectionQpmLimit: number;
}

export interface GooglePlaywrightIndexingRequestRead {
  status: string;
  reason?: string | null;
  requestedCount: number;
  plannedCount: number;
  candidateCount: number;
  attempted: number;
  success: number;
  failed: number;
  skipped: number;
  results: GoogleIndexingActionResult[];
}

export interface GoogleIndexStatusRefreshRead {
  status: string;
  reason?: string | null;
  attempted: number;
  success: number;
  failed: number;
  skipped: number;
  results: GoogleIndexingActionResult[];
}

export interface BloggerConfig {
  client_name: string;
  client_id_configured: boolean;
  client_secret_configured: boolean;
  access_token_configured: boolean;
  refresh_token_configured: boolean;
  redirect_uri: string;
  default_publish_mode: string;
  connected: boolean;
  remote_loaded?: boolean;
  authorization_url?: string | null;
  authorization_error?: string | null;
  connection_error?: string | null;
  oauth_scopes: string[];
  granted_scopes: string[];
  available_blogs: BloggerRemoteBlog[];
  profiles: BlogImportProfile[];
  imported_blogger_blog_ids: string[];
  search_console_sites: SearchConsoleSite[];
  analytics_properties: AnalyticsProperty[];
  warnings: string[];
  blogs: Array<{
    id: number;
    name: string;
    blogger_blog_id: string;
    blogger_url?: string;
    search_console_site_url: string;
    ga4_property_id: string;
    publish_mode: PublishMode;
    is_active: boolean;
  }>;
}



export type BlogRead = Blog;
export type SettingRead = SettingItem;
export type BloggerConfigRead = BloggerConfig;

export interface ModelPolicyRead {
  large: string[];
  small: string[];
  deprecated: string[];
  defaults: Record<string, string>;
  text_runtime_kind: string;
  text_runtime_model: string;
  image_runtime_kind: string;
  image_runtime_model: string;
  openai_usage_hard_cap_enabled: boolean;
  unexpected_openai_text_calls: number;
  banned_text_model_prefixes: string[];
}

export interface PlannerCategoryRead {
  key: string;
  name: string;
  weight: number;
  color: string | null;
  sortOrder: number;
  isActive: boolean;
  planningMode: "auto" | "weekly" | "weekdays";
  weeklyTarget: number | null;
  weekdays: number[];
}

export interface PlannerSlotRead {
  id: number;
  planDayId: number;
  channelId: string;
  publishMode: string | null;
  themeId: number | null;
  themeKey: string | null;
  themeName: string | null;
  categoryKey: string | null;
  categoryName: string | null;
  categoryColor: string | null;
  scheduledFor: string | null;
  slotOrder: number;
  status: string;
  briefTopic: string | null;
  briefAudience: string | null;
  briefInformationLevel: string | null;
  briefExtraContext: string | null;
  articleId: number | null;
  jobId: number | null;
  errorMessage: string | null;
  lastRunAt: string | null;
  articleTitle: string | null;
  articleSeoScore: number | null;
  articleGeoScore: number | null;
  articleSimilarityScore: number | null;
  articleMostSimilarUrl: string | null;
  articleQualityStatus: string | null;
  articlePublishStatus: string | null;
  articlePublishedUrl: string | null;
  resultTitle: string | null;
  resultUrl: string | null;
  resultStatus: string | null;
  qualityGateStatus: string | null;
}

export interface PlannerDayRead {
  id: number;
  channelId: string;
  blogId: number | null;
  planDate: string;
  targetPostCount: number;
  status: string;
  slotCount: number;
  categoryMix: Record<string, number>;
  slots: PlannerSlotRead[];
}

export interface PlannerCalendarRead {
  channelId: string;
  channelName: string;
  channelProvider: string;
  blogId: number | null;
  month: string;
  categories: PlannerCategoryRead[];
  days: PlannerDayRead[];
}

export interface PlannerMonthPlanRequest {
  channelId: string;
  month: string;
  targetPostCount?: number | null;
  overwrite?: boolean;
}

export interface PlannerCategoryRuleUpdateRequest {
  categoryKey: string;
  planningMode: "auto" | "weekly" | "weekdays";
  weeklyTarget?: number | null;
  weekdays?: number[];
}

export interface PlannerSlotCreateRequest {
  planDayId: number;
  categoryKey: string;
  scheduledFor: string;
  briefTopic: string;
  briefAudience: string;
  briefInformationLevel?: string;
  briefExtraContext?: string;
}

export interface PlannerSlotUpdateRequest {
  categoryKey?: string | null;
  scheduledFor?: string | null;
  slotOrder?: number | null;
  briefTopic?: string | null;
  briefAudience?: string | null;
  briefInformationLevel?: string | null;
  briefExtraContext?: string | null;
  status?: string | null;
  errorMessage?: string | null;
}

export interface PlannerBriefSuggestion {
  slotId: number;
  slotOrder: number | null;
  categoryKey: string | null;
  topic: string | null;
  audience: string | null;
  informationLevel: string | null;
  extraContext: string | null;
  expectedCtrLift: string | null;
  confidence: number | null;
  signalSource: string | null;
  reason: string | null;
}

export interface PlannerBriefRun {
  id: number;
  planDayId: number;
  channelId: string;
  blogId: number | null;
  provider: string;
  model: string | null;
  prompt: string;
  rawResponse: Record<string, unknown>;
  slotSuggestions: PlannerBriefSuggestion[];
  status: string;
  errorMessage: string | null;
  appliedSlotIds: number[];
  createdAt: string;
  updatedAt: string;
}

export interface PlannerDayBriefAnalysisRequest {
  promptOverride?: string | null;
}

export interface PlannerDayBriefAnalysisResponse {
  run: PlannerBriefRun;
}

export interface PlannerBriefSuggestionInput {
  slotId: number;
  topic?: string | null;
  audience?: string | null;
  informationLevel?: string | null;
  extraContext?: string | null;
  expectedCtrLift?: string | null;
  confidence?: number | null;
  signalSource?: string | null;
  reason?: string | null;
}

export interface PlannerDayBriefApplyRequest {
  runId?: number | null;
  slotSuggestions?: PlannerBriefSuggestionInput[] | null;
}

export interface PlannerDayBriefApplyResponse {
  planDayId: number;
  appliedSlotIds: number[];
  skippedSlotIds: number[];
  runId: number | null;
  status: string;
}

export interface ManagedChannelRead {
  provider: string;
  channelId: string;
  name: string;
  isEnabled: boolean;
  status: string;
  baseUrl: string | null;
  primaryCategory: string | null;
  purpose: string | null;
  postsCount: number;
  categoriesCount: number;
  promptsCount: number;
  plannerSupported: boolean;
  analyticsSupported: boolean;
  promptFlowSupported: boolean;
  capabilities: string[];
  oauthState: string;
  quotaState: Record<string, string | number | boolean | null>;
  agentPackSummary: Array<Record<string, string | number | boolean | null>>;
  liveWorkerCount: number;
  pendingItems: number;
  failedItems: number;
  linkedBlogId?: number | null;
}

export interface ContentItemPublicationRecord {
  id: number;
  provider: string;
  remoteId: string | null;
  remoteUrl: string | null;
  targetState: string;
  publishStatus: string;
  errorCode: string | null;
  scheduledFor: string | null;
  publishedAt: string | null;
  responsePayload: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface ContentItemRead {
  id: number;
  managedChannelId: number;
  idempotencyKey: string;
  channelId: string;
  provider: string;
  blogId: number | null;
  jobId: number | null;
  sourceArticleId: number | null;
  contentType: "blog_article" | "youtube_video" | "instagram_image" | "instagram_reel" | string;
  lifecycleStatus: string;
  status: string;
  title: string;
  description: string;
  summary: string;
  bodyText: string;
  body: string;
  caption: string;
  assetManifest: Record<string, unknown>;
  briefPayload: Record<string, unknown>;
  reviewNotes: unknown[];
  approvalStatus: string;
  scheduledFor: string | null;
  lastFeedback: string | null;
  blockedReason: string | null;
  lastScore: Record<string, unknown>;
  createdByAgent: string | null;
  latestPublication: ContentItemPublicationRecord | null;
  createdAt: string;
  updatedAt: string;
}

export interface ContentItemCreatePayload {
  channelId: string;
  idempotencyKey?: string | null;
  contentType: "blog_article" | "youtube_video" | "instagram_image" | "instagram_reel" | string;
  title: string;
  description?: string;
  bodyText?: string;
  assetManifest?: Record<string, unknown>;
  briefPayload?: Record<string, unknown>;
  scheduledFor?: string | null;
  createdByAgent?: string | null;
}

export interface ContentItemUpdatePayload {
  lifecycleStatus?: string | null;
  title?: string | null;
  description?: string | null;
  bodyText?: string | null;
  approvalStatus?: string | null;
  assetManifest?: Record<string, unknown> | null;
  briefPayload?: Record<string, unknown> | null;
  reviewNotes?: unknown[] | null;
  scheduledFor?: string | null;
  lastFeedback?: string | null;
  blockedReason?: string | null;
  lastScore?: Record<string, unknown> | null;
}

export interface ContentItemDuplicateCheckPayload {
  provider: string;
  channelId: string;
  contentType: string;
  topic: string;
  title: string;
}

export interface ContentItemDuplicateMatchRead {
  id: number;
  title: string;
  channelId: string;
  provider: string;
  contentType: string;
  lifecycleStatus: string;
  similarityScore: number;
  matchedField: string;
  updatedAt: string;
}

export interface ContentItemDuplicateCheckRead {
  isDuplicate: boolean;
  riskLevel: "low" | "medium" | "high" | string;
  matchedItems: ContentItemDuplicateMatchRead[];
}

export interface AgentWorkerRead {
  id: number;
  managedChannelId: number | null;
  channelId: string | null;
  workerKey: string;
  runtimeKind: "claude_cli" | "codex_cli" | "gemini_cli" | string;
  displayName: string;
  roleName: string;
  roleKey: string;
  queueName: string;
  concurrencyLimit: number;
  status: string;
  configPayload: Record<string, unknown>;
  oauthSubject: string | null;
  lastHeartbeatAt: string | null;
  lastError: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface AgentRunRead {
  id: number;
  managedChannelId: number | null;
  channelId: string | null;
  contentItemId: number | null;
  workerId: number | null;
  agentWorkerId: number | null;
  runKey: string;
  runtimeKind: "claude_cli" | "codex_cli" | "gemini_cli" | string;
  assignedRole: string;
  roleKey: string;
  providerModel: string | null;
  status: string;
  priority: number;
  queuePriority: number;
  timeoutSeconds: number;
  retryCount: number;
  attemptCount: number;
  maxRetries: number;
  maxAttempts: number;
  startedAt: string | null;
  endedAt: string | null;
  promptSnapshot: string;
  responseSnapshot: string;
  logLines: unknown[];
  errorMessage: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface PlatformCredentialRead {
  id: number;
  managedChannelId: number | null;
  channelId: string | null;
  provider: string;
  credentialKey: string;
  subject: string | null;
  displayName: string | null;
  scopes: string[];
  accessTokenConfigured: boolean;
  refreshTokenConfigured: boolean;
  expiresAt: string | null;
  tokenType: string;
  isValid: boolean;
  lastError: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface PlatformIntegrationRead {
  provider: string;
  channelId: string;
  displayName: string;
  oauthState: string;
  status: string;
  scopeCount: number;
  expiresAt: string | null;
  isValid: boolean;
  lastError: string | null;
}

export interface WorkspaceIntegrationOverviewRead {
  channels: ManagedChannelRead[];
  integrations: PlatformIntegrationRead[];
  credentials: PlatformCredentialRead[];
}

export interface WorkspaceRuntimeUsageBucketRead {
  providerKey: string;
  label: string;
  requestCount: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  estimatedCostUsd: number;
  errorCount: number;
  lastEventAt: string | null;
  models: string[];
}

export interface WorkspaceRuntimeUsageTotalsRead {
  requestCount: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  estimatedCostUsd: number;
  errorCount: number;
  lastEventAt: string | null;
  models: string[];
}

export interface WorkspaceRuntimeUsageRead {
  generatedAt: string;
  days: number;
  providers: WorkspaceRuntimeUsageBucketRead[];
  totals: WorkspaceRuntimeUsageTotalsRead;
}

export interface SeoTargetRead {
  targetId: string;
  provider: string;
  channelId: string | null;
  blogId: number | null;
  label: string;
  baseUrl: string | null;
  linkedBlogId: number | null;
  searchConsoleSiteUrl: string | null;
  ga4PropertyId: string | null;
  oauthState: string;
  isConnected: boolean;
}

export interface AgentRuntimeHealthRead {
  totalWorkers: number;
  liveWorkers: number;
  queuedRuns: number;
  failedRuns: number;
  runtimeStatus: string;
  runtimes: Array<Record<string, string | number | boolean | null>>;
}

export interface MissionControlAlertRead {
  key: string;
  level: string;
  title: string;
  message: string;
}

export interface MissionControlRead {
  workspaceLabel: string;
  channels: ManagedChannelRead[];
  workers: AgentWorkerRead[];
  runs: AgentRunRead[];
  recentContent: ContentItemRead[];
  runtimeHealth: AgentRuntimeHealthRead;
  alerts: MissionControlAlertRead[];
}

export interface PromptFlowStepRead {
  id: string;
  channelId: string;
  provider: string;
  stageType: string;
  stageLabel: string;
  name: string;
  roleName: string | null;
  objective: string | null;
  promptTemplate: string;
  providerHint: string | null;
  providerModel: string | null;
  isEnabled: boolean;
  isRequired: boolean;
  removable: boolean;
  promptEnabled: boolean;
  editable: boolean;
  structureEditable: boolean;
  contentEditable: boolean;
  sortOrder: number;
  backupRelativePath: string | null;
  backupExists: boolean;
}

export interface PromptFlowRead {
  channelId: string;
  channelName: string;
  provider: string;
  structureEditable: boolean;
  contentEditable: boolean;
  availableStageTypes: string[];
  steps: PromptFlowStepRead[];
  backupDirectory: string | null;
}

export interface AnalyticsArticleFactRead {
  id: number;
  blogId: number;
  articleId: number | null;
  syncedPostId: number | null;
  publishedAt: string | null;
  title: string;
  themeKey: string | null;
  themeName: string | null;
  category: string | null;
  seoScore: number | null;
  geoScore: number | null;
  lighthouseScore: number | null;
  lighthouseAccessibilityScore: number | null;
  lighthouseBestPracticesScore: number | null;
  lighthouseSeoScore: number | null;
  similarityScore: number | null;
  mostSimilarUrl: string | null;
  articlePatternId: string | null;
  articlePatternVersion: number | null;
  status: string | null;
  actualUrl: string | null;
  sourceType: string;
  ctr: number | null;
  ctrScore: number | null;
  liveImageCount: number | null;
  liveUniqueImageCount: number | null;
  liveDuplicateImageCount: number | null;
  liveWebpCount: number | null;
  livePngCount: number | null;
  liveOtherImageCount: number | null;
  liveImageIssue: string | null;
  refactorCandidate: boolean;
  indexStatus: "indexed" | "submitted" | "pending" | "blocked" | "failed" | "unknown" | string;
  indexCoverageState: string | null;
  lastCrawlTime: string | null;
  lastNotifyTime: string | null;
  nextEligibleAt: string | null;
  indexLastCheckedAt: string | null;
  statusVariant: string;
  canManualDelete: boolean;
}

export interface AnalyticsThemeMonthlyStatRead {
  id: number;
  blogId: number;
  month: string;
  themeKey: string;
  themeName: string;
  plannedPosts: number;
  actualPosts: number;
  plannedShare: number;
  actualShare: number;
  gapShare: number;
  avgSeoScore: number | null;
  avgGeoScore: number | null;
  avgSimilarityScore: number | null;
  coverageGapScore: number;
  nextMonthWeightSuggestion: number;
}

export interface AnalyticsBlogMonthlySummaryRead {
  blogId: number;
  blogName: string;
  month: string;
  totalPosts: number;
  avgSeoScore: number | null;
  avgGeoScore: number | null;
  avgSimilarityScore: number | null;
  mostUnderusedThemeName: string | null;
  mostOverusedThemeName: string | null;
  nextMonthFocus: string | null;
}

export interface AnalyticsBlogMonthlyListResponse {
  month: string;
  items: AnalyticsBlogMonthlySummaryRead[];
}

export interface AnalyticsBlogMonthlyReportRead {
  blogId: number;
  blogName: string;
  month: string;
  totalPosts: number;
  avgSeoScore: number | null;
  avgGeoScore: number | null;
  avgSimilarityScore: number | null;
  mostUnderusedThemeName: string | null;
  mostOverusedThemeName: string | null;
  nextMonthFocus: string | null;
  reportSummary: string | null;
  themeStats: AnalyticsThemeMonthlyStatRead[];
  articleFacts: AnalyticsArticleFactRead[];
}

export interface AnalyticsDailySummaryRead {
  date: string;
  totalPosts: number;
  generatedPosts: number;
  syncedPosts: number;
  avgSeo: number | null;
  avgGeo: number | null;
}

export interface AnalyticsDailySummaryListResponse {
  blogId: number;
  month: string;
  items: AnalyticsDailySummaryRead[];
}

export interface AnalyticsArticleFactListResponse {
  blogId: number;
  month: string;
  total: number;
  page: number;
  pageSize: number;
  items: AnalyticsArticleFactRead[];
}

export interface AnalyticsThemeWeightApplyResponse {
  blogId: number;
  sourceMonth: string;
  targetMonth: string;
  appliedWeights: Record<string, number>;
}

export interface AnalyticsBackfillRead {
  blogMonths: number;
  generatedFacts: number;
  syncedFacts: number;
}

export interface AnalyticsThemeFilterOptionRead {
  key: string;
  name: string;
}

export interface AnalyticsIntegratedKpiRead {
  totalPosts: number;
  avgSeoScore: number | null;
  avgGeoScore: number | null;
  avgSimilarityScore: number | null;
  mostUnderusedThemeName: string | null;
  mostOverusedThemeName: string | null;
  recentUploadCount: number;
}

export interface AnalyticsIntegratedRead {
  month: string;
  range: string;
  selectedBlogId: number | null;
  kpis: AnalyticsIntegratedKpiRead;
  blogs: AnalyticsBlogMonthlySummaryRead[];
  report: AnalyticsBlogMonthlyReportRead | null;
  sourceType: string;
  themeKey: string | null;
  category: string | null;
  status: string | null;
  availableThemes: AnalyticsThemeFilterOptionRead[];
  availableCategories: string[];
}

export interface CloudflarePerformanceCategoryOptionRead {
  slug: string;
  name: string;
  count: number;
}

export interface CloudflarePerformanceRowRead {
  channelId: string;
  channelName: string;
  categorySlug: string | null;
  categoryName: string | null;
  canonicalCategorySlug: string | null;
  canonicalCategoryName: string | null;
  title: string;
  url: string | null;
  publishedAt: string | null;
  seoScore: number | null;
  geoScore: number | null;
  ctr: number | null;
  lighthouseScore: number | null;
  indexStatus: string;
  liveImageCount: number | null;
  liveUniqueImageCount: number | null;
  liveDuplicateImageCount: number | null;
  liveWebpCount: number | null;
  livePngCount: number | null;
  liveOtherImageCount: number | null;
  liveImageIssue: string | null;
  liveImageAuditedAt: string | null;
  lighthouseAccessibilityScore: number | null;
  lighthouseBestPracticesScore: number | null;
  lighthouseSeoScore: number | null;
  articlePatternId: string | null;
  articlePatternVersion: number | null;
  refactorCandidate: boolean;
  status: string;
  qualityStatus: string | null;
}

export interface CloudflarePerformanceSummaryRead {
  month: string;
  channelId: string;
  channelName: string;
  total: number;
  lowScoreCount: number;
  refactorCandidateCount: number;
  lighthouseBelow70Count: number;
  availableCategories: CloudflarePerformanceCategoryOptionRead[];
  availableStatuses: string[];
}

export interface CloudflarePerformancePageRead {
  month: string;
  total: number;
  page: number;
  pageSize: number;
  summary: CloudflarePerformanceSummaryRead;
  items: CloudflarePerformanceRowRead[];
}

export interface QmsCoverageRead {
  name: string;
  label: string;
  total: number;
  covered: number;
  missing: number;
  coverage_percent: number;
}

export interface QmsCurrentKpiRead {
  generated_at: string;
  published_total: number;
  seo_scored_count: number;
  geo_scored_count: number;
  ctr_scored_count: number;
  lighthouse_scored_count: number;
  indexed_count: number;
  not_indexed_count: number;
  unknown_index_count: number;
  search_console_ctr_count: number;
  quality_gate_pass_count: number;
  rewrite_required_count: number;
  manual_review_count: number;
  publish_success_count: number;
  status_breakdown: Record<string, number>;
  coverage: QmsCoverageRead[];
}

export interface QmsDocumentRead {
  id: number | null;
  document_key: string;
  title: string;
  phase: string;
  clause: string | null;
  owner: string | null;
  status: string;
  version: string;
  source_path: string | null;
  runtime_path: string | null;
  checksum_sha256: string | null;
  last_reviewed_at: string | null;
  next_review_due: string | null;
}

export interface QmsSummaryRead {
  total: number;
  open: number;
  overdue: number;
  closed: number;
  by_status: Record<string, number>;
}

export interface QmsKpiSnapshotRead {
  id: number;
  snapshot_key: string;
  period_start: string | null;
  period_end: string | null;
  published_total: number;
  seo_scored_count: number;
  geo_scored_count: number;
  ctr_scored_count: number;
  lighthouse_scored_count: number;
  indexed_count: number;
  not_indexed_count: number;
  unknown_index_count: number;
  search_console_ctr_count: number;
  quality_gate_pass_count: number;
  rewrite_required_count: number;
  manual_review_count: number;
  publish_success_count: number;
  status_breakdown: Record<string, number>;
  created_at: string;
  updated_at: string;
}

export interface QmsRiskRead {
  id: number;
  risk_key: string;
  title: string;
  category: string;
  phase: string;
  source: string;
  severity: number;
  occurrence: number;
  detection: number;
  rpn: number;
  status: string;
  owner: string | null;
  mitigation_plan: string | null;
  due_date: string | null;
  closed_at: string | null;
}

export interface QmsCapaRead {
  id: number;
  capa_key: string;
  title: string;
  source_type: string;
  source_id: string | null;
  problem_statement: string;
  root_cause: string | null;
  status: string;
  priority: string;
  owner: string | null;
  due_date: string | null;
  verified_at: string | null;
  actions: Array<{ id: number; title: string; status: string; action_type: string; owner: string | null; due_date: string | null }>;
}

export interface QmsChangeRead {
  id: number;
  change_key: string;
  title: string;
  change_type: string;
  risk_level: string;
  status: string;
  requester: string | null;
  approver: string | null;
  planned_at: string | null;
  approved_at: string | null;
  implemented_at: string | null;
  released_at: string | null;
}

export interface QmsReleaseRead {
  id: number;
  release_key: string;
  title: string;
  status: string;
  branch: string | null;
  commit_hash: string | null;
  pushed: boolean;
  alembic_revision: string | null;
  test_summary: string | null;
  evidence_path: string | null;
  released_at: string | null;
}

export interface QmsSupplierRead {
  id: number;
  supplier_key: string;
  name: string;
  supplier_type: string;
  status: string;
  risk_level: string;
  service_scope: string | null;
  data_access_level: string;
  owner: string | null;
  review_cycle_days: number;
  last_reviewed_at: string | null;
  next_review_due: string | null;
}

export interface QmsAuditRead {
  id: number;
  audit_key: string;
  title: string;
  scope: string | null;
  status: string;
  auditor: string | null;
  scheduled_at: string | null;
  completed_at: string | null;
  findings: Array<{ id: number; title: string; severity: string; status: string; clause: string | null; owner: string | null; due_date: string | null }>;
}

export interface QmsManagementReviewRead {
  id: number;
  review_key: string;
  title: string;
  period_start: string | null;
  period_end: string | null;
  status: string;
  chair: string | null;
  scheduled_at: string | null;
  completed_at: string | null;
}

export interface QmsEvidenceRead {
  id: number;
  evidence_key: string;
  evidence_type: string;
  title: string;
  source_path: string | null;
  runtime_path: string | null;
  checksum_sha256: string | null;
  file_size: number | null;
  modified_at: string | null;
  status: string;
  captured_at: string | null;
}

export interface QmsRuntimeScanRead {
  id: number;
  scan_key: string;
  status: string;
  runtime_root: string;
  scanned_paths: string[];
  file_count: number;
  evidence_count: number;
  secrets_masked_count: number;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface QmsDashboardRead {
  generated_at: string;
  documents: QmsDocumentRead[];
  current_kpi: QmsCurrentKpiRead;
  latest_snapshot: QmsKpiSnapshotRead | null;
  risk_summary: QmsSummaryRead;
  capa_summary: QmsSummaryRead;
  change_summary: QmsSummaryRead;
  release_summary: QmsSummaryRead;
  supplier_summary: QmsSummaryRead;
  audit_summary: QmsSummaryRead;
  review_summary: QmsSummaryRead;
  runtime_summary: Record<string, any>;
  recent_evidence: QmsEvidenceRead[];
}

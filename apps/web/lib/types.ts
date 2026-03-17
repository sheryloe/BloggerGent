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

export type WorkflowStageType =
  | "topic_discovery"
  | "article_generation"
  | "image_prompt_generation"
  | "related_posts"
  | "image_generation"
  | "html_assembly"
  | "publishing";

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
  synced_at?: string | null;
}

export interface SyncedBloggerPostPage {
  items: SyncedBloggerPost[];
  total: number;
  page: number;
  page_size: number;
  last_synced_at?: string | null;
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

export interface Article {
  id: number;
  job_id: number;
  blog_id: number;
  topic_id?: number | null;
  title: string;
  meta_description: string;
  labels: string[];
  slug: string;
  excerpt: string;
  html_article: string;
  faq_section: Array<{ question: string; answer: string }>;
  image_collage_prompt: string;
  assembled_html?: string | null;
  reading_time_minutes: number;
  created_at: string;
  updated_at?: string;
  blog?: BlogCompact | null;
  image?: ImageAsset | null;
  blogger_post?: BloggerPost | null;
}

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
}

export interface BlogArchivePage {
  items: BlogArchiveItem[];
  total: number;
  page: number;
  page_size: number;
  last_synced_at?: string | null;
}

export interface Job {
  id: number;
  blog_id: number;
  topic_id?: number | null;
  keyword_snapshot: string;
  status: JobStatus;
  publish_mode: PublishMode;
  start_time?: string | null;
  end_time?: string | null;
  error_logs: Array<Record<string, unknown>>;
  raw_prompts: Record<string, unknown>;
  raw_responses: Record<string, unknown>;
  attempt_count: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
  blog?: BlogCompact | null;
  topic?: Topic | null;
  article?: Article | null;
  image?: ImageAsset | null;
  blogger_post?: BloggerPost | null;
  audit_logs: AuditLog[];
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
}

export interface SettingItem {
  key: string;
  value: string;
  description?: string | null;
  is_secret: boolean;
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

export interface BloggerConfig {
  client_name: string;
  client_id_configured: boolean;
  client_secret_configured: boolean;
  access_token_configured: boolean;
  refresh_token_configured: boolean;
  redirect_uri: string;
  default_publish_mode: string;
  connected: boolean;
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

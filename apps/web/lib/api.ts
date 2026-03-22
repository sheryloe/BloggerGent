import "server-only";

import {
  Article,
  ArchiveChannel,
  ArchiveChannelPage,
  BlogArchivePage,
  ArticleSeoMeta,
  Blog,
  BlogImportOptions,
  BlogSeoMeta,
  BloggerConfig,
  DashboardMetrics,
  GoogleBlogOverview,
  GoogleIntegrationConfig,
  IntegratedArchiveItem,
  IntegratedChannelSummary,
  IntegratedRunItem,
  Job,
  OpenAIFreeUsage,
  CloudflarePromptBundle,
  PromptTemplate,
  SettingItem,
  TrainingControlPayload,
  TrainingSchedule,
  TrainingStatus,
  SyncedBloggerPostPage,
  TelegramTestResult,
  Topic
} from "@/lib/types";

function resolveBaseUrl() {
  return process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${resolveBaseUrl()}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    throw new Error(`API request failed for ${path}: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function getDashboardMetrics(blogId?: number) {
  const query = blogId ? `?blog_id=${blogId}` : "";
  return apiFetch<DashboardMetrics>(`/dashboard${query}`);
}

export async function getBlogs() {
  return apiFetch<Blog[]>("/blogs");
}

export async function updateBlog(blogId: number, payload: {
  name: string;
  description?: string | null;
  content_category: string;
  primary_language: string;
  target_audience?: string | null;
  content_brief?: string | null;
  target_reading_time_min_minutes: number;
  target_reading_time_max_minutes: number;
  publish_mode: "draft" | "publish";
  is_active: boolean;
}) {
  return apiFetch<Blog>(`/blogs/${blogId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function getBlogImportOptions() {
  return apiFetch<BlogImportOptions>("/blogs/import-options");
}

export async function getJobs(blogId?: number) {
  const query = blogId ? `?blog_id=${blogId}` : "";
  return apiFetch<Job[]>(`/jobs${query}`);
}

export async function getArticles(blogId?: number) {
  const query = blogId ? `?blog_id=${blogId}` : "";
  return apiFetch<Article[]>(`/articles${query}`);
}

export async function getArticle(articleId: number) {
  return apiFetch<Article>(`/articles/${articleId}`);
}

export async function getArticleSeoMeta(articleId: number) {
  return apiFetch<ArticleSeoMeta>(`/articles/${articleId}/seo-meta`);
}

export async function getBlogArchive(blogId: number, page = 1, pageSize = 20) {
  return apiFetch<BlogArchivePage>(`/blogs/${blogId}/archive?page=${page}&page_size=${pageSize}`);
}

export async function getArchiveChannels() {
  const response = await apiFetch<{ items: ArchiveChannel[] }>("/archive/channels");
  return response.items;
}

export async function getArchiveChannelPage(channelKey: string, page = 1, pageSize = 24, category?: string) {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (category) {
    query.set("category", category);
  }
  return apiFetch<ArchiveChannelPage>(
    `/archive/channel/${encodeURIComponent(channelKey)}?${query.toString()}`,
  );
}

export async function getSettings() {
  return apiFetch<SettingItem[]>("/settings");
}

export async function getTrainingStatus() {
  return apiFetch<TrainingStatus>("/training/status");
}

export async function startTraining(payload: TrainingControlPayload) {
  return apiFetch<TrainingStatus>("/training/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function pauseTraining() {
  return apiFetch<TrainingStatus>("/training/pause", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function resumeTraining(payload: TrainingControlPayload) {
  return apiFetch<TrainingStatus>("/training/resume", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateTrainingSchedule(payload: TrainingSchedule) {
  return apiFetch<TrainingStatus>("/training/schedule", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function testTelegram(message?: string) {
  return apiFetch<TelegramTestResult>("/telegram/test", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export async function getOpenAIFreeUsage() {
  return apiFetch<OpenAIFreeUsage>("/settings/openai-free-usage");
}

export async function getTopics(blogId?: number) {
  const query = blogId ? `?blog_id=${blogId}` : "";
  return apiFetch<Topic[]>(`/topics${query}`);
}

export async function getPrompts() {
  return apiFetch<PromptTemplate[]>("/prompts");
}

export async function getBloggerConfig() {
  return apiFetch<BloggerConfig>("/blogger/config");
}

export async function getCloudflareOverview() {
  return apiFetch<IntegratedChannelSummary>("/cloudflare/overview");
}

export async function getCloudflarePosts() {
  return apiFetch<IntegratedArchiveItem[]>("/cloudflare/posts");
}

export async function getCloudflareRuns() {
  return apiFetch<IntegratedRunItem[]>("/cloudflare/runs");
}

export async function getCloudflarePrompts() {
  return apiFetch<CloudflarePromptBundle>("/cloudflare/prompts");
}

export async function updateCloudflarePrompt(category: string, stage: string, content: string) {
  return apiFetch(`/cloudflare/prompts/${category}/${stage}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export async function getGoogleIntegrations() {
  return apiFetch<GoogleIntegrationConfig>("/google/integrations");
}

export async function getGoogleBlogOverview(blogId: number, days = 28) {
  return apiFetch<GoogleBlogOverview>(`/google/blogs/${blogId}/overview?days=${days}`);
}

export async function getSyncedBloggerPosts(blogId: number, page = 1, pageSize = 20) {
  return apiFetch<SyncedBloggerPostPage>(
    `/google/blogs/${blogId}/synced-posts?page=${page}&page_size=${pageSize}`,
  );
}

export async function getBlogSeoMeta(blogId: number) {
  return apiFetch<BlogSeoMeta>(`/blogs/${blogId}/seo-meta`);
}

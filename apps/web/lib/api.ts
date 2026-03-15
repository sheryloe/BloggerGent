import "server-only";

import {
  Article,
  Blog,
  BlogImportOptions,
  BloggerConfig,
  DashboardMetrics,
  GoogleBlogOverview,
  GoogleIntegrationConfig,
  Job,
  PromptTemplate,
  SettingItem,
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

export async function getSettings() {
  return apiFetch<SettingItem[]>("/settings");
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

export async function getGoogleIntegrations() {
  return apiFetch<GoogleIntegrationConfig>("/google/integrations");
}

export async function getGoogleBlogOverview(blogId: number, days = 28) {
  return apiFetch<GoogleBlogOverview>(`/google/blogs/${blogId}/overview?days=${days}`);
}

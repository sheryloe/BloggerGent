import {
  ArchiveChannel,
  ArchiveChannelPage,
  BlogArchivePage,
  ArticleSeoMeta,
  ArticleDetail,
  ArticleListItem,
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
  JobDetail,
  JobListItem,
  OpsHealthLatestResponse,
  OpenAIFreeUsage,
  CloudflarePromptBundle,
  ContentOpsStatus,
  ContentReviewItem,
  ContentOverviewRecalculateResult,
  ContentOverviewResponse,
  ContentOverviewSyncPayload,
  ContentOverviewSyncResult,
  PromptTemplate,
  SettingItem,
  AnalyticsBackfillRead,
  AnalyticsDailySummaryListResponse,
  AnalyticsBlogMonthlySummaryRead,
  AnalyticsIntegratedRead,
  AgentRunRead,
  AgentRuntimeHealthRead,
  AgentWorkerRead,
  ContentItemRead,
  ManagedChannelRead,
  MissionControlRead,
  ModelPolicyRead,
  PlannerCalendarRead,
  PlannerCategoryRead,
  PlatformCredentialRead,
  PlannerMonthPlanRequest,
  PromptFlowRead,
  PlannerSlotCreateRequest,
  PlannerSlotRead,
  PlannerSlotUpdateRequest,
  AnalyticsArticleFactListResponse,
  AnalyticsBlogMonthlyListResponse,
  AnalyticsBlogMonthlyReportRead,
  AnalyticsThemeWeightApplyResponse,
  TrainingControlPayload,
  TrainingSchedule,
  TrainingStatus,
  SyncedBloggerPostPage,
  TelegramTestResult,
  Topic,
} from "@/lib/types";

function resolveBaseUrl() {
  return process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
}

type ApiFetchOptions = RequestInit & {
  revalidate?: number | false;
};

async function apiFetch<T>(path: string, init?: ApiFetchOptions): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const revalidate = init?.revalidate;
  const fetchInit: RequestInit & { next?: { revalidate?: number | false } } = {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  };

  if (!init?.cache) {
    if (method === "GET") {
      if (revalidate === false) {
        fetchInit.cache = "no-store";
      } else {
        fetchInit.next = { revalidate: typeof revalidate === "number" ? revalidate : 30 };
      }
    } else {
      fetchInit.cache = "no-store";
    }
  }

  const response = await fetch(`${resolveBaseUrl()}${path}`, fetchInit);
  if (!response.ok) {
    throw new Error(`API request failed for ${path}: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getDashboardMetrics(blogId?: number) {
  const query = blogId ? `?blog_id=${blogId}` : "";
  return apiFetch<DashboardMetrics>(`/dashboard${query}`);
}

export async function getContentOpsStatus() {
  return apiFetch<ContentOpsStatus>("/content-ops/status");
}

export async function getContentOpsReviews(blogId?: number, limit = 50) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (blogId) {
    query.set("blog_id", String(blogId));
  }
  return apiFetch<ContentReviewItem[]>(`/content-ops/reviews?${query.toString()}`);
}

export async function getContentOverview(
  profile?: string | null,
  publishedOnly = false,
  page = 1,
  pageSize = 50,
) {
  const query = new URLSearchParams();
  if (profile) {
    query.set("profile", profile);
  }
  if (publishedOnly) {
    query.set("published_only", "true");
  }
  query.set("page", String(page));
  query.set("page_size", String(pageSize));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<ContentOverviewResponse>(`/content-ops/overview${suffix}`, { revalidate: 30 });
}

export async function syncContentOverview(payload: ContentOverviewSyncPayload = {}) {
  return apiFetch<ContentOverviewSyncResult>("/content-ops/overview/sync", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function recalculateContentOverview(payload: ContentOverviewSyncPayload = {}) {
  return apiFetch<ContentOverviewRecalculateResult>("/content-ops/overview/recalculate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getBlogs() {
  return apiFetch<Blog[]>("/blogs");
}

export async function updateBlog(
  blogId: number,
  payload: {
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
  },
) {
  return apiFetch<Blog>(`/blogs/${blogId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function getBlogImportOptions() {
  return apiFetch<BlogImportOptions>("/blogs/import-options");
}

export async function getJobs(blogId?: number, limit = 30) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (blogId) {
    query.set("blog_id", String(blogId));
  }
  return apiFetch<JobListItem[]>(`/jobs?${query.toString()}`, { revalidate: 5 });
}

export async function getJob(jobId: number) {
  return apiFetch<JobDetail>(`/jobs/${jobId}`, { revalidate: false });
}

export async function getArticles(blogId?: number, limit = 20) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (blogId) {
    query.set("blog_id", String(blogId));
  }
  return apiFetch<ArticleListItem[]>(`/articles?${query.toString()}`, { revalidate: 5 });
}

export async function getArticle(articleId: number) {
  return apiFetch<ArticleDetail>(`/articles/${articleId}`, { revalidate: false });
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
  return apiFetch<ArchiveChannelPage>(`/archive/channel/${encodeURIComponent(channelKey)}?${query.toString()}`);
}

export async function getSettings() {
  return apiFetch<SettingItem[]>("/settings", { revalidate: false });
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

export async function getOpsHealthLatest() {
  return apiFetch<OpsHealthLatestResponse>("/admin/ops-health/latest", { revalidate: false });
}

export async function getTopics(blogId?: number) {
  const query = blogId ? `?blog_id=${blogId}` : "";
  return apiFetch<Topic[]>(`/topics${query}`);
}

export async function getPrompts() {
  return apiFetch<PromptTemplate[]>("/prompts");
}

export async function getBloggerConfig(includeRemote = false) {
  const search = new URLSearchParams();
  if (includeRemote) {
    search.set("include_remote", "true");
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiFetch<BloggerConfig>(`/blogger/config${suffix}`);
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
  return apiFetch<SyncedBloggerPostPage>(`/google/blogs/${blogId}/synced-posts?page=${page}&page_size=${pageSize}`);
}

export async function getBlogSeoMeta(blogId: number) {
  return apiFetch<BlogSeoMeta>(`/blogs/${blogId}/seo-meta`);
}


function mapPlannerCategory(item: any): PlannerCategoryRead {
  return {
    key: item.key,
    name: item.name,
    weight: item.weight,
    color: item.color ?? null,
    sortOrder: item.sort_order,
    isActive: item.is_active,
  };
}

function mapPlannerSlot(item: any): PlannerSlotRead {
  return {
    id: item.id,
    planDayId: item.plan_day_id,
    channelId: item.channel_id,
    publishMode: item.publish_mode ?? null,
    themeId: item.theme_id ?? null,
    themeKey: item.theme_key ?? null,
    themeName: item.theme_name ?? null,
    categoryKey: item.category_key ?? item.theme_key ?? null,
    categoryName: item.category_name ?? item.theme_name ?? null,
    categoryColor: item.category_color ?? null,
    scheduledFor: item.scheduled_for ?? null,
    slotOrder: item.slot_order,
    status: item.status,
    briefTopic: item.brief_topic ?? null,
    briefAudience: item.brief_audience ?? null,
    briefInformationLevel: item.brief_information_level ?? null,
    briefExtraContext: item.brief_extra_context ?? null,
    articleId: item.article_id ?? null,
    jobId: item.job_id ?? null,
    errorMessage: item.error_message ?? null,
    lastRunAt: item.last_run_at ?? null,
    articleTitle: item.article_title ?? null,
    articleSeoScore: item.article_seo_score ?? null,
    articleGeoScore: item.article_geo_score ?? null,
    articleSimilarityScore: item.article_similarity_score ?? null,
    articleMostSimilarUrl: item.article_most_similar_url ?? null,
    articleQualityStatus: item.article_quality_status ?? null,
    articlePublishStatus: item.article_publish_status ?? null,
    articlePublishedUrl: item.article_published_url ?? null,
    resultTitle: item.result_title ?? null,
    resultUrl: item.result_url ?? null,
    resultStatus: item.result_status ?? null,
    qualityGateStatus: item.quality_gate_status ?? null,
  };
}

function mapPlannerCalendar(payload: any): PlannerCalendarRead {
  return {
    channelId: payload.channel_id,
    channelName: payload.channel_name,
    channelProvider: payload.channel_provider,
    blogId: payload.blog_id ?? null,
    month: payload.month,
    categories: (payload.categories ?? []).map(mapPlannerCategory),
    days: (payload.days ?? []).map((day: any) => ({
      id: day.id,
      channelId: day.channel_id,
      blogId: day.blog_id ?? null,
      planDate: day.plan_date,
      targetPostCount: day.target_post_count,
      status: day.status,
      slotCount: day.slot_count,
      categoryMix: day.category_mix ?? {},
      slots: (day.slots ?? []).map(mapPlannerSlot),
    })),
  };
}

function mapManagedChannel(item: any): ManagedChannelRead {
  return {
    provider: item.provider,
    channelId: item.channel_id,
    name: item.name,
    status: item.status,
    baseUrl: item.base_url ?? null,
    primaryCategory: item.primary_category ?? null,
    purpose: item.purpose ?? null,
    postsCount: item.posts_count ?? 0,
    categoriesCount: item.categories_count ?? 0,
    promptsCount: item.prompts_count ?? 0,
    plannerSupported: item.planner_supported ?? false,
    analyticsSupported: item.analytics_supported ?? false,
    promptFlowSupported: item.prompt_flow_supported ?? false,
    capabilities: item.capabilities ?? [],
    oauthState: item.oauth_state ?? "unknown",
    quotaState: item.quota_state ?? {},
    agentPackSummary: item.agent_pack_summary ?? [],
    liveWorkerCount: item.live_worker_count ?? 0,
    pendingItems: item.pending_items ?? 0,
    failedItems: item.failed_items ?? 0,
    linkedBlogId: item.linked_blog_id ?? null,
  };
}

function mapContentItem(item: any): ContentItemRead {
  return {
    id: item.id,
    managedChannelId: item.managed_channel_id,
    channelId: item.channel_id ?? "",
    provider: item.provider ?? "",
    blogId: item.blog_id ?? null,
    jobId: item.job_id ?? null,
    sourceArticleId: item.source_article_id ?? null,
    contentType: item.content_type,
    lifecycleStatus: item.lifecycle_status ?? item.status ?? "draft",
    status: item.lifecycle_status ?? item.status ?? "draft",
    title: item.title ?? "",
    description: item.description ?? "",
    summary: item.description ?? "",
    bodyText: item.body_text ?? "",
    body: item.body_text ?? "",
    caption: item.brief_payload?.caption ?? item.description ?? "",
    assetManifest: item.asset_manifest ?? {},
    briefPayload: item.brief_payload ?? {},
    reviewNotes: item.review_notes ?? [],
    approvalStatus: item.approval_status ?? "pending",
    scheduledFor: item.scheduled_for ?? null,
    lastFeedback: item.last_feedback ?? null,
    lastScore: item.last_score ?? {},
    createdByAgent: item.created_by_agent ?? null,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  };
}

function mapAgentWorker(item: any): AgentWorkerRead {
  return {
    id: item.id,
    managedChannelId: item.managed_channel_id ?? null,
    channelId: item.channel_id ?? null,
    workerKey: item.worker_key,
    runtimeKind: item.runtime_kind,
    displayName: item.display_name,
    roleName: item.role_name ?? "",
    roleKey: item.role_name ?? "",
    queueName: item.queue_name ?? "default",
    concurrencyLimit: item.concurrency_limit ?? 1,
    status: item.status,
    configPayload: item.config_payload ?? {},
    oauthSubject: (item.config_payload?.oauth_subject as string | undefined) ?? null,
    lastHeartbeatAt: item.last_heartbeat_at ?? null,
    lastError: item.last_error ?? null,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  };
}

function mapAgentRun(item: any): AgentRunRead {
  return {
    id: item.id,
    managedChannelId: item.managed_channel_id ?? null,
    channelId: item.channel_id ?? null,
    contentItemId: item.content_item_id ?? null,
    workerId: item.worker_id ?? null,
    agentWorkerId: item.worker_id ?? null,
    runKey: item.run_key,
    runtimeKind: item.runtime_kind,
    assignedRole: item.assigned_role ?? "",
    roleKey: item.assigned_role ?? "",
    providerModel: item.provider_model ?? null,
    status: item.status,
    priority: item.priority ?? 50,
    queuePriority: item.priority ?? 50,
    timeoutSeconds: item.timeout_seconds ?? 900,
    retryCount: item.retry_count ?? 0,
    attemptCount: item.retry_count ?? 0,
    maxRetries: item.max_retries ?? 3,
    maxAttempts: item.max_retries ?? 3,
    startedAt: item.started_at ?? null,
    endedAt: item.ended_at ?? null,
    promptSnapshot: item.prompt_snapshot ?? "",
    responseSnapshot: item.response_snapshot ?? "",
    logLines: item.log_lines ?? [],
    errorMessage: item.error_message ?? null,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  };
}

function mapPlatformCredential(item: any): PlatformCredentialRead {
  return {
    id: item.id,
    managedChannelId: item.managed_channel_id ?? null,
    channelId: item.channel_id ?? null,
    provider: item.provider,
    credentialKey: item.credential_key ?? "",
    subject: item.subject ?? null,
    displayName: item.subject ?? null,
    scopes: item.scopes ?? [],
    accessTokenConfigured: item.access_token_configured ?? false,
    refreshTokenConfigured: item.refresh_token_configured ?? false,
    expiresAt: item.expires_at ?? null,
    tokenType: item.token_type ?? "Bearer",
    isValid: item.is_valid ?? false,
    lastError: item.last_error ?? null,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  };
}

function mapAgentRuntimeHealth(item: any): AgentRuntimeHealthRead {
  const workerStatus = item?.worker_status ?? {};
  const runStatus = item?.run_status ?? {};
  const failedRuns = Number(runStatus.failed ?? 0);
  const queuedRuns = Number(runStatus.queued ?? 0);
  const liveWorkers = Number(workerStatus.running ?? 0) + Number(workerStatus.busy ?? 0);
  const runtimeStatus = item?.healthy ? "healthy" : failedRuns > 0 ? "error" : queuedRuns > 0 ? "busy" : "standby";

  return {
    totalWorkers: item?.worker_count ?? 0,
    liveWorkers,
    queuedRuns,
    failedRuns,
    runtimeStatus,
    runtimes: (item?.runtime_kinds ?? []).map((runtimeKind: string) => ({
      runtimeKind,
      label: runtimeKind,
      active: runtimeStatus !== "standby",
    })),
  };
}

function mapMissionControl(payload: any): MissionControlRead {
  return {
    workspaceLabel: payload.workspace_label ?? "Bloggent Mission Control",
    channels: (payload.channels ?? []).map(mapManagedChannel),
    workers: (payload.workers ?? []).map(mapAgentWorker),
    runs: (payload.runs ?? []).map(mapAgentRun),
    recentContent: (payload.recent_content ?? []).map(mapContentItem),
    runtimeHealth: mapAgentRuntimeHealth(payload.runtime_health ?? {}),
    alerts: (payload.alerts ?? []).map((item: any) => ({
      key: item.key,
      level: item.level,
      title: item.title,
      message: item.message,
    })),
  };
}

export async function getMissionControl() {
  const payload = await apiFetch<any>("/workspace/mission-control", { revalidate: false });
  return mapMissionControl(payload);
}

function mapPromptFlow(payload: any): PromptFlowRead {
  return {
    channelId: payload.channel_id,
    channelName: payload.channel_name,
    provider: payload.provider,
    structureEditable: payload.structure_editable ?? true,
    contentEditable: payload.content_editable ?? true,
    availableStageTypes: payload.available_stage_types ?? [],
    steps: (payload.steps ?? []).map((item: any) => ({
      id: item.id,
      channelId: item.channel_id,
      provider: item.provider,
      stageType: item.stage_type,
      stageLabel: item.stage_label,
      name: item.name,
      roleName: item.role_name ?? null,
      objective: item.objective ?? null,
      promptTemplate: item.prompt_template ?? "",
      providerHint: item.provider_hint ?? null,
      providerModel: item.provider_model ?? null,
      isEnabled: item.is_enabled ?? true,
      isRequired: item.is_required ?? false,
      removable: item.removable ?? false,
      promptEnabled: item.prompt_enabled ?? true,
      editable: item.editable ?? true,
      structureEditable: item.structure_editable ?? true,
      contentEditable: item.content_editable ?? true,
      sortOrder: item.sort_order ?? 0,
    })),
  };
}

function mapAnalyticsArticleFact(item: any) {
  return {
    id: item.id,
    blogId: item.blog_id,
    articleId: item.article_id ?? null,
    syncedPostId: item.synced_post_id ?? null,
    publishedAt: item.published_at ?? null,
    title: item.title,
    themeKey: item.theme_key ?? null,
    themeName: item.theme_name ?? null,
    category: item.category ?? null,
    seoScore: item.seo_score ?? null,
    geoScore: item.geo_score ?? null,
    similarityScore: item.similarity_score ?? null,
    mostSimilarUrl: item.most_similar_url ?? null,
    status: item.status ?? null,
    actualUrl: item.actual_url ?? null,
    sourceType: item.source_type,
    ctr: item.ctr ?? null,
    indexStatus: item.index_status ?? "unknown",
    indexCoverageState: item.index_coverage_state ?? null,
    lastCrawlTime: item.last_crawl_time ?? null,
    lastNotifyTime: item.last_notify_time ?? null,
    nextEligibleAt: item.next_eligible_at ?? null,
    indexLastCheckedAt: item.index_last_checked_at ?? null,
  };
}

function mapAnalyticsThemeStat(item: any) {
  return {
    id: item.id,
    blogId: item.blog_id,
    month: item.month,
    themeKey: item.theme_key,
    themeName: item.theme_name,
    plannedPosts: item.planned_posts,
    actualPosts: item.actual_posts,
    plannedShare: item.planned_share,
    actualShare: item.actual_share,
    gapShare: item.gap_share,
    avgSeoScore: item.avg_seo_score ?? null,
    avgGeoScore: item.avg_geo_score ?? null,
    avgSimilarityScore: item.avg_similarity_score ?? null,
    coverageGapScore: item.coverage_gap_score,
    nextMonthWeightSuggestion: item.next_month_weight_suggestion,
  };
}

function mapAnalyticsSummary(item: any): AnalyticsBlogMonthlySummaryRead {
  return {
    blogId: item.blog_id,
    blogName: item.blog_name,
    month: item.month,
    totalPosts: item.total_posts,
    avgSeoScore: item.avg_seo_score ?? null,
    avgGeoScore: item.avg_geo_score ?? null,
    avgSimilarityScore: item.avg_similarity_score ?? null,
    mostUnderusedThemeName: item.most_underused_theme_name ?? null,
    mostOverusedThemeName: item.most_overused_theme_name ?? null,
    nextMonthFocus: item.next_month_focus ?? null,
  };
}

function mapAnalyticsDailySummary(item: any) {
  return {
    date: item.date,
    totalPosts: item.total_posts ?? 0,
    generatedPosts: item.generated_posts ?? 0,
    syncedPosts: item.synced_posts ?? 0,
    avgSeo: item.avg_seo ?? null,
    avgGeo: item.avg_geo ?? null,
  };
}

function mapAnalyticsReport(payload: any): AnalyticsBlogMonthlyReportRead {
  return {
    blogId: payload.blog_id,
    blogName: payload.blog_name,
    month: payload.month,
    totalPosts: payload.total_posts,
    avgSeoScore: payload.avg_seo_score ?? null,
    avgGeoScore: payload.avg_geo_score ?? null,
    avgSimilarityScore: payload.avg_similarity_score ?? null,
    mostUnderusedThemeName: payload.most_underused_theme_name ?? null,
    mostOverusedThemeName: payload.most_overused_theme_name ?? null,
    nextMonthFocus: payload.next_month_focus ?? null,
    reportSummary: payload.report_summary ?? null,
    themeStats: (payload.theme_stats ?? []).map(mapAnalyticsThemeStat),
    articleFacts: (payload.article_facts ?? []).map(mapAnalyticsArticleFact),
  };
}

export async function updateSettings(values: Record<string, string>) {
  return apiFetch<SettingItem[]>("/settings", {
    method: "PUT",
    body: JSON.stringify({ values }),
  });
}

export async function getModelPolicy() {
  return apiFetch<ModelPolicyRead>("/settings/model-policy");
}

export async function getChannels() {
  const payload = await apiFetch<any[]>("/channels", { revalidate: false });
  return (payload ?? []).map(mapManagedChannel);
}

export async function getChannelPromptFlow(channelId: string, signal?: AbortSignal) {
  const payload = await apiFetch<any>(`/channels/${encodeURIComponent(channelId)}/prompt-flow`, { revalidate: false, signal });
  return mapPromptFlow(payload);
}

export async function createChannelPromptFlowStep(channelId: string, stageType: string) {
  const payload = await apiFetch<any>(`/channels/${encodeURIComponent(channelId)}/prompt-flow/steps`, {
    method: "POST",
    body: JSON.stringify({ stage_type: stageType }),
  });
  return mapPromptFlow(payload);
}

export async function reorderChannelPromptFlow(channelId: string, orderedIds: string[]) {
  const payload = await apiFetch<any>(`/channels/${encodeURIComponent(channelId)}/prompt-flow/reorder`, {
    method: "POST",
    body: JSON.stringify({ ordered_ids: orderedIds }),
  });
  return mapPromptFlow(payload);
}

export async function updateChannelPromptFlowStep(channelId: string, stepId: string, values: Record<string, unknown>) {
  const payload = await apiFetch<any>(`/channels/${encodeURIComponent(channelId)}/prompt-flow/steps/${encodeURIComponent(stepId)}`, {
    method: "PATCH",
    body: JSON.stringify(values),
  });
  return mapPromptFlow(payload);
}

export async function deleteChannelPromptFlowStep(channelId: string, stepId: string) {
  const payload = await apiFetch<any>(`/channels/${encodeURIComponent(channelId)}/prompt-flow/steps/${encodeURIComponent(stepId)}`, {
    method: "DELETE",
  });
  return mapPromptFlow(payload);
}

export async function getPlannerCalendar(channelId: string, month: string) {
  const payload = await apiFetch<any>(`/planner/calendar?channel_id=${encodeURIComponent(channelId)}&month=${month}`, {
    revalidate: false,
  });
  return mapPlannerCalendar(payload);
}

export async function buildPlannerMonthPlan(payload: PlannerMonthPlanRequest) {
  const response = await apiFetch<any>("/planner/month-plan", {
    method: "POST",
    body: JSON.stringify({
      channel_id: payload.channelId,
      month: payload.month,
      target_post_count: payload.targetPostCount ?? null,
      overwrite: payload.overwrite,
    }),
  });
  return mapPlannerCalendar(response);
}

export async function createPlannerSlot(payload: PlannerSlotCreateRequest) {
  const response = await apiFetch<any>("/planner/slots", {
    method: "POST",
    body: JSON.stringify({
      plan_day_id: payload.planDayId,
      category_key: payload.categoryKey,
      scheduled_for: payload.scheduledFor,
      brief_topic: payload.briefTopic,
      brief_audience: payload.briefAudience,
      brief_information_level: payload.briefInformationLevel ?? null,
      brief_extra_context: payload.briefExtraContext ?? null,
    }),
  });
  return mapPlannerSlot(response);
}

export async function updatePlannerSlot(slotId: number, payload: PlannerSlotUpdateRequest) {
  const response = await apiFetch<any>(`/planner/slots/${slotId}`, {
    method: "PATCH",
    body: JSON.stringify({
      category_key: payload.categoryKey,
      scheduled_for: payload.scheduledFor,
      slot_order: payload.slotOrder,
      brief_topic: payload.briefTopic,
      brief_audience: payload.briefAudience,
      brief_information_level: payload.briefInformationLevel,
      brief_extra_context: payload.briefExtraContext,
      status: payload.status,
      error_message: payload.errorMessage,
    }),
  });
  return mapPlannerSlot(response);
}

export async function generatePlannerSlot(slotId: number) {
  const response = await apiFetch<any>(`/planner/slots/${slotId}/generate`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  return mapPlannerSlot(response);
}

export async function cancelPlannerSlot(slotId: number) {
  const response = await apiFetch<any>(`/planner/slots/${slotId}/cancel`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  return mapPlannerSlot(response);
}

export async function getAnalyticsMonthly(month: string) {
  const payload = await apiFetch<any>(`/analytics/blogs/monthly?month=${month}`);
  return {
    month: payload.month,
    items: (payload.items ?? []).map(mapAnalyticsSummary),
  } satisfies AnalyticsBlogMonthlyListResponse;
}

export async function getBlogMonthlyReport(blogId: number, month: string, signal?: AbortSignal) {
  const payload = await apiFetch<any>(`/analytics/blogs/${blogId}/monthly-report?month=${month}`, { signal });
  return mapAnalyticsReport(payload);
}

export async function getBlogDailySummary(
  blogId: number,
  params: {
    month: string;
    sourceType?: string;
    themeKey?: string | null;
    category?: string | null;
    status?: string | null;
    signal?: AbortSignal;
  },
) {
  const search = new URLSearchParams({
    month: params.month,
  });
  if (params.sourceType && params.sourceType !== "all") {
    search.set("source_type", params.sourceType);
  }
  if (params.themeKey) {
    search.set("theme_key", params.themeKey);
  }
  if (params.category) {
    search.set("category", params.category);
  }
  if (params.status) {
    search.set("status", params.status);
  }
  const payload = await apiFetch<any>(`/analytics/blogs/${blogId}/daily-summary?${search.toString()}`, { signal: params.signal });
  return {
    blogId: payload.blog_id,
    month: payload.month,
    items: (payload.items ?? []).map(mapAnalyticsDailySummary),
  } satisfies AnalyticsDailySummaryListResponse;
}

export async function getBlogMonthlyArticles(
  blogId: number,
  params: {
    month: string;
    date?: string | null;
    sourceType?: string;
    themeKey?: string | null;
    category?: string | null;
    status?: string | null;
    sort?: "published_at" | "seo" | "geo" | "similarity" | "title";
    dir?: "asc" | "desc";
    page?: number;
    pageSize?: number;
    signal?: AbortSignal;
  },
) {
  const search = new URLSearchParams({
    month: params.month,
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 50),
    sort: params.sort ?? "published_at",
    dir: params.dir ?? "desc",
  });
  if (params.date) {
    search.set("date", params.date);
  }
  if (params.sourceType && params.sourceType !== "all") {
    search.set("source_type", params.sourceType);
  }
  if (params.themeKey) {
    search.set("theme_key", params.themeKey);
  }
  if (params.category) {
    search.set("category", params.category);
  }
  if (params.status) {
    search.set("status", params.status);
  }
  const payload = await apiFetch<any>(`/analytics/blogs/${blogId}/articles?${search.toString()}`, { signal: params.signal });
  return {
    blogId: payload.blog_id,
    month: payload.month,
    total: payload.total ?? 0,
    page: payload.page ?? 1,
    pageSize: payload.page_size ?? params.pageSize ?? 50,
    items: (payload.items ?? []).map(mapAnalyticsArticleFact),
  } satisfies AnalyticsArticleFactListResponse;
}

export async function applyNextMonthWeights(blogId: number, month: string) {
  const payload = await apiFetch<any>(`/analytics/blogs/${blogId}/apply-next-month-weights`, {
    method: "POST",
    body: JSON.stringify({ month }),
  });
  return {
    blogId: payload.blog_id,
    sourceMonth: payload.source_month,
    targetMonth: payload.target_month,
    appliedWeights: payload.applied_weights ?? {},
  } satisfies AnalyticsThemeWeightApplyResponse;
}

export async function requestAnalyticsIndexing(payload: { blogId: number; url: string; force?: boolean }) {
  const response = await apiFetch<any>("/analytics/indexing/request", {
    method: "POST",
    body: JSON.stringify({
      blog_id: payload.blogId,
      url: payload.url,
      force: payload.force ?? false,
    }),
  });
  return {
    status: response.status,
    reason: response.reason ?? null,
    blogId: response.blog_id,
    url: response.url,
    indexStatus: response.index_status ?? "unknown",
    nextEligibleAt: response.next_eligible_at ?? null,
    lastNotifyTime: response.last_notify_time ?? null,
    indexLastCheckedAt: response.index_last_checked_at ?? null,
    lastError: response.last_error ?? null,
  };
}

export async function refreshAnalyticsIndexing(payload: { blogId: number; urls?: string[]; limit?: number }) {
  const response = await apiFetch<any>("/analytics/indexing/refresh", {
    method: "POST",
    body: JSON.stringify({
      blog_id: payload.blogId,
      urls: payload.urls ?? null,
      limit: payload.limit ?? 50,
    }),
  });
  return response;
}

export async function getIntegratedAnalytics(params: {
  range: string;
  month: string;
  blogId?: number | null;
  sourceType?: string;
  themeKey?: string | null;
  category?: string | null;
  status?: string | null;
  includeReport?: boolean;
  signal?: AbortSignal;
}) {
  const search = new URLSearchParams({
    range: params.range,
    month: params.month,
  });
  if (params.blogId != null) {
    search.set("blog_id", String(params.blogId));
  }
  if (params.sourceType && params.sourceType !== "all") {
    search.set("source_type", params.sourceType);
  }
  if (params.themeKey) {
    search.set("theme_key", params.themeKey);
  }
  if (params.category) {
    search.set("category", params.category);
  }
  if (params.status) {
    search.set("status", params.status);
  }
  if (params.includeReport) {
    search.set("include_report", "true");
  }
  const payload = await apiFetch<any>(`/analytics/integrated?${search.toString()}`, { signal: params.signal });
  return {
    month: payload.month,
    range: payload.range,
    selectedBlogId: payload.selected_blog_id ?? null,
    kpis: {
      totalPosts: payload.kpis?.total_posts ?? 0,
      avgSeoScore: payload.kpis?.avg_seo_score ?? null,
      avgGeoScore: payload.kpis?.avg_geo_score ?? null,
      avgSimilarityScore: payload.kpis?.avg_similarity_score ?? null,
      mostUnderusedThemeName: payload.kpis?.most_underused_theme_name ?? null,
      mostOverusedThemeName: payload.kpis?.most_overused_theme_name ?? null,
      recentUploadCount: payload.kpis?.recent_upload_count ?? 0,
    },
    blogs: (payload.blogs ?? []).map(mapAnalyticsSummary),
    report: payload.report ? mapAnalyticsReport(payload.report) : null,
    sourceType: payload.source_type ?? "all",
    themeKey: payload.theme_key ?? null,
    category: payload.category ?? null,
    status: payload.status ?? null,
    availableThemes: (payload.available_themes ?? []).map((item: any) => ({
      key: item.key,
      name: item.name,
    })),
    availableCategories: payload.available_categories ?? [],
  } satisfies AnalyticsIntegratedRead;
}

export async function triggerAnalyticsBackfill() {
  const payload = await apiFetch<any>("/analytics/backfill", {
    method: "POST",
    body: JSON.stringify({}),
  });
  return {
    blogMonths: payload.blog_months,
    generatedFacts: payload.generated_facts,
    syncedFacts: payload.synced_facts,
  } satisfies AnalyticsBackfillRead;
}

export const fetchBlogs = getBlogs;
export const fetchChannels = getChannels;
export const fetchSettings = getSettings;
export const fetchBloggerConfig = getBloggerConfig;

"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import {
  applyNextMonthWeights,
  getBlogDailySummary,
  getBlogMonthlyArticles,
  getBlogMonthlyReport,
  getCloudflarePosts,
  getIntegratedAnalytics,
  getSettings,
  refreshAnalyticsIndexing,
  requestAnalyticsIndexing,
  updateSettings,
} from "@/lib/api";
import type {
  AnalyticsArticleFactListResponse,
  AnalyticsArticleFactRead,
  AnalyticsBlogMonthlyReportRead,
  AnalyticsDailySummaryRead,
  AnalyticsIntegratedRead,
  BlogRead,
  ManagedChannelRead,
} from "@/lib/types";

type AnalyticsDashboardProps = {
  blogs: BlogRead[];
  channels: ManagedChannelRead[];
};

type SortKey = "published_at" | "seo" | "geo" | "similarity";
type SortDir = "asc" | "desc";
type DetailTab = "day" | "week" | "month";

type CalendarCell = {
  dateKey: string;
  dayNumber: number;
  summary: AnalyticsDailySummaryRead | null;
};

type IndexStatus = "indexed" | "submitted" | "pending" | "blocked" | "failed" | "unknown";

function defaultMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function parseBlogId(value: string | null, fallback: number | null) {
  if (!value) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseSortKey(value: string | null): SortKey {
  if (value === "seo" || value === "geo" || value === "similarity" || value === "published_at") return value;
  return "published_at";
}

function parseSortDir(value: string | null): SortDir {
  return value === "asc" ? "asc" : "desc";
}

function parseDetailTab(value: string | null): DetailTab {
  if (value === "day" || value === "week" || value === "month") return value;
  return "day";
}

function parseDateKey(value: string) {
  return new Date(`${value}T12:00:00`);
}

function formatDateKey(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatKoreanDate(value: string) {
  const date = parseDateKey(value);
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

function formatWeekday(value: string) {
  const date = parseDateKey(value);
  const labels = ["일", "월", "화", "수", "목", "금", "토"];
  return labels[date.getDay()];
}

function monthLabel(month: string) {
  const [yearText, monthText] = month.split("-");
  return `${yearText}년 ${Number(monthText)}월`;
}

function buildWeekDays(anchorDate: string) {
  const anchor = parseDateKey(anchorDate);
  const monday = new Date(anchor);
  monday.setDate(anchor.getDate() - ((anchor.getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, index) => {
    const next = new Date(monday);
    next.setDate(monday.getDate() + index);
    return formatDateKey(next);
  });
}

function buildMonthCells(month: string, grouped: Map<string, AnalyticsDailySummaryRead>) {
  const [yearText, monthText] = month.split("-");
  const year = Number(yearText);
  const monthIndex = Number(monthText) - 1;
  const firstDay = new Date(Date.UTC(year, monthIndex, 1));
  const daysInMonth = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
  const mondayOffset = (firstDay.getUTCDay() + 6) % 7;
  const cells: Array<CalendarCell | null> = Array.from({ length: mondayOffset }, () => null);

  for (let dayNumber = 1; dayNumber <= daysInMonth; dayNumber += 1) {
    const dateKey = `${month}-${String(dayNumber).padStart(2, "0")}`;
    cells.push({
      dateKey,
      dayNumber,
      summary: grouped.get(dateKey) ?? null,
    });
  }

  return cells;
}

function numberText(value: number | null | undefined, fractionDigits = 1) {
  if (value === null || value === undefined) return "N/A";
  return Number(value).toFixed(fractionDigits);
}

function percentText(value: number | null | undefined, fractionDigits = 2) {
  if (value === null || value === undefined) return "N/A";
  return `${(Number(value) * 100).toFixed(fractionDigits)}%`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  const hour = String(parsed.getHours()).padStart(2, "0");
  const minute = String(parsed.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hour}:${minute}`;
}

function toBool(value: string | undefined, fallback = false) {
  if (value === undefined) return fallback;
  return ["1", "true", "yes", "on", "enabled"].includes(value.trim().toLowerCase());
}

function parseQuotaMap(value: string | undefined) {
  if (!value) return {} as Record<number, number>;
  try {
    const payload = JSON.parse(value);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return {};
    const out: Record<number, number> = {};
    Object.entries(payload).forEach(([key, rawValue]) => {
      const blogId = Number(key);
      const quota = Number(rawValue);
      if (Number.isFinite(blogId) && Number.isFinite(quota) && blogId > 0 && quota >= 0) {
        out[blogId] = Math.floor(quota);
      }
    });
    return out;
  } catch {
    return {};
  }
}

function scoreTone(score: number | null) {
  if (score === null) return "bg-slate-100 text-slate-500";
  if (score >= 80) return "bg-emerald-50 text-emerald-700";
  if (score >= 60) return "bg-amber-50 text-amber-700";
  return "bg-rose-50 text-rose-700";
}

function indexStatusTone(status: string) {
  const normalized = status.toLowerCase() as IndexStatus;
  if (normalized === "indexed") return "bg-emerald-50 text-emerald-700";
  if (normalized === "submitted") return "bg-blue-50 text-blue-700";
  if (normalized === "pending") return "bg-amber-50 text-amber-700";
  if (normalized === "blocked") return "bg-rose-100 text-rose-800";
  if (normalized === "failed") return "bg-rose-50 text-rose-700";
  return "bg-slate-100 text-slate-600";
}

function pickArticle(items: AnalyticsArticleFactRead[], order: "best" | "worst") {
  const scored = items.filter((item) => item.seoScore !== null || item.geoScore !== null);
  if (!scored.length) return null;
  return [...scored].sort((left, right) => {
    const leftScore = (left.seoScore ?? 0) + (left.geoScore ?? 0);
    const rightScore = (right.seoScore ?? 0) + (right.geoScore ?? 0);
    return order === "best" ? rightScore - leftScore : leftScore - rightScore;
  })[0];
}

function summaryForDate(map: Map<string, AnalyticsDailySummaryRead>, dateKey: string): AnalyticsDailySummaryRead {
  return (
    map.get(dateKey) ?? {
      date: dateKey,
      totalPosts: 0,
      generatedPosts: 0,
      syncedPosts: 0,
      avgSeo: null,
      avgGeo: null,
    }
  );
}

export function AnalyticsDashboard({ blogs, channels }: AnalyticsDashboardProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const month = searchParams.get("month") ?? defaultMonth();
  const blogId = parseBlogId(searchParams.get("blog"), blogs[0]?.id ?? null);
  const sourceType = searchParams.get("source") ?? "all";
  const themeFilter = searchParams.get("theme") ?? "";
  const categoryFilter = searchParams.get("category") ?? "";
  const statusFilter = searchParams.get("status") ?? "";
  const sortKey = parseSortKey(searchParams.get("sort"));
  const sortDir = parseSortDir(searchParams.get("dir"));
  const selectedDateFromQuery = searchParams.get("selectedDate");
  const detailTab = parseDetailTab(searchParams.get("detailTab"));
  const articlePage = Math.max(1, Number(searchParams.get("articlePage") ?? "1") || 1);
  const articlePageSize = 20;

  const [payload, setPayload] = useState<AnalyticsIntegratedRead | null>(null);
  const [dailySummaries, setDailySummaries] = useState<AnalyticsDailySummaryRead[]>([]);
  const [dayArticles, setDayArticles] = useState<AnalyticsArticleFactListResponse>({
    blogId: blogId ?? 0,
    month,
    total: 0,
    page: 1,
    pageSize: articlePageSize,
    items: [],
  });
  const [report, setReport] = useState<AnalyticsBlogMonthlyReportRead | null>(null);
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null);
  const [cloudflarePosts, setCloudflarePosts] = useState<Array<{ title: string; published_url?: string | null; status?: string | null; category_slug?: string | null }>>([]);
  const [status, setStatus] = useState("");
  const [loadingReport, setLoadingReport] = useState(false);
  const [indexingSettingsLoaded, setIndexingSettingsLoaded] = useState(false);
  const [indexingScopeGranted, setIndexingScopeGranted] = useState(true);
  const [indexingAutomationEnabled, setIndexingAutomationEnabled] = useState(false);
  const [indexingPolicyMode, setIndexingPolicyMode] = useState("mixed");
  const [indexingDailyQuota, setIndexingDailyQuota] = useState("200");
  const [indexingCooldownDays, setIndexingCooldownDays] = useState("7");
  const [indexingBlogQuotaInputs, setIndexingBlogQuotaInputs] = useState<Record<number, string>>({});
  const [indexingSaving, setIndexingSaving] = useState(false);
  const [indexingRefreshing, setIndexingRefreshing] = useState(false);
  const [requestingUrl, setRequestingUrl] = useState<string | null>(null);
  const oauthStartUrl = `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"}/blogger/oauth/start`;

  const selectedChannel = useMemo(() => channels.find((channel) => channel.channelId === selectedChannelId) ?? null, [channels, selectedChannelId]);

  function setQuery(updates: Record<string, string | null | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === undefined || value === "") next.delete(key);
      else next.set(key, value);
    }
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  const summaryByDate = useMemo(() => {
    const map = new Map<string, AnalyticsDailySummaryRead>();
    for (const item of dailySummaries) {
      map.set(item.date, item);
    }
    return map;
  }, [dailySummaries]);

  const selectedDate = useMemo(() => {
    if (selectedDateFromQuery) return selectedDateFromQuery;
    return dailySummaries[dailySummaries.length - 1]?.date ?? `${month}-01`;
  }, [dailySummaries, month, selectedDateFromQuery]);

  async function loadIntegratedAndSummary(signal?: AbortSignal) {
    if (!blogId) {
      setPayload(null);
      setDailySummaries([]);
      return;
    }
    setStatus("분석 데이터를 불러오는 중입니다.");
    const [nextPayload, dailyPayload] = await Promise.all([
      getIntegratedAnalytics({
        month,
        range: "month",
        blogId,
        sourceType,
        themeKey: themeFilter || null,
        category: categoryFilter || null,
        status: statusFilter || null,
        includeReport: false,
        signal,
      }),
      getBlogDailySummary(blogId, {
        month,
        sourceType,
        themeKey: themeFilter || null,
        category: categoryFilter || null,
        status: statusFilter || null,
        signal,
      }),
    ]);
    setPayload(nextPayload);
    setDailySummaries(dailyPayload.items);
    setStatus("");
  }

  async function loadSelectedDayArticles(signal?: AbortSignal) {
    if (!blogId) {
      setDayArticles({
        blogId: 0,
        month,
        total: 0,
        page: 1,
        pageSize: articlePageSize,
        items: [],
      });
      return;
    }
    const next = await getBlogMonthlyArticles(blogId, {
      month,
      date: selectedDate || null,
      sourceType,
      themeKey: themeFilter || null,
      category: categoryFilter || null,
      status: statusFilter || null,
      sort: sortKey,
      dir: sortDir,
      page: articlePage,
      pageSize: articlePageSize,
      signal,
    });
    setDayArticles(next);
  }

  async function loadMonthlyReport(signal?: AbortSignal) {
    if (!blogId) {
      setReport(null);
      return;
    }
    setLoadingReport(true);
    try {
      const next = await getBlogMonthlyReport(blogId, month, signal);
      setReport(next);
    } finally {
      setLoadingReport(false);
    }
  }

  async function loadIndexingSettings() {
    try {
      const settings = await getSettings();
      const values = Object.fromEntries(settings.map((item) => [item.key, item.value]));
      const quotaMap = parseQuotaMap(values.google_indexing_blog_quota_map);
      const scopeSet = new Set((values.blogger_token_scope || "").split(/\s+/).filter(Boolean));

      setIndexingAutomationEnabled(toBool(values.automation_google_indexing_enabled, false));
      setIndexingPolicyMode((values.google_indexing_policy_mode || "mixed").toLowerCase() || "mixed");
      setIndexingDailyQuota(values.google_indexing_daily_quota || "200");
      setIndexingCooldownDays(values.google_indexing_cooldown_days || "7");
      setIndexingScopeGranted(scopeSet.has("https://www.googleapis.com/auth/indexing"));
      setIndexingBlogQuotaInputs(
        Object.fromEntries(
          blogs.map((blog) => [blog.id, String(quotaMap[blog.id] ?? 0)]),
        ) as Record<number, string>,
      );
      setIndexingSettingsLoaded(true);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "자동 색인 설정을 불러오지 못했습니다.");
    }
  }

  async function handleSaveIndexingSettings() {
    try {
      setIndexingSaving(true);
      const blogQuotaMap = Object.fromEntries(
        blogs.map((blog) => {
          const raw = indexingBlogQuotaInputs[blog.id] ?? "0";
          const parsed = Number(raw);
          return [String(blog.id), Math.max(0, Math.floor(Number.isFinite(parsed) ? parsed : 0))];
        }),
      );
      await updateSettings({
        automation_google_indexing_enabled: indexingAutomationEnabled ? "true" : "false",
        google_indexing_policy_mode: "mixed",
        google_indexing_daily_quota: String(Math.max(1, Math.floor(Number(indexingDailyQuota) || 200))),
        google_indexing_cooldown_days: String(Math.max(1, Math.floor(Number(indexingCooldownDays) || 7))),
        google_indexing_blog_quota_map: JSON.stringify(blogQuotaMap),
      });
      setStatus("자동 색인 설정을 저장했습니다.");
      await loadIndexingSettings();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "자동 색인 설정 저장에 실패했습니다.");
    } finally {
      setIndexingSaving(false);
    }
  }

  async function handleRefreshIndexingNow() {
    if (!blogId) return;
    try {
      setIndexingRefreshing(true);
      setStatus("선택 블로그 색인 상태를 즉시 갱신하는 중입니다.");
      await refreshAnalyticsIndexing({ blogId, limit: 80 });
      await loadSelectedDayArticles();
      setStatus("선택 블로그 색인 상태를 갱신했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "색인 상태 갱신에 실패했습니다.");
    } finally {
      setIndexingRefreshing(false);
    }
  }

  async function handleManualIndexRequest(fact: AnalyticsArticleFactRead, force: boolean) {
    if (!fact.actualUrl) return;
    try {
      setRequestingUrl(fact.actualUrl);
      const result = await requestAnalyticsIndexing({ blogId: fact.blogId, url: fact.actualUrl, force });
      const reason = result.reason ? ` (${result.reason})` : "";
      setStatus(`색인 요청 결과: ${result.status}${reason}`);
      await loadSelectedDayArticles();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "색인 요청에 실패했습니다.");
    } finally {
      setRequestingUrl(null);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void loadIntegratedAndSummary(controller.signal).catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setStatus(error instanceof Error ? error.message : "분석 데이터를 불러오지 못했습니다.");
      });
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [month, blogId, sourceType, themeFilter, categoryFilter, statusFilter]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void loadSelectedDayArticles(controller.signal).catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setStatus(error instanceof Error ? error.message : "일간 상세 데이터를 불러오지 못했습니다.");
      });
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [month, blogId, sourceType, themeFilter, categoryFilter, statusFilter, sortKey, sortDir, selectedDate, articlePage]);

  useEffect(() => {
    if (detailTab !== "month") return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void loadMonthlyReport(controller.signal).catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setStatus(error instanceof Error ? error.message : "월간 리포트를 불러오지 못했습니다.");
      });
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [detailTab, blogId, month]);

  useEffect(() => {
    setReport(null);
  }, [blogId, month]);

  useEffect(() => {
    void loadIndexingSettings();
  }, [blogs]);

  useEffect(() => {
    if (!selectedDateFromQuery && selectedDate) {
      setQuery({ selectedDate, detailTab, articlePage: "1" });
    }
  }, [selectedDateFromQuery, selectedDate, detailTab]);

  const monthCells = useMemo(() => buildMonthCells(month, summaryByDate), [summaryByDate, month]);
  const selectedDayFacts = dayArticles.items;
  const selectedDaySummary = useMemo(() => summaryForDate(summaryByDate, selectedDate), [summaryByDate, selectedDate]);
  const weekDateKeys = useMemo(() => buildWeekDays(selectedDate), [selectedDate]);
  const weekFacts = useMemo(
    () => weekDateKeys.map((dateKey) => summaryForDate(summaryByDate, dateKey)),
    [summaryByDate, weekDateKeys],
  );

  const strongest = useMemo(() => pickArticle(report?.articleFacts ?? [], "best"), [report]);
  const weakest = useMemo(() => pickArticle(report?.articleFacts ?? [], "worst"), [report]);

  async function handleApplyWeights() {
    if (!report) return;
    try {
      setStatus("다음 달 비중을 반영하는 중입니다.");
      await applyNextMonthWeights(report.blogId, report.month);
      await loadIntegratedAndSummary();
      await loadMonthlyReport();
      setStatus("다음 달 비중을 반영했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "다음 달 비중을 반영하지 못했습니다.");
    }
  }

  async function handleChannelSelect(channel: ManagedChannelRead) {
    setSelectedChannelId(channel.channelId);
    if (channel.provider === "blogger") {
      const linkedBlog = blogs.find((blog) => `blogger:${blog.id}` === channel.channelId);
      if (linkedBlog) {
        setQuery({ blog: String(linkedBlog.id), selectedDate: null, detailTab: "day", category: null, theme: null, articlePage: "1" });
      }
      return;
    }
    if (!cloudflarePosts.length) {
      const items = await getCloudflarePosts();
      setCloudflarePosts((items ?? []).map((item: any) => ({
        title: item.title,
        published_url: item.published_url ?? null,
        status: item.status ?? null,
        category_slug: item.category_slug ?? null,
      })));
    }
  }

  const detailPanel = (
    <div className="flex h-full flex-col rounded-[28px] bg-[#eef2ff] p-5 shadow-[0_18px_60px_rgba(15,23,42,0.08)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-500">상세 분석</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-900">{selectedChannel?.provider === "cloudflare" ? selectedChannel.name : formatKoreanDate(selectedDate)}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            {selectedChannel?.provider === "cloudflare"
              ? "Cloudflare 채널은 전용 요약 패널로 확인합니다."
              : "월간 메인 캔버스에서 날짜를 누르면 일간 성과, 주간 흐름, 월간 리포트를 분리해서 봅니다."}
          </p>
        </div>
        <div className="rounded-2xl bg-white px-4 py-3 text-xs leading-5 text-slate-500 shadow-sm">
          분석 기준도 일간 원본입니다.
          <br />
          우측 탭은 같은 데이터를 다른 밀도로 보여줍니다.
        </div>
      </div>

      {selectedChannel?.provider !== "cloudflare" ? (
        <div className="mt-5 grid grid-cols-3 gap-2 rounded-[24px] bg-white p-2 shadow-sm">
          <DetailTabButton active={detailTab === "day"} onClick={() => setQuery({ detailTab: "day", articlePage: "1" })} label="일간 성과" />
          <DetailTabButton active={detailTab === "week"} onClick={() => setQuery({ detailTab: "week" })} label="주간 흐름" />
          <DetailTabButton active={detailTab === "month"} onClick={() => setQuery({ detailTab: "month" })} label="월간 리포트" />
        </div>
      ) : null}

      <div className="mt-5 min-h-0 flex-1 overflow-y-auto">
        {selectedChannel?.provider === "cloudflare" ? (
          <div className="space-y-4">
            <MiniMetric label="채널 상태" value={selectedChannel.status} />
            <MiniMetric label="게시 수" value={`${selectedChannel.postsCount}건`} />
            <MiniMetric label="카테고리 수" value={`${selectedChannel.categoriesCount}개`} />
            <MiniMetric label="프롬프트 수" value={`${selectedChannel.promptsCount}개`} />
            <article className="rounded-[24px] bg-white p-4 shadow-sm">
              <p className="text-sm font-semibold text-slate-900">최근 게시글</p>
              <div className="mt-4 space-y-3">
                {cloudflarePosts.slice(0, 5).map((post, index) => (
                  <div key={`${post.title}-${index}`} className="rounded-[20px] bg-slate-50 p-3">
                    <p className="line-clamp-2 text-sm font-medium text-slate-900">{post.title}</p>
                    <p className="mt-1 text-xs text-slate-500">{post.category_slug ?? "미분류"} / {post.status ?? "상태 없음"}</p>
                    {post.published_url ? <a href={post.published_url} target="_blank" rel="noreferrer" title={post.published_url} className="mt-2 block truncate text-xs text-indigo-600 hover:underline">{post.published_url}</a> : null}
                  </div>
                ))}
              </div>
            </article>
          </div>
        ) : detailTab === "day" ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <MiniMetric label="당일 게시" value={`${selectedDaySummary.totalPosts}건`} />
              <MiniMetric label="앱 생성" value={`${selectedDaySummary.generatedPosts}건`} />
              <MiniMetric label="동기화" value={`${selectedDaySummary.syncedPosts}건`} />
            </div>
            <article className="rounded-[24px] bg-white p-4 shadow-sm">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">선택 날짜 글 목록</p>
                  <p className="mt-1 text-xs text-slate-500">URL 기준으로 CTR/색인 상태까지 함께 확인합니다.</p>
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                  <ViewChip label={`정렬 ${sortKey}/${sortDir}`} />
                  <ViewChip label={`총 ${dayArticles.total}건`} />
                </div>
              </div>
              {selectedDayFacts.length ? (
                <div className="mt-4 overflow-x-auto">
                  <table className="min-w-[980px] table-fixed border-separate border-spacing-y-2">
                    <thead>
                      <tr className="text-left text-xs uppercase tracking-[0.18em] text-slate-400">
                        <th className="w-[340px] px-3 py-2">URL</th>
                        <th className="w-[90px] px-3 py-2">SEO</th>
                        <th className="w-[90px] px-3 py-2">GEO</th>
                        <th className="w-[90px] px-3 py-2">CTR</th>
                        <th className="w-[130px] px-3 py-2">색인상태</th>
                        <th className="w-[150px] px-3 py-2">최근 요청</th>
                        <th className="w-[150px] px-3 py-2">다음 요청 가능</th>
                        <th className="w-[180px] px-3 py-2">액션</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedDayFacts.map((fact) => (
                        <tr key={fact.id} className="rounded-2xl bg-slate-50 text-sm text-slate-700">
                          <td className="rounded-l-2xl px-3 py-3 align-top">
                            <p className="line-clamp-2 font-semibold text-slate-900">{fact.title}</p>
                            {fact.actualUrl ? (
                              <a
                                href={fact.actualUrl}
                                target="_blank"
                                rel="noreferrer"
                                title={fact.actualUrl}
                                className="mt-1 block truncate text-xs text-indigo-600 hover:underline"
                              >
                                {fact.actualUrl}
                              </a>
                            ) : (
                              <p className="mt-1 text-xs text-slate-400">URL 없음</p>
                            )}
                            <p className="mt-1 text-[11px] text-slate-500">{fact.category ?? fact.themeName ?? "미분류"} / {fact.status ?? "상태 없음"}</p>
                          </td>
                          <td className="px-3 py-3 align-top">
                            <ScoreBadge score={fact.seoScore} label="SEO" />
                          </td>
                          <td className="px-3 py-3 align-top">
                            <ScoreBadge score={fact.geoScore} label="GEO" />
                          </td>
                          <td className="px-3 py-3 align-top">
                            <span className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-[11px] font-medium text-slate-700">{percentText(fact.ctr)}</span>
                          </td>
                          <td className="px-3 py-3 align-top">
                            <span className={`inline-flex rounded-full px-3 py-1 text-[11px] font-medium ${indexStatusTone(fact.indexStatus)}`}>
                              {fact.indexStatus ?? "unknown"}
                            </span>
                          </td>
                          <td className="px-3 py-3 align-top text-xs text-slate-600">
                            {formatDateTime(fact.lastNotifyTime)}
                          </td>
                          <td className="px-3 py-3 align-top text-xs text-slate-600">
                            {formatDateTime(fact.nextEligibleAt)}
                          </td>
                          <td className="rounded-r-2xl px-3 py-3 align-top">
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                disabled={!fact.actualUrl || requestingUrl === fact.actualUrl}
                                onClick={() => void handleManualIndexRequest(fact, false)}
                                className="rounded-xl bg-indigo-600 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-300"
                              >
                                요청
                              </button>
                              <button
                                type="button"
                                disabled={!fact.actualUrl || requestingUrl === fact.actualUrl}
                                onClick={() => void handleManualIndexRequest(fact, true)}
                                className="rounded-xl bg-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-300 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
                              >
                                강제
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="mt-4 flex items-center justify-end gap-2">
                    <button
                      type="button"
                      disabled={articlePage <= 1}
                      onClick={() => setQuery({ articlePage: String(Math.max(1, articlePage - 1)) })}
                      className="rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-200 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
                    >
                      이전
                    </button>
                    <span className="text-xs text-slate-500">
                      {articlePage} / {Math.max(1, Math.ceil(dayArticles.total / articlePageSize))}
                    </span>
                    <button
                      type="button"
                      disabled={articlePage >= Math.max(1, Math.ceil(dayArticles.total / articlePageSize))}
                      onClick={() => setQuery({ articlePage: String(articlePage + 1) })}
                      className="rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-200 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
                    >
                      다음
                    </button>
                  </div>
                </div>
              ) : (
                <div className="mt-4">
                  <EmptyBlock title="선택 날짜 데이터가 없습니다" body="월간 캔버스에서 다른 날짜를 선택하세요." />
                </div>
              )}
            </article>
          </div>
        ) : detailTab === "week" ? (
          <div className="space-y-4">
            {weekFacts.map((item) => (
              <article key={item.date} className="rounded-[24px] bg-white p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{formatKoreanDate(item.date)} ({formatWeekday(item.date)})</p>
                    <p className="mt-1 text-xs text-slate-500">게시 {item.totalPosts}건 / 앱 생성 {item.generatedPosts}건 / 동기화 {item.syncedPosts}건</p>
                  </div>
                  <button type="button" onClick={() => setQuery({ selectedDate: item.date, detailTab: 'day', articlePage: "1" })} className="rounded-2xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-200">당일 보기</button>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <ViewChip label={`평균 SEO ${numberText(item.avgSeo)}`} />
                  <ViewChip label={`평균 GEO ${numberText(item.avgGeo)}`} />
                </div>
              </article>
            ))}
          </div>
        ) : loadingReport ? (
          <div className="space-y-4">
            <article className="rounded-[24px] bg-white p-5 shadow-sm text-sm text-slate-500">월간 리포트를 불러오는 중입니다.</article>
          </div>
        ) : report ? (
          <div className="space-y-4">
            <article className="rounded-[24px] bg-white p-4 shadow-sm">
              <p className="text-sm font-semibold text-slate-900">월간 리포트</p>
              <p className="mt-2 text-sm leading-6 text-slate-500">{report.reportSummary ?? '월간 요약이 아직 없습니다.'}</p>
            </article>
            <div className="grid gap-3 sm:grid-cols-2">
              <MiniMetric label="총 게시" value={`${report.totalPosts}건`} />
              <MiniMetric label="평균 SEO" value={numberText(report.avgSeoScore)} />
              <MiniMetric label="평균 GEO" value={numberText(report.avgGeoScore)} />
              <MiniMetric label="평균 유사도" value={numberText(report.avgSimilarityScore)} />
            </div>
            <article className="rounded-[24px] bg-white p-4 shadow-sm">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">카테고리 월간 집계</p>
                  <p className="mt-1 text-xs text-slate-500">월간 메인 캔버스와 동일한 원본을 기준으로 계산합니다.</p>
                </div>
                <button type="button" onClick={handleApplyWeights} className="rounded-2xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500">다음 달 비중 적용</button>
              </div>
              <div className="mt-4 space-y-3">
                {report.themeStats.map((stat) => (
                  <div key={stat.id} className="rounded-[20px] bg-slate-50 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{stat.themeName}</p>
                        <p className="mt-1 text-xs text-slate-500">계획 {stat.plannedPosts}건 / 실제 {stat.actualPosts}건</p>
                      </div>
                      <ViewChip label={`다음 달 ${stat.nextMonthWeightSuggestion}`} />
                    </div>
                  </div>
                ))}
              </div>
            </article>
            <div className="grid gap-3 sm:grid-cols-2">
              <MiniMetric label="고성과 글" value={strongest?.title ?? '데이터 없음'} />
              <MiniMetric label="저성과 글" value={weakest?.title ?? '데이터 없음'} />
            </div>
          </div>
        ) : (
          <EmptyBlock title="리포트 데이터가 없습니다" body="상단 채널 또는 필터를 조정하세요." />
        )}
      </div>
    </div>
  );

  return (
    <div className="rounded-[32px] bg-[#f5f7ff] p-6 text-slate-900 shadow-[0_24px_80px_rgba(15,23,42,0.08)] md:p-8">
      <div className="space-y-8">
        <section className="rounded-[28px] bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-500">통합 분석 대시보드</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">월간 메인 캔버스 + 우측 상세 탭</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">분석도 월간 캔버스를 메인으로 두고, 날짜 클릭 후 우측 패널에서 일간 성과·주간 흐름·월간 리포트를 나눠서 봅니다.</p>
            </div>
            <div className="rounded-[24px] bg-indigo-50 px-5 py-4 text-sm leading-6 text-indigo-700">
              기준 월: {month}
              <br />
              정렬: {sortKey} / {sortDir}
            </div>
          </div>
          <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_auto_1fr_auto_1fr]">
            <GuideStep title="일간 원본" body="게시일, SEO, GEO, 유사도, URL, 카테고리가 일간 원본으로 저장됩니다." />
            <GuideArrow />
            <GuideStep title="주간 흐름" body="선택 날짜가 포함된 7일 흐름으로 생성/동기화 비율과 편중을 읽습니다." />
            <GuideArrow />
            <GuideStep title="월간 리포트" body="같은 원본으로 월간 KPI, 카테고리 비중, 다음 달 제안을 계산합니다." />
          </div>
        </section>

        <section className="rounded-[28px] bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-emerald-600">자동 색인 설정</p>
              <h2 className="mt-2 text-xl font-semibold text-slate-900">Google Indexing 자동화 + 상태 갱신</h2>
              <p className="mt-2 text-sm text-slate-500">정책 모드는 mixed 고정이며, 같은 URL 자동 요청은 쿨다운 일수 내 재요청을 건너뜁니다.</p>
              {!indexingScopeGranted ? (
                <p className="mt-2 rounded-2xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  현재 OAuth 토큰에 indexing scope가 없습니다. Google 재인증 후 자동 요청이 동작합니다.
                </p>
              ) : null}
              {!indexingScopeGranted ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  <a
                    href={oauthStartUrl}
                    className="rounded-xl bg-amber-600 px-3 py-2 text-xs font-medium text-white hover:bg-amber-500"
                  >
                    OAuth2 재인증
                  </a>
                  <a
                    href="/settings"
                    className="rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-200"
                  >
                    설정 열기
                  </a>
                  <a
                    href="/google"
                    className="rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-200"
                  >
                    연동 상태 확인
                  </a>
                </div>
              ) : null}
              {!indexingScopeGranted ? (
                <p className="mt-2 text-[11px] leading-5 text-slate-500">
                  해결 순서: 1) 설정에서 Client ID/Secret/Redirect URI 저장 2) OAuth2 재인증 3) `/google` 화면에서 승인 Scope에 indexing 포함 확인.
                </p>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void handleRefreshIndexingNow()}
                disabled={!blogId || indexingRefreshing}
                className="rounded-2xl bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
              >
                {indexingRefreshing ? "상태 갱신 중..." : "선택 블로그 상태 갱신"}
              </button>
              <button
                type="button"
                onClick={() => void handleSaveIndexingSettings()}
                disabled={!indexingSettingsLoaded || indexingSaving}
                className="rounded-2xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-emerald-300"
              >
                {indexingSaving ? "저장 중..." : "설정 저장"}
              </button>
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-4">
            <label className="block space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">자동화</span>
              <select
                value={indexingAutomationEnabled ? "true" : "false"}
                onChange={(event) => setIndexingAutomationEnabled(event.target.value === "true")}
                className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"
              >
                <option value="true">ON</option>
                <option value="false">OFF</option>
              </select>
            </label>
            <label className="block space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">정책 모드</span>
              <input
                value={indexingPolicyMode}
                onChange={(event) => setIndexingPolicyMode(event.target.value)}
                disabled
                className="w-full rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-500 outline-none"
              />
            </label>
            <label className="block space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">전역 일일 한도</span>
              <input
                type="number"
                min={1}
                step={1}
                value={indexingDailyQuota}
                onChange={(event) => setIndexingDailyQuota(event.target.value)}
                className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"
              />
            </label>
            <label className="block space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">쿨다운(일)</span>
              <input
                type="number"
                min={1}
                step={1}
                value={indexingCooldownDays}
                onChange={(event) => setIndexingCooldownDays(event.target.value)}
                className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"
              />
            </label>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {blogs.map((blog) => (
              <label key={blog.id} className="block space-y-2 rounded-2xl bg-slate-50 px-4 py-3">
                <span className="text-xs font-semibold text-slate-600">{blog.name}</span>
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={indexingBlogQuotaInputs[blog.id] ?? "0"}
                  onChange={(event) =>
                    setIndexingBlogQuotaInputs((prev) => ({
                      ...prev,
                      [blog.id]: event.target.value,
                    }))
                  }
                  className="w-full rounded-xl bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-emerald-200"
                />
              </label>
            ))}
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-3">
          {channels.map((channel) => {
            const linkedBlog = channel.provider === "blogger" ? blogs.find((blog) => `blogger:${blog.id}` === channel.channelId) : null;
            const selected = channel.provider === "blogger" ? linkedBlog?.id === blogId && selectedChannel?.provider !== 'cloudflare' : selectedChannel?.channelId === channel.channelId;
            return (
              <button key={channel.channelId} type="button" onClick={() => void handleChannelSelect(channel)} className={`rounded-[28px] p-5 text-left shadow-sm transition ${selected ? 'bg-indigo-50 ring-2 ring-indigo-200' : 'bg-white hover:bg-slate-50'}`}>
                <p className="text-sm font-semibold text-slate-900">{channel.name}</p>
                <p className="mt-1 text-xs uppercase tracking-[0.2em] text-slate-400">{channel.provider}</p>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-600">
                  <MiniStat label="게시" value={`${channel.postsCount}건`} />
                  <MiniStat label="카테고리" value={`${channel.categoriesCount}개`} />
                  <MiniStat label="상태" value={channel.status} />
                  <MiniStat label="플래너" value={channel.plannerSupported ? '지원' : '미지원'} />
                </div>
              </button>
            );
          })}
        </section>

        <section className="rounded-[28px] bg-white p-5 shadow-sm">
          <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-6">
            <Field label="기준 월"><input type="month" value={month} onChange={(event) => setQuery({ month: event.target.value, selectedDate: null, articlePage: "1" })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white" /></Field>
            <Field label="출처"><select value={sourceType} onChange={(event) => setQuery({ source: event.target.value || null, articlePage: "1" })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"><option value="all">전체</option><option value="generated">앱 생성</option><option value="synced">동기화</option></select></Field>
            <Field label="카테고리"><select value={categoryFilter} onChange={(event) => setQuery({ category: event.target.value || null, articlePage: "1" })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"><option value="">전체</option>{(payload?.availableCategories ?? []).map((item) => <option key={item} value={item}>{item}</option>)}</select></Field>
            <Field label="상태"><input type="text" value={statusFilter} onChange={(event) => setQuery({ status: event.target.value || null, articlePage: "1" })} placeholder="published" className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white" /></Field>
            <Field label="정렬"><select value={sortKey} onChange={(event) => setQuery({ sort: event.target.value, articlePage: "1" })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"><option value="published_at">발행일</option><option value="seo">SEO</option><option value="geo">GEO</option><option value="similarity">유사도</option></select></Field>
            <Field label="방향"><select value={sortDir} onChange={(event) => setQuery({ dir: event.target.value, articlePage: "1" })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"><option value="desc">내림차순</option><option value="asc">오름차순</option></select></Field>
          </div>
          {status ? <p className="mt-3 text-sm text-indigo-600">{status}</p> : null}
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(760px,1.6fr)_minmax(380px,0.9fr)] 2xl:grid-cols-[minmax(860px,1.7fr)_minmax(420px,0.95fr)]">
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MiniMetric label="총 게시" value={`${payload?.kpis.totalPosts ?? 0}건`} />
              <MiniMetric label="평균 SEO" value={numberText(payload?.kpis.avgSeoScore)} />
              <MiniMetric label="평균 GEO" value={numberText(payload?.kpis.avgGeoScore)} />
              <MiniMetric label="최근 업로드" value={`${payload?.kpis.recentUploadCount ?? 0}건`} />
            </div>

            <section className="rounded-[28px] bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">월간 메인 캔버스</p>
                  <h2 className="mt-2 text-2xl font-semibold text-slate-900">{monthLabel(month)}</h2>
                </div>
                <div className="rounded-2xl bg-slate-50 px-4 py-3 text-xs text-slate-500">클릭한 날짜는 우측에서 탭별로 분리해서 봅니다.</div>
              </div>

              {selectedChannel?.provider === "cloudflare" ? (
                <div className="mt-5 rounded-[24px] bg-slate-50 p-8 text-center text-sm leading-6 text-slate-500">Cloudflare 채널은 현재 월간 일자 캔버스를 제공하지 않습니다. 우측 전용 요약 패널에서 최근 게시와 채널 상태를 확인하세요.</div>
              ) : (
                <div className="mt-5 overflow-x-auto">
                  <div className="min-w-[820px]">
                    <div className="grid grid-cols-7 gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400 xl:gap-3">{['월', '화', '수', '목', '금', '토', '일'].map((label) => <div key={label} className="px-2">{label}</div>)}</div>
                    <div className="mt-3 grid grid-cols-7 gap-2 xl:gap-3">
                      {monthCells.map((cell, index) => cell ? (
                        <button key={cell.dateKey} type="button" onClick={() => setQuery({ selectedDate: cell.dateKey, detailTab: 'day', articlePage: "1" })} className={`min-h-[160px] rounded-[26px] p-4 text-left transition xl:min-h-[180px] ${cell.dateKey === selectedDate ? 'bg-indigo-50 ring-2 ring-indigo-200' : 'bg-slate-50 hover:bg-slate-100'}`}>
                          <div className="flex items-start justify-between gap-3"><p className="text-lg font-semibold text-slate-900">{cell.dayNumber}</p><ViewChip label={`${cell.summary?.totalPosts ?? 0}건`} /></div>
                          <p className="mt-2 text-xs text-slate-500">앱 생성 {cell.summary?.generatedPosts ?? 0} / 동기화 {cell.summary?.syncedPosts ?? 0}</p>
                          <div className="mt-4 h-2 overflow-hidden rounded-full bg-white"><div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.min(100, Math.max(12, cell.summary?.avgSeo ?? 0))}%` }} /></div>
                          <p className="mt-2 text-xs text-slate-500">평균 SEO {numberText(cell.summary?.avgSeo ?? null)}</p>
                        </button>
                      ) : <div key={`empty-${index}`} className="min-h-[160px] rounded-[26px] bg-transparent xl:min-h-[180px]" />)}
                    </div>
                  </div>
                </div>
              )}
            </section>
          </div>

          <div className="xl:sticky xl:top-6 xl:self-start">{detailPanel}</div>
        </section>
      </div>
    </div>
  );
}

function GuideStep({ title, body }: { title: string; body: string }) {
  return <article className="rounded-[24px] bg-slate-50 p-4"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{title}</p><p className="mt-3 text-sm leading-6 text-slate-600">{body}</p></article>;
}
function GuideArrow() { return <div className="hidden items-center justify-center lg:flex"><div className="h-px w-full bg-slate-200" /></div>; }
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="block space-y-2"><span className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{label}</span>{children}</label>; }
function DetailTabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) { return <button type="button" onClick={onClick} className={`rounded-2xl px-4 py-3 text-sm font-medium transition ${active ? 'bg-indigo-600 text-white' : 'text-slate-600 hover:bg-slate-50'}`}>{label}</button>; }
function MiniMetric({ label, value }: { label: string; value: string }) { return <article className="rounded-[24px] bg-white p-4 shadow-sm"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{label}</p><p className="mt-2 text-xl font-semibold text-slate-900">{value}</p></article>; }
function MiniStat({ label, value }: { label: string; value: string }) { return <div><p className="text-xs uppercase tracking-[0.2em] text-slate-400">{label}</p><p className="mt-1 font-semibold text-slate-900">{value}</p></div>; }
function ViewChip({ label }: { label: string }) { return <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">{label}</span>; }
function ScoreBadge({ score, label }: { score: number | null; label: string }) { return <span className={`inline-flex rounded-full px-3 py-1 text-[11px] font-medium ${scoreTone(score)}`}>{label} {score === null ? 'N/A' : score.toFixed(1)}</span>; }
function EmptyBlock({ title, body }: { title: string; body: string }) { return <article className="rounded-[24px] bg-white p-5 text-center shadow-sm"><p className="text-sm font-semibold text-slate-900">{title}</p><p className="mt-2 text-sm leading-6 text-slate-500">{body}</p></article>; }

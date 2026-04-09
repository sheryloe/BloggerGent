"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { deleteBlogMonthlyArticleFact, getBlogDailySummary, getBlogMonthlyArticles } from "@/lib/api";
import type { AnalyticsArticleFactRead, AnalyticsDailySummaryRead, Blog, ManagedChannelRead } from "@/lib/types";

import { AnalyticsPlatformTabs } from "./analytics-platform-tabs";

type BloggerSortKey = "publishedAt" | "title" | "status" | "seo" | "geo" | "ctr" | "lighthouse";
type SortDir = "asc" | "desc";
type LowFilter = "none" | "any70" | "lighthouse70";
type ViewMode = "list" | "calendar";

type BloggerRow = AnalyticsArticleFactRead & {
  lighthouseScore: number | null;
  lowFlag: boolean;
  lighthouseLow: boolean;
};

const PAGE_SIZE = 25;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function scoreOrZero(value: number | null) {
  return Number.isFinite(value as number) ? Number(value) : 0;
}

function resolveLighthouseScore(row: AnalyticsArticleFactRead) {
  if (typeof row.lighthouseScore === "number" && Number.isFinite(row.lighthouseScore)) {
    return clamp(Math.round(row.lighthouseScore * 10) / 10, 0, 100);
  }
  return null;
}

function isAnyLow(row: AnalyticsArticleFactRead) {
  const seo = scoreOrZero(row.seoScore);
  const geo = scoreOrZero(row.geoScore);
  const ctr = scoreOrZero(row.ctrScore);
  const lighthouse = scoreOrZero(resolveLighthouseScore(row));
  return seo < 70 || geo < 70 || ctr < 70 || lighthouse < 70;
}

function formatScore(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "-";
  return `${Math.round(value * 10) / 10}`;
}

function formatPublishedDate(value: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDate(value: string) {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("ko-KR", { month: "2-digit", day: "2-digit", weekday: "short" });
}

function toNumber(value: string | null, fallback = 1) {
  const parsed = Number(value ?? "");
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function buildCalendarCells(month: string, summaries: AnalyticsDailySummaryRead[]) {
  const [yearRaw, monthRaw] = month.split("-");
  const year = Number(yearRaw);
  const monthIndex = Number(monthRaw) - 1;

  if (!Number.isFinite(year) || !Number.isFinite(monthIndex) || monthIndex < 0 || monthIndex > 11) {
    return [] as Array<{ dateKey: string | null; summary: AnalyticsDailySummaryRead | null }>;
  }

  const summaryMap = new Map(summaries.map((item) => [item.date, item]));
  const firstDay = new Date(year, monthIndex, 1);
  const startOffset = firstDay.getDay();
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();

  const cells: Array<{ dateKey: string | null; summary: AnalyticsDailySummaryRead | null }> = [];
  for (let i = 0; i < startOffset; i += 1) {
    cells.push({ dateKey: null, summary: null });
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const dateKey = `${month}-${String(day).padStart(2, "0")}`;
    cells.push({ dateKey, summary: summaryMap.get(dateKey) ?? null });
  }

  return cells;
}

function scoreBadgeTone(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) {
    return {
      badgeClass: "bg-slate-100 text-slate-500",
      dotClass: "bg-slate-400",
    };
  }
  if (value >= 90) {
    return {
      badgeClass: "bg-emerald-100 text-emerald-700",
      dotClass: "bg-emerald-500",
    };
  }
  if (value >= 80) {
    return {
      badgeClass: "bg-violet-100 text-violet-700",
      dotClass: "bg-violet-500",
    };
  }
  if (value >= 70) {
    return {
      badgeClass: "bg-sky-100 text-sky-700",
      dotClass: "bg-sky-500",
    };
  }
  if (value <= 50) {
    return {
      badgeClass: "bg-rose-100 text-rose-700",
      dotClass: "bg-rose-500",
    };
  }
  return {
    badgeClass: "bg-amber-100 text-amber-700",
    dotClass: "bg-amber-500",
  };
}

function ScoreBadge({ value }: { value: number | null | undefined }) {
  const tone = scoreBadgeTone(value);
  return (
    <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${tone.badgeClass}`}>
      <span className={`h-2 w-2 rounded-full ${tone.dotClass}`} />
      {formatScore(value)}
    </span>
  );
}

function truncateTitle(value: string, limit = 30) {
  if (value.length <= limit) return value;
  return `${value.slice(0, limit)}...`;
}

function indexStatusTone(status: string | null | undefined) {
  const normalized = String(status ?? "unknown").trim().toLowerCase();
  if (normalized === "indexed") return "bg-emerald-100 text-emerald-700";
  if (normalized === "submitted") return "bg-blue-100 text-blue-700";
  if (normalized === "pending") return "bg-amber-100 text-amber-700";
  if (normalized === "blocked") return "bg-rose-100 text-rose-800";
  if (normalized === "failed") return "bg-rose-100 text-rose-700";
  return "bg-slate-100 text-slate-600";
}

function mapApiSort(sort: BloggerSortKey): "published_at" | "seo" | "geo" | "lighthouse" | "similarity" | "title" {
  if (sort === "lighthouse") return "lighthouse";
  if (sort === "seo") return "seo";
  if (sort === "geo") return "geo";
  if (sort === "title") return "title";
  return "published_at";
}

function statusBadge(row: AnalyticsArticleFactRead) {
  if (row.statusVariant === "error_deleted") {
    return {
      label: "에러",
      className: "bg-rose-100 text-rose-700",
    };
  }
  const normalized = String(row.status ?? "").trim().toLowerCase();
  if (normalized === "published") {
    return {
      label: "Published",
      className: "bg-emerald-100 text-emerald-700",
    };
  }
  if (normalized === "live" || row.statusVariant === "live") {
    return {
      label: "Live",
      className: "bg-emerald-100 text-emerald-700",
    };
  }
  return {
    label: row.status ? row.status : "unknown",
    className: "bg-slate-100 text-slate-600",
  };
}

export function BloggerAnalyticsWorkspace({ blogs, channels: _channels }: { blogs: Blog[]; channels: ManagedChannelRead[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const defaultMonth = useMemo(() => new Date().toISOString().slice(0, 7), []);

  const queryMonth = searchParams.get("month") ?? defaultMonth;
  const queryBlogId = toNumber(searchParams.get("blog"), 0);
  const queryView = (searchParams.get("view") as ViewMode | null) ?? "list";
  const queryLow = (searchParams.get("low") as LowFilter | null) ?? "none";
  const queryQ = (searchParams.get("q") ?? "").trim();
  const queryStatus = (searchParams.get("status") ?? "").trim();
  const querySort = (searchParams.get("sort") as BloggerSortKey | null) ?? "publishedAt";
  const queryDir = (searchParams.get("dir") as SortDir | null) ?? "desc";
  const queryPage = toNumber(searchParams.get("page"), 1);

  const availableBlogs = useMemo(() => blogs, [blogs]);

  const selectedBlogId = useMemo(() => {
    if (availableBlogs.some((blog) => blog.id === queryBlogId)) return queryBlogId;
    return availableBlogs[0]?.id ?? null;
  }, [availableBlogs, queryBlogId]);

  const [facts, setFacts] = useState<AnalyticsArticleFactRead[]>([]);
  const [dailySummaries, setDailySummaries] = useState<AnalyticsDailySummaryRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [deletingFactId, setDeletingFactId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const setQuery = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams.toString());
    Object.entries(patch).forEach(([key, value]) => {
      if (value == null || value === "") next.delete(key);
      else next.set(key, value);
    });
    const queryString = next.toString();
    router.replace(queryString ? `${pathname}?${queryString}` : pathname);
  };

  const handleSort = (key: BloggerSortKey) => {
    if (querySort === key) {
      setQuery({ dir: queryDir === "asc" ? "desc" : "asc", page: "1" });
      return;
    }
    const defaultDir: SortDir = key === "title" || key === "status" ? "asc" : "desc";
    setQuery({ sort: key, dir: defaultDir, page: "1" });
  };

  useEffect(() => {
    if (!selectedBlogId) {
      setFacts([]);
      setDailySummaries([]);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      getBlogMonthlyArticles(selectedBlogId, {
        month: queryMonth,
        status: queryStatus || null,
        page: 1,
        pageSize: 200,
        sort: mapApiSort(querySort),
        dir: queryDir,
      }),
      getBlogDailySummary(selectedBlogId, {
        month: queryMonth,
        status: queryStatus || null,
      }),
    ])
      .then(([factPayload, dailyPayload]) => {
        if (cancelled) return;
        setFacts(factPayload.items ?? []);
        setDailySummaries(dailyPayload.items ?? []);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        const message = cause instanceof Error ? cause.message : "분석 데이터를 불러오지 못했습니다.";
        setError(message);
        setFacts([]);
        setDailySummaries([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedBlogId, queryMonth, queryStatus, querySort, queryDir]);

  const rows = useMemo<BloggerRow[]>(() => {
    return facts.map((item) => ({
      ...item,
      lighthouseScore: resolveLighthouseScore(item),
      lowFlag: isAnyLow(item),
      lighthouseLow: scoreOrZero(resolveLighthouseScore(item)) < 70,
    }));
  }, [facts]);

  const handleManualDelete = async (row: BloggerRow) => {
    if (!selectedBlogId || !row.canManualDelete || deletingFactId === row.id) return;
    const confirmed = window.confirm("LIVE에서 이미 사라진 글을 로컬 DB에서 정리합니다. 계속할까요?");
    if (!confirmed) return;

    setDeletingFactId(row.id);
    setError(null);
    try {
      await deleteBlogMonthlyArticleFact(selectedBlogId, row.id);
      const [factPayload, dailyPayload] = await Promise.all([
        getBlogMonthlyArticles(selectedBlogId, {
          month: queryMonth,
          status: queryStatus || null,
          page: 1,
          pageSize: 200,
          sort: mapApiSort(querySort),
          dir: queryDir,
        }),
        getBlogDailySummary(selectedBlogId, {
          month: queryMonth,
          status: queryStatus || null,
        }),
      ]);
      setFacts(factPayload.items ?? []);
      setDailySummaries(dailyPayload.items ?? []);
    } catch (cause: unknown) {
      const message = cause instanceof Error ? cause.message : "게시글 수동 삭제에 실패했습니다.";
      setError(message);
    } finally {
      setDeletingFactId(null);
    }
  };

  const filteredRows = useMemo(() => {
    const loweredQ = queryQ.toLowerCase();

    const bySearch = rows.filter((row) => {
      if (!loweredQ) return true;
      const title = row.title.toLowerCase();
      const category = (row.category ?? "").toLowerCase();
      const url = (row.actualUrl ?? "").toLowerCase();
      return title.includes(loweredQ) || category.includes(loweredQ) || url.includes(loweredQ);
    });

    const byLow = bySearch.filter((row) => {
      if (queryLow === "none") return true;
      if (queryLow === "any70") return row.lowFlag;
      return scoreOrZero(row.lighthouseScore) < 70;
    });

    const sorted = [...byLow].sort((a, b) => {
      const direction = queryDir === "asc" ? 1 : -1;
      const compareText = (left: string | null | undefined, right: string | null | undefined) =>
        (left ?? "").localeCompare(right ?? "", "ko");

      if (querySort === "title") return compareText(a.title, b.title) * direction;
      if (querySort === "status") return compareText(statusBadge(a).label, statusBadge(b).label) * direction;
      if (querySort === "publishedAt") {
        const left = a.publishedAt ? new Date(a.publishedAt).getTime() : 0;
        const right = b.publishedAt ? new Date(b.publishedAt).getTime() : 0;
        return (left - right) * direction;
      }
      if (querySort === "seo") return (scoreOrZero(a.seoScore) - scoreOrZero(b.seoScore)) * direction;
      if (querySort === "geo") return (scoreOrZero(a.geoScore) - scoreOrZero(b.geoScore)) * direction;
      if (querySort === "ctr") return (scoreOrZero(a.ctrScore) - scoreOrZero(b.ctrScore)) * direction;
      return (scoreOrZero(a.lighthouseScore) - scoreOrZero(b.lighthouseScore)) * direction;
    });

    return sorted;
  }, [queryDir, queryLow, queryQ, querySort, rows]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const currentPage = clamp(queryPage, 1, totalPages);

  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredRows.slice(start, start + PAGE_SIZE);
  }, [currentPage, filteredRows]);

  const lowCount = filteredRows.filter((row) => row.lowFlag).length;
  const lighthouseLowCount = filteredRows.filter((row) => scoreOrZero(row.lighthouseScore) < 70).length;
  const calendarCells = useMemo(() => buildCalendarCells(queryMonth, dailySummaries), [queryMonth, dailySummaries]);

  return (
    <div className="space-y-5">
      <AnalyticsPlatformTabs />

      <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">Blogger Analytics</p>
            <h1 className="mt-2 text-2xl font-semibold text-slate-900">게시글 성과 테이블</h1>
            <p className="mt-1 text-sm text-slate-600">SEO, GEO, CTR 점수, Lighthouse, 색인 상태를 한 줄에서 확인합니다.</p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs font-semibold">
            <span className="rounded-xl bg-slate-100 px-3 py-2 text-slate-700">행 수 {filteredRows.length}</span>
            <span className="rounded-xl bg-rose-100 px-3 py-2 text-rose-700">저점 항목 {lowCount}</span>
            <span className="rounded-xl bg-amber-100 px-3 py-2 text-amber-700">Lighthouse 70 미만 {lighthouseLowCount}</span>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-8">
          <label className="text-xs font-semibold text-slate-600">
            기준 월
            <input type="month" value={queryMonth} onChange={(event) => setQuery({ month: event.target.value, page: "1" })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm" />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            블로그
            <select value={selectedBlogId ?? ""} onChange={(event) => setQuery({ blog: event.target.value || null, page: "1" })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              {availableBlogs.map((blog) => (
                <option key={blog.id} value={blog.id}>{blog.name}</option>
              ))}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            보기 방식
            <select value={queryView} onChange={(event) => setQuery({ view: event.target.value, page: "1" })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              <option value="list">글 목록</option>
              <option value="calendar">캘린더</option>
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            저점 필터
            <select value={queryLow} onChange={(event) => setQuery({ low: event.target.value, page: "1" })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              <option value="none">전체</option>
              <option value="any70">SEO/GEO/CTR/Lighthouse 중 70 미만</option>
              <option value="lighthouse70">Lighthouse 70 미만</option>
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            상태
            <input type="text" value={queryStatus} onChange={(event) => setQuery({ status: event.target.value || null, page: "1" })} placeholder="published" className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm" />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            검색
            <input type="text" value={queryQ} onChange={(event) => setQuery({ q: event.target.value || null, page: "1" })} placeholder="제목 / 카테고리 / URL" className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm" />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            정렬 기준
            <select value={querySort} onChange={(event) => setQuery({ sort: event.target.value, page: "1" })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              <option value="publishedAt">발행일</option>
              <option value="title">제목</option>
              <option value="status">상태</option>
              <option value="seo">SEO</option>
              <option value="geo">GEO</option>
              <option value="ctr">CTR</option>
              <option value="lighthouse">Lighthouse</option>
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            정렬 방향
            <select value={queryDir} onChange={(event) => setQuery({ dir: event.target.value, page: "1" })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              <option value="desc">내림차순</option>
              <option value="asc">오름차순</option>
            </select>
          </label>
        </div>
      </section>

      {error ? <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}

      {loading ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-6 text-sm text-slate-500">분석 데이터를 불러오는 중입니다.</div>
      ) : queryView === "calendar" ? (
        <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="grid grid-cols-7 gap-2 text-center text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
            {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((weekday) => (
              <div key={weekday} className="rounded-xl bg-slate-100 px-2 py-2">{weekday}</div>
            ))}
          </div>
          <div className="mt-3 grid grid-cols-7 gap-2">
            {calendarCells.map((cell, index) => (
              <div key={`${cell.dateKey ?? "blank"}-${index}`} className={`min-h-[130px] rounded-2xl border p-3 ${cell.dateKey ? "border-slate-200 bg-slate-50" : "border-transparent bg-transparent"}`}>
                {cell.dateKey ? (
                  <>
                    <p className="text-xs font-semibold text-slate-600">{formatDate(cell.dateKey)}</p>
                    <p className="mt-2 text-sm font-semibold text-slate-900">게시 {cell.summary?.totalPosts ?? 0}</p>
                    <p className="mt-1 text-xs text-slate-600">SEO {formatScore(cell.summary?.avgSeo ?? null)}</p>
                    <p className="text-xs text-slate-600">GEO {formatScore(cell.summary?.avgGeo ?? null)}</p>
                  </>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="rounded-[28px] border border-slate-200 bg-white p-0 shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1480px] border-collapse text-sm">
              <thead>
                <tr className="bg-slate-100 text-left text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("seo")}>SEO</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("geo")}>GEO</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("ctr")}>CTR</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("lighthouse")}>Lighthouse</button></th>
                  <th className="px-3 py-3">색인 여부</th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("publishedAt")}>발행일</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("title")}>제목</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("status")}>상태</button></th>
                  <th className="px-3 py-3">품질 상태</th>
                  <th className="px-3 py-3">URL</th>
                  <th className="px-3 py-3">액션</th>
                </tr>
              </thead>
              <tbody>
                {pagedRows.map((row) => {
                  const statusTone = statusBadge(row);
                  const displayTitle = row.title ? truncateTitle(row.title) : "(제목 없음)";
                  return (
                    <tr key={row.id} className="border-t border-slate-100 align-top hover:bg-slate-50">
                      <td className="px-3 py-3"><ScoreBadge value={row.seoScore} /></td>
                      <td className="px-3 py-3"><ScoreBadge value={row.geoScore} /></td>
                      <td className="px-3 py-3"><ScoreBadge value={row.ctrScore} /></td>
                      <td className="px-3 py-3"><ScoreBadge value={row.lighthouseScore} /></td>
                      <td className="px-3 py-3">
                        <span className={`rounded-lg px-2 py-1 text-xs font-semibold ${indexStatusTone(row.indexStatus)}`}>
                          {row.indexStatus ?? "unknown"}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-600">{formatPublishedDate(row.publishedAt)}</td>
                      <td className="max-w-[320px] px-3 py-3 font-medium text-slate-900" title={row.title || "(제목 없음)"}>
                        {displayTitle}
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-600">
                        <span className={`rounded-lg px-2 py-1 text-xs font-semibold ${statusTone.className}`}>
                          {statusTone.label}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <span className={`rounded-lg px-2 py-1 text-xs font-semibold ${row.lighthouseLow ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700"}`}>
                          {row.lighthouseLow ? "주의" : "정상"}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs">
                        {row.actualUrl ? (
                          <Link href={row.actualUrl} target="_blank" className="text-sky-700 underline-offset-2 hover:underline">
                            링크 열기
                          </Link>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-xs">
                        {row.canManualDelete ? (
                          <button
                            type="button"
                            onClick={() => handleManualDelete(row)}
                            disabled={deletingFactId === row.id}
                            className="rounded-lg border border-rose-200 px-3 py-1 font-semibold text-rose-700 disabled:opacity-40"
                          >
                            {deletingFactId === row.id ? "삭제 중" : "수동 삭제"}
                          </button>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {pagedRows.length === 0 ? (
                  <tr>
                    <td colSpan={11} className="px-4 py-8 text-center text-sm text-slate-500">조건에 맞는 게시글이 없습니다.</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-sm">
            <p className="text-slate-600">페이지 {currentPage} / {totalPages}</p>
            <div className="flex gap-2">
              <button type="button" disabled={currentPage <= 1} onClick={() => setQuery({ page: String(currentPage - 1) })} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40">
                이전
              </button>
              <button type="button" disabled={currentPage >= totalPages} onClick={() => setQuery({ page: String(currentPage + 1) })} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40">
                다음
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

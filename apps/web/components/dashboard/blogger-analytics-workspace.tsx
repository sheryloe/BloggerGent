"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { getBlogDailySummary, getBlogMonthlyArticles } from "@/lib/api";
import type { AnalyticsArticleFactRead, AnalyticsDailySummaryRead, Blog, ManagedChannelRead } from "@/lib/types";

import { AnalyticsPlatformTabs } from "./analytics-platform-tabs";

type BloggerSortKey = "publishedAt" | "title" | "status" | "seo" | "geo" | "ctr" | "dbs";
type SortDir = "asc" | "desc";
type LowFilter = "none" | "any70" | "dbs70";
type ViewMode = "list" | "calendar";

type BloggerRow = AnalyticsArticleFactRead & {
  dbsScore: number;
  lowFlag: boolean;
  blogName: string;
};

const PAGE_SIZE = 25;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function scoreOrZero(value: number | null) {
  return Number.isFinite(value as number) ? Number(value) : 0;
}

function computeDbs(row: AnalyticsArticleFactRead) {
  const seo = scoreOrZero(row.seoScore);
  const geo = scoreOrZero(row.geoScore);
  const ctr = scoreOrZero(row.ctr);
  const raw = seo * 0.4 + geo * 0.35 + ctr * 0.25;
  return clamp(Math.round(raw * 10) / 10, 0, 100);
}

function isAnyLow(row: AnalyticsArticleFactRead) {
  const seo = scoreOrZero(row.seoScore);
  const geo = scoreOrZero(row.geoScore);
  const ctr = scoreOrZero(row.ctr);
  return seo < 70 || geo < 70 || ctr < 70;
}

function formatScore(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "-";
  return `${Math.round(value * 10) / 10}`;
}

function formatDateTime(value: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
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

function lowToneClass(value: number) {
  if (value >= 80) return "bg-emerald-100 text-emerald-700";
  if (value >= 70) return "bg-sky-100 text-sky-700";
  return "bg-rose-100 text-rose-700";
}

function mapApiSort(sort: BloggerSortKey): "published_at" | "seo" | "geo" | "similarity" | "title" {
  if (sort === "seo") return "seo";
  if (sort === "geo") return "geo";
  if (sort === "title") return "title";
  return "published_at";
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

  const selectedBlog = useMemo(() => {
    if (!selectedBlogId) return null;
    return availableBlogs.find((blog) => blog.id === selectedBlogId) ?? null;
  }, [availableBlogs, selectedBlogId]);

  const [facts, setFacts] = useState<AnalyticsArticleFactRead[]>([]);
  const [dailySummaries, setDailySummaries] = useState<AnalyticsDailySummaryRead[]>([]);
  const [loading, setLoading] = useState(false);
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
        pageSize: 500,
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
    const blogName = selectedBlog?.name ?? "-";
    return facts.map((item) => ({
      ...item,
      dbsScore: computeDbs(item),
      lowFlag: isAnyLow(item),
      blogName,
    }));
  }, [facts, selectedBlog]);

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
      return row.dbsScore < 70;
    });

    const sorted = [...byLow].sort((a, b) => {
      const direction = queryDir === "asc" ? 1 : -1;
      const compareText = (left: string | null | undefined, right: string | null | undefined) =>
        (left ?? "").localeCompare(right ?? "", "ko");

      if (querySort === "title") return compareText(a.title, b.title) * direction;
      if (querySort === "status") return compareText(a.status, b.status) * direction;
      if (querySort === "publishedAt") {
        const left = a.publishedAt ? new Date(a.publishedAt).getTime() : 0;
        const right = b.publishedAt ? new Date(b.publishedAt).getTime() : 0;
        return (left - right) * direction;
      }
      if (querySort === "seo") return (scoreOrZero(a.seoScore) - scoreOrZero(b.seoScore)) * direction;
      if (querySort === "geo") return (scoreOrZero(a.geoScore) - scoreOrZero(b.geoScore)) * direction;
      if (querySort === "ctr") return (scoreOrZero(a.ctr) - scoreOrZero(b.ctr)) * direction;
      return (a.dbsScore - b.dbsScore) * direction;
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
  const dbsLowCount = filteredRows.filter((row) => row.dbsScore < 70).length;
  const calendarCells = useMemo(() => buildCalendarCells(queryMonth, dailySummaries), [queryMonth, dailySummaries]);

  return (
    <div className="space-y-5">
      <AnalyticsPlatformTabs />

      <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">Blogger Analytics</p>
            <h1 className="mt-2 text-2xl font-semibold text-slate-900">게시글 성과 테이블</h1>
            <p className="mt-1 text-sm text-slate-600">SEO, GEO, CTR, DBS 지표를 블로그별로 정렬하고 필터링할 수 있습니다.</p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs font-semibold">
            <span className="rounded-xl bg-slate-100 px-3 py-2 text-slate-700">행 수 {filteredRows.length}</span>
            <span className="rounded-xl bg-rose-100 px-3 py-2 text-rose-700">저점 항목 {lowCount}</span>
            <span className="rounded-xl bg-amber-100 px-3 py-2 text-amber-700">DBS 70 미만 {dbsLowCount}</span>
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
              <option value="any70">SEO/GEO/CTR 중 70 미만</option>
              <option value="dbs70">DBS 70 미만</option>
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
              <option value="dbs">DBS</option>
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
            <table className="w-full min-w-[1420px] border-collapse text-sm">
              <thead>
                <tr className="bg-slate-100 text-left text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("publishedAt")}>발행일</button></th>
                  <th className="px-3 py-3">블로그</th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("title")}>제목</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("status")}>상태</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("seo")}>SEO</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("geo")}>GEO</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("ctr")}>CTR</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("dbs")}>DBS</button></th>
                  <th className="px-3 py-3">품질 상태</th>
                  <th className="px-3 py-3">URL</th>
                </tr>
              </thead>
              <tbody>
                {pagedRows.map((row) => (
                  <tr key={row.id} className="border-t border-slate-100 align-top hover:bg-slate-50">
                    <td className="px-3 py-3 text-xs text-slate-600">{formatDateTime(row.publishedAt)}</td>
                    <td className="px-3 py-3 text-xs text-slate-700">{row.blogName}</td>
                    <td className="px-3 py-3 font-medium text-slate-900">{row.title || "(제목 없음)"}</td>
                    <td className="px-3 py-3 text-xs text-slate-600">{row.status ?? "-"}</td>
                    <td className="px-3 py-3"><span className={`rounded-lg px-2 py-1 text-xs font-semibold ${lowToneClass(scoreOrZero(row.seoScore))}`}>{formatScore(row.seoScore)}</span></td>
                    <td className="px-3 py-3"><span className={`rounded-lg px-2 py-1 text-xs font-semibold ${lowToneClass(scoreOrZero(row.geoScore))}`}>{formatScore(row.geoScore)}</span></td>
                    <td className="px-3 py-3"><span className={`rounded-lg px-2 py-1 text-xs font-semibold ${lowToneClass(scoreOrZero(row.ctr))}`}>{formatScore(row.ctr)}</span></td>
                    <td className="px-3 py-3"><span className={`rounded-lg px-2 py-1 text-xs font-semibold ${lowToneClass(row.dbsScore)}`}>{formatScore(row.dbsScore)}</span></td>
                    <td className="px-3 py-3">
                      <span className={`rounded-lg px-2 py-1 text-xs font-semibold ${row.lowFlag ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700"}`}>
                        {row.lowFlag ? "주의" : "정상"}
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
                  </tr>
                ))}
                {pagedRows.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="px-4 py-8 text-center text-sm text-slate-500">조건에 맞는 게시글이 없습니다.</td>
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

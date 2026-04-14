"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { getCloudflarePerformance, getCloudflarePerformanceSummary } from "@/lib/api";
import type { CloudflarePerformancePageRead, CloudflarePerformanceRowRead, CloudflarePerformanceSummaryRead } from "@/lib/types";

import { AnalyticsPlatformTabs } from "./analytics-platform-tabs";

type CloudflareSortKey = "publishedAt" | "title" | "seo" | "geo" | "ctr" | "lighthouse";
type SortDir = "asc" | "desc";
type LowFilter = "none" | "any70" | "any80" | "refactor80" | "lighthouse70";

const PAGE_SIZE = 25;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function toNumber(value: string | null, fallback = 1) {
  const parsed = Number(value ?? "");
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function scoreOrZero(value: number | null | undefined) {
  return Number.isFinite(value as number) ? Number(value) : 0;
}

function formatScore(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "-";
  return `${Math.round(value * 10) / 10}`;
}

function formatPublishedDate(value: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function truncateTitle(value: string, limit = 34) {
  if (value.length <= limit) return value;
  return `${value.slice(0, limit)}...`;
}

function scoreBadgeTone(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) {
    return { badgeClass: "bg-slate-100 text-slate-500", dotClass: "bg-slate-400" };
  }
  if (value >= 90) {
    return { badgeClass: "bg-emerald-100 text-emerald-700", dotClass: "bg-emerald-500" };
  }
  if (value >= 80) {
    return { badgeClass: "bg-violet-100 text-violet-700", dotClass: "bg-violet-500" };
  }
  if (value >= 70) {
    return { badgeClass: "bg-sky-100 text-sky-700", dotClass: "bg-sky-500" };
  }
  if (value <= 50) {
    return { badgeClass: "bg-rose-100 text-rose-700", dotClass: "bg-rose-500" };
  }
  return { badgeClass: "bg-amber-100 text-amber-700", dotClass: "bg-amber-500" };
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

function indexStatusTone(status: string | null | undefined) {
  const normalized = String(status ?? "unknown").trim().toLowerCase();
  if (normalized === "indexed") return "bg-emerald-100 text-emerald-700";
  if (normalized === "submitted") return "bg-blue-100 text-blue-700";
  if (normalized === "pending") return "bg-amber-100 text-amber-700";
  if (normalized === "blocked") return "bg-rose-100 text-rose-800";
  if (normalized === "failed") return "bg-rose-100 text-rose-700";
  return "bg-slate-100 text-slate-600";
}

function statusBadge(row: CloudflarePerformanceRowRead) {
  const normalized = String(row.status ?? "").trim().toLowerCase();
  if (normalized === "published") {
    return { label: "Published", className: "bg-emerald-100 text-emerald-700" };
  }
  if (normalized === "live") {
    return { label: "Live", className: "bg-emerald-100 text-emerald-700" };
  }
  return {
    label: row.status ? row.status : "unknown",
    className: "bg-slate-100 text-slate-600",
  };
}

function isLow(row: CloudflarePerformanceRowRead) {
  return (
    scoreOrZero(row.seoScore) < 70 ||
    scoreOrZero(row.geoScore) < 70 ||
    scoreOrZero(row.ctr) < 70 ||
    scoreOrZero(row.lighthouseScore) < 70
  );
}

function isRefactorCandidate(row: CloudflarePerformanceRowRead) {
  return (
    scoreOrZero(row.seoScore) < 80 ||
    scoreOrZero(row.geoScore) < 80 ||
    scoreOrZero(row.ctr) < 80 ||
    scoreOrZero(row.lighthouseScore) < 80
  );
}

function mapApiSort(sort: CloudflareSortKey): "published_at" | "title" | "seo" | "geo" | "ctr" | "lighthouse" {
  if (sort === "publishedAt") return "published_at";
  if (sort === "title") return "title";
  if (sort === "seo") return "seo";
  if (sort === "geo") return "geo";
  if (sort === "ctr") return "ctr";
  return "lighthouse";
}

export function CloudflareAnalyticsWorkspace() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const defaultMonth = useMemo(() => new Date().toISOString().slice(0, 7), []);

  const queryMonth = searchParams.get("month") ?? defaultMonth;
  const queryCategory = (searchParams.get("category") ?? "").trim();
  const queryLow = (searchParams.get("low") as LowFilter | null) ?? "none";
  const queryQ = (searchParams.get("q") ?? "").trim();
  const queryStatus = (searchParams.get("status") ?? "").trim();
  const querySort = (searchParams.get("sort") as CloudflareSortKey | null) ?? "publishedAt";
  const queryDir = (searchParams.get("dir") as SortDir | null) ?? "desc";
  const queryPage = toNumber(searchParams.get("page"), 1);

  const [payload, setPayload] = useState<CloudflarePerformancePageRead | null>(null);
  const [summary, setSummary] = useState<CloudflarePerformanceSummaryRead | null>(null);
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

  const handleSort = (key: CloudflareSortKey) => {
    if (querySort === key) {
      setQuery({ dir: queryDir === "asc" ? "desc" : "asc", page: "1" });
      return;
    }
    const defaultDir: SortDir = key === "title" ? "asc" : "desc";
    setQuery({ sort: key, dir: defaultDir, page: "1" });
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      getCloudflarePerformance({
        month: queryMonth,
        status: queryStatus || null,
        category: queryCategory || null,
        sort: mapApiSort(querySort),
        dir: queryDir,
        page: 1,
        pageSize: 500,
      }),
      getCloudflarePerformanceSummary(queryMonth),
    ])
      .then(([pagePayload, summaryPayload]) => {
        if (cancelled) return;
        setPayload(pagePayload);
        setSummary(summaryPayload);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        const message = cause instanceof Error ? cause.message : "Cloudflare 성과 데이터를 불러오지 못했습니다.";
        setError(message);
        setPayload(null);
        setSummary(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [queryCategory, queryDir, queryMonth, querySort, queryStatus]);

  const rows = payload?.items ?? [];

  const filteredRows = useMemo(() => {
    const loweredQ = queryQ.toLowerCase();
    const searched = rows.filter((row) => {
      if (!loweredQ) return true;
      const title = row.title.toLowerCase();
      const category = (row.canonicalCategoryName ?? row.categoryName ?? "").toLowerCase();
      const url = (row.url ?? "").toLowerCase();
      return title.includes(loweredQ) || category.includes(loweredQ) || url.includes(loweredQ);
    });

    const lowFiltered = searched.filter((row) => {
      if (queryLow === "none") return true;
      if (queryLow === "any70") return isLow(row);
      if (queryLow === "any80" || queryLow === "refactor80") return isRefactorCandidate(row);
      return scoreOrZero(row.lighthouseScore) < 70;
    });

    const sorted = [...lowFiltered].sort((a, b) => {
      const direction = queryDir === "asc" ? 1 : -1;
      if (querySort === "title") return a.title.localeCompare(b.title, "ko") * direction;
      if (querySort === "publishedAt") {
        const left = a.publishedAt ? new Date(a.publishedAt).getTime() : 0;
        const right = b.publishedAt ? new Date(b.publishedAt).getTime() : 0;
        return (left - right) * direction;
      }
      if (querySort === "seo") return (scoreOrZero(a.seoScore) - scoreOrZero(b.seoScore)) * direction;
      if (querySort === "geo") return (scoreOrZero(a.geoScore) - scoreOrZero(b.geoScore)) * direction;
      if (querySort === "ctr") return (scoreOrZero(a.ctr) - scoreOrZero(b.ctr)) * direction;
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

  const lowCount = filteredRows.filter((row) => isLow(row)).length;
  const refactorCandidateCount = filteredRows.filter((row) => isRefactorCandidate(row)).length;
  const lighthouseLowCount = filteredRows.filter((row) => scoreOrZero(row.lighthouseScore) < 70).length;

  return (
    <div className="space-y-5">
      <AnalyticsPlatformTabs />

      <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">Cloudflare Analytics</p>
            <h1 className="mt-2 text-2xl font-semibold text-slate-900">게시글 성과 테이블</h1>
            <p className="mt-1 text-sm text-slate-600">SEO, GEO, CTR 점수, Lighthouse, 색인 상태와 이미지 포맷 수를 한 줄에서 확인합니다.</p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs font-semibold">
            <span className="rounded-xl bg-slate-100 px-3 py-2 text-slate-700">행 수 {filteredRows.length}</span>
            <span className="rounded-xl bg-rose-100 px-3 py-2 text-rose-700">저점 항목 {lowCount}</span>
            <span className="rounded-xl bg-violet-100 px-3 py-2 text-violet-700">리팩토링 후보 {refactorCandidateCount}</span>
            <span className="rounded-xl bg-amber-100 px-3 py-2 text-amber-700">Lighthouse 70 미만 {lighthouseLowCount}</span>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-8">
          <label className="text-xs font-semibold text-slate-600">
            기준 월
            <input type="month" value={queryMonth} onChange={(event) => setQuery({ month: event.target.value, page: "1" })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm" />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            카테고리
            <select value={queryCategory} onChange={(event) => setQuery({ category: event.target.value || null, page: "1" })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              <option value="">전체</option>
              {(summary?.availableCategories ?? []).map((item) => (
                <option key={item.slug} value={item.slug}>{item.name}</option>
              ))}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            보기 방식
            <select value="list" disabled className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              <option value="list">글 목록</option>
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            저점 필터
            <select value={queryLow} onChange={(event) => setQuery({ low: event.target.value, page: "1" })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              <option value="none">전체</option>
              <option value="any70">SEO/GEO/CTR/Lighthouse 중 70 미만</option>
              <option value="refactor80">리팩토링 후보 80 미만</option>
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
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-6 text-sm text-slate-500">Cloudflare 성과 데이터를 불러오는 중입니다.</div>
      ) : (
        <section className="rounded-[28px] border border-slate-200 bg-white p-0 shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1780px] border-collapse text-sm">
              <thead>
                <tr className="bg-slate-100 text-left text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("seo")}>SEO</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("geo")}>GEO</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("ctr")}>CTR</button></th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("lighthouse")}>Lighthouse</button></th>
                  <th className="px-3 py-3">색인 여부</th>
                  <th className="px-3 py-3">이미지</th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("publishedAt")}>발행일</button></th>
                  <th className="px-3 py-3">카테고리</th>
                  <th className="px-3 py-3"><button type="button" onClick={() => handleSort("title")}>제목</button></th>
                  <th className="px-3 py-3">상태</th>
                  <th className="px-3 py-3">품질 상태</th>
                  <th className="px-3 py-3">URL</th>
                </tr>
              </thead>
              <tbody>
                {pagedRows.map((row, index) => {
                  const statusTone = statusBadge(row);
                  const displayTitle = truncateTitle(row.title || "(제목 없음)");
                  return (
                    <tr key={`${row.url ?? row.title}-${index}`} className="border-t border-slate-100 align-top hover:bg-slate-50">
                      <td className="px-3 py-3"><ScoreBadge value={row.seoScore} /></td>
                      <td className="px-3 py-3"><ScoreBadge value={row.geoScore} /></td>
                      <td className="px-3 py-3"><ScoreBadge value={row.ctr} /></td>
                      <td className="px-3 py-3"><ScoreBadge value={row.lighthouseScore} /></td>
                      <td className="px-3 py-3">
                        <span className={`rounded-lg px-2 py-1 text-xs font-semibold ${indexStatusTone(row.indexStatus)}`}>
                          {row.indexStatus}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-600">
                        <div>총 {row.liveImageCount ?? "-"}</div>
                        <div>webp {row.liveWebpCount ?? "-"}</div>
                        <div>png {row.livePngCount ?? "-"}</div>
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-600">{formatPublishedDate(row.publishedAt)}</td>
                      <td className="px-3 py-3 text-xs text-slate-600">{row.canonicalCategoryName ?? row.categoryName ?? "-"}</td>
                      <td className="max-w-[340px] px-3 py-3 font-medium text-slate-900" title={row.title}>{displayTitle}</td>
                      <td className="px-3 py-3 text-xs">
                        <span className={`rounded-lg px-2 py-1 text-xs font-semibold ${statusTone.className}`}>{statusTone.label}</span>
                      </td>
                      <td className="px-3 py-3">
                        <span className={`rounded-lg px-2 py-1 text-xs font-semibold ${isLow(row) ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700"}`}>
                          {isLow(row) ? "주의" : "정상"}
                        </span>
                        {row.refactorCandidate && !isLow(row) ? (
                          <div className="mt-1">
                            <span className="rounded-lg bg-violet-100 px-2 py-1 text-[11px] font-semibold text-violet-700">
                              리팩토링 후보
                            </span>
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-3 text-xs">
                        {row.url ? (
                          <Link href={row.url} target="_blank" className="text-sky-700 underline-offset-2 hover:underline">
                            링크 열기
                          </Link>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {pagedRows.length === 0 ? (
                  <tr>
                    <td colSpan={12} className="px-4 py-8 text-center text-sm text-slate-500">조건에 맞는 게시글이 없습니다.</td>
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

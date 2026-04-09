"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { getWorkspaceContentItems } from "@/lib/api";
import type { ContentItemRead, ManagedChannelRead } from "@/lib/types";

import { AnalyticsPlatformTabs } from "./analytics-platform-tabs";

type PlatformProvider = "youtube" | "instagram";
type SortKey = "updatedAt" | "publishedAt" | "title" | "status";
type SortDir = "asc" | "desc";

const PAGE_SIZE = 25;

function toNumber(value: string | null, fallback = 1) {
  const parsed = Number(value ?? "");
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
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

function providerLabel(provider: PlatformProvider) {
  return provider === "youtube" ? "YouTube" : "Instagram";
}

export function MediaAnalyticsWorkspace({ provider, channels }: { provider: PlatformProvider; channels: ManagedChannelRead[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const queryQ = (searchParams.get("q") ?? "").trim().toLowerCase();
  const queryStatus = (searchParams.get("status") ?? "").trim().toLowerCase();
  const querySort = (searchParams.get("sort") as SortKey | null) ?? "updatedAt";
  const queryDir = (searchParams.get("dir") as SortDir | null) ?? "desc";
  const queryPage = toNumber(searchParams.get("page"), 1);

  const [items, setItems] = useState<ContentItemRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setQuery = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams.toString());
    Object.entries(patch).forEach(([key, value]) => {
      if (value == null || value === "") next.delete(key);
      else next.set(key, value);
    });
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname);
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getWorkspaceContentItems({ provider, limit: 200 })
      .then((payload) => {
        if (!cancelled) setItems(payload ?? []);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        const message = cause instanceof Error ? cause.message : "콘텐츠 목록을 불러오지 못했습니다.";
        setError(message);
        setItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [provider]);

  const channelNameById = useMemo(() => {
    const map = new Map<string, string>();
    channels
      .filter((channel) => channel.provider === provider)
      .forEach((channel) => map.set(channel.channelId, channel.name));
    return map;
  }, [channels, provider]);

  const filteredItems = useMemo(() => {
    const searched = items.filter((item) => {
      if (!queryQ) return true;
      const text = `${item.title} ${item.channelId} ${item.contentType}`.toLowerCase();
      return text.includes(queryQ);
    });

    const statusFiltered = searched.filter((item) => {
      if (!queryStatus) return true;
      const lifecycle = (item.lifecycleStatus ?? "").toLowerCase();
      const publication = (item.latestPublication?.publishStatus ?? "").toLowerCase();
      return lifecycle.includes(queryStatus) || publication.includes(queryStatus);
    });

    const sorted = [...statusFiltered].sort((a, b) => {
      const direction = queryDir === "asc" ? 1 : -1;
      const compareText = (left: string | null | undefined, right: string | null | undefined) =>
        (left ?? "").localeCompare(right ?? "", "ko");

      if (querySort === "title") return compareText(a.title, b.title) * direction;
      if (querySort === "status") return compareText(a.lifecycleStatus, b.lifecycleStatus) * direction;
      if (querySort === "publishedAt") {
        const left = a.latestPublication?.publishedAt ? new Date(a.latestPublication.publishedAt).getTime() : 0;
        const right = b.latestPublication?.publishedAt ? new Date(b.latestPublication.publishedAt).getTime() : 0;
        return (left - right) * direction;
      }
      return (new Date(a.updatedAt).getTime() - new Date(b.updatedAt).getTime()) * direction;
    });

    return sorted;
  }, [items, queryDir, queryQ, querySort, queryStatus]);

  const totalPages = Math.max(1, Math.ceil(filteredItems.length / PAGE_SIZE));
  const currentPage = clamp(queryPage, 1, totalPages);
  const pagedItems = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredItems.slice(start, start + PAGE_SIZE);
  }, [currentPage, filteredItems]);

  return (
    <div className="space-y-5">
      <AnalyticsPlatformTabs />

      <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">{providerLabel(provider)} Analytics</p>
            <h1 className="mt-2 text-2xl font-semibold text-slate-900">플랫폼 콘텐츠 리스트</h1>
            <p className="mt-1 text-sm text-slate-600">통합 분석 없이 플랫폼 단위로 목록/상태를 확인합니다.</p>
          </div>
          <span className="rounded-xl bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-700">Rows {filteredItems.length}</span>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="text-xs font-semibold text-slate-600">
            검색
            <input
              type="text"
              value={searchParams.get("q") ?? ""}
              onChange={(event) => setQuery({ q: event.target.value || null, page: "1" })}
              placeholder="제목/채널/타입"
              className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            상태
            <input
              type="text"
              value={searchParams.get("status") ?? ""}
              onChange={(event) => setQuery({ status: event.target.value || null, page: "1" })}
              placeholder="published/live"
              className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            정렬
            <select
              value={querySort}
              onChange={(event) => setQuery({ sort: event.target.value, page: "1" })}
              className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
            >
              <option value="updatedAt">수정일</option>
              <option value="publishedAt">발행일</option>
              <option value="title">제목</option>
              <option value="status">상태</option>
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            방향
            <select
              value={queryDir}
              onChange={(event) => setQuery({ dir: event.target.value, page: "1" })}
              className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
            >
              <option value="desc">내림차순</option>
              <option value="asc">오름차순</option>
            </select>
          </label>
        </div>
      </section>

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      ) : null}

      {loading ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-6 text-sm text-slate-500">콘텐츠를 로딩 중입니다.</div>
      ) : (
        <section className="rounded-[28px] border border-slate-200 bg-white p-0 shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1240px] border-collapse text-sm">
              <thead>
                <tr className="bg-slate-100 text-left text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  <th className="px-3 py-3">수정일</th>
                  <th className="px-3 py-3">채널</th>
                  <th className="px-3 py-3">제목</th>
                  <th className="px-3 py-3">콘텐츠 타입</th>
                  <th className="px-3 py-3">상태</th>
                  <th className="px-3 py-3">발행 상태</th>
                  <th className="px-3 py-3">발행일</th>
                  <th className="px-3 py-3">원격 URL</th>
                </tr>
              </thead>
              <tbody>
                {pagedItems.map((item) => (
                  <tr key={item.id} className="border-t border-slate-100 align-top hover:bg-slate-50">
                    <td className="px-3 py-3 text-xs text-slate-600">{formatDateTime(item.updatedAt)}</td>
                    <td className="px-3 py-3 text-xs text-slate-700">{channelNameById.get(item.channelId) ?? item.channelId}</td>
                    <td className="px-3 py-3 font-medium text-slate-900">{item.title || "(제목 없음)"}</td>
                    <td className="px-3 py-3 text-xs text-slate-600">{item.contentType}</td>
                    <td className="px-3 py-3 text-xs text-slate-600">{item.lifecycleStatus}</td>
                    <td className="px-3 py-3 text-xs text-slate-600">{item.latestPublication?.publishStatus ?? "-"}</td>
                    <td className="px-3 py-3 text-xs text-slate-600">{formatDateTime(item.latestPublication?.publishedAt ?? null)}</td>
                    <td className="px-3 py-3 text-xs">
                      {item.latestPublication?.remoteUrl ? (
                        <Link href={item.latestPublication.remoteUrl} target="_blank" className="text-sky-700 underline-offset-2 hover:underline">
                          링크 열기
                        </Link>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                  </tr>
                ))}
                {pagedItems.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-sm text-slate-500">
                      조건에 맞는 항목이 없습니다.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-sm">
            <p className="text-slate-600">
              Page {currentPage} / {totalPages}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={currentPage <= 1}
                onClick={() => setQuery({ page: String(currentPage - 1) })}
                className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40"
              >
                이전
              </button>
              <button
                type="button"
                disabled={currentPage >= totalPages}
                onClick={() => setQuery({ page: String(currentPage + 1) })}
                className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40"
              >
                다음
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import { applyNextMonthWeights, getCloudflarePosts, getIntegratedAnalytics } from "@/lib/api";
import type { AnalyticsArticleFactRead, AnalyticsIntegratedRead, BlogRead, ManagedChannelRead } from "@/lib/types";

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
  facts: AnalyticsArticleFactRead[];
};

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

function buildMonthCells(month: string, grouped: Map<string, AnalyticsArticleFactRead[]>) {
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
      facts: grouped.get(dateKey) ?? [],
    });
  }

  return cells;
}

function numberText(value: number | null | undefined, fractionDigits = 1) {
  if (value === null || value === undefined) return "N/A";
  return Number(value).toFixed(fractionDigits);
}

function sourceTone(sourceType: string) {
  return sourceType === "generated"
    ? "bg-indigo-50 text-indigo-700"
    : "bg-slate-100 text-slate-600";
}

function scoreTone(score: number | null) {
  if (score === null) return "bg-slate-100 text-slate-500";
  if (score >= 80) return "bg-emerald-50 text-emerald-700";
  if (score >= 60) return "bg-amber-50 text-amber-700";
  return "bg-rose-50 text-rose-700";
}

function compareNullable(left: number | string | null, right: number | string | null, dir: SortDir) {
  if (left === null && right === null) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  if (typeof left === "number" && typeof right === "number") return dir === "asc" ? left - right : right - left;
  const result = String(left).localeCompare(String(right));
  return dir === "asc" ? result : -result;
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

function dailyAverageSeo(items: AnalyticsArticleFactRead[]) {
  const scored = items.filter((item) => item.seoScore !== null);
  if (!scored.length) return null;
  return scored.reduce((sum, item) => sum + (item.seoScore ?? 0), 0) / scored.length;
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

  const [payload, setPayload] = useState<AnalyticsIntegratedRead | null>(null);
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null);
  const [cloudflarePosts, setCloudflarePosts] = useState<Array<{ title: string; published_url?: string | null; status?: string | null; category_slug?: string | null }>>([]);
  const [status, setStatus] = useState("");

  const selectedChannel = useMemo(() => channels.find((channel) => channel.channelId === selectedChannelId) ?? null, [channels, selectedChannelId]);
  const report = payload?.report ?? null;

  function setQuery(updates: Record<string, string | null | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === undefined || value === "") next.delete(key);
      else next.set(key, value);
    }
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  async function load() {
    try {
      setStatus("분석 데이터를 불러오는 중입니다.");
      const next = await getIntegratedAnalytics({
        month,
        range: "month",
        blogId,
        sourceType,
        themeKey: themeFilter || null,
        category: categoryFilter || null,
        status: statusFilter || null,
      });
      setPayload(next);
      setStatus("");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "분석 데이터를 불러오지 못했습니다.");
    }
  }

  useEffect(() => {
    void load();
  }, [month, blogId, sourceType, themeFilter, categoryFilter, statusFilter]);

  const sortedFacts = useMemo(() => {
    const items = [...(report?.articleFacts ?? [])];
    return items.sort((left, right) => {
      if (sortKey === "seo") return compareNullable(left.seoScore, right.seoScore, sortDir);
      if (sortKey === "geo") return compareNullable(left.geoScore, right.geoScore, sortDir);
      if (sortKey === "similarity") return compareNullable(left.similarityScore, right.similarityScore, sortDir);
      return compareNullable(left.publishedAt, right.publishedAt, sortDir);
    });
  }, [report, sortDir, sortKey]);

  const groupedByDate = useMemo(() => {
    const map = new Map<string, AnalyticsArticleFactRead[]>();
    for (const item of sortedFacts) {
      const dateKey = item.publishedAt?.slice(0, 10);
      if (!dateKey) continue;
      const list = map.get(dateKey) ?? [];
      list.push(item);
      map.set(dateKey, list);
    }
    return map;
  }, [sortedFacts]);

  const selectedDate = useMemo(() => {
    if (selectedDateFromQuery) return selectedDateFromQuery;
    return [...groupedByDate.keys()][0] ?? `${month}-01`;
  }, [groupedByDate, month, selectedDateFromQuery]);

  useEffect(() => {
    if (!selectedDateFromQuery && selectedDate) {
      setQuery({ selectedDate, detailTab });
    }
  }, [selectedDateFromQuery, selectedDate, detailTab]);

  const monthCells = useMemo(() => buildMonthCells(month, groupedByDate), [groupedByDate, month]);
  const selectedDayFacts = useMemo(() => groupedByDate.get(selectedDate) ?? [], [groupedByDate, selectedDate]);
  const weekDateKeys = useMemo(() => buildWeekDays(selectedDate), [selectedDate]);
  const weekFacts = useMemo(
    () => weekDateKeys.map((dateKey) => ({ dateKey, items: groupedByDate.get(dateKey) ?? [] })),
    [groupedByDate, weekDateKeys],
  );

  const strongest = useMemo(() => pickArticle(report?.articleFacts ?? [], "best"), [report]);
  const weakest = useMemo(() => pickArticle(report?.articleFacts ?? [], "worst"), [report]);
  const generatedCount = useMemo(() => (report?.articleFacts ?? []).filter((item) => item.sourceType === "generated").length, [report]);
  const syncedCount = useMemo(() => (report?.articleFacts ?? []).filter((item) => item.sourceType === "synced").length, [report]);

  async function handleApplyWeights() {
    if (!report) return;
    try {
      setStatus("다음 달 비중을 반영하는 중입니다.");
      await applyNextMonthWeights(report.blogId, report.month);
      await load();
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
        setQuery({ blog: String(linkedBlog.id), selectedDate: null, detailTab: "day", category: null, theme: null });
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
          <DetailTabButton active={detailTab === "day"} onClick={() => setQuery({ detailTab: "day" })} label="일간 성과" />
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
              <MiniMetric label="당일 게시" value={`${selectedDayFacts.length}건`} />
              <MiniMetric label="앱 생성" value={`${selectedDayFacts.filter((item) => item.sourceType === 'generated').length}건`} />
              <MiniMetric label="동기화" value={`${selectedDayFacts.filter((item) => item.sourceType === 'synced').length}건`} />
            </div>
            <article className="rounded-[24px] bg-white p-4 shadow-sm">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">선택 날짜 글 목록</p>
                  <p className="mt-1 text-xs text-slate-500">정렬 상태는 URL과 함께 유지됩니다.</p>
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                  <ViewChip label={`정렬 ${sortKey}/${sortDir}`} />
                </div>
              </div>
              <div className="mt-4 space-y-3">
                {selectedDayFacts.length ? selectedDayFacts.map((fact) => (
                  <article key={fact.id} className="rounded-[22px] bg-slate-50 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="line-clamp-2 text-sm font-semibold text-slate-900">{fact.title}</p>
                        <p className="mt-1 text-xs text-slate-500">{fact.category ?? fact.themeName ?? '미분류'} / {fact.status ?? '상태 없음'}</p>
                      </div>
                      <span className={`inline-flex rounded-full px-3 py-1 text-[11px] font-medium ${sourceTone(fact.sourceType)}`}>{fact.sourceType === 'generated' ? '앱 생성' : '동기화'}</span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                      <ScoreBadge score={fact.seoScore} label="SEO" />
                      <ScoreBadge score={fact.geoScore} label="GEO" />
                      <ScoreBadge score={fact.similarityScore} label="유사도" />
                    </div>
                    {fact.actualUrl ? <a href={fact.actualUrl} target="_blank" rel="noreferrer" title={fact.actualUrl} className="mt-3 block truncate text-xs text-indigo-600 hover:underline">{fact.actualUrl}</a> : null}
                  </article>
                )) : <EmptyBlock title="선택 날짜 데이터가 없습니다" body="월간 캔버스에서 다른 날짜를 선택하세요." />}
              </div>
            </article>
          </div>
        ) : detailTab === "week" ? (
          <div className="space-y-4">
            {weekFacts.map(({ dateKey, items }) => (
              <article key={dateKey} className="rounded-[24px] bg-white p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{formatKoreanDate(dateKey)} ({formatWeekday(dateKey)})</p>
                    <p className="mt-1 text-xs text-slate-500">게시 {items.length}건 / 앱 생성 {items.filter((item) => item.sourceType === 'generated').length}건 / 동기화 {items.filter((item) => item.sourceType === 'synced').length}건</p>
                  </div>
                  <button type="button" onClick={() => setQuery({ selectedDate: dateKey, detailTab: 'day' })} className="rounded-2xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-200">당일 보기</button>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <ViewChip label={`평균 SEO ${numberText(dailyAverageSeo(items))}`} />
                  <ViewChip label={`카테고리 ${new Set(items.map((item) => item.category ?? item.themeName ?? '미분류')).size}개`} />
                </div>
              </article>
            ))}
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
            <Field label="기준 월"><input type="month" value={month} onChange={(event) => setQuery({ month: event.target.value, selectedDate: null })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white" /></Field>
            <Field label="출처"><select value={sourceType} onChange={(event) => setQuery({ source: event.target.value || null })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"><option value="all">전체</option><option value="generated">앱 생성</option><option value="synced">동기화</option></select></Field>
            <Field label="카테고리"><select value={categoryFilter} onChange={(event) => setQuery({ category: event.target.value || null })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"><option value="">전체</option>{(payload?.availableCategories ?? []).map((item) => <option key={item} value={item}>{item}</option>)}</select></Field>
            <Field label="상태"><input type="text" value={statusFilter} onChange={(event) => setQuery({ status: event.target.value || null })} placeholder="published" className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white" /></Field>
            <Field label="정렬"><select value={sortKey} onChange={(event) => setQuery({ sort: event.target.value })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"><option value="published_at">발행일</option><option value="seo">SEO</option><option value="geo">GEO</option><option value="similarity">유사도</option></select></Field>
            <Field label="방향"><select value={sortDir} onChange={(event) => setQuery({ dir: event.target.value })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm outline-none focus:bg-white"><option value="desc">내림차순</option><option value="asc">오름차순</option></select></Field>
          </div>
          {status ? <p className="mt-3 text-sm text-indigo-600">{status}</p> : null}
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1.75fr)_440px] 2xl:grid-cols-[minmax(0,1.9fr)_460px]">
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
                <>
                  <div className="mt-5 grid grid-cols-7 gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{['월', '화', '수', '목', '금', '토', '일'].map((label) => <div key={label} className="px-2">{label}</div>)}</div>
                  <div className="mt-3 grid grid-cols-7 gap-3">
                    {monthCells.map((cell, index) => cell ? (
                      <button key={cell.dateKey} type="button" onClick={() => setQuery({ selectedDate: cell.dateKey, detailTab: 'day' })} className={`min-h-[180px] rounded-[26px] p-4 text-left transition ${cell.dateKey === selectedDate ? 'bg-indigo-50 ring-2 ring-indigo-200' : 'bg-slate-50 hover:bg-slate-100'}`}>
                        <div className="flex items-start justify-between gap-3"><p className="text-lg font-semibold text-slate-900">{cell.dayNumber}</p><ViewChip label={`${cell.facts.length}건`} /></div>
                        <p className="mt-2 text-xs text-slate-500">앱 생성 {cell.facts.filter((item) => item.sourceType === 'generated').length} / 동기화 {cell.facts.filter((item) => item.sourceType === 'synced').length}</p>
                        <div className="mt-4 flex flex-wrap gap-2">{cell.facts.slice(0, 2).map((item) => <span key={item.id} className="rounded-full bg-white px-3 py-1 text-[11px] text-slate-600">{item.category ?? item.themeName ?? '미분류'}</span>)}</div>
                        <div className="mt-4 h-2 overflow-hidden rounded-full bg-white"><div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.min(100, Math.max(12, (dailyAverageSeo(cell.facts) ?? 0)))}%` }} /></div>
                        <p className="mt-2 text-xs text-slate-500">평균 SEO {numberText(dailyAverageSeo(cell.facts))}</p>
                      </button>
                    ) : <div key={`empty-${index}`} className="min-h-[180px] rounded-[26px] bg-transparent" />)}
                  </div>
                </>
              )}
            </section>
          </div>

          <div>{detailPanel}</div>
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

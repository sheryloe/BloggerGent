"use client";

import { Fragment, useEffect, useMemo, useRef, useState, useTransition } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ContentOverviewResponse, ContentOverviewRow } from "@/lib/types";

const PROFILE_OPTIONS = [
  { value: "", label: "전체" },
  { value: "korea_travel", label: "korea_travel" },
  { value: "world_mystery", label: "world_mystery" },
] as const;
const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

type ContentOverviewRecalculateResult = {
  updated_articles: number;
  total_articles: number;
  status: string;
};

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `요청 실패 (${response.status})`);
  }

  return response.json() as Promise<T>;
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatScore(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return value.toFixed(1);
}

function clampScore(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function scoreTone(score: number) {
  if (score >= 75) return "border-emerald-200 bg-emerald-500/10 text-emerald-700";
  if (score >= 55) return "border-amber-200 bg-amber-500/10 text-amber-700";
  return "border-rose-200 bg-rose-500/10 text-rose-700";
}

function similarityTone(score: number) {
  if (score >= 75) return "border-rose-200 bg-rose-500/10 text-rose-700";
  if (score >= 55) return "border-amber-200 bg-amber-500/10 text-amber-700";
  return "border-emerald-200 bg-emerald-500/10 text-emerald-700";
}

function actionTone(value: string) {
  if (value.includes("rewrite") || value.includes("duplicate") || value.includes("review")) {
    return "bg-amber-500/10 text-amber-700";
  }
  if (value.includes("fix") || value.includes("cleanup") || value.includes("collage")) {
    return "bg-sky-500/10 text-sky-700";
  }
  return "bg-emerald-500/10 text-emerald-700";
}

function reviewTone(row: Pick<ContentOverviewRow, "auto_fixable" | "manual_review" | "quality_status">) {
  if (row.manual_review) return "bg-amber-500/10 text-amber-700";
  if (row.auto_fixable) return "bg-sky-500/10 text-sky-700";
  if ((row.quality_status ?? "").toLowerCase().includes("ok")) return "bg-emerald-500/10 text-emerald-700";
  return "bg-slate-500/10 text-slate-700";
}

export function ContentOverviewManager({
  initialRows = [],
  initialTotal = 0,
  initialProfile,
  initialPublishedOnly = false,
  initialPage = 1,
  initialPageSize = 50,
}: {
  initialRows?: ContentOverviewRow[];
  initialTotal?: number;
  initialProfile?: string | null;
  initialPublishedOnly?: boolean;
  initialPage?: number;
  initialPageSize?: number;
}) {
  const [rows, setRows] = useState<ContentOverviewRow[]>(initialRows);
  const [total, setTotal] = useState(initialTotal);
  const [profile, setProfile] = useState(initialProfile ?? "");
  const [publishedOnly, setPublishedOnly] = useState(initialPublishedOnly);
  const [page, setPage] = useState(initialPage);
  const [pageSize, setPageSize] = useState(initialPageSize);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [loading, startTransition] = useTransition();
  const [expandedArticleId, setExpandedArticleId] = useState<number | null>(null);
  const initializedRef = useRef(false);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const autoFixCount = useMemo(() => rows.filter((row) => row.auto_fixable).length, [rows]);
  const manualCount = useMemo(() => rows.filter((row) => row.manual_review).length, [rows]);

  const reload = async (targetPage = page, targetPageSize = pageSize) => {
    const query = new URLSearchParams({
      page: String(targetPage),
      page_size: String(targetPageSize),
    });
    if (profile) {
      query.set("profile", profile);
    }
    if (publishedOnly) {
      query.set("published_only", "true");
    }

    const next = await fetchJson<ContentOverviewResponse>(`/content-ops/overview?${query.toString()}`);
    setRows(next.rows);
    setTotal(next.total);
    setError("");
  };

  useEffect(() => {
    if (!initializedRef.current) {
      initializedRef.current = true;
      return;
    }
    startTransition(() => {
      void reload();
    });
  }, [profile, publishedOnly, page, pageSize]);

  const onRefresh = () => {
    startTransition(async () => {
      setFeedback("");
      setError("");
      try {
        await reload();
        setFeedback("저장된 품질 데이터를 다시 불러왔습니다.");
      } catch (reloadError) {
        setError(reloadError instanceof Error ? reloadError.message : "조회에 실패했습니다.");
      }
    });
  };

  const onRecalculate = () => {
    startTransition(async () => {
      setFeedback("");
      setError("");
      try {
        const result = await fetchJson<ContentOverviewRecalculateResult>("/content-ops/overview/recalculate", {
          method: "POST",
          body: JSON.stringify({
            profile: profile || null,
            published_only: publishedOnly,
            sync_sheet: false,
          }),
        });
        await reload(1, pageSize);
        setPage(1);
        setFeedback(`품질 점수를 다시 계산했습니다. ${result.updated_articles}/${result.total_articles}건 갱신됨`);
      } catch (recalculateError) {
        setError(recalculateError instanceof Error ? recalculateError.message : "재계산에 실패했습니다.");
      }
    });
  };


  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>전체 글 현황</CardTitle>
          <CardDescription>
            저장된 품질 점수, 카테고리, 유사도 상태를 페이지 단위로 확인합니다. 시트 경로는 제거하고 내부 분석 기준으로만 운영합니다.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-2 text-sm text-slate-700">
              <span>프로필</span>
              <select
                value={profile}
                onChange={(event) => {
                  setProfile(event.target.value);
                  setPage(1);
                }}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                {PROFILE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-2 text-sm text-slate-700">
              <span>페이지 크기</span>
              <select
                value={pageSize}
                onChange={(event) => {
                  setPageSize(Number(event.target.value));
                  setPage(1);
                }}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                {PAGE_SIZE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}개
                  </option>
                ))}
              </select>
            </label>

            <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={publishedOnly}
                onChange={(event) => {
                  setPublishedOnly(event.currentTarget.checked);
                  setPage(1);
                }}
              />
              <span>공개글만 보기</span>
            </label>

            <Button onClick={onRefresh} disabled={loading}>조회</Button>
            <Button variant="outline" onClick={onRecalculate} disabled={loading}>점수 재계산</Button>
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <Card>
              <CardHeader>
                <CardDescription>총 대상</CardDescription>
                <CardTitle>{total}</CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader>
                <CardDescription>현재 페이지</CardDescription>
                <CardTitle>
                  {page} / {totalPages}
                </CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader>
                <CardDescription>자동 처리 가능</CardDescription>
                <CardTitle>{autoFixCount}</CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader>
                <CardDescription>수동 판단 필요</CardDescription>
                <CardTitle>{manualCount}</CardTitle>
              </CardHeader>
            </Card>
          </div>

          {feedback ? <p className="text-sm text-slate-600">{feedback}</p> : null}
          {error ? <p className="text-sm text-rose-600">{error}</p> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription>콘텐츠 목록</CardDescription>
          <CardTitle>시트 기반 품질 검토</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <div className="min-w-[920px]">
            <Table className="table-fixed">
              <TableHeader>
                <TableRow>
                  <TableHead>제목</TableHead>
                  <TableHead className="w-[120px]">품질</TableHead>
                  <TableHead className="w-[90px]">SEO</TableHead>
                  <TableHead className="w-[90px]">GEO</TableHead>
                  <TableHead className="w-[90px]">유사율</TableHead>
                  <TableHead className="w-[260px]">권장</TableHead>
                  <TableHead className="w-[120px]">링크</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <Fragment key={row.article_id}>
                    <TableRow key={row.article_id}>
                      <TableCell className="align-top">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <button
                              type="button"
                              onClick={() => setExpandedArticleId((prev) => (prev === row.article_id ? null : row.article_id))}
                              className="block w-full text-left"
                            >
                              <p className="line-clamp-2 font-medium text-slate-900">{row.title}</p>
                            </button>
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                              <span className="rounded-full bg-slate-100 px-3 py-1">{row.blog}</span>
                              <span className="rounded-full bg-slate-100 px-3 py-1">{row.profile}</span>
                              <span className="rounded-full bg-slate-100 px-3 py-1">{row.status}</span>
                              <span className="rounded-full bg-slate-100 px-3 py-1">업데이트 {formatDate(row.updated_at)}</span>
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => setExpandedArticleId((prev) => (prev === row.article_id ? null : row.article_id))}
                            className="shrink-0 rounded-2xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-200"
                          >
                            {expandedArticleId === row.article_id ? "접기" : "상세"}
                          </button>
                        </div>
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge className={reviewTone(row)}>{row.quality_status || "미정"}</Badge>
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge className={scoreTone(clampScore(row.seo_score))}>{formatScore(row.seo_score)}</Badge>
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge className={scoreTone(clampScore(row.geo_score))}>{formatScore(row.geo_score)}</Badge>
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge className={similarityTone(clampScore(row.similarity_score))}>{formatScore(row.similarity_score)}</Badge>
                      </TableCell>
                      <TableCell className="align-top">
                        {row.suggested_action ? (
                          <div className="space-y-2">
                            <Badge className={actionTone(row.suggested_action)}>{row.auto_fixable ? "자동 수정 가능" : row.manual_review ? "수동 검토" : "확인"}</Badge>
                            <p className="line-clamp-2 text-xs leading-5 text-slate-600">{row.suggested_action}</p>
                          </div>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell className="align-top">
                        {row.url ? (
                          <a
                            href={row.url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center justify-center rounded-2xl bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100"
                          >
                            사이트가기
                          </a>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                    </TableRow>

                    {expandedArticleId === row.article_id ? (
                      <TableRow key={`${row.article_id}-details`}>
                        <TableCell colSpan={7} className="bg-slate-50/60">
                          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                            <DetailLine label="카테고리" value={row.content_category || "-"} />
                            <DetailLine label="카테고리 키" value={row.category_key || "-"} />
                            <DetailLine label="주제 클러스터" value={row.topic_cluster || "-"} />
                            <DetailLine label="주제 각도" value={row.topic_angle || "-"} />
                            <DetailLine label="미디어 상태" value={row.media_state || "-"} />
                            <DetailLine label="재작성" value={String(row.rewrite_attempts ?? 0)} />
                            <DetailLine label="마지막 점검" value={formatDate(row.last_audited_at)} />
                            <DetailLine label="가장 유사한 URL" value={row.most_similar_url || "-"} href={row.most_similar_url || undefined} />
                          </div>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                ))}
                {rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="py-8 text-center text-slate-500">
                      현재 필터에 해당하는 글이 없습니다.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
            <p>
              총 {total}건 중 {rows.length}건 표시
            </p>
            <div className="flex items-center gap-2">
              <Button variant="outline" disabled={loading || page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>
                이전
              </Button>
              <span>
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                disabled={loading || page >= totalPages}
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              >
                다음
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function DetailLine({ label, value, href }: { label: string; value: string; href?: string }) {
  return (
    <div className="rounded-[22px] bg-white p-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{label}</p>
      {href && href !== "-" ? (
        <a href={href} target="_blank" rel="noreferrer" className="mt-2 block break-words text-sm font-medium text-indigo-600 hover:underline">
          {value}
        </a>
      ) : (
        <p className="mt-2 break-words text-sm font-medium text-slate-900">{value}</p>
      )}
    </div>
  );
}

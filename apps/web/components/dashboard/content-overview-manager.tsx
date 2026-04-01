"use client";

import { useEffect, useMemo, useRef, useState, useTransition } from "react";

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

function actionTone(value: string) {
  if (value.includes("rewrite") || value.includes("duplicate") || value.includes("review")) {
    return "bg-amber-500/10 text-amber-700";
  }
  if (value.includes("fix") || value.includes("cleanup") || value.includes("collage")) {
    return "bg-sky-500/10 text-sky-700";
  }
  return "bg-emerald-500/10 text-emerald-700";
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
          <div className="min-w-[1280px]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>제목</TableHead>
                  <TableHead>본문 URL</TableHead>
                  <TableHead>프로필</TableHead>
                  <TableHead>카테고리</TableHead>
                  <TableHead>카테고리 키</TableHead>
                  <TableHead>주제 클러스터</TableHead>
                  <TableHead>주제 각도</TableHead>
                  <TableHead>유사율</TableHead>
                  <TableHead>SEO</TableHead>
                  <TableHead>GEO</TableHead>
                  <TableHead>미디어 상태</TableHead>
                  <TableHead>품질 상태</TableHead>
                  <TableHead>권장 조치</TableHead>
                  <TableHead>재작성</TableHead>
                  <TableHead>마지막 점검</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.article_id}>
                    <TableCell className="max-w-[260px]">
                      <p className="line-clamp-2 font-medium text-slate-900">{row.title}</p>
                    </TableCell>
                    <TableCell className="max-w-[220px]">
                      {row.url ? (
                        <a href={row.url} target="_blank" rel="noreferrer" className="text-blue-700 underline underline-offset-4">
                          {row.url}
                        </a>
                      ) : (
                        "-"
                      )}
                    </TableCell>
                    <TableCell>{row.profile}</TableCell>
                    <TableCell>{row.content_category || "-"}</TableCell>
                    <TableCell>{row.category_key || "-"}</TableCell>
                    <TableCell>{row.topic_cluster || "-"}</TableCell>
                    <TableCell>{row.topic_angle || "-"}</TableCell>
                    <TableCell>
                      <Badge className={actionTone(row.suggested_action)}>{formatScore(row.similarity_score)}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge className={scoreTone(clampScore(row.seo_score))}>{formatScore(row.seo_score)}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge className={scoreTone(clampScore(row.geo_score))}>{formatScore(row.geo_score)}</Badge>
                    </TableCell>
                    <TableCell>{row.media_state || "-"}</TableCell>
                    <TableCell>{row.quality_status || "-"}</TableCell>
                    <TableCell className="max-w-[220px] text-xs text-slate-600">{row.suggested_action || "-"}</TableCell>
                    <TableCell>{row.rewrite_attempts}</TableCell>
                    <TableCell>{formatDate(row.last_audited_at)}</TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={15} className="py-8 text-center text-slate-500">
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



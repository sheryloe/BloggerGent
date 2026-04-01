"use client";

import { useState, useTransition } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ContentOpsStatus, ContentReviewItem } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

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
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

function riskTone(level: string) {
  if (level === "high") {
    return "border-rose-200 bg-rose-500/10 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/15 dark:text-rose-200";
  }
  if (level === "medium") {
    return "border-amber-200 bg-amber-500/10 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/15 dark:text-amber-200";
  }
  return "border-emerald-200 bg-emerald-500/10 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/15 dark:text-emerald-200";
}

function statusTone(value: string) {
  if (value === "failed" || value === "rejected") {
    return "border-rose-200 bg-rose-500/10 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/15 dark:text-rose-200";
  }
  if (value === "approved" || value === "applied" || value === "auto_approved") {
    return "border-emerald-200 bg-emerald-500/10 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/15 dark:text-emerald-200";
  }
  return "border-slate-200 bg-slate-500/10 text-slate-700 dark:border-white/10 dark:bg-white/10 dark:text-zinc-200";
}

function issueMessage(issue: Record<string, unknown>) {
  const code = String(issue.code ?? "issue");
  const message = String(issue.message ?? "");
  return `${code}: ${message}`;
}

export function ContentOpsManager({
  initialStatus,
  initialReviews,
}: {
  initialStatus: ContentOpsStatus;
  initialReviews: ContentReviewItem[];
}) {
  const [status, setStatus] = useState(initialStatus);
  const [reviews, setReviews] = useState(initialReviews);
  const [feedback, setFeedback] = useState<string>("");
  const [isPending, startTransition] = useTransition();

  const refreshData = async () => {
    const [nextStatus, nextReviews] = await Promise.all([
      fetchJson<ContentOpsStatus>("/content-ops/status"),
      fetchJson<ContentReviewItem[]>("/content-ops/reviews?limit=50"),
    ]);
    setStatus(nextStatus);
    setReviews(nextReviews);
  };

  const runAction = (path: string, successMessage: string) => {
    startTransition(async () => {
      try {
        setFeedback("");
        await fetchJson(path, { method: "POST" });
        await refreshData();
        setFeedback(successMessage);
      } catch (error) {
        setFeedback(error instanceof Error ? error.message : "작업 실행에 실패했습니다.");
      }
    });
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardDescription>리뷰 대기</CardDescription>
            <CardTitle>{status.review_queue_count}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>고위험</CardDescription>
            <CardTitle>{status.high_risk_count}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>오늘 자동 수정</CardDescription>
            <CardTitle>{status.auto_fix_applied_today}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>학습 스냅샷 경과</CardDescription>
            <CardTitle>{status.learning_snapshot_age ?? "N/A"}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>운영 제어</CardTitle>
          <CardDescription>
            learning_paused={String(status.learning_paused)} | snapshot={status.learning_snapshot_path || "not built"}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button onClick={() => runAction("/content-ops/sync-now", "실시간 동기화를 완료했습니다.")} disabled={isPending}>
            지금 동기화
          </Button>
          <Button variant="outline" onClick={() => startTransition(refreshData)} disabled={isPending}>
            새로고침
          </Button>
          {feedback ? <p className="text-sm text-slate-500 dark:text-zinc-400">{feedback}</p> : null}
        </CardContent>
      </Card>

      <div className="grid gap-4">
        {reviews.map((item) => (
          <Card key={item.id}>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={riskTone(item.risk_level)}>{item.risk_level}</Badge>
                <Badge className={statusTone(item.approval_status)}>{item.approval_status}</Badge>
                <Badge className={statusTone(item.apply_status)}>{item.apply_status}</Badge>
                <Badge>{item.review_kind}</Badge>
              </div>
              <CardTitle className="text-lg">{item.source_title}</CardTitle>
              <CardDescription>
                review #{item.id} | score={item.quality_score} | source={item.source_type}:{item.source_id}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {item.source_url ? (
                <a
                  href={item.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-indigo-600 underline underline-offset-4 dark:text-indigo-300"
                >
                  {item.source_url}
                </a>
              ) : null}

              <div className="space-y-2">
                <p className="text-sm font-semibold text-slate-900 dark:text-zinc-100">이슈</p>
                {item.issues.length === 0 ? (
                  <p className="text-sm text-slate-500 dark:text-zinc-400">이슈가 없습니다. 이 항목은 기준 품질 데이터로 사용할 수 있습니다.</p>
                ) : (
                  <div className="space-y-2">
                    {item.issues.slice(0, 4).map((issue, index) => (
                      <p key={`${item.id}-issue-${index}`} className="text-sm text-slate-600 dark:text-zinc-300">
                        {issueMessage(issue)}
                      </p>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <p className="text-sm font-semibold text-slate-900 dark:text-zinc-100">패치 키</p>
                <p className="text-sm text-slate-500 dark:text-zinc-400">
                  {Object.keys(item.proposed_patch ?? {}).join(", ") || "none"}
                </p>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => runAction(`/content-ops/reviews/${item.id}/approve`, `리뷰 #${item.id}를 승인했습니다.`)}
                  disabled={isPending}
                >
                  승인
                </Button>
                <Button
                  size="sm"
                  onClick={() => runAction(`/content-ops/reviews/${item.id}/apply`, `리뷰 #${item.id}를 적용했습니다.`)}
                  disabled={isPending}
                >
                  적용
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => runAction(`/content-ops/reviews/${item.id}/reject`, `리뷰 #${item.id}를 거절했습니다.`)}
                  disabled={isPending}
                >
                  거절
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => runAction(`/content-ops/reviews/${item.id}/rerun`, `리뷰 #${item.id}를 다시 실행했습니다.`)}
                  disabled={isPending}
                >
                  재실행
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

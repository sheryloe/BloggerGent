"use client";

import { useEffect, useMemo, useState, useTransition } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getWorkspaceContentItems, processWorkspacePublishQueue, queueWorkspaceContentItemPublish } from "@/lib/api";
import type { ContentItemRead, ContentOpsStatus, ContentReviewItem } from "@/lib/types";

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
  if (value === "blocked_asset" || value === "blocked") {
    return "border-amber-200 bg-amber-500/10 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/15 dark:text-amber-200";
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

function readScore(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function scoreSummary(lastScore: Record<string, unknown>) {
  const pairs: Array<[string, string]> = [
    ["seo_ctr", "SEO/CTR"],
    ["watch_quality", "Watch"],
    ["engagement_quality", "Engage"],
  ];
  const segments: string[] = [];
  pairs.forEach(([key, label]) => {
    const score = readScore(lastScore[key]);
    if (score !== null) {
      segments.push(`${label} ${score.toFixed(1)}`);
    }
  });
  return segments.join(" · ");
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
  const [platformItems, setPlatformItems] = useState<ContentItemRead[]>([]);
  const [platformStatusFilter, setPlatformStatusFilter] = useState<string>("all");
  const [feedback, setFeedback] = useState<string>("");
  const [isPending, startTransition] = useTransition();

  const platformSummary = useMemo(() => {
    const queued = platformItems.filter((item) => item.lifecycleStatus === "queued" || item.lifecycleStatus === "scheduled").length;
    const failed = platformItems.filter((item) => item.lifecycleStatus === "failed" || item.lifecycleStatus === "blocked").length;
    const blockedAsset = platformItems.filter((item) => item.lifecycleStatus === "blocked_asset").length;
    const published = platformItems.filter((item) => item.lifecycleStatus === "published" || item.lifecycleStatus === "review").length;
    return { queued, failed, blockedAsset, published };
  }, [platformItems]);

  const filteredPlatformItems = useMemo(() => {
    if (platformStatusFilter === "all") {
      return platformItems;
    }
    return platformItems.filter((item) => item.lifecycleStatus === platformStatusFilter);
  }, [platformItems, platformStatusFilter]);

  const loadPlatformItems = async () => {
    const [youtubeItems, instagramItems] = await Promise.all([
      getWorkspaceContentItems({ provider: "youtube", limit: 30 }),
      getWorkspaceContentItems({ provider: "instagram", limit: 30 }),
    ]);
    const merged = [...youtubeItems, ...instagramItems].sort((left, right) => {
      const leftTime = new Date(left.updatedAt).getTime();
      const rightTime = new Date(right.updatedAt).getTime();
      return rightTime - leftTime;
    });
    setPlatformItems(merged.slice(0, 20));
  };

  const refreshData = async () => {
    const [nextStatus, nextReviews] = await Promise.all([
      fetchJson<ContentOpsStatus>("/content-ops/status"),
      fetchJson<ContentReviewItem[]>("/content-ops/reviews?limit=50"),
    ]);
    setStatus(nextStatus);
    setReviews(nextReviews);
    await loadPlatformItems();
  };

  useEffect(() => {
    startTransition(async () => {
      try {
        await loadPlatformItems();
      } catch {
        setFeedback("플랫폼 게시 대기열을 불러오지 못했습니다.");
      }
    });
  }, []);

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

  const processPlatformQueue = () => {
    startTransition(async () => {
      try {
        setFeedback("");
        const result = await processWorkspacePublishQueue(10);
        await refreshData();
        setFeedback(`플랫폼 게시 큐를 실행했습니다. 처리 건수: ${result.processed_count ?? 0}`);
      } catch (error) {
        setFeedback(error instanceof Error ? error.message : "플랫폼 게시 큐 실행에 실패했습니다.");
      }
    });
  };

  const queuePlatformItem = (itemId: number) => {
    startTransition(async () => {
      try {
        setFeedback("");
        await queueWorkspaceContentItemPublish(itemId);
        await refreshData();
        setFeedback(`콘텐츠 #${itemId}를 게시 대기열로 전환했습니다.`);
      } catch (error) {
        setFeedback(error instanceof Error ? error.message : "게시 대기열 등록에 실패했습니다.");
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

      <Card>
        <CardHeader>
          <CardTitle>YouTube / Instagram 게시 큐</CardTitle>
          <CardDescription>
            queued={platformSummary.queued} | blocked_asset={platformSummary.blockedAsset} | failed={platformSummary.failed} | published/review={platformSummary.published}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button onClick={processPlatformQueue} disabled={isPending}>
              게시 큐 처리
            </Button>
            <Button variant="outline" onClick={() => startTransition(refreshData)} disabled={isPending}>
              상태 새로고침
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              ["all", "전체"],
              ["blocked_asset", "에셋 대기"],
              ["ready_to_publish", "게시 준비"],
              ["failed", "실패"],
              ["queued", "큐"],
            ].map(([value, label]) => (
              <Button
                key={value}
                size="sm"
                variant={platformStatusFilter === value ? "default" : "outline"}
                onClick={() => setPlatformStatusFilter(value)}
                disabled={isPending}
              >
                {label}
              </Button>
            ))}
          </div>
          <div className="grid gap-3">
            {filteredPlatformItems.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-zinc-400">플랫폼 콘텐츠 항목이 없습니다.</p>
            ) : (
              filteredPlatformItems.map((item) => {
                const failureCode = String(
                  item.latestPublication?.errorCode ??
                    item.latestPublication?.responsePayload?.error_code ??
                    item.latestPublication?.responsePayload?.failure_code ??
                    "",
                ).trim();
                const scores = scoreSummary(item.lastScore);
                return (
                  <div key={item.id} className="rounded-lg border border-slate-200 px-3 py-3 dark:border-white/10">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="space-y-1">
                        <p className="text-sm font-semibold text-slate-900 dark:text-zinc-100">
                          [{item.provider}] {item.title || "(제목 없음)"}
                        </p>
                        <p className="text-xs text-slate-500 dark:text-zinc-400">
                          #{item.id} · {item.contentType} · {item.lifecycleStatus} · {item.updatedAt}
                        </p>
                        {scores ? (
                          <p className="text-xs text-slate-500 dark:text-zinc-400">{scores}</p>
                        ) : null}
                        {item.blockedReason ? (
                          <p className="text-xs font-medium text-amber-700 dark:text-amber-300">blocked: {item.blockedReason}</p>
                        ) : null}
                        {failureCode ? (
                          <p className="text-xs font-medium text-rose-600 dark:text-rose-300">error: {failureCode}</p>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge className={statusTone(item.lifecycleStatus)}>{item.lifecycleStatus}</Badge>
                        {(item.lifecycleStatus === "draft" ||
                          item.lifecycleStatus === "review" ||
                          item.lifecycleStatus === "failed" ||
                          item.lifecycleStatus === "blocked_asset" ||
                          item.lifecycleStatus === "ready_to_publish") ? (
                          <Button size="sm" variant="outline" onClick={() => queuePlatformItem(item.id)} disabled={isPending}>
                            게시 대기 등록
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
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

import Link from "next/link";

import { ResetGeneratedDataButton } from "@/components/dashboard/reset-generated-data-button";
import { RetryButton } from "@/components/dashboard/retry-button";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getJob, getJobs } from "@/lib/api";

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function parsePositiveInt(value: string | string[] | undefined, fallback: number) {
  const resolved = firstParam(value);
  const parsed = Number(resolved);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function buildHref(searchParams: Record<string, string | string[] | undefined> | undefined, jobId: number) {
  const params = new URLSearchParams();
  Object.entries(searchParams ?? {}).forEach(([key, value]) => {
    const resolved = firstParam(value);
    if (resolved) {
      params.set(key, resolved);
    }
  });
  params.set("tab", "jobs");
  params.set("job", String(jobId));
  const query = params.toString();
  return query ? `/content-ops?${query}` : "/content-ops?tab=jobs";
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export async function ContentOpsJobsPanel({
  searchParams,
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  const jobs = await getJobs(undefined, 30);
  const selectedId = parsePositiveInt(searchParams?.job, jobs[0]?.id ?? 0);
  const selectedJob = selectedId ? await getJob(selectedId).catch(() => null) : null;
  const errorLogs = selectedJob?.error_logs ?? [];
  const auditLogs = selectedJob?.audit_logs ?? [];
  const completedJobs = jobs.filter((job) => job.status === "COMPLETED").length;
  const failedJobs = jobs.filter((job) => job.status === "FAILED").length;
  const pendingPublish = jobs.filter((job) => job.publish_status === "queued" || job.publish_status === "scheduled").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-950 dark:text-zinc-50">작업 큐</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-zinc-400">
            최근 작업 30건만 목록으로 받고, 상세 정보는 선택한 작업만 추가 조회합니다.
          </p>
        </div>
        <ResetGeneratedDataButton />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card><CardContent className="p-5"><p className="text-sm text-slate-500">표시 작업</p><p className="mt-2 text-3xl font-semibold text-slate-950">{jobs.length}</p></CardContent></Card>
        <Card><CardContent className="p-5"><p className="text-sm text-slate-500">완료 / 실패</p><p className="mt-2 text-3xl font-semibold text-slate-950">{completedJobs} / {failedJobs}</p></CardContent></Card>
        <Card><CardContent className="p-5"><p className="text-sm text-slate-500">발행 대기</p><p className="mt-2 text-3xl font-semibold text-slate-950">{pendingPublish}</p></CardContent></Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="h-fit xl:sticky xl:top-6">
          <CardHeader>
            <CardDescription>최근 작업</CardDescription>
            <CardTitle>경량 목록</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {jobs.map((job) => {
              const active = selectedJob?.id === job.id;
              return (
                <Link
                  key={job.id}
                  href={buildHref(searchParams, job.id)}
                  prefetch={false}
                  className={`block rounded-[22px] border px-4 py-4 transition ${active ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white hover:bg-slate-50"}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className={`text-xs uppercase tracking-[0.16em] ${active ? "text-white/60" : "text-slate-500"}`}>Job #{job.id}</p>
                      <p className="mt-1 line-clamp-2 font-semibold">{job.article?.title ?? job.keyword_snapshot}</p>
                      <p className={`mt-2 text-sm ${active ? "text-white/80" : "text-slate-600"}`}>{job.blog?.name ?? "-"}</p>
                    </div>
                    <StatusBadge status={job.status} />
                  </div>
                </Link>
              );
            })}
          </CardContent>
        </Card>

        {!selectedJob ? (
          <Card><CardContent className="px-6 py-10 text-sm text-slate-600">상세를 볼 작업이 없습니다.</CardContent></Card>
        ) : (
          <Card className="overflow-hidden">
            <CardHeader className="border-b border-slate-200/70 bg-white/70 dark:border-white/10 dark:bg-white/5">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <CardTitle className="break-words">{selectedJob.article?.title ?? selectedJob.keyword_snapshot}</CardTitle>
                    <StatusBadge status={selectedJob.status} />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge>작업 #{selectedJob.id}</Badge>
                    {selectedJob.blog?.name ? <Badge className="bg-transparent">{selectedJob.blog.name}</Badge> : null}
                    <Badge className="bg-transparent">재시도 {selectedJob.attempt_count}/{selectedJob.max_attempts}</Badge>
                  </div>
                </div>
                <RetryButton jobId={selectedJob.id} />
              </div>
            </CardHeader>
            <CardContent className="space-y-6 p-6">
              <div className="grid gap-4 xl:grid-cols-3">
                <div className="rounded-[24px] border border-slate-200/70 bg-white/70 p-4">
                  <p className="text-sm text-slate-500">처리 시간</p>
                  <div className="mt-3 space-y-2 text-sm leading-6 text-slate-700">
                    <p><strong>시작:</strong> {formatDateTime(selectedJob.start_time)}</p>
                    <p><strong>종료:</strong> {formatDateTime(selectedJob.end_time)}</p>
                    <p><strong>갱신:</strong> {formatDateTime(selectedJob.updated_at)}</p>
                  </div>
                </div>
                <div className="rounded-[24px] border border-slate-200/70 bg-white/70 p-4">
                  <p className="text-sm text-slate-500">발행 상태</p>
                  <div className="mt-3 space-y-2 text-sm leading-6 text-slate-700">
                    <p>파이프라인: {selectedJob.execution_status}</p>
                    <p>발행 상태: {selectedJob.publish_status}</p>
                    {selectedJob.blogger_post?.published_url ? (
                      <a href={selectedJob.blogger_post.published_url} target="_blank" rel="noreferrer" className="break-all text-blue-700 underline underline-offset-4">
                        {selectedJob.blogger_post.published_url}
                      </a>
                    ) : (
                      <p>아직 라이브 URL이 없습니다.</p>
                    )}
                  </div>
                </div>
                <div className="rounded-[24px] border border-slate-200/70 bg-white/70 p-4">
                  <p className="text-sm text-slate-500">텔레그램</p>
                  <div className="mt-3 space-y-2 text-sm leading-6 text-slate-700">
                    <p>전송 상태: {selectedJob.telegram_delivery_status ?? "-"}</p>
                    <p>오류 코드: {selectedJob.telegram_error_code ?? "-"}</p>
                    <p>{selectedJob.telegram_error_message ?? "오류 없음"}</p>
                  </div>
                </div>
              </div>

              {errorLogs.length > 0 ? (
                <details className="rounded-[24px] border border-rose-200 bg-rose-50 p-4">
                  <summary className="cursor-pointer text-sm font-semibold text-rose-800">에러 로그</summary>
                  <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs leading-6 text-rose-950">{JSON.stringify(errorLogs, null, 2)}</pre>
                </details>
              ) : null}

              <div className="space-y-3">
                <p className="text-sm font-semibold text-slate-900">감사 로그</p>
                {auditLogs.length > 0 ? (
                  <div className="space-y-3">
                    {auditLogs.map((log) => (
                      <div key={log.id} className="rounded-[24px] border border-slate-200/70 bg-white/70 p-4">
                        <div className="flex flex-wrap items-center gap-3">
                          <Badge>{log.stage}</Badge>
                          <span className="text-xs uppercase tracking-[0.16em] text-slate-500">{formatDateTime(log.created_at)}</span>
                        </div>
                        <p className="mt-3 text-sm leading-7 text-slate-700">{log.message}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-[24px] border border-dashed border-slate-200 bg-white/50 px-4 py-5 text-sm text-slate-600">감사 로그가 없습니다.</div>
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

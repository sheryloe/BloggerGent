import Link from "next/link";

import { ResetGeneratedDataButton } from "@/components/dashboard/reset-generated-data-button";
import { RetryButton } from "@/components/dashboard/retry-button";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getJobs } from "@/lib/api";

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

function countPublishPending(jobs: Awaited<ReturnType<typeof getJobs>>) {
  return jobs.filter((job) => {
    if (!job.article) return false;
    if (!job.blogger_post) return true;
    return job.blogger_post.is_draft;
  }).length;
}

export default async function JobsPage({
  searchParams,
}: {
  searchParams?: { job?: string };
}) {
  const jobs = await getJobs();
  const completedJobs = jobs.filter((job) => job.status === "COMPLETED").length;
  const failedJobs = jobs.filter((job) => job.status === "FAILED").length;
  const pendingPublish = countPublishPending(jobs);

  const selectedJobId = Number(searchParams?.job);
  const selectedJob = jobs.find((job) => job.id === selectedJobId) ?? jobs[0] ?? null;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-ink">작업 현황</h1>
          <p className="mt-2 text-base leading-7 text-slate-600">
            최근 생성 작업을 목록으로 보고, 선택한 작업의 단계·로그·연결 글을 아래에서 차분하게 확인할 수 있습니다.
          </p>
        </div>
        <ResetGeneratedDataButton />
      </div>

      <section className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="p-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">총 작업</p>
            <p className="mt-2 text-3xl font-semibold text-ink">{jobs.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">완료 / 실패</p>
            <p className="mt-2 text-3xl font-semibold text-ink">
              {completedJobs} / {failedJobs}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">공개 게시 대기</p>
            <p className="mt-2 text-3xl font-semibold text-ink">{pendingPublish}</p>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardDescription>최근 작업 목록</CardDescription>
          <CardTitle>Job List</CardTitle>
        </CardHeader>
        <CardContent>
          {jobs.length === 0 ? (
            <div className="rounded-[24px] border border-dashed border-ink/15 bg-white/50 px-4 py-5 text-sm text-slate-600">
              아직 생성된 작업이 없습니다.
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {jobs.map((job) => {
                const selected = selectedJob?.id === job.id;
                return (
                  <Link
                    key={job.id}
                    href={`/jobs?job=${job.id}`}
                    className={`rounded-[22px] border px-4 py-4 transition ${
                      selected ? "border-ink bg-ink text-white" : "border-ink/10 bg-white/70 text-ink hover:bg-white"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className={`text-xs uppercase tracking-[0.16em] ${selected ? "text-white/60" : "text-slate-500"}`}>
                          Job #{job.id}
                        </p>
                        <p className="mt-1 break-words font-semibold">{job.keyword_snapshot}</p>
                        <p className={`mt-2 text-sm ${selected ? "text-white/80" : "text-slate-600"}`}>
                          {job.blog?.name ?? "블로그 없음"}
                        </p>
                      </div>
                      <div className="shrink-0">
                        <StatusBadge status={job.status} />
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="overflow-hidden">
        {!selectedJob ? (
          <CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">선택된 작업이 없습니다.</CardContent>
        ) : (
          <>
            <CardHeader className="border-b border-ink/10 bg-white/70">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <CardTitle className="break-words">{selectedJob.keyword_snapshot}</CardTitle>
                    <StatusBadge status={selectedJob.status} />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge>작업 #{selectedJob.id}</Badge>
                    {selectedJob.blog?.name ? <Badge className="bg-transparent">{selectedJob.blog.name}</Badge> : null}
                    <Badge className="bg-transparent">시도 {selectedJob.attempt_count}/{selectedJob.max_attempts}</Badge>
                  </div>
                </div>
                <RetryButton jobId={selectedJob.id} />
              </div>
            </CardHeader>

            <CardContent className="space-y-6 p-6">
              <div className="grid gap-4 xl:grid-cols-3">
                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">처리 시간</p>
                  <div className="mt-3 space-y-2 text-sm leading-6 text-slate-700">
                    <p>
                      <strong>시작:</strong> {formatDateTime(selectedJob.start_time)}
                    </p>
                    <p>
                      <strong>종료:</strong> {formatDateTime(selectedJob.end_time)}
                    </p>
                  </div>
                </div>

                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">생성 글</p>
                  <div className="mt-3 space-y-3 text-sm leading-6 text-slate-700">
                    {selectedJob.article ? (
                      <>
                        <p className="font-medium text-ink">{selectedJob.article.title}</p>
                        <Link href={`/articles?article=${selectedJob.article.id}`} className="text-ember underline-offset-4 hover:underline">
                          글 상세 보기
                        </Link>
                      </>
                    ) : (
                      <p>아직 생성된 글이 없습니다.</p>
                    )}
                  </div>
                </div>

                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">게시 상태</p>
                  <div className="mt-3 space-y-3 text-sm leading-6 text-slate-700">
                    {selectedJob.blogger_post?.published_url ? (
                      <>
                        <p>{selectedJob.blogger_post.is_draft ? "Blogger 초안 저장됨" : "공개 게시 완료"}</p>
                        <a
                          href={selectedJob.blogger_post.published_url}
                          target="_blank"
                          rel="noreferrer"
                          className="break-all text-ember underline-offset-4 hover:underline"
                        >
                          링크 보기
                        </a>
                      </>
                    ) : selectedJob.article ? (
                      <p>HTML과 이미지 생성이 끝났습니다. 생성 글 목록의 공개 게시 버튼에서 최종 게시하세요.</p>
                    ) : (
                      <p>아직 게시 가능한 글이 없습니다.</p>
                    )}
                  </div>
                </div>
              </div>

              {selectedJob.error_logs.length ? (
                <details className="rounded-[24px] border border-rose-200 bg-rose-50 p-4">
                  <summary className="cursor-pointer text-xs uppercase tracking-[0.16em] text-rose-800">에러 로그 보기</summary>
                  <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs leading-6 text-rose-950">
                    {JSON.stringify(selectedJob.error_logs, null, 2)}
                  </pre>
                </details>
              ) : null}

              <div className="space-y-3">
                <p className="text-xs uppercase tracking-[0.16em] text-slate-500">감사 로그</p>
                {selectedJob.audit_logs.length ? (
                  <div className="space-y-3">
                    {selectedJob.audit_logs.map((log) => (
                      <div key={log.id} className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                        <div className="flex flex-wrap items-center gap-3">
                          <Badge>{log.stage}</Badge>
                          <span className="text-xs uppercase tracking-[0.16em] text-slate-500">
                            {formatDateTime(log.created_at)}
                          </span>
                        </div>
                        <p className="mt-3 text-sm leading-7 text-slate-700">{log.message}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-[24px] border border-dashed border-ink/15 bg-white/50 px-4 py-5 text-sm text-slate-600">
                    아직 감사 로그가 없습니다.
                  </div>
                )}
              </div>
            </CardContent>
          </>
        )}
      </Card>
    </div>
  );
}

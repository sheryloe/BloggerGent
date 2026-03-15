import { ResetGeneratedDataButton } from "@/components/dashboard/reset-generated-data-button";
import { RetryButton } from "@/components/dashboard/retry-button";
import { StatusBadge } from "@/components/dashboard/status-badge";
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

export default async function JobsPage() {
  const jobs = await getJobs();

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-ink">작업 현황</h1>
          <p className="mt-2 text-base leading-7 text-slate-600">
            파이프라인 단계, 재시도 횟수, 오류 로그, 감사 로그를 한 화면에서 확인합니다.
          </p>
        </div>
        <ResetGeneratedDataButton />
      </div>

      <div className="grid gap-5">
        {jobs.length === 0 ? (
          <Card>
            <CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">
              아직 생성된 작업이 없습니다. 블로그를 가져온 뒤 주제 발굴이나 수동 키워드 실행으로 첫 작업을
              시작해 주세요.
            </CardContent>
          </Card>
        ) : null}

        {jobs.map((job) => (
          <Card key={job.id}>
            <CardHeader className="gap-4 md:flex-row md:items-start md:justify-between">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-3">
                  <CardTitle>{job.keyword_snapshot}</CardTitle>
                  <StatusBadge status={job.status} />
                </div>
                <CardDescription>
                  작업 #{job.id} / {job.blog?.name ?? "블로그 미연결"} / 발행 모드{" "}
                  {job.publish_mode === "draft" ? "초안 저장" : "즉시 발행"} / 재시도 {job.attempt_count}/
                  {job.max_attempts}
                </CardDescription>
              </div>
              <RetryButton jobId={job.id} />
            </CardHeader>
            <CardContent className="grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
              <div className="space-y-4 rounded-[24px] border border-ink/10 bg-white/60 p-5">
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">처리 시간</p>
                  <p className="mt-2 text-sm leading-7 text-slate-700">
                    시작: {formatDateTime(job.start_time)}
                    <br />
                    종료: {formatDateTime(job.end_time)}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">오류 로그</p>
                  <pre className="mt-2 overflow-x-auto rounded-2xl bg-ink px-4 py-3 text-xs leading-6 text-white">
                    {JSON.stringify(job.error_logs, null, 2)}
                  </pre>
                </div>
              </div>

              <div className="space-y-3">
                {job.audit_logs.map((log) => (
                  <div key={log.id} className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                        {log.stage}
                      </span>
                      <span className="text-xs uppercase tracking-[0.16em] text-slate-500">
                        {formatDateTime(log.created_at)}
                      </span>
                    </div>
                    <p className="mt-3 text-sm leading-7 text-slate-700">{log.message}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

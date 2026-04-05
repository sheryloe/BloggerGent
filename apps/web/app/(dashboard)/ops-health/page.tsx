import { OpsHealthSyncControls } from "@/components/dashboard/ops-health-sync-controls";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getOpsHealthLatest, getWorkspaceRuntimeUsage } from "@/lib/api";

function statusTone(status: string) {
  const value = status.toLowerCase();
  if (value === "ok") return "border-emerald-200 bg-emerald-500/10 text-emerald-700";
  if (value === "warning") return "border-amber-200 bg-amber-500/10 text-amber-700";
  return "border-rose-200 bg-rose-500/10 text-rose-700";
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatNumber(value: number | undefined) {
  return new Intl.NumberFormat("ko-KR").format(value ?? 0);
}

export default async function OpsHealthPage() {
  const [latest, usage] = await Promise.all([
    getOpsHealthLatest().catch(() => null),
    getWorkspaceRuntimeUsage(7).catch(() => null),
  ]);
  const report = latest?.report ?? null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardDescription>Ops Monitor</CardDescription>
          <CardTitle>운영 점검 동기화</CardTitle>
        </CardHeader>
        <CardContent>
          <OpsHealthSyncControls />
        </CardContent>
      </Card>

      {!latest || latest.status !== "ok" || !report ? (
        <Card>
          <CardHeader>
            <CardTitle>운영 점검</CardTitle>
            <CardDescription>점검 리포트를 아직 불러오지 못했습니다.</CardDescription>
          </CardHeader>
            <CardContent className="space-y-3 text-sm text-slate-600">
              <p>위 동기화 버튼을 먼저 실행한 뒤 페이지를 새로고침하세요.</p>
              <pre className="overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                {`docker compose --env-file .env exec -T api python -m app.tools.ops_health_report`}
              </pre>
            </CardContent>
          </Card>
      ) : (
        <>
          {usage ? (
            <Card>
              <CardHeader>
                <CardTitle>최근 7일 AI 사용량</CardTitle>
                <CardDescription>Gemini CLI, Codex CLI, OpenAI 사용량을 최근 이벤트 기준으로 집계합니다.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {usage.providers.length ? (
                  usage.providers.map((provider) => (
                    <Card key={provider.providerKey}>
                      <CardHeader>
                        <CardDescription>{provider.label}</CardDescription>
                        <CardTitle>{formatNumber(provider.requestCount)}회</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-2 text-sm text-slate-600">
                        <p>토큰 합계: {formatNumber(provider.totalTokens)}</p>
                        <p>입력 / 출력: {formatNumber(provider.inputTokens)} / {formatNumber(provider.outputTokens)}</p>
                        <p>오류 수: {formatNumber(provider.errorCount)}</p>
                        <p>최근 이벤트: {formatDateTime(provider.lastEventAt)}</p>
                      </CardContent>
                    </Card>
                  ))
                ) : (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                    최근 7일 사용량 이벤트가 없습니다.
                  </div>
                )}
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle>운영 점검</CardTitle>
                <Badge className={statusTone(report.overall_status)}>{report.overall_status.toUpperCase()}</Badge>
              </div>
              <CardDescription>
                생성 시간: {formatDateTime(report.generated_at_kst)} · 리포트 파일: {latest.file_path || "-"}
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-3">
              <Card>
                <CardHeader>
                  <CardDescription>최근 24시간 실패 작업</CardDescription>
                  <CardTitle>{formatNumber(report.failed_jobs_last_24h.length)}</CardTitle>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader>
                  <CardDescription>시트 중복 헤더</CardDescription>
                  <CardTitle>{formatNumber(report.sheet_issues?.duplicates?.length ?? 0)}</CardTitle>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader>
                  <CardDescription>시트 영문 헤더</CardDescription>
                  <CardTitle>{formatNumber(report.sheet_issues?.english_columns?.length ?? 0)}</CardTitle>
                </CardHeader>
              </Card>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>무료 토큰 사용량</CardTitle>
              <CardDescription>UTC 날짜 기준 집계입니다.</CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              {report.token_usage ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>버전</TableHead>
                      <TableHead>사용량</TableHead>
                      <TableHead>잔여</TableHead>
                      <TableHead>사용률</TableHead>
                      <TableHead>모델</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <TableRow>
                      <TableCell>대형(1M)</TableCell>
                      <TableCell>
                        {formatNumber(report.token_usage.large.used_tokens)} / {formatNumber(report.token_usage.large.limit_tokens)}
                      </TableCell>
                      <TableCell>{formatNumber(report.token_usage.large.remaining_tokens)}</TableCell>
                      <TableCell>{report.token_usage.large.usage_percent}%</TableCell>
                      <TableCell className="max-w-[460px]">{report.token_usage.large.matched_models.join(", ") || "-"}</TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell>소형(10M)</TableCell>
                      <TableCell>
                        {formatNumber(report.token_usage.small.used_tokens)} / {formatNumber(report.token_usage.small.limit_tokens)}
                      </TableCell>
                      <TableCell>{formatNumber(report.token_usage.small.remaining_tokens)}</TableCell>
                      <TableCell>{report.token_usage.small.usage_percent}%</TableCell>
                      <TableCell className="max-w-[460px]">{report.token_usage.small.matched_models.join(", ") || "-"}</TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              ) : (
                <p className="text-sm text-rose-600">{report.token_error || "토큰 사용량을 불러오지 못했습니다."}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>최근 24시간 실패 작업</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Job ID</TableHead>
                    <TableHead>블로그</TableHead>
                    <TableHead>키워드</TableHead>
                    <TableHead>종료 시각(UTC)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.failed_jobs_last_24h.map((item: { job_id: number; blog_slug: string; blog_id: number; keyword: string; ended_at_utc: string }) => (
                    <TableRow key={item.job_id}>
                      <TableCell>{item.job_id}</TableCell>
                      <TableCell>{item.blog_slug || `blog-${item.blog_id}`}</TableCell>
                      <TableCell className="max-w-[460px]">{item.keyword || "-"}</TableCell>
                      <TableCell>{item.ended_at_utc || "-"}</TableCell>
                    </TableRow>
                  ))}
                  {report.failed_jobs_last_24h.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} className="text-sm text-slate-500">
                        최근 24시간 실패 작업이 없습니다.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

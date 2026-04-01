import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getOpsHealthLatest } from "@/lib/api";

function statusTone(status: string) {
  const value = status.toLowerCase();
  if (value === "ok") {
    return "border-emerald-200 bg-emerald-500/10 text-emerald-700";
  }
  if (value === "warning") {
    return "border-amber-200 bg-amber-500/10 text-amber-700";
  }
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
  const latest = await getOpsHealthLatest().catch(() => null);
  const report = latest?.report ?? null;

  if (!latest || latest.status !== "ok" || !report) {
    return (
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>운영 점검</CardTitle>
            <CardDescription>점검 리포트를 아직 불러오지 못했습니다.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-slate-600">
            <p>터미널에서 아래 명령을 먼저 실행한 뒤 페이지를 새로고침하세요.</p>
            <pre className="overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
              {`python D:\\Donggri_Platform\\BloggerGent\\scripts\\ops_health_report.py`}
            </pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  const tokenUsage = report.token_usage;
  const duplicateCount = report.sheet_issues?.duplicates?.length ?? 0;
  const englishCount = report.sheet_issues?.english_columns?.length ?? 0;

  return (
    <div className="space-y-6">
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
        <CardContent className="grid gap-3 md:grid-cols-4">
          <Card>
            <CardHeader>
              <CardDescription>최근 24시간 실패 작업</CardDescription>
              <CardTitle>{formatNumber(report.failed_jobs_last_24h.length)}</CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader>
              <CardDescription>시트 중복 헤더</CardDescription>
              <CardTitle>{formatNumber(duplicateCount)}</CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader>
              <CardDescription>시트 영문 헤더</CardDescription>
              <CardTitle>{formatNumber(englishCount)}</CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader>
              <CardDescription>클라우드플레어 최근 리포트</CardDescription>
              <CardTitle>{formatNumber(report.latest_cloudflare_reports.length)}</CardTitle>
            </CardHeader>
          </Card>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>무료 토큰 사용량</CardTitle>
          <CardDescription>UTC 일일 버킷 기준 사용량입니다.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {tokenUsage ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>버킷</TableHead>
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
                    {formatNumber(tokenUsage.large.used_tokens)} / {formatNumber(tokenUsage.large.limit_tokens)}
                  </TableCell>
                  <TableCell>{formatNumber(tokenUsage.large.remaining_tokens)}</TableCell>
                  <TableCell>{tokenUsage.large.usage_percent}%</TableCell>
                  <TableCell className="max-w-[460px]">{tokenUsage.large.matched_models.join(", ") || "-"}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>소형(10M)</TableCell>
                  <TableCell>
                    {formatNumber(tokenUsage.small.used_tokens)} / {formatNumber(tokenUsage.small.limit_tokens)}
                  </TableCell>
                  <TableCell>{formatNumber(tokenUsage.small.remaining_tokens)}</TableCell>
                  <TableCell>{tokenUsage.small.usage_percent}%</TableCell>
                  <TableCell className="max-w-[460px]">{tokenUsage.small.matched_models.join(", ") || "-"}</TableCell>
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
          <CardTitle>클라우드플레어 최근 생성 리포트</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>파일</TableHead>
                <TableHead>상태</TableHead>
                <TableHead>생성</TableHead>
                <TableHead>실패</TableHead>
                <TableHead>생성시각(UTC)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.latest_cloudflare_reports.map((item) => (
                <TableRow key={item.file}>
                  <TableCell>{item.file}</TableCell>
                  <TableCell>
                    <Badge className={statusTone(item.status)}>{item.status}</Badge>
                  </TableCell>
                  <TableCell>{formatNumber(item.created_count)}</TableCell>
                  <TableCell>{formatNumber(item.failed_count)}</TableCell>
                  <TableCell>{item.generated_at_utc || "-"}</TableCell>
                </TableRow>
              ))}
              {report.latest_cloudflare_reports.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-sm text-slate-500">
                    표시할 리포트가 없습니다.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
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
                <TableHead>종료시각(UTC)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.failed_jobs_last_24h.map((item) => (
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
    </div>
  );
}

import { AnalyticsPlatformTabs } from "@/components/dashboard/analytics-platform-tabs";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getCloudflareOverview, getCloudflarePosts, getCloudflareRuns } from "@/lib/api";

function formatNumber(value: number | undefined | null) {
  return new Intl.NumberFormat("ko-KR").format(value ?? 0);
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

export default async function CloudflareAnalyticsPage() {
  const [overview, posts, runs] = await Promise.all([
    getCloudflareOverview().catch(() => null),
    getCloudflarePosts().catch(() => []),
    getCloudflareRuns().catch(() => []),
  ]);

  return (
    <div className="space-y-5">
      <AnalyticsPlatformTabs />

      <Card>
        <CardHeader>
          <CardDescription>Cloudflare 분석</CardDescription>
          <CardTitle>Cloudflare 채널 운영 현황</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          <Metric label="게시글 수" value={formatNumber(overview?.posts_count)} />
          <Metric label="카테고리 수" value={formatNumber(overview?.categories_count)} />
          <Metric label="프롬프트 수" value={formatNumber(overview?.prompts_count)} />
          <Metric label="실행 이력 수" value={formatNumber(runs.length)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription>최근 게시글</CardDescription>
          <CardTitle>Cloudflare 게시글 목록</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {!posts.length ? (
            <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">표시할 게시글이 없습니다.</p>
          ) : (
            posts.slice(0, 20).map((post) => (
              <div key={post.remote_id} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium text-slate-900">{post.title}</p>
                  <Badge className="bg-transparent">{post.provider_status}</Badge>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  카테고리: {post.category_slug || "-"} · SEO: {post.seo_score ?? "-"}
                </p>
                {post.published_url ? (
                  <a href={post.published_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex text-sm text-sky-700 hover:underline">
                    게시 URL 열기
                  </a>
                ) : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription>최근 실행</CardDescription>
          <CardTitle>Cloudflare 실행 로그</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {!runs.length ? (
            <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">실행 이력이 없습니다.</p>
          ) : (
            runs.slice(0, 20).map((run) => (
              <div key={run.remote_id} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium text-slate-900">{run.title}</p>
                  <Badge className="bg-transparent">{run.status}</Badge>
                </div>
                <p className="mt-1 text-xs text-slate-500">업데이트: {formatDateTime(run.updated_at)}</p>
                <p className="mt-1 text-xs text-slate-500">{run.summary || "요약 없음"}</p>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] border border-slate-200 bg-slate-50 p-4">
      <p className="text-xs uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}

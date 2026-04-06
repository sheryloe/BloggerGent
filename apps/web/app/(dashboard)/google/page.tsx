import Link from "next/link";

import { GoogleIndexingControls } from "@/components/dashboard/google-indexing-controls";
import { GooglePostSyncButton } from "@/components/dashboard/google-post-sync-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getCloudflareOverview,
  getCloudflarePosts,
  getGoogleBlogOverview,
  getSeoTargets,
  getSyncedBloggerPosts,
} from "@/lib/api";

const isStaticPreview = process.env.GITHUB_ACTIONS === "true";

function formatNumber(value: number | undefined | null) {
  return new Intl.NumberFormat("ko-KR").format(value ?? 0);
}

function formatPercent(value: number | undefined | null) {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
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

function readFirst(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function buildTargetHref(searchParams: Record<string, string | string[] | undefined> | undefined, targetId: string) {
  const query = new URLSearchParams();
  if (searchParams) {
    for (const [key, rawValue] of Object.entries(searchParams)) {
      if (key === "target") continue;
      if (Array.isArray(rawValue)) {
        rawValue.forEach((item) => query.append(key, item));
      } else if (typeof rawValue === "string" && rawValue.trim()) {
        query.set(key, rawValue);
      }
    }
  }
  query.set("target", targetId);
  return `/google?${query.toString()}`;
}

function providerLabel(provider: string) {
  if (provider === "blogger") return "Blogger";
  if (provider === "cloudflare") return "Cloudflare";
  return provider;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] border border-slate-200 bg-slate-50 p-4">
      <p className="text-xs uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}

export default async function GoogleDataPage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  if (isStaticPreview) {
    return (
      <div className="rounded-[28px] border border-slate-200 bg-white p-6 text-sm leading-6 text-slate-500 shadow-sm">
        GitHub Pages 프리뷰에서는 SEO / 색인 데이터를 실시간으로 불러오지 않습니다.
      </div>
    );
  }

  const targets = await getSeoTargets().catch(() => []);

  if (!targets.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>SEO / 색인</CardTitle>
          <CardDescription>연동된 블로그가 아직 없습니다.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const requestedTargetId = readFirst(searchParams?.target);
  const selectedTarget = targets.find((item) => item.targetId === requestedTargetId) ?? targets[0];

  const bloggerPayload =
    selectedTarget.provider === "blogger" && selectedTarget.linkedBlogId
      ? await Promise.all([
          getGoogleBlogOverview(selectedTarget.linkedBlogId).catch(() => null),
          getSyncedBloggerPosts(selectedTarget.linkedBlogId, 1, 20).catch(() => null),
        ])
      : [null, null];

  const [blogOverview, syncedPosts] = bloggerPayload;
  const [cloudflareOverview, cloudflarePosts]: [
    Awaited<ReturnType<typeof getCloudflareOverview>> | null,
    Awaited<ReturnType<typeof getCloudflarePosts>>,
  ] =
    selectedTarget.provider === "cloudflare"
      ? await Promise.all([getCloudflareOverview().catch(() => null), getCloudflarePosts().catch(() => [])])
      : [null, []];
  const searchTotals = blogOverview?.search_console?.totals ?? {};
  const analyticsTotals = blogOverview?.analytics?.totals ?? {};

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardDescription>SEO / 색인</CardDescription>
          <CardTitle>연동 블로그별 색인 관리</CardTitle>
          <p className="text-sm leading-7 text-slate-600">
            실제로 연결된 Blogger 블로그와 Cloudflare 블로그만 목록에 보여주고, 선택한 대상 단위로 색인과 분석 상태를 관리합니다.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {targets.map((target) => {
              const active = target.targetId === selectedTarget.targetId;
              return (
                <Link
                  key={target.targetId}
                  href={buildTargetHref(searchParams, target.targetId)}
                  className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                    active ? "bg-slate-900 text-white" : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {target.label}
                </Link>
              );
            })}
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <Metric label="연동 대상 수" value={formatNumber(targets.length)} />
            <Metric label="정상 연결" value={formatNumber(targets.filter((item) => item.isConnected).length)} />
            <Metric label="Search Console 연결" value={formatNumber(targets.filter((item) => Boolean(item.searchConsoleSiteUrl)).length)} />
            <Metric label="GA4 연결" value={formatNumber(targets.filter((item) => Boolean(item.ga4PropertyId)).length)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardDescription>선택 대상</CardDescription>
              <CardTitle>{selectedTarget.label}</CardTitle>
              <p className="mt-1 text-sm text-slate-600">
                공급자: {providerLabel(selectedTarget.provider)} · OAuth 상태: {selectedTarget.oauthState}
              </p>
            </div>
            {selectedTarget.provider === "blogger" && selectedTarget.linkedBlogId ? (
              <GooglePostSyncButton blogId={selectedTarget.linkedBlogId} />
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge>{providerLabel(selectedTarget.provider)}</Badge>
            {selectedTarget.baseUrl ? <Badge className="bg-transparent">기준 URL 연결</Badge> : null}
            {selectedTarget.searchConsoleSiteUrl ? <Badge className="bg-transparent">Search Console 연결</Badge> : null}
            {selectedTarget.ga4PropertyId ? <Badge className="bg-transparent">GA4 연결</Badge> : null}
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {selectedTarget.provider === "blogger" ? (
            <>
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
                <Metric label="SC 클릭" value={formatNumber(searchTotals.clicks)} />
                <Metric label="SC 노출" value={formatNumber(searchTotals.impressions)} />
                <Metric label="SC CTR" value={formatPercent(searchTotals.ctr)} />
                <Metric label="SC 평균 순위" value={String(searchTotals.position ?? 0)} />
                <Metric label="GA4 페이지뷰" value={formatNumber(analyticsTotals.screenPageViews)} />
                <Metric label="동기화 글" value={formatNumber(syncedPosts?.total ?? 0)} />
              </div>

              <div className="space-y-3">
                <h3 className="text-base font-semibold text-slate-900">동기화된 게시글</h3>
                {!syncedPosts?.items?.length ? (
                  <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                    아직 동기화된 게시글이 없습니다.
                  </p>
                ) : (
                  syncedPosts.items.map((post) => (
                    <div key={post.id} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-slate-900">{post.title}</p>
                        {post.status ? <Badge className="bg-transparent">{post.status}</Badge> : null}
                      </div>
                      <p className="mt-1 text-xs text-slate-500">수정 시각: {formatDateTime(post.updated)}</p>
                      {post.url ? (
                        <a href={post.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex text-sm text-sky-700 hover:underline">
                          게시글 열기
                        </a>
                      ) : null}
                    </div>
                  ))
                )}
              </div>

              {selectedTarget.linkedBlogId ? <GoogleIndexingControls blogId={selectedTarget.linkedBlogId} /> : null}
            </>
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-4">
                <Metric label="게시글 수" value={formatNumber(cloudflareOverview?.posts_count)} />
                <Metric label="카테고리 수" value={formatNumber(cloudflareOverview?.categories_count)} />
                <Metric label="프롬프트 수" value={formatNumber(cloudflareOverview?.prompts_count)} />
                <Metric label="기준 URL" value={cloudflareOverview?.base_url || "-"} />
              </div>

              <div className="space-y-3">
                <h3 className="text-base font-semibold text-slate-900">Cloudflare 게시글</h3>
                {!cloudflarePosts.length ? (
                  <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                    표시할 게시글이 없습니다.
                  </p>
                ) : (
                  cloudflarePosts.slice(0, 20).map((post) => (
                    <div key={post.remote_id} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-slate-900">{post.title}</p>
                        <Badge className="bg-transparent">{post.provider_status}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        카테고리: {post.category_slug || "-"} · 수정 시각: {formatDateTime(post.updated_at)}
                      </p>
                      {post.published_url ? (
                        <a href={post.published_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex text-sm text-sky-700 hover:underline">
                          게시글 열기
                        </a>
                      ) : null}
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

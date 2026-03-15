import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getBlogs, getBloggerConfig, getGoogleBlogOverview } from "@/lib/api";

function formatNumber(value: number | undefined | null) {
  return new Intl.NumberFormat("ko-KR").format(value ?? 0);
}

function formatPercent(value: number | undefined | null) {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
      <p className="text-xs uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-ink">{value}</p>
    </div>
  );
}

function MappingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-2 text-sm leading-7 text-slate-700 sm:grid-cols-[132px_minmax(0,1fr)]">
      <p className="font-medium text-slate-500">{label}</p>
      <p className="min-w-0 break-all">{value}</p>
    </div>
  );
}

export default async function GoogleDataPage() {
  const [blogs, bloggerConfig] = await Promise.all([getBlogs(), getBloggerConfig()]);
  const overviews = await Promise.all(blogs.map((blog) => getGoogleBlogOverview(blog.id).catch(() => null)));

  return (
    <div className="space-y-8">
      <section className="grid gap-6 xl:grid-cols-[1.4fr_0.9fr]">
        <Card>
          <CardHeader>
            <CardDescription>Google 운영 데이터</CardDescription>
            <CardTitle>블로그 채널 현황</CardTitle>
            <p className="text-sm leading-7 text-slate-600">
              Blogger, Search Console, Google Analytics 데이터를 블로그별로 모아 봅니다. 긴 주소와 속성 ID도
              카드 안에서 줄바꿈되도록 정리했습니다.
            </p>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-4">
            <SummaryMetric label="연결된 Blogger 블로그" value={formatNumber(bloggerConfig.available_blogs.length)} />
            <SummaryMetric label="Search Console 속성" value={formatNumber(bloggerConfig.search_console_sites.length)} />
            <SummaryMetric label="GA4 속성" value={formatNumber(bloggerConfig.analytics_properties.length)} />
            <SummaryMetric label="승인된 OAuth Scope" value={formatNumber(bloggerConfig.granted_scopes.length)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardDescription>권한 상태</CardDescription>
            <CardTitle>현재 승인된 Scope</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {bloggerConfig.granted_scopes.length ? (
              bloggerConfig.granted_scopes.map((scope) => (
                <div key={scope} className="rounded-[20px] border border-ink/10 bg-white/70 px-4 py-3">
                  <p className="break-all font-mono text-xs text-slate-700">{scope}</p>
                </div>
              ))
            ) : (
              <p className="text-sm leading-7 text-slate-600">
                아직 승인된 Google OAuth 권한이 없습니다. 설정 화면에서 Google 계정 연결을 진행하면 Blogger,
                Search Console, GA4 권한을 함께 요청합니다.
              </p>
            )}
          </CardContent>
        </Card>
      </section>

      <section className="space-y-6">
        {blogs.map((blog, index) => {
          const overview = overviews[index];
          const pageview7d = overview?.pageviews.find((item) => item.range === "7D")?.count ?? 0;
          const pageview30d = overview?.pageviews.find((item) => item.range === "30D")?.count ?? 0;
          const pageviewAll = overview?.pageviews.find((item) => item.range === "all")?.count ?? 0;
          const searchTotals = overview?.search_console?.totals ?? {};
          const analyticsTotals = overview?.analytics?.totals ?? {};

          return (
            <Card key={blog.id} className="overflow-hidden">
              <CardHeader className="border-b border-ink/10 bg-white/70">
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div className="space-y-2">
                    <CardDescription>블로그별 Google 데이터</CardDescription>
                    <CardTitle>{blog.name}</CardTitle>
                    <p className="text-sm leading-6 text-slate-600">{blog.content_brief}</p>
                    <div className="flex flex-wrap gap-2 pt-1">
                      <Badge>{blog.content_category}</Badge>
                      <Badge className="bg-transparent">{blog.primary_language}</Badge>
                      {blog.blogger_blog_id ? <Badge className="bg-transparent">Blogger 연결</Badge> : null}
                      {blog.search_console_site_url ? <Badge className="bg-transparent">SC 연결</Badge> : null}
                      {blog.ga4_property_id ? <Badge className="bg-transparent">GA4 연결</Badge> : null}
                    </div>
                  </div>
                  {overview?.remote_blog?.url ? (
                    <a
                      href={overview.remote_blog.url}
                      target="_blank"
                      rel="noreferrer"
                      className="break-all text-sm font-medium text-ember underline-offset-4 hover:underline"
                    >
                      실제 블로그 열기
                    </a>
                  ) : null}
                </div>
              </CardHeader>

              <CardContent className="space-y-6 p-6">
                {overview?.warnings?.length ? (
                  <div className="rounded-[24px] border border-amber-200 bg-amber-50 px-4 py-4 text-sm leading-7 text-amber-950">
                    {overview.warnings.map((warning) => (
                      <p key={warning}>{warning}</p>
                    ))}
                  </div>
                ) : null}

                <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
                  <SummaryMetric label="Blogger 7일" value={formatNumber(pageview7d)} />
                  <SummaryMetric label="Blogger 30일" value={formatNumber(pageview30d)} />
                  <SummaryMetric label="Blogger 전체" value={formatNumber(pageviewAll)} />
                  <SummaryMetric label="SC 클릭" value={formatNumber(searchTotals.clicks)} />
                  <SummaryMetric label="SC 노출" value={formatNumber(searchTotals.impressions)} />
                  <SummaryMetric label="GA4 페이지뷰" value={formatNumber(analyticsTotals.screenPageViews)} />
                </div>

                <div className="grid gap-6 xl:grid-cols-2">
                  <Card className="border border-ink/10 shadow-none">
                    <CardHeader>
                      <CardDescription>최근 게시글</CardDescription>
                      <CardTitle>Blogger 글 목록</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {overview?.recent_posts?.length ? (
                        overview.recent_posts.map((post) => (
                          <div key={post.id} className="rounded-[20px] border border-ink/10 px-4 py-3">
                            {post.url ? (
                              <a
                                href={post.url}
                                target="_blank"
                                rel="noreferrer"
                                className="break-words font-medium text-ember underline-offset-4 hover:underline"
                              >
                                {post.title}
                              </a>
                            ) : (
                              <p className="break-words font-medium text-ink">{post.title}</p>
                            )}
                            <p className="mt-1 text-xs text-slate-500">
                              {post.status || "-"} / {formatDate(post.updated || post.published)}
                            </p>
                            {post.labels.length ? (
                              <p className="mt-1 break-all text-xs text-slate-500">{post.labels.join(", ")}</p>
                            ) : null}
                          </div>
                        ))
                      ) : (
                        <p className="text-sm leading-7 text-slate-600">표시할 Blogger 게시글 데이터가 아직 없습니다.</p>
                      )}
                    </CardContent>
                  </Card>

                  <Card className="border border-ink/10 shadow-none">
                    <CardHeader>
                      <CardDescription>블로그 연결 정보</CardDescription>
                      <CardTitle>현재 매핑된 채널</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <MappingRow label="Blogger ID" value={blog.blogger_blog_id || "-"} />
                      <MappingRow label="Search Console" value={blog.search_console_site_url || "-"} />
                      <MappingRow label="GA4 속성 ID" value={blog.ga4_property_id || "-"} />
                      <MappingRow label="원격 포스트 수" value={formatNumber(overview?.remote_blog?.posts_total_items)} />
                      <MappingRow label="원격 페이지 수" value={formatNumber(overview?.remote_blog?.pages_total_items)} />
                      <MappingRow label="마지막 업데이트" value={formatDate(overview?.remote_blog?.updated)} />
                    </CardContent>
                  </Card>
                </div>

                <div className="grid gap-6 xl:grid-cols-2">
                  <Card className="border border-ink/10 shadow-none">
                    <CardHeader>
                      <CardDescription>Search Console</CardDescription>
                      <CardTitle>최근 28일 검색 성과</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-5">
                      {overview?.search_console ? (
                        <>
                          <div className="grid gap-3 md:grid-cols-4">
                            <SummaryMetric label="클릭" value={formatNumber(searchTotals.clicks)} />
                            <SummaryMetric label="노출" value={formatNumber(searchTotals.impressions)} />
                            <SummaryMetric label="CTR" value={formatPercent(searchTotals.ctr)} />
                            <SummaryMetric label="평균 순위" value={Number(searchTotals.position ?? 0).toFixed(1)} />
                          </div>
                          <div className="grid gap-3 lg:grid-cols-2">
                            <div className="space-y-3">
                              <p className="text-sm font-semibold text-ink">상위 검색어</p>
                              {(overview.search_console.top_queries ?? []).slice(0, 5).map((row) => (
                                <div key={row.keys[0]} className="rounded-[20px] border border-ink/10 px-4 py-3">
                                  <p className="break-words font-medium text-ink">{row.keys[0]}</p>
                                  <p className="mt-1 text-xs text-slate-500">
                                    클릭 {formatNumber(row.clicks)} / 노출 {formatNumber(row.impressions)} / CTR {formatPercent(row.ctr)}
                                  </p>
                                </div>
                              ))}
                            </div>
                            <div className="space-y-3">
                              <p className="text-sm font-semibold text-ink">상위 페이지</p>
                              {(overview.search_console.top_pages ?? []).slice(0, 5).map((row) => (
                                <div key={row.keys[0]} className="rounded-[20px] border border-ink/10 px-4 py-3">
                                  <p className="break-all font-medium text-ink">{row.keys[0]}</p>
                                  <p className="mt-1 text-xs text-slate-500">
                                    클릭 {formatNumber(row.clicks)} / 노출 {formatNumber(row.impressions)} / 순위 {row.position.toFixed(1)}
                                  </p>
                                </div>
                              ))}
                            </div>
                          </div>
                        </>
                      ) : (
                        <p className="text-sm leading-7 text-slate-600">Search Console 데이터가 연결되지 않았거나 아직 없습니다.</p>
                      )}
                    </CardContent>
                  </Card>

                  <Card className="border border-ink/10 shadow-none">
                    <CardHeader>
                      <CardDescription>Google Analytics 4</CardDescription>
                      <CardTitle>최근 28일 트래픽</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-5">
                      {overview?.analytics ? (
                        <>
                          <div className="grid gap-3 md:grid-cols-3">
                            <SummaryMetric label="세션" value={formatNumber(analyticsTotals.sessions)} />
                            <SummaryMetric label="페이지뷰" value={formatNumber(analyticsTotals.screenPageViews)} />
                            <SummaryMetric label="사용자" value={formatNumber(analyticsTotals.activeUsers)} />
                          </div>
                          <div className="space-y-3">
                            <p className="text-sm font-semibold text-ink">상위 페이지</p>
                            {(overview.analytics.top_pages ?? []).slice(0, 5).map((page) => (
                              <div key={page.page_path} className="rounded-[20px] border border-ink/10 px-4 py-3">
                                <p className="break-all font-medium text-ink">{page.page_path || "/"}</p>
                                <p className="mt-1 text-xs text-slate-500">
                                  페이지뷰 {formatNumber(page.screenPageViews)} / 세션 {formatNumber(page.sessions)}
                                </p>
                              </div>
                            ))}
                          </div>
                        </>
                      ) : (
                        <p className="text-sm leading-7 text-slate-600">GA4 데이터가 연결되지 않았거나 아직 없습니다.</p>
                      )}
                    </CardContent>
                  </Card>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </section>
    </div>
  );
}

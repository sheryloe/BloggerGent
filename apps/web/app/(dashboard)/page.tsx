import { Clock3, Flame, Rocket, ShieldX } from "lucide-react";

import { ProcessingChart } from "@/components/dashboard/charts";
import { DiscoverButton } from "@/components/dashboard/discover-button";
import { MetricCard } from "@/components/dashboard/metric-card";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getBlogs, getDashboardMetrics, getJobs } from "@/lib/api";

export default async function DashboardPage() {
  const [metrics, jobs, blogs] = await Promise.all([getDashboardMetrics(), getJobs(), getBlogs()]);

  return (
    <div className="space-y-8">
      <section className="grid gap-6 xl:grid-cols-[1.5fr_0.9fr]">
        <Card className="overflow-hidden">
          <CardContent className="grid gap-8 p-8 md:grid-cols-[1.2fr_0.8fr]">
            <div className="space-y-5">
              <Badge className="bg-white/90 text-spruce">서비스형 블로그 반자동 운영</Badge>
              <div className="space-y-3">
                <h2 className="font-display text-4xl font-semibold leading-tight text-ink md:text-5xl">
                  블로그마다 다른 에이전트와 프롬프트를 배정해서 주제 발굴부터 Blogger 발행까지 자동으로
                  운영합니다.
                </h2>
                <p className="max-w-2xl text-base leading-8 text-slate-600">
                  여행, 축제, 행사 블로그와 미스터리 블로그처럼 서로 다른 성격의 채널도 같은 서비스 안에서
                  개별 워크플로로 운영할 수 있습니다.
                </p>
              </div>
            </div>

            <div className="space-y-4 rounded-[28px] bg-ink px-6 py-6 text-white">
              <p className="text-xs uppercase tracking-[0.2em] text-white/70">운영 중인 블로그</p>
              <div className="space-y-3">
                {blogs.length ? (
                  blogs.map((blog) => (
                    <div key={blog.id} className="rounded-3xl bg-white/8 px-4 py-4">
                      <p className="break-words font-medium">{blog.name}</p>
                      <p className="mt-2 break-words text-sm leading-6 text-white/70">{blog.description}</p>
                      <p className="mt-2 text-xs uppercase tracking-[0.16em] text-white/60">
                        {blog.content_category} / {blog.publish_mode}
                      </p>
                    </div>
                  ))
                ) : (
                  <div className="rounded-3xl bg-white/8 px-4 py-4 text-sm text-white/75">
                    아직 가져온 Blogger 블로그가 없습니다. 설정 화면에서 실제 블로그를 먼저 가져와 주세요.
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-1">
          <MetricCard
            title="오늘 완료"
            value={metrics.today_generated_posts.toString()}
            description="오늘 완료된 자동 생성 작업 수입니다."
            icon={<Rocket className="h-5 w-5" />}
          />
          <MetricCard
            title="평균 처리 시간"
            value={`${Math.round(metrics.avg_processing_seconds)}s`}
            description="본문 생성부터 Blogger 발행까지 걸린 평균 시간입니다."
            icon={<Clock3 className="h-5 w-5" />}
          />
        </div>
      </section>

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="성공 작업"
          value={metrics.success_jobs.toString()}
          description="완료 상태까지 정상 처리된 전체 작업 수입니다."
          icon={<Flame className="h-5 w-5" />}
        />
        <MetricCard
          title="실패 작업"
          value={metrics.failed_jobs.toString()}
          description="재시도나 설정 보정이 필요한 작업 수입니다."
          icon={<ShieldX className="h-5 w-5" />}
        />
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardDescription>상태 요약</CardDescription>
            <CardTitle>현재 작업 분포</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            {Object.entries(metrics.jobs_by_status).map(([status, count]) => (
              <div key={status} className="flex items-center justify-between rounded-3xl border border-ink/10 bg-white/60 px-4 py-3">
                <StatusBadge status={status as never} />
                <span className="text-lg font-semibold text-ink">{count}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        {blogs.map((blog) => {
          const summary = metrics.blog_summaries.find((item) => item.blog_id === blog.id);
          return (
            <Card key={blog.id}>
              <CardHeader>
                <CardDescription>블로그별 진행</CardDescription>
                <CardTitle>{blog.name}</CardTitle>
                <p className="break-words text-sm leading-6 text-slate-600">{blog.content_brief}</p>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-3xl border border-ink/10 bg-white/70 px-4 py-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">완료 / 실패 / 대기</p>
                    <p className="mt-2 text-lg font-semibold text-ink">
                      {summary?.completed_jobs ?? 0} / {summary?.failed_jobs ?? 0} / {summary?.queued_jobs ?? 0}
                    </p>
                  </div>
                  <div className="rounded-3xl border border-ink/10 bg-white/70 px-4 py-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">게시 수</p>
                    <p className="mt-2 text-lg font-semibold text-ink">{summary?.published_posts ?? 0}</p>
                  </div>
                </div>

                <div className="space-y-2">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">최근 발굴 주제</p>
                  <div className="flex flex-wrap gap-2">
                    {(summary?.latest_topic_keywords ?? []).length ? (
                      summary?.latest_topic_keywords.map((keyword) => <Badge key={keyword}>{keyword}</Badge>)
                    ) : (
                      <p className="text-sm text-slate-500">아직 수집된 주제가 없습니다.</p>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <DiscoverButton blogId={blog.id} label={`${blog.name} 주제 발굴`} />
                  {summary?.latest_published_url ? (
                    <a
                      href={summary.latest_published_url}
                      target="_blank"
                      rel="noreferrer"
                      className="break-all text-sm font-medium text-ember underline-offset-4 hover:underline"
                    >
                      최근 게시글 보기
                    </a>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <ProcessingChart data={metrics.processing_series} />
        <Card>
          <CardHeader>
            <CardDescription>최근 Blogger 결과</CardDescription>
            <CardTitle>발행 링크</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {metrics.latest_published_links.length ? (
              metrics.latest_published_links.map((post) => (
                <a
                  key={post.id}
                  href={post.published_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded-3xl border border-ink/10 bg-white/70 px-4 py-4 transition hover:bg-white"
                >
                  <p className="break-all text-sm font-semibold text-ink">{post.published_url}</p>
                  <p className="mt-2 text-xs uppercase tracking-[0.16em] text-slate-500">
                    {post.is_draft ? "초안 상태" : "발행 완료"}
                  </p>
                </a>
              ))
            ) : (
              <p className="text-sm leading-6 text-slate-600">
                아직 발행된 링크가 없습니다. 먼저 블로그별 주제 발굴이나 수동 실행을 시작해 보세요.
              </p>
            )}
          </CardContent>
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader>
            <CardDescription>최신 파이프라인</CardDescription>
            <CardTitle>최근 작업</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {jobs.slice(0, 6).map((job) => (
              <div key={job.id} className="flex flex-col gap-3 rounded-3xl border border-ink/10 bg-white/70 px-5 py-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="break-words font-semibold text-ink">{job.keyword_snapshot}</p>
                  <p className="mt-1 text-sm text-slate-500">
                    {job.blog?.name ?? "미연결 블로그"} / 시도 {job.attempt_count} / {job.max_attempts}
                  </p>
                </div>
                <StatusBadge status={job.status} />
              </div>
            ))}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

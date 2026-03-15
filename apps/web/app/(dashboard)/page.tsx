import { CheckCircle2, Clock3, Rocket, ShieldX } from "lucide-react";

import { ProcessingChart } from "@/components/dashboard/charts";
import { DiscoverButton } from "@/components/dashboard/discover-button";
import { MetricCard } from "@/components/dashboard/metric-card";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getBlogs, getDashboardMetrics, getJobs } from "@/lib/api";

export default async function DashboardPage() {
  const [metrics, jobs, blogs] = await Promise.all([getDashboardMetrics(), getJobs(), getBlogs()]);
  const currentBlog = blogs[0] ?? null;
  const currentSummary = currentBlog ? metrics.blog_summaries.find((item) => item.blog_id === currentBlog.id) : null;

  return (
    <div className="space-y-8">
      <section className="grid gap-6 xl:grid-cols-[1.35fr_0.85fr]">
        <Card className="overflow-hidden">
          <CardContent className="grid gap-8 p-8 md:grid-cols-[1.2fr_0.8fr]">
            <div className="space-y-5">
              <div className="space-y-3">
                <h1 className="font-display text-4xl font-semibold leading-tight text-ink md:text-5xl">
                  Google Blogger 반자동 운영 대시보드
                </h1>
                <p className="max-w-2xl text-base leading-8 text-slate-600">
                  지금 작업할 블로그를 기준으로 주제 발굴, 글 생성, 이미지, 게시 상태를 빠르게 확인하고 관리합니다.
                </p>
              </div>

              {currentBlog ? (
                <div className="flex flex-wrap items-center gap-3">
                  <DiscoverButton blogId={currentBlog.id} label={`${currentBlog.name} 주제 발굴`} />
                  {currentSummary?.latest_published_url ? (
                    <a
                      href={currentSummary.latest_published_url}
                      target="_blank"
                      rel="noreferrer"
                      className="break-all text-sm font-medium text-ember underline-offset-4 hover:underline"
                    >
                      최근 게시글 보기
                    </a>
                  ) : null}
                </div>
              ) : null}
            </div>

            <div className="space-y-4 rounded-[28px] bg-ink px-6 py-6 text-white">
              <div className="space-y-1">
                <p className="text-xs uppercase tracking-[0.2em] text-white/70">현재 작업 중인 블로그</p>
                <p className="text-2xl font-semibold">{currentBlog?.name ?? "연결된 블로그 없음"}</p>
              </div>

              {currentSummary ? (
                <div className="space-y-3">
                  <div className="rounded-3xl bg-white/8 px-4 py-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-white/55">완료 / 실패 / 대기</p>
                    <p className="mt-2 text-lg font-semibold text-white">
                      {currentSummary.completed_jobs} / {currentSummary.failed_jobs} / {currentSummary.queued_jobs}
                    </p>
                  </div>
                  <div className="rounded-3xl bg-white/8 px-4 py-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-white/55">게시 글 수</p>
                    <p className="mt-2 text-lg font-semibold text-white">{currentSummary.published_posts}</p>
                  </div>
                  <div className="rounded-3xl bg-white/8 px-4 py-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-white/55">최근 주제</p>
                    <p className="mt-2 break-words text-sm leading-6 text-white/85">
                      {currentSummary.latest_topic_keywords.join(", ") || "아직 없습니다."}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="rounded-3xl bg-white/8 px-4 py-4 text-sm leading-6 text-white/75">
                  아직 가져온 Blogger 블로그가 없습니다. 설정 화면에서 실제 블로그를 먼저 가져와 주세요.
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-1">
          <MetricCard
            title="오늘 완료"
            value={metrics.today_generated_posts.toString()}
            description="오늘 완료 처리된 생성/게시 작업 수입니다."
            icon={<Rocket className="h-5 w-5" />}
          />
          <MetricCard
            title="평균 처리 시간"
            value={`${Math.round(metrics.avg_processing_seconds)}s`}
            description="최근 작업 기준 평균 소요 시간입니다."
            icon={<Clock3 className="h-5 w-5" />}
          />
        </div>
      </section>

      <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="완료 작업"
          value={metrics.success_jobs.toString()}
          description="정상적으로 글 생성과 게시까지 반영된 작업 수입니다."
          icon={<CheckCircle2 className="h-5 w-5" />}
        />
        <MetricCard
          title="실패 작업"
          value={metrics.failed_jobs.toString()}
          description="확인이 필요한 실패 작업 수입니다."
          icon={<ShieldX className="h-5 w-5" />}
        />
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardDescription>상태 요약</CardDescription>
            <CardTitle>현재 작업 분포</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            {Object.entries(metrics.jobs_by_status).map(([status, count]) => (
              <div
                key={status}
                className="flex items-center justify-between rounded-3xl border border-ink/10 bg-white/60 px-4 py-3"
              >
                <StatusBadge status={status as never} />
                <span className="text-lg font-semibold text-ink">{count}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <ProcessingChart data={metrics.processing_series} />
        <Card>
          <CardHeader>
            <CardDescription>최근 작업</CardDescription>
            <CardTitle>최근 6개 작업</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {jobs.slice(0, 6).map((job) => (
              <div
                key={job.id}
                className="flex flex-col gap-3 rounded-3xl border border-ink/10 bg-white/70 px-5 py-4 md:flex-row md:items-center md:justify-between"
              >
                <div className="min-w-0">
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

      <section>
        <Card>
          <CardHeader>
            <CardDescription>최근 Blogger 결과</CardDescription>
            <CardTitle>게시 링크</CardTitle>
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
                    {post.is_draft ? "초안" : "공개 게시"}
                  </p>
                </a>
              ))
            ) : (
              <p className="text-sm leading-6 text-slate-600">아직 게시된 링크가 없습니다.</p>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

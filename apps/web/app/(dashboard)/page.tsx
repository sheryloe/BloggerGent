import Link from "next/link";
import {
  ArrowUpRight,
  CalendarClock,
  FileText,
  ImageIcon,
  Layers3,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { ArticlePreviewFrame } from "@/components/dashboard/article-preview-frame";
import { ContentActionPanel } from "@/components/dashboard/content-action-panel";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  getArticleSeoMeta,
  getArticles,
  getBlogs,
  getDashboardMetrics,
  getJobs,
  getTopics,
} from "@/lib/api";
import type { ArticleSeoMeta, Job, JobStatus } from "@/lib/types";

const inactiveStatuses: JobStatus[] = ["COMPLETED", "FAILED", "STOPPED"];

function formatNumber(value: number | undefined | null) {
  return new Intl.NumberFormat("ko-KR").format(value ?? 0);
}

function formatDateTime(value?: string | null) {
  if (!value) return "데이터 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function isToday(value?: string | null) {
  if (!value) return false;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return false;

  const now = new Date();
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  );
}

function getSeoScore(meta: ArticleSeoMeta | null) {
  if (!meta) return null;

  const statuses = [
    meta.head_meta_description_status.status,
    meta.og_description_status.status,
    meta.twitter_description_status.status,
  ];

  const total = statuses.reduce((score, status) => {
    if (status === "ok") return score + 100;
    if (status === "warning") return score + 55;
    return score + 20;
  }, 0);

  return Math.round(total / statuses.length);
}

function scoreTone(score: number | null) {
  if (score === null) return "text-slate-500 dark:text-zinc-400";
  if (score >= 85) return "text-emerald-600 dark:text-emerald-300";
  if (score >= 60) return "text-amber-600 dark:text-amber-300";
  return "text-rose-600 dark:text-rose-300";
}

function formatMetaStatus(status: string) {
  if (status === "ok") return "정상";
  if (status === "warning") return "주의";
  if (status === "idle") return "대기";
  return status;
}

function formatMetaLabel(label: string) {
  if (label.toLowerCase() === "verification") return "검증";
  return label;
}

function StatCard({
  title,
  value,
  detail,
  icon,
  accentClass,
}: {
  title: string;
  value: string;
  detail: string;
  icon: React.ReactNode;
  accentClass: string;
}) {
  return (
    <Card className="h-full overflow-hidden">
      <CardContent className="flex h-full flex-col gap-5 p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 space-y-2">
            <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{title}</p>
            <p className="font-display text-3xl font-semibold tracking-tight text-slate-950 dark:text-zinc-50 sm:text-4xl">
              {value}
            </p>
          </div>
          <div className={`shrink-0 rounded-[20px] p-3 ${accentClass}`}>{icon}</div>
        </div>
        <p className="text-sm leading-6 text-slate-500 dark:text-zinc-400">{detail}</p>
      </CardContent>
    </Card>
  );
}

function SummaryTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-[24px] border border-white/60 bg-white/70 px-4 py-4 shadow-sm backdrop-blur dark:border-white/10 dark:bg-white/5">
      <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{label}</p>
      <p className="mt-2 truncate text-xl font-semibold text-slate-950 dark:text-zinc-50">{value}</p>
      <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-500 dark:text-zinc-400">{hint}</p>
    </div>
  );
}

function MetaPill({
  label,
  status,
  message,
}: {
  label: string;
  status: string;
  message: string;
}) {
  const statusClass =
    status === "ok"
      ? "border-emerald-200/80 bg-emerald-500/10 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200"
      : status === "warning"
        ? "border-amber-200/80 bg-amber-500/10 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200"
        : "border-slate-200/80 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-zinc-400";

  return (
    <div className={`rounded-[22px] border px-4 py-4 ${statusClass}`}>
      <div className="flex items-center justify-between gap-3">
        <p className="truncate text-sm font-semibold">{formatMetaLabel(label)}</p>
        <span className="shrink-0 text-[11px] uppercase tracking-[0.18em]">{formatMetaStatus(status)}</span>
      </div>
      <p className="mt-2 line-clamp-3 text-sm leading-6">{message}</p>
    </div>
  );
}

function MobileQueueCard({ job }: { job: Job }) {
  return (
    <div className="rounded-[24px] border border-slate-200/70 bg-white/85 p-4 shadow-sm dark:border-white/10 dark:bg-white/5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="line-clamp-2 text-base font-semibold text-slate-950 dark:text-zinc-100">
            {job.article?.title ?? job.keyword_snapshot}
          </p>
          <p className="mt-1 truncate text-sm text-slate-500 dark:text-zinc-400">
            {job.blog?.name ?? "블로그 미지정"}
          </p>
        </div>
        <StatusBadge status={job.status} />
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 text-sm text-slate-500 dark:text-zinc-400">
        <span className="rounded-full border border-indigo-200/80 bg-indigo-500/10 px-3 py-1 text-indigo-700 dark:border-indigo-500/20 dark:bg-indigo-500/15 dark:text-indigo-200">
          Blogger
        </span>
        <span className="shrink-0">{formatDateTime(job.created_at)}</span>
      </div>
    </div>
  );
}

export default async function DashboardPage() {
  const [metrics, jobs, blogs, topics, articles] = await Promise.all([
    getDashboardMetrics(),
    getJobs(),
    getBlogs(),
    getTopics(),
    getArticles(),
  ]);

  const featuredArticle = articles[0] ?? null;
  const featuredSeo = featuredArticle ? await getArticleSeoMeta(featuredArticle.id).catch(() => null) : null;

  const totalPublishedPosts = metrics.blog_summaries.reduce((sum, item) => sum + item.published_posts, 0);
  const scheduledPosts = jobs.filter((job) => !inactiveStatuses.includes(job.status)).length;
  const imagesToday = jobs.filter((job) => job.image && isToday(job.updated_at ?? job.created_at)).length;
  const seoScore = getSeoScore(featuredSeo);
  const publishedLinks = metrics.latest_published_links.slice(0, 4);
  const queueRows = jobs.slice(0, 8);
  const leadBlog = blogs[0] ?? null;
  const latestPublishedAt = metrics.latest_published_links[0]?.published_at ?? null;

  return (
    <div className="space-y-6 lg:space-y-8">
      <section className="overflow-hidden rounded-[34px] border border-slate-200/70 bg-white/80 px-5 py-5 shadow-[0_30px_70px_rgba(15,23,42,0.08)] backdrop-blur-xl dark:border-white/10 dark:bg-zinc-950/70 dark:shadow-[0_30px_70px_rgba(0,0,0,0.38)] sm:px-6 sm:py-6 lg:px-8 lg:py-8">
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.9fr)]">
          <div className="min-w-0 space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="border-indigo-200/80 bg-indigo-500/10 text-indigo-700 dark:border-indigo-500/20 dark:bg-indigo-500/15 dark:text-indigo-200">
                운영 대시보드
              </Badge>
              <Badge className="bg-transparent">UI 전용 리프레시</Badge>
            </div>

            <div className="space-y-3">
              <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">
                왼쪽 내비게이션, 상단 상태 요약, 메인 작업 그리드를 한 장에 정리했습니다.
              </p>
              <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-950 dark:text-zinc-50 sm:text-4xl xl:text-5xl">
                글 작성부터 발행 현황까지
                <br className="hidden sm:block" />
                흐름이 바로 보이게 정리했습니다.
              </h1>
              <p className="max-w-3xl text-sm leading-7 text-slate-500 dark:text-zinc-400 sm:text-base">
                긴 문구와 넘치는 레이아웃을 줄이고, 현재 필요한 수치와 작업 버튼만 빠르게 보이도록 밀도를 낮췄습니다.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <SummaryTile
                label="연결 블로그"
                value={formatNumber(blogs.length)}
                hint={leadBlog ? `대표 작업공간: ${leadBlog.name}` : "설정에서 블로그를 먼저 연결하세요."}
              />
              <SummaryTile
                label="대기 작업"
                value={formatNumber(scheduledPosts)}
                hint="현재 처리 중이거나 예약된 글 생성 작업입니다."
              />
              <SummaryTile
                label="최근 발행"
                value={latestPublishedAt ? formatDateTime(latestPublishedAt) : "아직 없음"}
                hint="최근 공개된 포스트 기준으로 표시합니다."
              />
            </div>

            <div className="flex flex-wrap gap-3">
              <Button asChild size="lg">
                <Link href="/articles">
                  글 보관함 보기
                  <ArrowUpRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link href="/settings">연동 상태 확인</Link>
              </Button>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
            <SummaryTile
              label="대표 블로그"
              value={leadBlog?.name ?? "미설정"}
              hint={leadBlog?.content_category ?? "콘텐츠 분류 정보가 없습니다."}
            />
            <SummaryTile
              label="SEO 준비도"
              value={seoScore === null ? "대기" : `${seoScore}%`}
              hint={featuredArticle ? `"${featuredArticle.title}" 기준` : "대표 글이 아직 없습니다."}
            />
            <SummaryTile
              label="발굴 주제"
              value={formatNumber(topics.length)}
              hint="현재 블로그별로 저장된 최신 토픽 수입니다."
            />
            <SummaryTile
              label="생성된 글"
              value={formatNumber(articles.length)}
              hint="초안과 발행 전 글까지 포함한 전체 수입니다."
            />
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
        <StatCard
          title="총 발행 글 수"
          value={formatNumber(totalPublishedPosts)}
          detail="연결된 전체 블로그의 누적 발행 글 수입니다."
          icon={<FileText className="h-5 w-5" />}
          accentClass="bg-indigo-500/10 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200"
        />
        <StatCard
          title="예약된 포스팅"
          value={formatNumber(scheduledPosts)}
          detail="완료 전 상태의 작업을 합산해서 보여줍니다."
          icon={<CalendarClock className="h-5 w-5" />}
          accentClass="bg-slate-950 text-white dark:bg-white dark:text-slate-950"
        />
        <StatCard
          title="오늘 생성된 이미지"
          value={formatNumber(imagesToday)}
          detail="오늘 업데이트된 작업 중 이미지 결과가 있는 건수입니다."
          icon={<ImageIcon className="h-5 w-5" />}
          accentClass="bg-emerald-500/10 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200"
        />
        <StatCard
          title="현재 SEO 점수"
          value={seoScore === null ? "--" : `${seoScore}%`}
          detail="대표 글의 메타 설명, OG, Twitter 상태를 기준으로 계산합니다."
          icon={<ShieldCheck className="h-5 w-5" />}
          accentClass="bg-sky-500/10 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200"
        />
      </section>

      <section className="grid gap-6 2xl:grid-cols-[minmax(0,1.12fr)_minmax(340px,0.88fr)]">
        <div className="space-y-6">
          <ContentActionPanel blogs={blogs} topics={topics} />

          <Card className="overflow-hidden">
            <CardHeader className="border-b border-slate-200/70 dark:border-white/10">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div className="min-w-0">
                  <CardDescription>작업 현황</CardDescription>
                  <CardTitle className="text-2xl sm:text-[28px]">현재 진행 중인 글</CardTitle>
                </div>
                <Badge className="w-fit">{queueRows.length}건 표시 중</Badge>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {queueRows.length ? (
                <>
                  <div className="grid gap-3 p-4 md:hidden">
                    {queueRows.map((job) => (
                      <MobileQueueCard key={job.id} job={job} />
                    ))}
                  </div>

                  <div className="hidden overflow-x-auto md:block">
                    <Table className="min-w-[720px] table-fixed">
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-[45%]">제목</TableHead>
                          <TableHead className="w-[18%]">플랫폼</TableHead>
                          <TableHead className="w-[19%]">상태</TableHead>
                          <TableHead className="w-[18%]">생성 시간</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {queueRows.map((job) => (
                          <TableRow key={job.id}>
                            <TableCell className="min-w-0">
                              <div className="min-w-0 space-y-1">
                                <p className="line-clamp-2 text-sm font-semibold leading-6 text-slate-950 dark:text-zinc-100 lg:text-base">
                                  {job.article?.title ?? job.keyword_snapshot}
                                </p>
                                <p className="truncate text-xs uppercase tracking-[0.16em] text-slate-400 dark:text-zinc-500">
                                  {job.blog?.name ?? "블로그 미지정"}
                                </p>
                              </div>
                            </TableCell>
                            <TableCell>
                              <Badge className="border-indigo-200/80 bg-indigo-500/10 text-indigo-700 dark:border-indigo-500/20 dark:bg-indigo-500/15 dark:text-indigo-200">
                                Blogger
                              </Badge>
                            </TableCell>
                            <TableCell>
                              <StatusBadge status={job.status} />
                            </TableCell>
                            <TableCell className="whitespace-nowrap text-sm text-slate-500 dark:text-zinc-400">
                              {formatDateTime(job.created_at)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </>
              ) : (
                <div className="px-6 py-12 text-sm leading-7 text-slate-500 dark:text-zinc-400">
                  아직 생성된 작업이 없습니다. 위 작성 패널에서 첫 초안을 만들어 주세요.
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="overflow-hidden">
            <CardHeader className="border-b border-slate-200/70 dark:border-white/10">
              <div className="flex flex-col gap-3">
                <CardDescription>미리보기</CardDescription>
                <CardTitle className="text-2xl sm:text-[28px]">실제 포스트 프리뷰</CardTitle>
              </div>
            </CardHeader>

            <CardContent className="space-y-5 p-5 sm:p-6">
              {featuredArticle ? (
                <>
                  <div className="space-y-3">
                    <div className="flex flex-wrap gap-2">
                      <Badge className="border-emerald-200/80 bg-emerald-500/10 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/15 dark:text-emerald-200">
                        대표 초안
                      </Badge>
                      {featuredArticle.labels.slice(0, 3).map((label) => (
                        <Badge key={label} className="max-w-[160px] truncate">
                          {label}
                        </Badge>
                      ))}
                    </div>
                    <h2 className="line-clamp-2 text-2xl font-semibold leading-tight text-slate-950 dark:text-zinc-50">
                      {featuredArticle.title}
                    </h2>
                    <p className="line-clamp-4 text-sm leading-7 text-slate-500 dark:text-zinc-400">
                      {featuredArticle.excerpt}
                    </p>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-3">
                    <div className="rounded-[22px] border border-slate-200/70 bg-slate-50/80 px-4 py-4 dark:border-white/10 dark:bg-white/5">
                      <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">읽는 시간</p>
                      <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-zinc-50">
                        {featuredArticle.reading_time_minutes}분
                      </p>
                    </div>
                    <div className="rounded-[22px] border border-slate-200/70 bg-slate-50/80 px-4 py-4 dark:border-white/10 dark:bg-white/5">
                      <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">SEO 점수</p>
                      <p className={`mt-2 text-lg font-semibold ${scoreTone(seoScore)}`}>
                        {seoScore === null ? "대기" : `${seoScore}%`}
                      </p>
                    </div>
                    <div className="rounded-[22px] border border-slate-200/70 bg-slate-50/80 px-4 py-4 dark:border-white/10 dark:bg-white/5">
                      <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">라벨 수</p>
                      <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-zinc-50">
                        {featuredArticle.labels.length}개
                      </p>
                    </div>
                  </div>

                  <div className="overflow-hidden rounded-[28px] border border-slate-200/70 bg-slate-50/70 p-2 dark:border-white/10 dark:bg-white/5">
                    <ArticlePreviewFrame article={featuredArticle} height={560} />
                  </div>

                  {featuredSeo ? (
                    <div className="space-y-3">
                      <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">메타 검수</p>
                      <div className="grid gap-3">
                        <MetaPill
                          label={featuredSeo.head_meta_description_status.label}
                          status={featuredSeo.head_meta_description_status.status}
                          message={featuredSeo.head_meta_description_status.message}
                        />
                        <MetaPill
                          label={featuredSeo.og_description_status.label}
                          status={featuredSeo.og_description_status.status}
                          message={featuredSeo.og_description_status.message}
                        />
                        <MetaPill
                          label={featuredSeo.twitter_description_status.label}
                          status={featuredSeo.twitter_description_status.status}
                          message={featuredSeo.twitter_description_status.message}
                        />
                      </div>
                    </div>
                  ) : null}

                  <Button asChild variant="outline" className="w-full">
                    <Link href={`/articles?article=${featuredArticle.id}`}>전체 글 작업 화면 열기</Link>
                  </Button>
                </>
              ) : (
                <div className="rounded-[28px] border border-dashed border-slate-200/80 bg-slate-50/80 px-4 py-6 text-sm leading-7 text-slate-500 dark:border-white/10 dark:bg-white/5 dark:text-zinc-400">
                  아직 생성된 글이 없어 프리뷰를 보여줄 수 없습니다. 위에서 주제를 입력하거나 AI 발굴을 실행해 주세요.
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardDescription>발행 링크</CardDescription>
              <CardTitle className="text-2xl sm:text-[28px]">최근 공개된 포스트</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {publishedLinks.length ? (
                publishedLinks.map((post) => (
                  <a
                    key={post.id}
                    href={post.published_url}
                    target="_blank"
                    rel="noreferrer"
                    className="block rounded-[24px] border border-slate-200/70 bg-white/85 px-4 py-4 transition hover:-translate-y-0.5 hover:bg-white dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-950 dark:text-zinc-100 sm:text-base">
                          {post.published_url}
                        </p>
                        <p className="mt-2 text-xs uppercase tracking-[0.16em] text-slate-400 dark:text-zinc-500">
                          {post.is_draft ? "임시저장" : "공개됨"}
                        </p>
                      </div>
                      <Layers3 className="mt-1 h-4 w-4 shrink-0 text-slate-300 dark:text-zinc-600" />
                    </div>
                  </a>
                ))
              ) : (
                <div className="rounded-[24px] border border-dashed border-slate-200/80 bg-slate-50/80 px-4 py-5 text-sm leading-7 text-slate-500 dark:border-white/10 dark:bg-white/5 dark:text-zinc-400">
                  아직 공개된 링크가 없습니다. 첫 발행이 완료되면 여기에 표시됩니다.
                </div>
              )}

              <div className="rounded-[28px] border border-slate-200/70 bg-slate-50/80 px-4 py-5 dark:border-white/10 dark:bg-white/5">
                <div className="flex items-center gap-3">
                  <div className="rounded-2xl bg-indigo-500/10 p-2 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200">
                    <Sparkles className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-medium text-slate-950 dark:text-zinc-100">UI만 손봤습니다</p>
                    <p className="text-sm leading-6 text-slate-500 dark:text-zinc-400">
                      글 생성 흐름, API, DB, 블로그 연결 정보는 그대로 두고 배치와 가독성만 정리했습니다.
                    </p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  );
}

import Link from "next/link";

import { ArticlePreviewFrame } from "@/components/dashboard/article-preview-frame";
import { ArchiveBlogSelector } from "@/components/dashboard/archive-blog-selector";
import { ArticleSeoMetaCard } from "@/components/dashboard/article-seo-meta-card";
import { PublishArticleButton } from "@/components/dashboard/publish-article-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getArticle, getArticleSeoMeta, getBlogArchive, getBlogs } from "@/lib/api";
import type { Article, Blog, BlogArchiveItem } from "@/lib/types";

const ARCHIVE_PAGE_SIZE = 20;

function parsePositiveInt(value: string | string[] | undefined, fallback: number) {
  const raw = Array.isArray(value) ? value[0] : value;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function readString(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "short", day: "numeric" }).format(date);
}

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

function DetailsRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[120px_minmax(0,1fr)]">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className={`min-w-0 text-sm text-slate-700 ${mono ? "break-all font-mono text-xs" : "break-words"}`}>{value}</p>
    </div>
  );
}

function sourceBadge(source: BlogArchiveItem["source"]) {
  return source === "generated" ? "생성 글" : "기존 Blogger 글";
}

function statusBadge(item: BlogArchiveItem) {
  if (item.source === "synced") return "공개";
  if (item.status === "published") return "공개";
  if (item.status === "scheduled") return "예약됨";
  if (item.status === "draft") return "초안";
  return "생성됨";
}

function buildArchiveHref(
  searchParams: Record<string, string | string[] | undefined> | undefined,
  updates: Record<string, string | null>,
) {
  const params = new URLSearchParams();

  if (searchParams) {
    for (const [key, rawValue] of Object.entries(searchParams)) {
      if (updates[key] === null) continue;
      if (Array.isArray(rawValue)) {
        for (const value of rawValue) params.append(key, value);
      } else if (typeof rawValue === "string" && rawValue.length > 0) {
        params.set(key, rawValue);
      }
    }
  }

  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === "") {
      params.delete(key);
    } else {
      params.set(key, value);
    }
  }

  const query = params.toString();
  return query ? `/articles?${query}` : "/articles";
}

function ArchiveListCard({ item, selected, href }: { item: BlogArchiveItem; selected: boolean; href: string }) {
  return (
    <Link
      href={href}
      className={`block rounded-[24px] border px-4 py-4 transition ${
        selected ? "border-ink bg-white shadow-sm" : "border-ink/10 bg-white/60 hover:bg-white"
      }`}
    >
      <div className="flex gap-4">
        <div className="h-20 w-20 shrink-0 overflow-hidden rounded-[18px] border border-ink/10 bg-slate-100">
          {item.thumbnail_url ? (
            <img src={item.thumbnail_url} alt={item.title} className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-[11px] font-medium text-slate-400">NO IMAGE</div>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={item.source === "generated" ? "bg-ink text-white" : "bg-slate-200 text-slate-800"}>
              {sourceBadge(item.source)}
            </Badge>
            <Badge className="border border-ink/10 bg-white text-ink">{statusBadge(item)}</Badge>
          </div>
          <p className="mt-2 line-clamp-2 font-semibold text-ink">{item.title}</p>
          <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-600">{item.excerpt || "요약이 아직 없습니다."}</p>
          <p className="mt-2 text-xs text-slate-500">
            발행 {formatDate(item.published_at ?? item.scheduled_for)} / 수정 {formatDate(item.updated_at)}
          </p>
        </div>
      </div>
    </Link>
  );
}

function SyncedArchiveDetail({ item, blog }: { item: BlogArchiveItem; blog: Blog }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap gap-2">
          <Badge className="bg-slate-900 text-white">기존 Blogger 글</Badge>
          <Badge className="bg-transparent">{blog.name}</Badge>
          {item.labels.map((label) => (
            <Badge key={label}>{label}</Badge>
          ))}
        </div>
        <CardDescription>읽기 전용 보관함</CardDescription>
        <CardTitle className="text-2xl leading-tight">{item.title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {item.thumbnail_url ? (
          <div className="overflow-hidden rounded-[28px] border border-ink/10 bg-white">
            <img src={item.thumbnail_url} alt={item.title} className="h-[280px] w-full object-cover" />
          </div>
        ) : null}

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-4">
            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">요약</p>
              <p className="mt-3 text-sm leading-7 text-slate-700">{item.excerpt || "요약이 아직 없습니다."}</p>
            </div>

            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">본문 미리보기</p>
              <p className="mt-3 text-sm leading-7 text-slate-700">
                {item.excerpt || "본문 요약을 불러오지 못했습니다."}
              </p>
            </div>
          </div>

          <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">메타 정보</p>
            <div className="mt-4 space-y-3">
              <DetailsRow label="Source" value="Synced Blogger Post" mono />
              <DetailsRow label="상태" value={item.status || "live"} />
              <DetailsRow label="발행일" value={formatDate(item.published_at)} />
              <DetailsRow label="수정일" value={formatDate(item.updated_at)} />
            </div>

            <div className="mt-5 space-y-3">
              {item.published_url ? (
                <a
                  href={item.published_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block break-all text-sm font-medium text-amber-700 underline-offset-4 hover:underline"
                >
                  원문 보기
                </a>
              ) : (
                <p className="text-sm leading-7 text-slate-600">원문 링크가 없는 게시글입니다.</p>
              )}
              <p className="text-sm leading-7 text-slate-600">
                기존 Blogger 글은 비교와 참고용으로만 보여주고, 여기에서는 게시나 SEO 편집 버튼을 표시하지 않습니다.
              </p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function GeneratedArchiveDetail({
  article,
  seoMeta,
}: {
  article: Article;
  seoMeta: Awaited<ReturnType<typeof getArticleSeoMeta>> | null;
}) {
  const publishState = article.blogger_post?.published_url
    ? article.blogger_post.post_status === "scheduled"
      ? "scheduled"
      : article.blogger_post.is_draft
        ? "draft"
        : "published"
    : "unpublished";

  const publishStatusLabel =
    publishState === "published"
      ? "Blogger 공개 게시"
      : publishState === "scheduled"
        ? "Blogger 예약 발행"
        : publishState === "draft"
          ? "Blogger 초안"
          : "게시 전";

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap gap-2">
          {article.blog?.name ? <Badge className="bg-ink text-white">{article.blog.name}</Badge> : null}
          <Badge className="bg-slate-200 text-slate-800">생성 글</Badge>
          {article.labels.map((label) => (
            <Badge key={label}>{label}</Badge>
          ))}
        </div>
        <CardDescription>생성 글 상세</CardDescription>
        <CardTitle className="text-2xl leading-tight">{article.title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-4">
            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">메타 설명</p>
              <p className="mt-3 text-sm leading-7 text-slate-700">{article.meta_description}</p>
            </div>
            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">요약</p>
              <p className="mt-3 text-sm leading-7 text-slate-700">{article.excerpt}</p>
            </div>
          </div>

          <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">메타 정보</p>
            <div className="mt-4 space-y-3">
              <DetailsRow label="Slug" value={article.slug} mono />
              <DetailsRow label="생성일" value={formatDate(article.created_at)} />
              <DetailsRow label="수정일" value={formatDate(article.updated_at)} />
              <DetailsRow label="읽기 시간" value={`${article.reading_time_minutes}분`} />
              <DetailsRow label="게시 상태" value={publishStatusLabel} />
              {article.blogger_post?.scheduled_for ? (
                <DetailsRow label="예약일" value={formatDateTime(article.blogger_post.scheduled_for)} />
              ) : null}
            </div>

            <div className="mt-5 space-y-3">
              {article.blogger_post?.published_url ? (
                <a
                  href={article.blogger_post.published_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block break-all text-sm font-medium text-amber-700 underline-offset-4 hover:underline"
                >
                  {article.blogger_post.post_status === "scheduled"
                    ? "Blogger 예약 글 보기"
                    : article.blogger_post.is_draft
                      ? "Blogger 초안 보기"
                      : "공개 글 보기"}
                </a>
              ) : (
                <p className="text-sm leading-7 text-slate-600">
                  아직 Blogger에 게시하지 않았습니다. 아래 버튼으로 즉시 발행하거나 예약 발행할 수 있습니다.
                </p>
              )}
              <PublishArticleButton articleId={article.id} publishState={publishState} />
            </div>
          </div>
        </div>

        {seoMeta ? <ArticleSeoMetaCard articleId={article.id} initialMeta={seoMeta} /> : null}

        <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
          <p className="text-xs uppercase tracking-[0.16em] text-slate-500">미리보기</p>
          <p className="mt-2 text-sm leading-7 text-slate-600">실제 게시 형태에 가깝게 조립된 HTML 미리보기를 확인할 수 있습니다.</p>
          <div className="mt-4">
            <ArticlePreviewFrame article={article} />
          </div>
        </div>

        <div className="space-y-4">
          <details className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
            <summary className="cursor-pointer text-sm font-semibold text-ink">이미지 프롬프트 보기</summary>
            <p className="mt-4 break-words text-sm leading-7 text-slate-700">{article.image_collage_prompt}</p>
          </details>

          <details className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
            <summary className="cursor-pointer text-sm font-semibold text-ink">조립 HTML 보기</summary>
            <pre className="mt-4 overflow-auto rounded-[20px] bg-slate-950 p-4 text-xs leading-6 text-slate-100">
              <code>{article.assembled_html ?? article.html_article}</code>
            </pre>
          </details>
        </div>
      </CardContent>
    </Card>
  );
}

export default async function ArticlesPage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  const blogs = await getBlogs();

  if (blogs.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="font-display text-4xl font-semibold text-ink">글보관함</h1>
          <p className="mt-2 text-base leading-7 text-slate-600">
            블로그를 먼저 import하면 생성 글과 기존 Blogger 글을 한 화면에서 볼 수 있습니다.
          </p>
        </div>
        <Card>
          <CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">
            아직 가져온 블로그가 없습니다. Google 연결 후 Blogger 블로그를 import해 주세요.
          </CardContent>
        </Card>
      </div>
    );
  }

  const selectedBlogId = parsePositiveInt(searchParams?.blog, blogs[0].id);
  const selectedBlog = blogs.find((blog) => blog.id === selectedBlogId) ?? blogs[0];
  const currentPage = parsePositiveInt(searchParams?.page, 1);
  const archive = await getBlogArchive(selectedBlog.id, currentPage, ARCHIVE_PAGE_SIZE);

  const requestedSource = readString(searchParams?.source) as BlogArchiveItem["source"] | "";
  const requestedItemId = readString(searchParams?.item);
  const selectedItem =
    archive.items.find((item) => item.source === requestedSource && item.id === requestedItemId) ??
    archive.items[0] ??
    null;

  let selectedArticle: Article | null = null;
  let selectedSeoMeta: Awaited<ReturnType<typeof getArticleSeoMeta>> | null = null;

  if (selectedItem?.source === "generated") {
    const articleId = Number(selectedItem.id);
    selectedArticle = await getArticle(articleId).catch(() => null);
    selectedSeoMeta = selectedArticle ? await getArticleSeoMeta(selectedArticle.id).catch(() => null) : null;
  }

  const totalPages = Math.max(1, Math.ceil(archive.total / archive.page_size));
  const currentBlogGeneratedCount = archive.items.filter((item) => item.source === "generated").length;
  const currentBlogSyncedCount = archive.items.filter((item) => item.source === "synced").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-ink">글보관함</h1>
          <p className="mt-2 max-w-3xl text-base leading-7 text-slate-600">
            선택한 블로그 기준으로 생성 글과 기존 Blogger 공개 글을 함께 확인합니다. 기존 글 이미지와 요약도 같이 보여서 관련 글 작성과 중복 확인에 바로 사용할 수 있습니다.
          </p>
        </div>
        <div className="w-full max-w-sm">
          <ArchiveBlogSelector blogs={blogs} selectedBlogId={selectedBlog.id} />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="px-5 py-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">선택 블로그</p>
            <p className="mt-2 text-lg font-semibold text-ink">{selectedBlog.name}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="px-5 py-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">현재 페이지 항목</p>
            <p className="mt-2 text-lg font-semibold text-ink">{archive.items.length}개</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="px-5 py-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">전체 보관함</p>
            <p className="mt-2 text-lg font-semibold text-ink">{archive.total}개</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="px-5 py-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">마지막 동기화</p>
            <p className="mt-2 text-lg font-semibold text-ink">{formatDateTime(archive.last_synced_at)}</p>
          </CardContent>
        </Card>
      </div>

      {archive.total === 0 ? (
        <Card>
          <CardContent className="space-y-3 px-6 py-10 text-sm leading-7 text-slate-600">
            <p>이 블로그에는 아직 생성 글도, 가져온 Blogger 공개 글도 없습니다.</p>
            <p>
              Google 페이지에서{" "}
              <Link href="/google" className="font-medium text-amber-700 underline-offset-4 hover:underline">
                현재 게시글 가져오기
              </Link>
              를 실행하거나, 대시보드에서 새 글을 생성하면 이 보관함에 바로 반영됩니다.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <Card className="h-fit xl:sticky xl:top-6">
            <CardHeader>
              <CardDescription>선택 블로그 통합 목록</CardDescription>
              <CardTitle>생성 글 + 기존 Blogger 글</CardTitle>
              <p className="text-sm leading-7 text-slate-600">
                이 페이지에서는 생성 글 {currentBlogGeneratedCount}개, 기존 Blogger 글 {currentBlogSyncedCount}개를 보고 있습니다.
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              {archive.items.map((item) => (
                <ArchiveListCard
                  key={`${item.source}:${item.id}`}
                  item={item}
                  selected={selectedItem?.source === item.source && selectedItem.id === item.id}
                  href={buildArchiveHref(searchParams, {
                    blog: String(selectedBlog.id),
                    page: String(archive.page),
                    source: item.source,
                    item: item.id,
                  })}
                />
              ))}

              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[24px] border border-ink/10 px-4 py-4 text-sm text-slate-600">
                <p>
                  페이지 {archive.page} / {totalPages}
                </p>
                <div className="flex items-center gap-2">
                  {archive.page > 1 ? (
                    <Link
                      href={buildArchiveHref(searchParams, {
                        blog: String(selectedBlog.id),
                        page: String(archive.page - 1),
                        source: null,
                        item: null,
                      })}
                      className="rounded-full border border-ink/10 px-4 py-2 font-medium text-ink"
                    >
                      이전
                    </Link>
                  ) : (
                    <span className="rounded-full border border-ink/10 px-4 py-2 text-slate-400">이전</span>
                  )}
                  {archive.page < totalPages ? (
                    <Link
                      href={buildArchiveHref(searchParams, {
                        blog: String(selectedBlog.id),
                        page: String(archive.page + 1),
                        source: null,
                        item: null,
                      })}
                      className="rounded-full border border-ink/10 px-4 py-2 font-medium text-ink"
                    >
                     다음
                    </Link>
                  ) : (
                    <span className="rounded-full border border-ink/10 px-4 py-2 text-slate-400">다음</span>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          {!selectedItem ? (
            <Card>
              <CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">선택한 글이 없습니다.</CardContent>
            </Card>
          ) : selectedItem.source === "generated" && selectedArticle ? (
            <GeneratedArchiveDetail article={selectedArticle} seoMeta={selectedSeoMeta} />
          ) : selectedItem.source === "generated" ? (
            <Card>
              <CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">
                생성 글 상세를 불러오지 못했습니다. 목록에서 다시 선택하거나 페이지를 새로고침해 주세요.
              </CardContent>
            </Card>
          ) : (
            <SyncedArchiveDetail item={selectedItem} blog={selectedBlog} />
          )}
        </div>
      )}
    </div>
  );
}

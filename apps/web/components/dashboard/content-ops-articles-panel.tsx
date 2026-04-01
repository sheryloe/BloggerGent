import Link from "next/link";

import { ArticlePreviewFrame } from "@/components/dashboard/article-preview-frame";
import { ArchiveBlogSelector } from "@/components/dashboard/archive-blog-selector";
import { FallbackImage } from "@/components/dashboard/fallback-image";
import { PublishArticleButton } from "@/components/dashboard/publish-article-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getArticle, getBlogArchive, getBlogs } from "@/lib/api";
import type { BlogArchiveItem } from "@/lib/types";

const ARCHIVE_PAGE_SIZE = 20;
type PublishState = "unpublished" | "draft" | "scheduled" | "published" | "queued";

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function parsePositiveInt(value: string | string[] | undefined, fallback: number) {
  const resolved = firstParam(value);
  const parsed = Number(resolved);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function buildHref(
  searchParams: Record<string, string | string[] | undefined> | undefined,
  updates: Record<string, string | null>,
) {
  const params = new URLSearchParams();
  Object.entries(searchParams ?? {}).forEach(([key, value]) => {
    const resolved = firstParam(value);
    if (resolved && updates[key] !== null) {
      params.set(key, resolved);
    }
  });
  Object.entries(updates).forEach(([key, value]) => {
    if (!value) {
      params.delete(key);
      return;
    }
    params.set(key, value);
  });
  const query = params.toString();
  return query ? `/content-ops?${query}` : "/content-ops?tab=articles";
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

function sourceLabel(item: BlogArchiveItem) {
  return item.source === "generated" ? "생성 글" : "동기화 글";
}

function archiveStatusLabel(item: BlogArchiveItem) {
  if (item.source === "synced") return item.status || "live";
  if (item.status === "published") return "published";
  if (item.status === "scheduled") return "scheduled";
  if (item.status === "draft") return "draft";
  return "generated";
}

export async function ContentOpsArticlesPanel({
  searchParams,
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  const blogs = await getBlogs();

  if (blogs.length === 0) {
    return (
      <Card><CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">가져온 Blogger 블로그가 없습니다. 설정에서 Google 연동과 블로그 import를 먼저 완료하세요.</CardContent></Card>
    );
  }

  const selectedBlogId = parsePositiveInt(searchParams?.blog, blogs[0].id);
  const selectedBlog = blogs.find((blog) => blog.id === selectedBlogId) ?? blogs[0];
  const currentPage = parsePositiveInt(searchParams?.page, 1);
  const archive = await getBlogArchive(selectedBlog.id, currentPage, ARCHIVE_PAGE_SIZE);
  const requestedSource = firstParam(searchParams?.source) as BlogArchiveItem["source"] | undefined;
  const requestedItemId = firstParam(searchParams?.item) ?? "";
  const selectedItem = archive.items.find((item) => item.source === requestedSource && item.id === requestedItemId) ?? archive.items[0] ?? null;
  const selectedArticle = selectedItem?.source === "generated" ? await getArticle(Number(selectedItem.id)).catch(() => null) : null;
  const totalPages = Math.max(1, Math.ceil(archive.total / archive.page_size));
  const publishState: PublishState =
    selectedArticle?.publish_queue && ["queued", "scheduled", "processing"].includes(selectedArticle.publish_queue.status)
      ? "queued"
      : selectedArticle?.blogger_post?.published_url
        ? selectedArticle.blogger_post.post_status === "scheduled"
          ? "scheduled"
          : selectedArticle.blogger_post.is_draft
            ? "draft"
            : "published"
        : "unpublished";

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-950 dark:text-zinc-50">글 보관</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-zinc-400">선택한 블로그의 보관함만 조회하고, 선택한 항목만 상세 로드합니다.</p>
        </div>
        <div className="w-full max-w-sm">
          <ArchiveBlogSelector blogs={blogs} selectedBlogId={selectedBlog.id} basePath="/content-ops" fixedParams={{ tab: "articles" }} />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card><CardContent className="px-5 py-5"><p className="text-sm text-slate-500">선택 블로그</p><p className="mt-2 text-lg font-semibold text-slate-950">{selectedBlog.name}</p></CardContent></Card>
        <Card><CardContent className="px-5 py-5"><p className="text-sm text-slate-500">현재 페이지 항목</p><p className="mt-2 text-lg font-semibold text-slate-950">{archive.items.length}</p></CardContent></Card>
        <Card><CardContent className="px-5 py-5"><p className="text-sm text-slate-500">전체 보관 항목</p><p className="mt-2 text-lg font-semibold text-slate-950">{archive.total}</p></CardContent></Card>
        <Card><CardContent className="px-5 py-5"><p className="text-sm text-slate-500">마지막 동기화</p><p className="mt-2 text-lg font-semibold text-slate-950">{formatDateTime(archive.last_synced_at)}</p></CardContent></Card>
      </div>

      {archive.total === 0 ? (
        <Card><CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">이 블로그에는 아직 생성 글이나 동기화 글이 없습니다.</CardContent></Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <Card className="h-fit xl:sticky xl:top-6">
            <CardHeader><CardDescription>보관 목록</CardDescription><CardTitle>Generated + Synced</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {archive.items.map((item) => (
                <Link
                  key={`${item.source}:${item.id}`}
                  href={buildHref(searchParams, { tab: "articles", blog: String(selectedBlog.id), page: String(archive.page), source: item.source, item: item.id })}
                  prefetch={false}
                  className={`block rounded-[24px] border px-4 py-4 transition ${selectedItem?.source === item.source && selectedItem.id === item.id ? "border-slate-950 bg-white shadow-sm" : "border-slate-200 bg-white/70 hover:bg-white"}`}
                >
                  <div className="flex gap-4">
                    <div className="h-20 w-20 shrink-0 overflow-hidden rounded-[18px] border border-slate-200 bg-slate-100">
                      {item.thumbnail_url ? <FallbackImage src={item.thumbnail_url} alt={item.title} className="h-full w-full object-cover" /> : <div className="flex h-full w-full items-center justify-center text-[11px] font-medium text-slate-400">NO IMAGE</div>}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge className={item.source === "generated" ? "bg-slate-950 text-white" : "bg-slate-200 text-slate-800"}>{sourceLabel(item)}</Badge>
                        <Badge className="border border-slate-200 bg-white text-slate-800">{archiveStatusLabel(item)}</Badge>
                      </div>
                      <p className="mt-2 line-clamp-2 font-semibold text-slate-950">{item.title}</p>
                      <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-600">{item.excerpt || "요약이 없습니다."}</p>
                    </div>
                  </div>
                </Link>
              ))}
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[24px] border border-slate-200 px-4 py-4 text-sm text-slate-600">
                <p>페이지 {archive.page} / {totalPages}</p>
                <div className="flex items-center gap-2">
                  {archive.page > 1 ? <Link href={buildHref(searchParams, { tab: "articles", blog: String(selectedBlog.id), page: String(archive.page - 1), source: null, item: null })} prefetch={false} className="rounded-full border border-slate-200 px-4 py-2 font-medium text-slate-800">이전</Link> : <span className="rounded-full border border-slate-200 px-4 py-2 text-slate-400">이전</span>}
                  {archive.page < totalPages ? <Link href={buildHref(searchParams, { tab: "articles", blog: String(selectedBlog.id), page: String(archive.page + 1), source: null, item: null })} prefetch={false} className="rounded-full border border-slate-200 px-4 py-2 font-medium text-slate-800">다음</Link> : <span className="rounded-full border border-slate-200 px-4 py-2 text-slate-400">다음</span>}
                </div>
              </div>
            </CardContent>
          </Card>

          {!selectedItem ? (
            <Card><CardContent className="px-6 py-10 text-sm text-slate-600">선택된 글이 없습니다.</CardContent></Card>
          ) : selectedItem.source === "generated" && selectedArticle ? (
            <Card>
              <CardHeader>
                <div className="flex flex-wrap gap-2">
                  <Badge className="bg-slate-950 text-white">생성 글</Badge>
                  {selectedArticle.blog?.name ? <Badge className="bg-transparent">{selectedArticle.blog.name}</Badge> : null}
                </div>
                <CardDescription>생성 글 상세</CardDescription>
                <CardTitle>{selectedArticle.title}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="rounded-[24px] border border-slate-200 bg-white/70 p-5">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">메타 설명</p>
                  <p className="mt-3 text-sm leading-7 text-slate-700">{selectedArticle.meta_description}</p>
                </div>
                <div className="rounded-[24px] border border-slate-200 bg-white/70 p-5">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">발행</p>
                  <div className="mt-3 space-y-2 text-sm leading-6 text-slate-700">
                    <p>읽기 시간: {selectedArticle.reading_time_minutes}분</p>
                    <p>생성: {formatDateTime(selectedArticle.created_at)}</p>
                    {selectedArticle.blogger_post?.published_url ? <a href={selectedArticle.blogger_post.published_url} target="_blank" rel="noreferrer" className="break-all text-blue-700 underline underline-offset-4">{selectedArticle.blogger_post.published_url}</a> : <p>아직 라이브 URL이 없습니다.</p>}
                  </div>
                  <div className="mt-4">
                    <PublishArticleButton articleId={selectedArticle.id} publishState={publishState} publishQueue={selectedArticle.publish_queue} />
                  </div>
                </div>
                <ArticlePreviewFrame article={selectedArticle} />
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <div className="flex flex-wrap gap-2">
                  <Badge className="bg-slate-900 text-white">기존 Blogger 글</Badge>
                  <Badge className="bg-transparent">{selectedBlog.name}</Badge>
                </div>
                <CardDescription>동기화 상세</CardDescription>
                <CardTitle>{selectedItem.title}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                {selectedItem.thumbnail_url ? <div className="overflow-hidden rounded-[28px] border border-slate-200 bg-white"><FallbackImage src={selectedItem.thumbnail_url} alt={selectedItem.title} className="h-[280px] w-full object-cover" /></div> : null}
                <div className="rounded-[24px] border border-slate-200 bg-white/70 p-5">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">요약</p>
                  <p className="mt-3 text-sm leading-7 text-slate-700">{selectedItem.excerpt || "요약이 없습니다."}</p>
                </div>
                {selectedItem.published_url ? <a href={selectedItem.published_url} target="_blank" rel="noreferrer" className="break-all text-blue-700 underline underline-offset-4">{selectedItem.published_url}</a> : null}
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

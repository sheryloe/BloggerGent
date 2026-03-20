import Link from "next/link";

import { ArticlePreviewFrame } from "@/components/dashboard/article-preview-frame";
import { ArchiveBlogSelector } from "@/components/dashboard/archive-blog-selector";
import { ArticleSeoMetaCard } from "@/components/dashboard/article-seo-meta-card";
import { FallbackImage } from "@/components/dashboard/fallback-image";
import { PublishArticleButton } from "@/components/dashboard/publish-article-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getArticle, getArticleSeoMeta, getBlogArchive, getBlogs } from "@/lib/api";
import type { Article, Blog, BlogArchiveItem } from "@/lib/types";

const ARCHIVE_PAGE_SIZE = 20;

type PublishState = "unpublished" | "draft" | "scheduled" | "published" | "queued";

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
    <div className="grid gap-1 sm:grid-cols-[140px_minmax(0,1fr)]">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className={`min-w-0 text-sm text-slate-700 ${mono ? "break-all font-mono text-xs" : "break-words"}`}>{value}</p>
    </div>
  );
}

function sourceBadge(source: BlogArchiveItem["source"]) {
  return source === "generated" ? "Generated" : "Synced";
}

function statusBadge(item: BlogArchiveItem) {
  if (item.source === "synced") return item.status || "live";
  if (item.status === "published") return "published";
  if (item.status === "scheduled") return "scheduled";
  if (item.status === "draft") return "draft";
  return "generated";
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
            <FallbackImage src={item.thumbnail_url} alt={item.title} className="h-full w-full object-cover" />
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
          <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-600">{item.excerpt || "No excerpt available."}</p>
          <p className="mt-2 text-xs text-slate-500">
            Published {formatDate(item.published_at ?? item.scheduled_for)} / Updated {formatDate(item.updated_at)}
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
          <Badge className="bg-slate-900 text-white">Existing Blogger post</Badge>
          <Badge className="bg-transparent">{blog.name}</Badge>
          {item.labels.map((label) => (
            <Badge key={label}>{label}</Badge>
          ))}
        </div>
        <CardDescription>Reference post</CardDescription>
        <CardTitle className="text-2xl leading-tight">{item.title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {item.thumbnail_url ? (
          <div className="overflow-hidden rounded-[28px] border border-ink/10 bg-white">
            <FallbackImage src={item.thumbnail_url} alt={item.title} className="h-[280px] w-full object-cover" />
          </div>
        ) : null}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-4">
            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Excerpt</p>
              <p className="mt-3 text-sm leading-7 text-slate-700">{item.excerpt || "No excerpt available."}</p>
            </div>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Metadata</p>
            <div className="mt-4 space-y-3">
              <DetailsRow label="Source" value="Synced Blogger post" mono />
              <DetailsRow label="Status" value={item.status || "live"} />
              <DetailsRow label="Published" value={formatDate(item.published_at)} />
              <DetailsRow label="Updated" value={formatDate(item.updated_at)} />
            </div>
            <div className="mt-5 space-y-3">
              {item.published_url ? (
                <a
                  href={item.published_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block break-all text-sm font-medium text-amber-700 underline-offset-4 hover:underline"
                >
                  Open live post
                </a>
              ) : (
                <p className="text-sm leading-7 text-slate-600">This synced record does not include a live URL.</p>
              )}
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
  const publishState: PublishState =
    article.publish_queue && ["queued", "scheduled", "processing"].includes(article.publish_queue.status)
      ? "queued"
      : article.blogger_post?.published_url
        ? article.blogger_post.post_status === "scheduled"
          ? "scheduled"
          : article.blogger_post.is_draft
            ? "draft"
            : "published"
        : "unpublished";

  const publishStatusLabel =
    publishState === "queued"
      ? "Queued"
      : publishState === "published"
        ? "Published"
        : publishState === "scheduled"
          ? "Scheduled"
          : publishState === "draft"
            ? "Draft"
            : "Not published";

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap gap-2">
          {article.blog?.name ? <Badge className="bg-ink text-white">{article.blog.name}</Badge> : null}
          <Badge className="bg-slate-200 text-slate-800">Generated article</Badge>
          {article.labels.map((label) => (
            <Badge key={label}>{label}</Badge>
          ))}
        </div>
        <CardDescription>Generated article detail</CardDescription>
        <CardTitle className="text-2xl leading-tight">{article.title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-4">
            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Meta description</p>
              <p className="mt-3 text-sm leading-7 text-slate-700">{article.meta_description || "-"}</p>
            </div>
            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Excerpt</p>
              <p className="mt-3 text-sm leading-7 text-slate-700">{article.excerpt || "-"}</p>
            </div>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Metadata</p>
            <div className="mt-4 space-y-3">
              <DetailsRow label="Slug" value={article.slug} mono />
              <DetailsRow label="Created" value={formatDate(article.created_at)} />
              <DetailsRow label="Updated" value={formatDate(article.updated_at)} />
              <DetailsRow label="Reading time" value={`${article.reading_time_minutes} minutes`} />
              <DetailsRow label="Publish state" value={publishStatusLabel} />
              {article.publish_queue ? <DetailsRow label="Queue execution" value={formatDateTime(article.publish_queue.not_before)} /> : null}
              {article.blogger_post?.scheduled_for ? <DetailsRow label="Blogger scheduled for" value={formatDateTime(article.blogger_post.scheduled_for)} /> : null}
            </div>
            <div className="mt-5 space-y-3">
              {article.blogger_post?.published_url ? (
                <a
                  href={article.blogger_post.published_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block break-all text-sm font-medium text-amber-700 underline-offset-4 hover:underline"
                >
                  Open Blogger post
                </a>
              ) : (
                <p className="text-sm leading-7 text-slate-600">This article has not been pushed to Blogger yet.</p>
              )}
              <PublishArticleButton articleId={article.id} publishState={publishState} publishQueue={article.publish_queue} />
            </div>
          </div>
        </div>

        {article.usage_summary ? (
          <div className="grid gap-4 md:grid-cols-4">
            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Usage events</p>
              <p className="mt-2 text-3xl font-semibold text-ink">{article.usage_summary.event_count}</p>
            </div>
            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Requests</p>
              <p className="mt-2 text-3xl font-semibold text-ink">{article.usage_summary.total_requests}</p>
            </div>
            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Total tokens</p>
              <p className="mt-2 text-3xl font-semibold text-ink">{article.usage_summary.total_tokens}</p>
            </div>
            <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Estimated cost</p>
              <p className="mt-2 text-3xl font-semibold text-ink">
                {article.usage_summary.estimated_cost_usd == null ? "-" : `$${article.usage_summary.estimated_cost_usd.toFixed(4)}`}
              </p>
            </div>
          </div>
        ) : null}

        {article.usage_events.length > 0 ? (
          <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Usage events</p>
            <div className="mt-4 space-y-3">
              {article.usage_events.map((event) => (
                <div key={event.id} className="rounded-[18px] border border-ink/10 bg-white px-4 py-3">
                  <div className="flex flex-wrap gap-2">
                    <Badge className="border border-ink/10 bg-white text-ink">{event.stage_type}</Badge>
                    <Badge className="border border-ink/10 bg-white text-ink">{event.provider_name}</Badge>
                    {event.provider_model ? <Badge className="border border-ink/10 bg-white text-ink">{event.provider_model}</Badge> : null}
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-3">
                    <DetailsRow label="Endpoint" value={event.endpoint} mono />
                    <DetailsRow label="Tokens" value={String(event.total_tokens)} />
                    <DetailsRow label="Images" value={String(event.image_count)} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {seoMeta ? <ArticleSeoMetaCard articleId={article.id} initialMeta={seoMeta} /> : null}

        <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
          <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Preview</p>
          <div className="mt-4">
            <ArticlePreviewFrame article={article} />
          </div>
        </div>

        <details className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
          <summary className="cursor-pointer text-sm font-semibold text-ink">Assembled HTML</summary>
          <pre className="mt-4 overflow-auto rounded-[20px] bg-slate-950 p-4 text-xs leading-6 text-slate-100">
            <code>{article.assembled_html ?? article.html_article}</code>
          </pre>
        </details>
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
          <h1 className="font-display text-4xl font-semibold text-ink">Articles</h1>
          <p className="mt-2 text-base leading-7 text-slate-600">Import at least one Blogger blog before using the archive.</p>
        </div>
        <Card>
          <CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">
            No imported blog is available yet. Connect Google and import a Blogger blog first.
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
  const selectedItem = archive.items.find((item) => item.source === requestedSource && item.id === requestedItemId) ?? archive.items[0] ?? null;

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
          <h1 className="font-display text-4xl font-semibold text-ink">Articles</h1>
          <p className="mt-2 max-w-3xl text-base leading-7 text-slate-600">
            Review generated drafts and synced Blogger posts in one place. This screen is built for quality checks, usage tracking, and safe publish queueing.
          </p>
        </div>
        <div className="w-full max-w-sm">
          <ArchiveBlogSelector blogs={blogs} selectedBlogId={selectedBlog.id} />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card><CardContent className="px-5 py-5"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">Selected blog</p><p className="mt-2 text-lg font-semibold text-ink">{selectedBlog.name}</p></CardContent></Card>
        <Card><CardContent className="px-5 py-5"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">Items on this page</p><p className="mt-2 text-lg font-semibold text-ink">{archive.items.length}</p></CardContent></Card>
        <Card><CardContent className="px-5 py-5"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">Total archive items</p><p className="mt-2 text-lg font-semibold text-ink">{archive.total}</p></CardContent></Card>
        <Card><CardContent className="px-5 py-5"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">Last sync</p><p className="mt-2 text-lg font-semibold text-ink">{formatDateTime(archive.last_synced_at)}</p></CardContent></Card>
      </div>

      {archive.total === 0 ? (
        <Card>
          <CardContent className="space-y-3 px-6 py-10 text-sm leading-7 text-slate-600">
            <p>No generated article or synced Blogger post exists for this blog yet.</p>
            <p>
              Sync existing Blogger posts from the{" "}
              <Link href="/google" className="font-medium text-amber-700 underline-offset-4 hover:underline">
                Google page
              </Link>{" "}
              or generate a new article from the dashboard.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <Card className="h-fit xl:sticky xl:top-6">
            <CardHeader>
              <CardDescription>Combined archive</CardDescription>
              <CardTitle>Generated + synced posts</CardTitle>
              <p className="text-sm leading-7 text-slate-600">
                This page currently shows {currentBlogGeneratedCount} generated items and {currentBlogSyncedCount} synced Blogger posts.
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
                <p>Page {archive.page} / {totalPages}</p>
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
                      Previous
                    </Link>
                  ) : (
                    <span className="rounded-full border border-ink/10 px-4 py-2 text-slate-400">Previous</span>
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
                      Next
                    </Link>
                  ) : (
                    <span className="rounded-full border border-ink/10 px-4 py-2 text-slate-400">Next</span>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          {!selectedItem ? (
            <Card><CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">No article is selected.</CardContent></Card>
          ) : selectedItem.source === "generated" && selectedArticle ? (
            <GeneratedArchiveDetail article={selectedArticle} seoMeta={selectedSeoMeta} />
          ) : selectedItem.source === "generated" ? (
            <Card><CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">The generated article detail could not be loaded.</CardContent></Card>
          ) : (
            <SyncedArchiveDetail item={selectedItem} blog={selectedBlog} />
          )}
        </div>
      )}
    </div>
  );
}

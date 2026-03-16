import Link from "next/link";

import { ArticlePreviewFrame } from "@/components/dashboard/article-preview-frame";
import { ArticleSeoMetaCard } from "@/components/dashboard/article-seo-meta-card";
import { PublishArticleButton } from "@/components/dashboard/publish-article-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getArticleSeoMeta, getArticles } from "@/lib/api";

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

function DetailsRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[120px_minmax(0,1fr)]">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className={`min-w-0 text-sm text-slate-700 ${mono ? "break-all font-mono text-xs" : "break-words"}`}>{value}</p>
    </div>
  );
}

export default async function ArticlesPage({
  searchParams,
}: {
  searchParams?: { article?: string };
}) {
  const articles = await getArticles();
  const selectedArticleId = Number(searchParams?.article);
  const selectedArticle = articles.find((article) => article.id === selectedArticleId) ?? articles[0] ?? null;
  const selectedSeoMeta = selectedArticle ? await getArticleSeoMeta(selectedArticle.id) : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-semibold text-ink">생성 글</h1>
        <p className="mt-2 text-base leading-7 text-slate-600">
          왼쪽에서 글 제목을 고르면 오른쪽에서 실제 게시 상태에 가까운 미리보기와 SEO 검증 정보를 함께 확인할 수 있습니다.
        </p>
      </div>

      {articles.length === 0 ? (
        <Card>
          <CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">아직 생성된 글이 없습니다.</CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <Card className="h-fit xl:sticky xl:top-6">
            <CardHeader>
              <CardDescription>생성된 글 목록</CardDescription>
              <CardTitle>제목 선택</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {articles.map((article, index) => {
                const selected = selectedArticle?.id === article.id;
                const published = Boolean(article.blogger_post?.published_url) && !article.blogger_post?.is_draft;
                const drafted = Boolean(article.blogger_post?.published_url) && article.blogger_post?.is_draft;

                return (
                  <Link
                    key={article.id}
                    href={`/articles?article=${article.id}`}
                    className={`block rounded-[22px] border px-4 py-4 transition ${
                      selected ? "border-ink bg-white shadow-sm" : "border-ink/10 bg-white/60 hover:bg-white"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Article {index + 1}</p>
                        <p className="mt-1 break-words font-semibold text-ink">{article.title}</p>
                      </div>
                      <Badge className={published ? "bg-emerald-700 text-white" : drafted ? "bg-slate-800 text-white" : "bg-amber-100 text-amber-900"}>
                        {published ? "공개" : drafted ? "초안" : "게시 대기"}
                      </Badge>
                    </div>
                  </Link>
                );
              })}
            </CardContent>
          </Card>

          {!selectedArticle ? (
            <Card>
              <CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">선택된 글이 없습니다.</CardContent>
            </Card>
          ) : (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <div className="flex flex-wrap gap-2">
                    {selectedArticle.blog?.name ? <Badge className="bg-ink text-white">{selectedArticle.blog.name}</Badge> : null}
                    {selectedArticle.labels.map((label) => (
                      <Badge key={label}>{label}</Badge>
                    ))}
                  </div>
                  <CardDescription>선택한 글 정보</CardDescription>
                  <CardTitle className="text-2xl leading-tight">{selectedArticle.title}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                    <div className="space-y-4">
                      <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
                        <p className="text-xs uppercase tracking-[0.16em] text-slate-500">검색 설명</p>
                        <p className="mt-3 text-sm leading-7 text-slate-700">{selectedArticle.meta_description}</p>
                      </div>
                      <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
                        <p className="text-xs uppercase tracking-[0.16em] text-slate-500">요약</p>
                        <p className="mt-3 text-sm leading-7 text-slate-700">{selectedArticle.excerpt}</p>
                      </div>
                    </div>

                    <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
                      <p className="text-xs uppercase tracking-[0.16em] text-slate-500">메타 정보</p>
                      <div className="mt-4 space-y-3">
                        <DetailsRow label="Slug" value={selectedArticle.slug} mono />
                        <DetailsRow label="생성일" value={formatDate(selectedArticle.created_at)} />
                        <DetailsRow label="읽기 시간" value={`${selectedArticle.reading_time_minutes}분`} />
                        <DetailsRow
                          label="게시 상태"
                          value={
                            selectedArticle.blogger_post?.published_url
                              ? selectedArticle.blogger_post.is_draft
                                ? "Blogger 초안 저장"
                                : "Blogger 공개 게시"
                              : "게시 대기"
                          }
                        />
                      </div>

                      <div className="mt-5 space-y-3">
                        {selectedArticle.blogger_post?.published_url ? (
                          <a
                            href={selectedArticle.blogger_post.published_url}
                            target="_blank"
                            rel="noreferrer"
                            className="block break-all text-sm font-medium text-ember underline-offset-4 hover:underline"
                          >
                            {selectedArticle.blogger_post.is_draft ? "Blogger 초안 보기" : "공개 글 보기"}
                          </a>
                        ) : (
                          <p className="text-sm leading-7 text-slate-600">
                            아직 공개하지 않았습니다. 미리보기를 확인한 뒤 아래 버튼에서 직접 게시하세요.
                          </p>
                        )}
                        <PublishArticleButton
                          articleId={selectedArticle.id}
                          publishState={
                            selectedArticle.blogger_post?.published_url
                              ? selectedArticle.blogger_post.is_draft
                                ? "draft"
                                : "published"
                              : "unpublished"
                          }
                        />
                      </div>
                    </div>
                  </div>

                  {selectedSeoMeta ? <ArticleSeoMetaCard articleId={selectedArticle.id} initialMeta={selectedSeoMeta} /> : null}

                  <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">실제 게시 미리보기</p>
                    <p className="mt-2 text-sm leading-7 text-slate-600">
                      아래 미리보기는 조립된 HTML을 실제 게시물 형태에 가깝게 바로 렌더링한 결과입니다. 내부 스크롤 없이 페이지 흐름 안에서 전체 내용을 확인할 수 있습니다.
                    </p>
                    <div className="mt-4">
                      <ArticlePreviewFrame article={selectedArticle} />
                    </div>
                  </div>

                  <div className="space-y-4">
                    <details className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
                      <summary className="cursor-pointer text-sm font-semibold text-ink">이미지 프롬프트 보기</summary>
                      <p className="mt-4 break-words text-sm leading-7 text-slate-700">{selectedArticle.image_collage_prompt}</p>
                    </details>

                    <details className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
                      <summary className="cursor-pointer text-sm font-semibold text-ink">조립 HTML 소스 보기</summary>
                      <pre className="mt-4 overflow-auto rounded-[20px] bg-slate-950 p-4 text-xs leading-6 text-slate-100">
                        <code>{selectedArticle.assembled_html ?? selectedArticle.html_article}</code>
                      </pre>
                    </details>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

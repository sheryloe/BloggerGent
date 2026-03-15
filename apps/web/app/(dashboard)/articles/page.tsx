import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getArticles } from "@/lib/api";

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

export default async function ArticlesPage({
  searchParams,
}: {
  searchParams?: { article?: string };
}) {
  const articles = await getArticles();
  const selectedArticleId = Number(searchParams?.article);
  const selectedArticle = articles.find((article) => article.id === selectedArticleId) ?? articles[0] ?? null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-semibold text-ink">생성 글</h1>
        <p className="mt-2 text-base leading-7 text-slate-600">
          왼쪽 목록에서 글을 선택하면 오른쪽에서 HTML과 메타 정보를 한 번에 미리볼 수 있습니다.
        </p>
      </div>

      <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader>
            <CardDescription>생성된 글 목록</CardDescription>
            <CardTitle>Article Library</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {articles.length === 0 ? (
              <div className="rounded-[24px] border border-dashed border-ink/15 bg-white/50 px-4 py-5 text-sm text-slate-600">
                아직 생성된 글이 없습니다.
              </div>
            ) : (
              articles.map((article) => {
                const selected = selectedArticle?.id === article.id;
                return (
                  <Link
                    key={article.id}
                    href={`/articles?article=${article.id}`}
                    className={`block rounded-[24px] border px-4 py-4 transition ${
                      selected ? "border-ink bg-ink text-white" : "border-ink/10 bg-white/70 text-ink"
                    }`}
                  >
                    <p className="line-clamp-2 font-semibold">{article.title}</p>
                    <p className={`mt-2 text-sm ${selected ? "text-white/80" : "text-slate-600"}`}>
                      {article.blog?.name ?? "블로그 미지정"}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {article.labels.slice(0, 3).map((label) => (
                        <Badge key={label} className={selected ? "border-white/30 bg-white/10 text-white" : "bg-transparent"}>
                          {label}
                        </Badge>
                      ))}
                    </div>
                  </Link>
                );
              })
            )}
          </CardContent>
        </Card>

        <Card className="min-w-0 overflow-hidden">
          {!selectedArticle ? (
            <CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">
              아직 선택된 글이 없습니다.
            </CardContent>
          ) : (
            <>
              {selectedArticle.image?.public_url ? (
                <img src={selectedArticle.image.public_url} alt={selectedArticle.title} className="h-72 w-full object-cover" />
              ) : null}
              <CardHeader className="border-b border-ink/10 bg-white/70">
                <div className="flex flex-wrap gap-2">
                  {selectedArticle.blog?.name ? <Badge className="bg-ink text-white">{selectedArticle.blog.name}</Badge> : null}
                  {selectedArticle.labels.map((label) => (
                    <Badge key={label}>{label}</Badge>
                  ))}
                </div>
                <CardTitle className="text-2xl">{selectedArticle.title}</CardTitle>
                <CardDescription>{selectedArticle.meta_description}</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-6 p-6 xl:grid-cols-[320px_minmax(0,1fr)]">
                <div className="space-y-4">
                  <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">기본 정보</p>
                    <div className="mt-3 space-y-3 text-sm leading-6 text-slate-700">
                      <p>
                        <strong>Slug:</strong> <span className="break-all">{selectedArticle.slug}</span>
                      </p>
                      <p>
                        <strong>생성일:</strong> {formatDate(selectedArticle.created_at)}
                      </p>
                      <p>
                        <strong>예상 읽기 시간:</strong> {selectedArticle.reading_time_minutes}분
                      </p>
                    </div>
                  </div>

                  <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">요약</p>
                    <p className="mt-3 text-sm leading-7 text-slate-700">{selectedArticle.excerpt}</p>
                  </div>

                  <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">이미지 프롬프트</p>
                    <p className="mt-3 break-words text-sm leading-7 text-slate-700">
                      {selectedArticle.image_collage_prompt}
                    </p>
                  </div>

                  {selectedArticle.blogger_post?.published_url ? (
                    <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                      <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Blogger</p>
                      <a
                        href={selectedArticle.blogger_post.published_url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-3 inline-block break-all text-sm font-medium text-ember underline-offset-4 hover:underline"
                      >
                        Blogger 글 보기
                      </a>
                    </div>
                  ) : null}
                </div>

                <div className="min-w-0 space-y-4">
                  <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">HTML 미리보기</p>
                    <div
                      className="article-prose mt-4 max-h-[900px] overflow-auto rounded-[20px] border border-ink/10 bg-white p-6"
                      dangerouslySetInnerHTML={{ __html: selectedArticle.assembled_html ?? selectedArticle.html_article }}
                    />
                  </div>
                </div>
              </CardContent>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}

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
          생성된 글 제목만 먼저 빠르게 보고, 선택한 글의 HTML과 메타 정보를 아래에서 확인할 수 있게 정리했습니다.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardDescription>생성된 글 목록</CardDescription>
          <CardTitle>Article List</CardTitle>
        </CardHeader>
        <CardContent>
          {articles.length === 0 ? (
            <div className="rounded-[24px] border border-dashed border-ink/15 bg-white/50 px-4 py-5 text-sm text-slate-600">
              아직 생성된 글이 없습니다.
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {articles.map((article, index) => {
                const selected = selectedArticle?.id === article.id;
                return (
                  <Link
                    key={article.id}
                    href={`/articles?article=${article.id}`}
                    className={`rounded-[22px] border px-4 py-4 transition ${
                      selected ? "border-ink bg-ink text-white" : "border-ink/10 bg-white/70 text-ink hover:bg-white"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className={`text-xs uppercase tracking-[0.16em] ${selected ? "text-white/60" : "text-slate-500"}`}>
                          Article {index + 1}
                        </p>
                        <p className="mt-1 break-words font-semibold">{article.title}</p>
                      </div>
                      {article.blogger_post?.published_url ? (
                        <Badge className={selected ? "border-white/30 bg-white/10 text-white" : "bg-ink text-white"}>
                          게시됨
                        </Badge>
                      ) : (
                        <Badge className={selected ? "border-white/30 bg-white/10 text-white" : ""}>미게시</Badge>
                      )}
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="overflow-hidden">
        {!selectedArticle ? (
          <CardContent className="px-6 py-10 text-sm leading-7 text-slate-600">아직 선택된 글이 없습니다.</CardContent>
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

            <CardContent className="space-y-6 p-6">
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">기본 정보</p>
                  <div className="mt-3 space-y-2 text-sm leading-6 text-slate-700">
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
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Blogger</p>
                  {selectedArticle.blogger_post?.published_url ? (
                    <a
                      href={selectedArticle.blogger_post.published_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-3 inline-block break-all text-sm font-medium text-ember underline-offset-4 hover:underline"
                    >
                      게시글 열기
                    </a>
                  ) : (
                    <p className="mt-3 text-sm text-slate-600">아직 Blogger에 게시되지 않았습니다.</p>
                  )}
                </div>
              </div>

              <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                <p className="text-xs uppercase tracking-[0.16em] text-slate-500">이미지 프롬프트</p>
                <p className="mt-3 break-words text-sm leading-7 text-slate-700">{selectedArticle.image_collage_prompt}</p>
              </div>

              <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                <p className="text-xs uppercase tracking-[0.16em] text-slate-500">HTML 미리보기</p>
                <div
                  className="article-prose mt-4 max-h-[1100px] overflow-auto rounded-[20px] border border-ink/10 bg-white p-6"
                  dangerouslySetInnerHTML={{ __html: selectedArticle.assembled_html ?? selectedArticle.html_article }}
                />
              </div>
            </CardContent>
          </>
        )}
      </Card>
    </div>
  );
}

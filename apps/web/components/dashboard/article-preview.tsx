import { ArticlePreviewFrame } from "@/components/dashboard/article-preview-frame";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Article } from "@/lib/types";

export function ArticlePreview({ article }: { article: Article }) {
  const postStatus = article.blogger_post?.post_status;
  const statusLabel = postStatus === "published" ? "공개됨" : postStatus === "scheduled" ? "예약됨" : "게시 대기";
  const statusClass =
    postStatus === "published"
      ? "bg-emerald-700 text-white"
      : postStatus === "scheduled"
        ? "bg-sky-100 text-sky-900"
        : "bg-amber-100 text-amber-900";

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap gap-2">
          {article.blog?.name ? <Badge className="bg-ink text-white">{article.blog.name}</Badge> : null}
          {article.labels.map((label) => (
            <Badge key={label}>{label}</Badge>
          ))}
        </div>
        <CardTitle className="text-2xl">{article.title}</CardTitle>
        <CardDescription>{article.meta_description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">
          <span>예상 읽기 시간 {article.reading_time_minutes}분</span>
          <Badge className={statusClass}>{statusLabel}</Badge>
          {article.blogger_post?.published_url ? (
            <a
              href={article.blogger_post.published_url}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-ember underline-offset-4 hover:underline"
            >
              Blogger 글 보기
            </a>
          ) : null}
        </div>
        <ArticlePreviewFrame article={article} />
      </CardContent>
    </Card>
  );
}

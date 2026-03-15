import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Article } from "@/lib/types";

export function ArticlePreview({ article }: { article: Article }) {
  return (
    <Card className="overflow-hidden">
      {article.image?.public_url ? (
        <img src={article.image.public_url} alt={article.title} className="h-64 w-full object-cover" />
      ) : null}
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
        <div
          className="article-prose max-h-[420px] overflow-auto rounded-[24px] border border-ink/10 bg-white/70 p-6"
          dangerouslySetInnerHTML={{ __html: article.assembled_html ?? article.html_article }}
        />
      </CardContent>
    </Card>
  );
}

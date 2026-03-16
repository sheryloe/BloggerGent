import { Article } from "@/lib/types";
import { cn } from "@/lib/utils";

function buildPreviewHtml(article: Article) {
  return (
    article.assembled_html ??
    `<article style="max-width:860px;margin:0 auto;padding:32px 20px 48px;">${article.html_article}</article>`
  );
}

export function ArticlePreviewFrame({
  article,
  height,
  className,
}: {
  article: Article;
  height?: number;
  className?: string;
}) {
  const category = article.blog?.content_category?.toLowerCase() ?? "";
  const isDarkPreview = category === "mystery";

  return (
    <div
      className={cn(
        "overflow-hidden rounded-[28px] border shadow-sm",
        isDarkPreview
          ? "border-white/10 bg-slate-950"
          : "border-slate-200/80 bg-white dark:border-white/10 dark:bg-zinc-950",
        className,
      )}
    >
      <div
        className={cn(
          "article-preview-content px-3 py-3 sm:px-4 sm:py-4",
          isDarkPreview
            ? "bg-[radial-gradient(circle_at_top,rgba(71,85,105,0.35),transparent_34%),linear-gradient(180deg,#020617_0%,#0f172a_100%)]"
            : "bg-[linear-gradient(180deg,#f8fafc_0%,#eef2ff_100%)] dark:bg-[linear-gradient(180deg,#09090b_0%,#18181b_100%)]",
        )}
        style={height ? { minHeight: height } : undefined}
        dangerouslySetInnerHTML={{ __html: buildPreviewHtml(article) }}
      />
    </div>
  );
}

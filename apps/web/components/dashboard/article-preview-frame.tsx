import { Article } from "@/lib/types";
import { cn } from "@/lib/utils";

function buildPreviewDocument(article: Article) {
  const previewHtml =
    article.assembled_html ??
    `<article style="max-width:860px;margin:0 auto;padding:32px 20px 48px;">${article.html_article}</article>`;

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root { color-scheme: light; }
      * { box-sizing: border-box; }
      html, body { margin: 0; padding: 0; background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%); }
      body { min-height: 100vh; color: #0f172a; font-family: ui-sans-serif, system-ui, sans-serif; }
      img { max-width: 100%; border-radius: 18px; height: auto; }
      table { width: 100%; overflow: hidden; }
      pre, code { white-space: pre-wrap; word-break: break-word; }
      * { max-width: 100%; }
      a { color: #4f46e5; }
    </style>
  </head>
  <body>${previewHtml}</body>
</html>`;
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
  const resolvedHeight = height ?? Math.max(920, article.reading_time_minutes * 180 + 420);

  return (
    <iframe
      title={`${article.title} preview`}
      srcDoc={buildPreviewDocument(article)}
      className={cn(
        "w-full rounded-[28px] border border-slate-200/80 bg-white shadow-sm dark:border-white/10 dark:bg-zinc-950",
        className,
      )}
      style={{ height: resolvedHeight }}
    />
  );
}

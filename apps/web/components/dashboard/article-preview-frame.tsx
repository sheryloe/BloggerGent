import { Article } from "@/lib/types";

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
      html, body { margin: 0; padding: 0; background: #f8fafc; }
      body { min-height: 100vh; color: #0f172a; }
      img { max-width: 100%; }
      a { color: #0f766e; }
    </style>
  </head>
  <body>${previewHtml}</body>
</html>`;
}

export function ArticlePreviewFrame({ article }: { article: Article }) {
  const height = Math.max(1500, article.reading_time_minutes * 320 + 720);

  return (
    <iframe
      title={`${article.title} preview`}
      srcDoc={buildPreviewDocument(article)}
      className="w-full rounded-[28px] border border-ink/10 bg-white"
      style={{ height }}
    />
  );
}

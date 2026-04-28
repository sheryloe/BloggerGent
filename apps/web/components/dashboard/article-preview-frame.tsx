"use client";

import * as React from "react";
import { Article } from "@/lib/types";
import { cn } from "@/lib/utils";
import { injectImageFallbacks } from "@/lib/public-assets";

function buildPreviewHtml(article: Article) {
  const html =
    article.assembled_html ??
    `<article style="max-width:860px;margin:0 auto;padding:32px 20px 48px;">${article.html_article}</article>`;

  return injectImageFallbacks(html);
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
  const contentRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!contentRef.current) return;
    
    // Find all figure elements with tradingview-chart block
    const chartBlocks = contentRef.current.querySelectorAll('figure[data-media-block="tradingview-chart"]');
    chartBlocks.forEach((block) => {
      const symbol = block.getAttribute('data-symbol') || 'NASDAQ:AAPL';
      const theme = block.getAttribute('data-theme') || 'dark';
      
      // Clear existing content and inject iframe
      block.innerHTML = `
        <div class="chart-container-nasdaq" style="width: 100%; height: 500px; background: #131722; border-radius: 12px; overflow: hidden; margin: 24px 0;">
          <iframe 
            src="https://s.tradingview.com/widgetembed/?symbol=${symbol}&interval=D&theme=${theme}" 
            width="100%" 
            height="500" 
            frameborder="0" 
            allowfullscreen>
          </iframe>
        </div>
      `;
    });
  }, [article.html_article, article.assembled_html]);

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
      ref={contentRef}
      className={cn(
        "article-preview-content px-3 py-3 sm:px-4 sm:py-4",
        isDarkPreview
          ? "bg-[radial-gradient(circle_at_top,rgba(71,85,105,0.35),transparent_34%),linear-gradient(180deg,#020617_0%,#0f172a_100%)] text-slate-100"
          : "bg-[linear-gradient(180deg,#f8fafc_0%,#eef2ff_100%)] text-slate-900 dark:bg-[linear-gradient(180deg,#09090b_0%,#18181b_100%)] dark:text-zinc-100",
      )}
      style={height ? { minHeight: height } : undefined}
    >
      <style dangerouslySetInnerHTML={{ __html: `
        .article-preview-content iframe {
          border-radius: 12px;
          box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        .article-preview-content figure {
          margin: 0;
          padding: 0;
        }
      `}} />
      <div dangerouslySetInnerHTML={{ __html: buildPreviewHtml(article) }} />
    </div>
    </div>
  );
}

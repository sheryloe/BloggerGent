from __future__ import annotations

import re

from app.models.entities import Article
from app.services.related_posts import render_related_cards_html


def render_faq_html(faq_section: list[dict], section_title: str = "Frequently Asked Questions") -> str:
    if not faq_section:
        return ""
    items = []
    for item in faq_section:
        items.append(
            "<div style='border:1px solid #e5e7eb;border-radius:16px;padding:16px;background:#fff;'>"
            f"<h3 style='font-size:19px;line-height:1.5;margin:0 0 10px;'>{item['question']}</h3>"
            f"<p style='margin:0;color:#4b5563;line-height:1.8;'>{item['answer']}</p>"
            "</div>"
        )
    return (
        "<section style='margin-top:36px;'>"
        f"<h2 style='font-size:28px;margin-bottom:16px;'>{section_title}</h2>"
        "<div style='display:grid;gap:12px;'>"
        + "".join(items)
        + "</div></section>"
    )


def assemble_article_html(article: Article, hero_image_url: str, related_posts: list[dict]) -> str:
    category = (article.blog.content_category if article.blog else "").lower()
    related_title = "Related Mystery Stories" if category == "mystery" else "Related Korea Travel Reads"
    faq_title = "FAQ About This Story" if category == "mystery" else "Frequently Asked Questions"
    eyebrow = article.blog.name if article.blog else "Bloggent Automated Publishing"

    related_html = render_related_cards_html(related_posts, section_title=related_title)
    article_html = re.sub(r"<p>\s*<!--RELATED_POSTS-->\s*</p>", related_html, article.html_article, flags=re.IGNORECASE)
    article_html = article_html.replace("<!--RELATED_POSTS-->", related_html)
    if "<!--RELATED_POSTS-->" not in article.html_article:
        article_html = article_html + related_html

    faq_html = render_faq_html(article.faq_section or [], section_title=faq_title)
    return f"""
<article style="max-width:860px;margin:0 auto;padding:20px 16px;font-family:'Arial',sans-serif;color:#111827;">
  <header style="margin-bottom:24px;">
    <p style="font-size:12px;letter-spacing:0.18em;text-transform:uppercase;color:#fb923c;">{eyebrow}</p>
    <h1 style="font-size:40px;line-height:1.15;margin:8px 0 12px;">{article.title}</h1>
    <p style="font-size:18px;line-height:1.7;color:#4b5563;">{article.excerpt}</p>
  </header>
  <figure style="margin:0 0 28px;">
    <img src="{hero_image_url}" alt="{article.title}" style="width:100%;border-radius:24px;display:block;object-fit:cover;" />
  </figure>
  <section style="font-size:17px;line-height:1.85;">{article_html}</section>
  {faq_html}
</article>
""".strip()

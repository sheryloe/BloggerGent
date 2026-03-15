from __future__ import annotations

import re

from app.models.entities import Article
from app.services.related_posts import render_related_cards_html


def _inject_inline_style(html: str, tag: str, style: str) -> str:
    pattern = re.compile(rf"<{tag}([^>]*)>", re.IGNORECASE)

    def replacer(match: re.Match[str]) -> str:
        attrs = match.group(1) or ""
        if "style=" in attrs.lower():
            return match.group(0)
        if attrs.strip():
            return f"<{tag}{attrs} style=\"{style}\">"
        return f"<{tag} style=\"{style}\">"

    return pattern.sub(replacer, html)


def _theme_config(category: str) -> dict[str, str]:
    if category == "mystery":
        return {
            "accent": "#f8fafc",
            "article_background": "transparent",
            "article_border": "transparent",
            "article_shadow": "none",
            "heading": "#f8fafc",
            "body": "#f3f4f6",
            "muted": "#d1d5db",
            "faq_background": "rgba(255,255,255,0.04)",
            "faq_border": "rgba(255,255,255,0.14)",
        }
    return {
        "accent": "#0f766e",
        "article_background": "#ffffff",
        "article_border": "#e2e8f0",
        "article_shadow": "0 20px 60px rgba(15,23,42,0.08)",
        "heading": "#0f172a",
        "body": "#1e293b",
        "muted": "#475569",
        "faq_background": "#f8fafc",
        "faq_border": "#e2e8f0",
    }


def _style_article_body(html: str, *, accent: str, heading: str, body: str) -> str:
    styled = html
    styled = _inject_inline_style(
        styled,
        "h2",
        f"font-size:30px;line-height:1.28;margin:42px 0 16px;color:{heading};font-weight:800;letter-spacing:-0.02em;",
    )
    styled = _inject_inline_style(
        styled,
        "h3",
        f"font-size:22px;line-height:1.45;margin:26px 0 12px;color:{heading};font-weight:700;",
    )
    styled = _inject_inline_style(
        styled,
        "p",
        f"margin:0 0 18px;color:{body};font-size:17px;line-height:1.9;",
    )
    styled = _inject_inline_style(
        styled,
        "ul",
        f"margin:0 0 24px;padding-left:22px;color:{body};",
    )
    styled = _inject_inline_style(
        styled,
        "li",
        f"margin:0 0 10px;color:{body};font-size:16px;line-height:1.8;",
    )
    styled = _inject_inline_style(
        styled,
        "strong",
        f"color:{heading};font-weight:700;",
    )
    styled = _inject_inline_style(
        styled,
        "a",
        f"color:{accent};font-weight:600;text-decoration:underline;text-underline-offset:2px;",
    )
    return styled


def render_faq_html(
    faq_section: list[dict],
    section_title: str = "Frequently Asked Questions",
    *,
    heading: str,
    body: str,
    card_background: str,
    card_border: str,
) -> str:
    if not faq_section:
        return ""
    items = []
    for item in faq_section:
        items.append(
            f"<div style='border:1px solid {card_border};border-radius:18px;padding:18px;background:{card_background};'>"
            f"<h3 style='font-size:19px;line-height:1.5;margin:0 0 10px;color:{heading};'>{item['question']}</h3>"
            f"<p style='margin:0;color:{body};line-height:1.8;'>{item['answer']}</p>"
            "</div>"
        )
    return (
        "<section style='margin-top:36px;'>"
        f"<h2 style='font-size:28px;margin-bottom:16px;color:{heading};'>{section_title}</h2>"
        "<div style='display:grid;gap:12px;'>"
        + "".join(items)
        + "</div></section>"
    )


def assemble_article_html(article: Article, hero_image_url: str, related_posts: list[dict]) -> str:
    category = (article.blog.content_category if article.blog else "").lower()
    theme = _theme_config(category)
    related_title = "Related Mystery Stories" if category == "mystery" else "Related Korea Travel Reads"
    faq_title = "FAQ About This Story" if category == "mystery" else "Frequently Asked Questions"
    eyebrow = article.blog.name if article.blog else "Bloggent Automated Publishing"

    related_html = render_related_cards_html(related_posts, section_title=related_title, category=category)
    article_html = re.sub(r"<p>\s*<!--RELATED_POSTS-->\s*</p>", "", article.html_article, flags=re.IGNORECASE)
    article_html = article_html.replace("<!--RELATED_POSTS-->", "")
    article_html = _style_article_body(
        article_html,
        accent=theme["accent"],
        heading=theme["heading"],
        body=theme["body"],
    )

    faq_html = render_faq_html(
        article.faq_section or [],
        section_title=faq_title,
        heading=theme["heading"],
        body=theme["body"],
        card_background=theme["faq_background"],
        card_border=theme["faq_border"],
    )
    return f"""
<article style="max-width:860px;margin:0 auto;padding:32px 22px 48px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:{theme['heading']};background:{theme['article_background']};border:1px solid {theme['article_border']};border-radius:{'0px' if category == 'mystery' else '32px'};box-shadow:{theme['article_shadow']};">
  <header style="margin-bottom:28px;">
    <p style="font-size:12px;letter-spacing:0.18em;text-transform:uppercase;color:{theme['accent']};font-weight:700;">{eyebrow}</p>
    <h1 style="font-size:40px;line-height:1.12;margin:10px 0 14px;color:{theme['heading']};">{article.title}</h1>
    <p style="font-size:18px;line-height:1.8;color:{theme['muted']};margin:0;">{article.excerpt}</p>
  </header>
  <figure style="margin:0 0 32px;">
    <img src="{hero_image_url}" alt="{article.title}" style="width:100%;border-radius:28px;display:block;object-fit:cover;" />
  </figure>
  <section style="font-size:17px;line-height:1.9;color:{theme['body']};">{article_html}</section>
  {faq_html}
  {related_html}
</article>
""".strip()

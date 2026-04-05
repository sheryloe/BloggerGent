from __future__ import annotations

import html
import re

from app.models.entities import Article
from app.services.related_posts import render_related_cards_html

MYSTERY_COLLAGE_MARKER_PATTERNS = (
    re.compile(r"<p>\s*4-panel investigation collage\s*</p>", re.IGNORECASE),
    re.compile(r"<p>\s*AI-generated editorial collage\s*</p>", re.IGNORECASE),
    re.compile(r"4-panel investigation collage", re.IGNORECASE),
    re.compile(r"AI-generated editorial collage", re.IGNORECASE),
)

LANGUAGE_SWITCH_START_MARKER = "<!--BLOGGENT_LANGUAGE_SWITCH_START-->"
LANGUAGE_SWITCH_END_MARKER = "<!--BLOGGENT_LANGUAGE_SWITCH_END-->"


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


def _lead_summary(article: Article) -> str:
    meta_description = (article.meta_description or "").strip()
    if meta_description:
        return meta_description
    return (article.excerpt or "").strip()


def _strip_mystery_inline_artifacts(html_fragment: str) -> str:
    cleaned = html_fragment
    for pattern in MYSTERY_COLLAGE_MARKER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"<figure\b[^>]*>.*?</figure>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<img\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _resolve_inline_collage_media(article: Article, *, slot_name: str) -> dict | None:
    media_items = article.inline_media if isinstance(article.inline_media, list) else []
    for item in media_items:
        if not isinstance(item, dict):
            continue
        slot = str(item.get("slot") or "").strip().lower()
        delivery = item.get("delivery") if isinstance(item.get("delivery"), dict) else {}
        cloudflare_meta = delivery.get("cloudflare") if isinstance(delivery, dict) else {}
        cloudinary_meta = delivery.get("cloudinary") if isinstance(delivery, dict) else {}
        image_url_candidates = [
            str(cloudflare_meta.get("original_url") or "").strip() if isinstance(cloudflare_meta, dict) else "",
            str(cloudinary_meta.get("secure_url_original") or "").strip() if isinstance(cloudinary_meta, dict) else "",
            str(item.get("image_url") or "").strip(),
        ]
        image_url = next((candidate for candidate in image_url_candidates if candidate), "")
        if slot == slot_name.strip().lower() and image_url:
            resolved = dict(item)
            resolved["image_url"] = image_url
            return resolved
    return None


def _insert_inline_figure(article_html: str, media_item: dict, *, title: str, marker_name: str, alt_suffix: str) -> str:
    image_url = html.escape(str(media_item.get("image_url") or "").strip(), quote=True)
    if not image_url:
        return article_html
    marker = f"<!--{marker_name}-->"
    if marker in article_html:
        return article_html
    alt_text = html.escape(f"{title} {alt_suffix}", quote=True)
    width = int(media_item.get("width") or 0)
    height = int(media_item.get("height") or 0)
    width_attr = f' width="{width}"' if width > 0 else ""
    height_attr = f' height="{height}"' if height > 0 else ""
    figure_html = (
        f"{marker}<figure style=\"margin:30px 0 30px;\">"
        f'<img src="{image_url}"{width_attr}{height_attr} alt="{alt_text}" loading="lazy" decoding="async" '
        'style="width:100%;border-radius:20px;display:block;object-fit:cover;" />'
        "</figure>"
    )

    paragraph_matches = list(re.finditer(r"</p>", article_html, flags=re.IGNORECASE))
    if paragraph_matches:
        insert_index = paragraph_matches[len(paragraph_matches) // 2].end()
        return f"{article_html[:insert_index]}{figure_html}{article_html[insert_index:]}"
    return f"{article_html}\n{figure_html}"


def _resolve_primary_image_url(article: Article, fallback_url: str) -> str:
    image = article.image
    metadata = image.image_metadata if image else None
    delivery = metadata.get("delivery") if isinstance(metadata, dict) else None

    candidates: list[str] = []
    if isinstance(delivery, dict):
        cloudflare_meta = delivery.get("cloudflare")
        if isinstance(cloudflare_meta, dict):
            candidates.append(str(cloudflare_meta.get("original_url") or "").strip())

        cloudinary_meta = delivery.get("cloudinary")
        if isinstance(cloudinary_meta, dict):
            candidates.append(str(cloudinary_meta.get("secure_url_original") or "").strip())

        candidates.append(str(delivery.get("local_public_url") or "").strip())
        candidates.append(str(delivery.get("public_url") or "").strip())

    candidates.extend(
        [
            str(fallback_url or "").strip(),
            str(image.public_url or "").strip() if image else "",
        ]
    )

    for candidate in candidates:
        if candidate:
            return candidate
    return ""


def upsert_language_switch_html(assembled_html: str, language_switch_html: str) -> str:
    source = str(assembled_html or "")
    block = str(language_switch_html or "").strip()
    pattern = re.compile(
        rf"{re.escape(LANGUAGE_SWITCH_START_MARKER)}.*?{re.escape(LANGUAGE_SWITCH_END_MARKER)}",
        flags=re.DOTALL,
    )
    replacement = f"{LANGUAGE_SWITCH_START_MARKER}\n{block}\n{LANGUAGE_SWITCH_END_MARKER}"
    if pattern.search(source):
        return pattern.sub(replacement, source, count=1)

    insertion = f"\n{replacement}\n"
    closing_tag = "</article>"
    if closing_tag in source:
        return source.replace(closing_tag, f"{insertion}{closing_tag}", 1)
    return f"{source}{insertion}".strip()


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


def assemble_article_html(
    article: Article,
    hero_image_url: str,
    related_posts: list[dict],
    *,
    language_switch_html: str = "",
) -> str:
    category = (article.blog.content_category if article.blog else "").lower()
    theme = _theme_config(category)
    related_title = "Related Mystery Stories" if category == "mystery" else "Related Korea Travel Reads"
    faq_title = "FAQ About This Story" if category == "mystery" else "Frequently Asked Questions"
    eyebrow = article.blog.name if article.blog else "Bloggent Automated Publishing"

    related_html = render_related_cards_html(related_posts, section_title=related_title, category=category)
    article_html = re.sub(r"<p>\s*<!--RELATED_POSTS-->\s*</p>", "", article.html_article, flags=re.IGNORECASE)
    article_html = article_html.replace("<!--RELATED_POSTS-->", "")
    if category == "mystery":
        article_html = _strip_mystery_inline_artifacts(article_html)
    article_html = _style_article_body(
        article_html,
        accent=theme["accent"],
        heading=theme["heading"],
        body=theme["body"],
    )
    if category == "travel":
        travel_inline_media = _resolve_inline_collage_media(article, slot_name="travel-inline-3x2")
        if travel_inline_media:
            article_html = _insert_inline_figure(
                article_html,
                travel_inline_media,
                title=article.title,
                marker_name="TRAVEL_INLINE_3X2",
                alt_suffix="supporting travel collage",
            )
    elif category == "mystery":
        mystery_inline_media = _resolve_inline_collage_media(article, slot_name="mystery-inline-3x2")
        if mystery_inline_media:
            article_html = _insert_inline_figure(
                article_html,
                mystery_inline_media,
                title=article.title,
                marker_name="MYSTERY_INLINE_3X2",
                alt_suffix="supporting mystery collage",
            )

    faq_html = render_faq_html(
        article.faq_section or [],
        section_title=faq_title,
        heading=theme["heading"],
        body=theme["body"],
        card_background=theme["faq_background"],
        card_border=theme["faq_border"],
    )
    lead_summary = _lead_summary(article)
    escaped_lead_summary = html.escape(lead_summary, quote=True)
    hidden_lead_summary = html.escape(lead_summary)
    escaped_title = html.escape(article.title, quote=True)
    language_switch_block = str(language_switch_html or "").strip()
    hero_url = _resolve_primary_image_url(article, hero_image_url)
    hero_figure_html = ""
    if hero_url:
        escaped_hero_url = html.escape(hero_url, quote=True)
        hero_width = article.image.width if article.image else None
        hero_height = article.image.height if article.image else None
        hero_width_attr = f' width="{int(hero_width)}"' if isinstance(hero_width, int) and hero_width > 0 else ""
        hero_height_attr = f' height="{int(hero_height)}"' if isinstance(hero_height, int) and hero_height > 0 else ""
        hero_figure_html = (
            '<figure style="margin:0 0 32px;">'
            f'<img src="{escaped_hero_url}"{hero_width_attr}{hero_height_attr} alt="{escaped_title}" '
            'loading="eager" decoding="async" style="width:100%;border-radius:28px;display:block;object-fit:cover;" />'
            "</figure>"
        )
    return f"""
<article data-bloggent-meta-description="{escaped_lead_summary}" style="max-width:860px;margin:0 auto;padding:32px 22px 48px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:{theme['heading']};background:{theme['article_background']};border:1px solid {theme['article_border']};border-radius:{'0px' if category == 'mystery' else '32px'};box-shadow:{theme['article_shadow']};">
  <header style="margin-bottom:28px;display:flex;flex-direction:column;">
    <p style="order:3;font-size:18px;line-height:1.8;color:{theme['muted']};margin:0;">{lead_summary}</p>
    <p style="order:1;font-size:12px;letter-spacing:0.18em;text-transform:uppercase;color:{theme['accent']};font-weight:700;margin:0 0 10px;">{eyebrow}</p>
    <h1 style="order:2;font-size:40px;line-height:1.12;margin:0 0 14px;color:{theme['heading']};">{article.title}</h1>
  </header>
  <div id="bloggent-seo-meta" data-bloggent-meta-source="body" style="display:none!important;visibility:hidden!important;max-height:0;overflow:hidden;">{hidden_lead_summary}</div>
  {hero_figure_html}
  <section style="font-size:17px;line-height:1.9;color:{theme['body']};">{article_html}</section>
  {faq_html}
  {LANGUAGE_SWITCH_START_MARKER}
  {language_switch_block}
  {LANGUAGE_SWITCH_END_MARKER}
  {related_html}
</article>
""".strip()

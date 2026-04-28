from __future__ import annotations

import html
import re

from app.models.entities import Article
from app.services.blogger.blogger_live_audit_service import extract_best_article_fragment
from app.services.content.faq_hygiene import filter_generic_faq_items
from app.services.content.related_posts import render_related_cards_html

MYSTERY_COLLAGE_MARKER_PATTERNS = (
    re.compile(r"<p>\s*4-panel investigation collage\s*</p>", re.IGNORECASE),
    re.compile(r"<p>\s*AI-generated editorial collage\s*</p>", re.IGNORECASE),
    re.compile(r"4-panel investigation collage", re.IGNORECASE),
    re.compile(r"AI-generated editorial collage", re.IGNORECASE),
)

LANGUAGE_SWITCH_START_MARKER = "<!--BLOGGENT_LANGUAGE_SWITCH_START-->"
LANGUAGE_SWITCH_END_MARKER = "<!--BLOGGENT_LANGUAGE_SWITCH_END-->"
HANGUL_CHAR_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]+")
MULTISPACE_RE = re.compile(r"\s{2,}")
EMPTY_PAREN_RE = re.compile(r"\(\s*\)")
ARTICLE_BODY_ROLE_RE = re.compile(
    r"<section\b[^>]*data-bloggent-role=['\"]article-body['\"][^>]*>(?P<body>.*?)</section>",
    re.IGNORECASE | re.DOTALL,
)
TRAVEL_INLINE_MARKER_RE = re.compile(r"<!--\s*TRAVEL_INLINE_3X2\s*-->", re.IGNORECASE)
ARTICLE_TAG_ONLY_RE = re.compile(r"</?article\b[^>]*>", re.IGNORECASE)
FIGURE_BLOCK_RE = re.compile(r"<figure\b[^>]*>.*?</figure>", re.IGNORECASE | re.DOTALL)
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
SEO_META_BLOCK_RE = re.compile(
    r"<div\b[^>]*id=['\"]bloggent-seo-meta['\"][^>]*>.*?</div>",
    re.IGNORECASE | re.DOTALL,
)
HEADER_BLOCK_RE = re.compile(r"<header\b[^>]*>.*?</header>", re.IGNORECASE | re.DOTALL)
LEGACY_ARTICLE_WRAPPER_SECTION_RE = re.compile(
    r"<article\b[^>]*(?:data-bloggent-meta-description|class=['\"]dossier-body['\"])[^>]*>.*?(?P<section><section\b[^>]*>.*?</section>).*?</article>",
    re.IGNORECASE | re.DOTALL,
)
LEGACY_SHELL_SECTION_RE = re.compile(
    r"<div\b[^>]*id=['\"]bloggent-seo-meta['\"][^>]*>.*?</div>\s*(?:<figure\b[^>]*>.*?</figure>\s*)?(?P<section><section\b[^>]*>.*?</section>)",
    re.IGNORECASE | re.DOTALL,
)
OUTER_SECTION_BODY_RE = re.compile(r"^<section\b[^>]*>(?P<body>.*)</section>$", re.IGNORECASE | re.DOTALL)
SECTION_TAG_RE = re.compile(r"<(/?)section\b[^>]*>", re.IGNORECASE)

JSON_LD_TEMPLATE = """
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "{title}",
  "description": "{description}",
  "image": "{image_url}",
  "author": {{
    "@type": "Organization",
    "name": "BloggerGent Mystery Archives"
  }},
  "publisher": {{
    "@type": "Organization",
    "name": "{blog_name}",
    "logo": {{
      "@type": "ImageObject",
      "url": "https://api.dongriarchive.com/assets/mystery-logo.webp"
    }}
  }},
  "datePublished": "{date_published}"
}}
</script>
"""

CRITICAL_MYSTERY_CSS = """
<style>
  .dossier-body { font-display: swap; line-height: 1.8; color: #cbd5e1; }
  .dossier-body h2 { color: #f8fafc; font-family: 'Newsreader', serif; border-bottom: 1px solid #1e293b; padding-bottom: 8px; margin-top: 40px; }
  .dossier-body img { border: 1px solid rgba(255,255,255,0.05); box-shadow: 0 20px 25px -5px rgba(0,0,0,0.3); }
  .evidence-table { width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; margin: 24px 0; }
  .evidence-table th { background: #334155; color: #60a5fa; text-align: left; padding: 12px; font-size: 14px; text-transform: uppercase; }
  .evidence-table td { padding: 12px; border-top: 1px solid #334155; font-size: 15px; }
</style>
"""


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
            "accent": "#60a5fa",
            "article_background": "#0f172a",
            "article_border": "#1e293b",
            "article_shadow": "none",
            "heading": "#f8fafc",
            "body": "#cbd5e1",
            "muted": "#94a3b8",
            "faq_border": "#334155",
            "table_background": "#1e293b",
            "table_header_background": "#334155",
        }
    return {
        "accent": "#0d9488",
        "article_background": "#ffffff",
        "article_border": "#f1f5f9",
        "article_shadow": "none",
        "heading": "#0f172a",
        "body": "#334155",
        "muted": "#64748b",
        "faq_background": "#f8fafc",
        "faq_border": "#e2e8f0",
        "table_background": "#ffffff",
        "table_header_background": "#f8fafc",
    }


def _normalize_locale(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("ja"):
        return "ja"
    if text.startswith("es"):
        return "es"
    if text.startswith("ko"):
        return "ko"
    return "en"


def _localized_faq_title(locale: str) -> str:
    if locale == "ja":
        return "よくある質問（FAQ）"
    if locale == "es":
        return "Preguntas frecuentes"
    if locale == "ko":
        return "자주 묻는 질문"
    return "Frequently Asked Questions"


def _localized_related_title(locale: str, *, category: str) -> str:
    if locale == "ja":
        return "関連記事" if category == "mystery" else "あわせて読みたい記事"
    if locale == "es":
        return "Lecturas relacionadas"
    if locale == "ko":
        return "함께 읽으면 좋은 글"
    return "Related Mystery Stories" if category == "mystery" else "Related Korea Travel Reads"


def _localized_related_empty_message(locale: str) -> str:
    if locale == "ja":
        return "関連記事は公開記事が増えるとここに表示されます。"
    if locale == "es":
        return "Aquí aparecerán lecturas relacionadas cuando el blog tenga más publicaciones."
    if locale == "ko":
        return "관련 글은 게시물이 더 쌓이면 여기에서 보여집니다."
    return "Relevant posts will appear here once this blog has more published content."


def _strip_hangul_text(value: str) -> str:
    cleaned = HANGUL_CHAR_RE.sub("", str(value or ""))
    cleaned = EMPTY_PAREN_RE.sub("", cleaned)
    cleaned = MULTISPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def _normalize_english_mystery_faq_section(faq_section: list[dict]) -> list[dict]:
    defaults = [
        {
            "question": "What are the key verified facts in this case?",
            "answer": "Start from records that can be dated, sourced, and cross-checked before considering later retellings.",
        },
        {
            "question": "How should readers evaluate competing theories?",
            "answer": "Compare each theory against documented evidence, timeline consistency, and source credibility.",
        },
    ]
    normalized: list[dict] = []
    for item in faq_section:
        question = _strip_hangul_text(str(item.get("question") or item.get("q") or item.get("title") or ""))
        answer = _strip_hangul_text(str(item.get("answer") or item.get("a") or item.get("text") or ""))
        if question and answer:
            normalized.append({"question": question, "answer": answer})

    if len(normalized) >= 2:
        return normalized
    return normalized + defaults[: max(0, 2 - len(normalized))]


def _style_article_body(
    html: str,
    *,
    accent: str,
    heading: str,
    body: str,
    border: str,
    table_background: str,
    table_header_background: str,
    details_background: str,
) -> str:
    styled = html
    styled = _inject_inline_style(
        styled,
        "h2",
        f"font-size:24px;line-height:1.3;margin:32px 0 12px;color:{heading};font-weight:700;",
    )
    styled = _inject_inline_style(
        styled,
        "h3",
        f"font-size:20px;line-height:1.4;margin:24px 0 10px;color:{heading};font-weight:700;",
    )
    styled = _inject_inline_style(
        styled,
        "p",
        f"margin:0 0 16px;color:{body};font-size:16px;line-height:1.7;",
    )
    styled = _inject_inline_style(
        styled,
        "ul",
        f"margin:0 0 20px;padding-left:20px;color:{body};",
    )
    styled = _inject_inline_style(
        styled,
        "li",
        f"margin:0 0 8px;color:{body};font-size:16px;line-height:1.6;",
    )
    styled = _inject_inline_style(
        styled,
        "strong",
        f"color:{heading};font-weight:700;",
    )
    styled = _inject_inline_style(
        styled,
        "a",
        f"color:{accent};text-decoration:underline;",
    )
    styled = _inject_inline_style(
        styled,
        "table",
        f"width:100%;border-collapse:collapse;margin:20px 0;background:{table_background};border:1px solid {border};",
    )
    styled = _inject_inline_style(
        styled,
        "th",
        f"border:1px solid {border};padding:10px;background:{table_header_background};color:{heading};text-align:left;font-size:14px;",
    )
    styled = _inject_inline_style(
        styled,
        "td",
        f"border:1px solid {border};padding:10px;color:{body};font-size:14px;vertical-align:top;",
    )
    styled = _inject_inline_style(
        styled,
        "details",
        f"margin:0 0 10px;border:1px solid {border};border-radius:12px;background:{details_background};padding:0;",
    )
    styled = _inject_inline_style(
        styled,
        "summary",
        f"cursor:pointer;padding:12px 14px;color:{heading};font-size:17px;font-weight:700;",
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


def _strip_existing_related_posts_section(html_fragment: str) -> str:
    cleaned = re.sub(
        r"<section\b[^>]*class=['\"][^'\"]*related-posts[^'\"]*['\"][^>]*>.*?</section>",
        "",
        html_fragment,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_canonical_body_fragment(html_fragment: str) -> str:
    current = str(html_fragment or "").strip()
    if not current:
        return current

    for _ in range(4):
        changed = False
        article_count = len(re.findall(r"<article\b", current, flags=re.IGNORECASE))
        if article_count > 1:
            narrowed = extract_best_article_fragment(current)
            if narrowed and len(narrowed) < len(current):
                current = narrowed.strip()
                changed = True
        role_match = ARTICLE_BODY_ROLE_RE.search(current)
        if role_match:
            current = str(role_match.group("body") or "").strip()
            changed = True
        elif any(
            token in current
            for token in (
                "data-bloggent-meta-source=\"body\"",
                "data-bloggent-meta-description",
                "class=\"dossier-body\"",
                "id=\"bloggent-seo-meta\"",
            )
        ):
            extracted_section_body = _extract_first_section_body(current, anchor_token='id="bloggent-seo-meta"')
            if not extracted_section_body:
                extracted_section_body = _extract_first_section_body(current)
            if extracted_section_body:
                current = extracted_section_body
                changed = True
            else:
                shell_match = LEGACY_ARTICLE_WRAPPER_SECTION_RE.search(current) or LEGACY_SHELL_SECTION_RE.search(current)
                if shell_match:
                    current = str(shell_match.group("section") or "").strip()
                    outer_section_match = OUTER_SECTION_BODY_RE.match(current)
                    if outer_section_match:
                        current = str(outer_section_match.group("body") or "").strip()
                    changed = True
        if not changed:
            break
    return current


def _extract_first_section_body(source: str, *, anchor_token: str | None = None) -> str:
    current = str(source or "")
    anchor_index = 0
    if anchor_token:
        located = current.find(anchor_token)
        if located >= 0:
            anchor_index = located
    section_match = re.search(r"<section\b[^>]*>", current[anchor_index:], flags=re.IGNORECASE)
    if not section_match:
        return ""

    section_start = anchor_index + section_match.start()
    depth = 0
    for tag_match in SECTION_TAG_RE.finditer(current[section_start:]):
        closing = tag_match.group(1) == "/"
        if not closing:
            depth += 1
            continue
        depth -= 1
        if depth == 0:
            absolute_end = section_start + tag_match.end()
            wrapped = current[section_start:absolute_end]
            body_match = OUTER_SECTION_BODY_RE.match(wrapped.strip())
            return str(body_match.group("body") or "").strip() if body_match else ""
    return ""


def _strip_travel_body_shell(article_html: str) -> str:
    current = str(article_html or "").strip()
    if not current:
        return current

    preserved_restore_figures: list[tuple[str, str]] = []

    def preserve_restore_figure(match: re.Match[str]) -> str:
        figure_html = match.group(0)
        lower = figure_html.lower()
        if "data-bloggent-restore-slot=\"inline\"" not in lower and "data-bloggent-restore-slot='inline'" not in lower:
            return ""
        token = f"__BLOGGENT_RESTORE_INLINE_{len(preserved_restore_figures)}__"
        preserved_restore_figures.append((token, figure_html))
        return token

    current = TRAVEL_INLINE_MARKER_RE.sub("", current)
    current = FIGURE_BLOCK_RE.sub(preserve_restore_figure, current)
    current = IMG_TAG_RE.sub("", current)
    current = SEO_META_BLOCK_RE.sub("", current)
    current = HEADER_BLOCK_RE.sub("", current)
    current = ARTICLE_TAG_ONLY_RE.sub("", current)
    for token, figure_html in preserved_restore_figures:
        current = current.replace(token, figure_html)
    current = re.sub(r"\n{3,}", "\n\n", current)
    return current.strip()


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

    candidates: list[str] = [
        str(fallback_url or "").strip(),
        str(image.public_url or "").strip() if image else "",
    ]
    if isinstance(delivery, dict):
        cloudflare_meta = delivery.get("cloudflare")
        if isinstance(cloudflare_meta, dict):
            candidates.append(str(cloudflare_meta.get("original_url") or "").strip())

        cloudinary_meta = delivery.get("cloudinary")
        if isinstance(cloudinary_meta, dict):
            candidates.append(str(cloudinary_meta.get("secure_url_original") or "").strip())

        candidates.append(str(delivery.get("local_public_url") or "").strip())
        candidates.append(str(delivery.get("public_url") or "").strip())

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
    faq_items = filter_generic_faq_items(faq_section)
    if not faq_items:
        return ""
    items = []
    for item in faq_items:
        items.append(
            f"<details style='border:1px solid {card_border};border-radius:18px;background:{card_background};overflow:hidden;'>"
            f"<summary style='cursor:pointer;list-style:none;padding:16px 18px;color:{heading};font-size:18px;font-weight:700;'>{item['question']}</summary>"
            f"<div style='padding:0 18px 18px;'><p style='margin:0;color:{body};line-height:1.8;'>{item['answer']}</p></div>"
            "</details>"
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
    locale = _normalize_locale(getattr(article.blog, "primary_language", ""))
    english_mystery = category == "mystery" and locale == "en"
    ui_locale = "en" if category == "mystery" else locale
    theme = _theme_config(category)
    related_title = _localized_related_title(ui_locale, category=category)
    faq_title = _localized_faq_title(ui_locale)
    eyebrow = article.blog.name if article.blog else "Bloggent Automated Publishing"

    related_html = render_related_cards_html(
        related_posts,
        section_title=related_title,
        category=category,
        empty_message=_localized_related_empty_message(ui_locale),
    )
    hero_url = _resolve_primary_image_url(article, hero_image_url)
    article_html = _extract_canonical_body_fragment(article.html_article)
    article_html = re.sub(r"<p>\s*<!--RELATED_POSTS-->\s*</p>", "", article_html, flags=re.IGNORECASE)
    article_html = article_html.replace("<!--RELATED_POSTS-->", "")
    article_html = _strip_existing_related_posts_section(article_html)
    if category == "travel":
        article_html = _strip_travel_body_shell(article_html)
    elif category == "mystery":
        article_html = _strip_mystery_inline_artifacts(article_html)
    faq_section = article.faq_section or []
    if category == "mystery":
        faq_section = []  # User requested to remove FAQ for mystery
    if english_mystery:
        article_html = _strip_hangul_text(article_html)
        faq_section = _normalize_english_mystery_faq_section(list(faq_section))
    article_html = _style_article_body(
        article_html,
        accent=theme["accent"],
        heading=theme["heading"],
        body=theme["body"],
        border=theme["faq_border"],
        table_background=theme["table_background"],
        table_header_background=theme["table_header_background"],
        details_background=theme.get("faq_background", "#1e293b"),
    )
    if category == "mystery":
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
        faq_section,
        section_title=faq_title,
        heading=theme["heading"],
        body=theme["body"],
        card_background=theme.get("faq_background", "#1e293b"),
        card_border=theme["faq_border"],
    )

    # [최적화] 이미지 로딩 전략 및 규격화
    img_count = 0
    def img_replacer(match):
        nonlocal img_count
        tag = match.group(0)
        img_count += 1
        # width/height가 없으면 기본값 주입하여 CLS 방지
        if 'width=' not in tag.lower():
            tag = re.sub(r'<img\b', '<img width="800" height="450"', tag, flags=re.IGNORECASE)
        
        # 첫 번째 이미지는 즉시 로드(LCP), 나머지는 지연 로드
        if img_count == 1:
            tag = re.sub(r'<img\b', '<img fetchpriority="high"', tag, flags=re.IGNORECASE)
        else:
            tag = re.sub(r'<img\b', '<img loading="lazy" decoding="async"', tag, flags=re.IGNORECASE)
        return tag

    article_html = re.sub(r'<img\b[^>]*>', img_replacer, article_html, flags=re.IGNORECASE)
    lead_summary = _lead_summary(article)
    article_title = article.title
    if english_mystery:
        lead_summary = _strip_hangul_text(lead_summary) or lead_summary
        article_title = _strip_hangul_text(article_title) or article_title
    escaped_lead_summary = html.escape(lead_summary, quote=True)
    hidden_lead_summary = html.escape(lead_summary)
    escaped_title = html.escape(article_title, quote=True)
    language_switch_block = str(language_switch_html or "").strip()
    hero_figure_html = ""
    if hero_url:
        escaped_hero_url = html.escape(hero_url, quote=True)
        hero_width = article.image.width if article.image else None
        hero_height = article.image.height if article.image else None
        hero_width_attr = f' width="{int(hero_width)}"' if isinstance(hero_width, int) and hero_width > 0 else ""
        hero_height_attr = f' height="{int(hero_height)}"' if isinstance(hero_height, int) and hero_height > 0 else ""
        hero_figure_html = (
            '<figure data-bloggent-role="hero-figure" style="margin:0 0 32px;">'
            f'<img src="{escaped_hero_url}"{hero_width_attr}{hero_height_attr} alt="{escaped_title}" '
            'fetchpriority="high" loading="eager" decoding="async" style="width:100%;border-radius:28px;display:block;object-fit:cover;" />'
            "</figure>"
        )
    # [최적화] 구조화 데이터 생성
    created_at = getattr(article, "created_at", None)
    json_ld = JSON_LD_TEMPLATE.format(
        title=escaped_title,
        description=escaped_lead_summary,
        image_url=hero_url or "",
        blog_name=html.escape(article.blog.name if article.blog else "The Midnight Archives"),
        date_published=created_at.isoformat() if created_at else "",
    )

    locale = ui_locale
    related_title = _localized_related_title(locale, category=category)
    empty_msg = _localized_related_empty_message(locale)
    
    # We use the imported service to render cards
    related_html = render_related_cards_html(
        related_posts or [],
        section_title=related_title,
        category=category,
        empty_message=empty_msg
    )

    article_padding = "padding:10px;background:transparent;"
    header_border = f"border-bottom:1px solid {theme['article_border']};padding-bottom:12px;"
    content_spacing = "margin-top:16px;"

    optimized_html = f"""
{CRITICAL_MYSTERY_CSS if category == 'mystery' else ''}
<article class="dossier-body" data-bloggent-article="canonical" data-bloggent-meta-description="{escaped_lead_summary}" style="{article_padding}font-family:sans-serif;color:{theme['heading']};text-align:left;">
  <header style="margin-bottom:20px;{header_border}">
    <p style="font-size:12px;text-transform:uppercase;color:{theme['accent']};font-weight:700;margin:0 0 4px;">{eyebrow}</p>
    <h1 data-bloggent-role="article-title" style="font-size:28px;line-height:1.2;margin:0 0 8px;color:{theme['heading']};font-weight:700;">{article_title}</h1>
    <p style="font-size:16px;line-height:1.5;color:{theme['muted']};margin:0;">{lead_summary}</p>
  </header>
  <div id="bloggent-seo-meta" data-bloggent-meta-source="body" style="display:none!important;visibility:hidden!important;max-height:0;overflow:hidden;">{hidden_lead_summary}</div>
  {hero_figure_html}
  <section data-bloggent-role="article-body" style="{content_spacing}font-size:17px;line-height:1.9;color:{theme['body']};text-align:left;">
    {article_html}
  </section>
  {faq_html}
  {LANGUAGE_SWITCH_START_MARKER}
  {language_switch_block}
  {LANGUAGE_SWITCH_END_MARKER}
  <div class="article-footer" style="margin-top:40px;border-top:1px solid {theme['article_border']};padding-top:24px;">
    {related_html}
  </div>
</article>
{json_ld}
""".strip()
    return optimized_html

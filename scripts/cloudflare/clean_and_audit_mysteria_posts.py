from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.package_common import CloudflareIntegrationClient, safe_filename, write_json  # noqa: E402


REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")
RUNTIME_ENV_PATH = Path(r"D:\Donggri_Runtime\BloggerGent\env\runtime.settings.env")
TARGET_CATEGORY_ID = "cat-world-mysteria-story"
TARGET_CATEGORY_SLUG = "미스테리아-스토리"
PUBLIC_BASE = "https://dongriarchive.com/ko/post"

NUMBER_RE = re.compile(r"^mystery-archive-(\d+)(?:-|$)", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
IMG_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"][^>]*>", re.IGNORECASE)
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
FIGURE_RE = re.compile(r"(?is)<figure\b[^>]*>.*?</figure>")
SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*>.*?</script>")
STYLE_RE = re.compile(r"(?is)<style\b[^>]*>.*?</style>")
HTML_H1_RE = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>")
HTML_H2_RE = re.compile(r"(?is)<h2[^>]*>(.*?)</h2>")
HTML_H3_RE = re.compile(r"(?is)<h3[^>]*>(.*?)</h3>")
HTML_P_RE = re.compile(r"(?is)<p[^>]*>(.*?)</p>")
HTML_LI_RE = re.compile(r"(?is)<li[^>]*>(.*?)</li>")
HTML_BR_RE = re.compile(r"(?is)<br\s*/?>")
H1_RE = re.compile(r"<h1\b", re.IGNORECASE)
H2_RE = re.compile(r"<h2\b", re.IGNORECASE)
TABLE_RE = re.compile(r"<table\b", re.IGNORECASE)
MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+", re.MULTILINE)
MARKDOWN_H2_RE = re.compile(r"^\s*#{2,3}\s+", re.MULTILINE)
MARKDOWN_H1_RE = re.compile(r"^\s*#\s+", re.MULTILINE)
BLOGGER_URL_RE = re.compile(r"https?://(?:www\.)?dongdonggri\.blogspot\.com/[^\s\"'<>)]*", re.IGNORECASE)
GENERIC_BLOGSPOT_URL_RE = re.compile(r"https?://[^/\"'<>]*blogspot\.com/[^\s\"'<>)]*", re.IGNORECASE)
SOURCE_MARKER_RE = re.compile(
    r"(?:원문\s*(?:참고|링크)|참고\s*원문|주제\s*출처|source[_\s-]*(?:url|link)|original\s*source|blogger\s*source)",
    re.IGNORECASE,
)
SOURCE_BLOCK_RE = re.compile(
    r"(?is)<(?P<tag>p|div|section|li|blockquote|aside)[^>]*>[^<]*(?:원문\s*(?:참고|링크)|참고\s*원문|주제\s*출처|"
    r"source[_\s-]*(?:url|link)|original\s*source|blogger\s*source|dongdonggri\.blogspot\.com|blogspot\.com)"
    r"[\s\S]*?</(?P=tag)>"
)
FREEFORM_HTML_RE = re.compile(r"<(?:article|section|div|p|blockquote|ul|ol|table|thead|tbody|tr|th|td|aside|h1|h2|h3|span|strong|em|b)\b", re.IGNORECASE)


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _build_client(args: argparse.Namespace) -> CloudflareIntegrationClient:
    runtime = _load_env_file(RUNTIME_ENV_PATH)
    base_url = (
        args.api_base_url
        or os.environ.get("CLOUDFLARE_BLOG_API_BASE_URL")
        or runtime.get("CLOUDFLARE_BLOG_API_BASE_URL")
        or "https://api.dongriarchive.com"
    )
    token = (
        args.token
        or os.environ.get("DONGRI_M2M_TOKEN")
        or os.environ.get("CLOUDFLARE_BLOG_M2M_TOKEN")
        or runtime.get("CLOUDFLARE_BLOG_M2M_TOKEN")
    )
    return CloudflareIntegrationClient(base_url=base_url, token=token or "")


def _number_from_slug(slug: str) -> int | None:
    match = NUMBER_RE.match(_safe_text(slug))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _strip_tags(value: str) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", value or "")).strip()


def _html_fragment_to_markdown(value: str) -> str:
    text = _safe_text(value)
    text = SCRIPT_RE.sub("", text)
    text = STYLE_RE.sub("", text)
    text = FIGURE_RE.sub("", text)
    text = IMG_TAG_RE.sub("", text)
    text = HTML_H1_RE.sub(lambda m: "\n\n## " + _strip_tags(m.group(1)) + "\n\n", text)
    text = HTML_H2_RE.sub(lambda m: "\n\n## " + _strip_tags(m.group(1)) + "\n\n", text)
    text = HTML_H3_RE.sub(lambda m: "\n\n### " + _strip_tags(m.group(1)) + "\n\n", text)
    text = HTML_P_RE.sub(lambda m: "\n\n" + _strip_tags(m.group(1)) + "\n\n", text)
    text = HTML_LI_RE.sub(lambda m: "\n- " + _strip_tags(m.group(1)), text)
    text = HTML_BR_RE.sub("\n", text)
    text = re.sub(r"(?is)</?(?:div|section|article|aside|blockquote|ul|ol|table|thead|tbody|tr|th|td|strong|em|b|span)[^>]*>", "\n", text)
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = _clean_source_refs(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _korean_count(value: str) -> int:
    return len(re.findall(r"[가-힣]", _strip_tags(value)))


def _has_source_ref(value: str) -> bool:
    text = value or ""
    return bool(BLOGGER_URL_RE.search(text) or GENERIC_BLOGSPOT_URL_RE.search(text) or SOURCE_MARKER_RE.search(text))


def _clean_source_refs(value: str) -> str:
    text = value or ""
    before = None
    while before != text:
        before = text
        text = SOURCE_BLOCK_RE.sub("", text)
    text = re.sub(
        r"(?im)^\s*.*(?:원문\s*(?:참고|링크)|참고\s*원문|주제\s*출처|source[_\s-]*(?:url|link)|original\s*source|"
        r"blogger\s*source|dongdonggri\.blogspot\.com|blogspot\.com).*$",
        "",
        text,
    )
    text = BLOGGER_URL_RE.sub("", text)
    text = GENERIC_BLOGSPOT_URL_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r">\s{2,}<", "><", text)
    return text.strip()


def _ensure_one_cover_image(content: str, cover_image: str, title: str) -> tuple[str, str]:
    current = content or ""
    imgs = IMG_RE.findall(current)
    if len(imgs) == 1:
        return current, "kept_existing"
    if not cover_image:
        return current, "missing_cover"

    current = re.sub(r"(?is)<figure\b[^>]*>.*?<img\b[\s\S]*?</figure>", "", current)
    current = re.sub(r"(?is)<img\b[^>]*>", "", current)
    escaped_cover = html.escape(cover_image, quote=True)
    escaped_title = html.escape(title, quote=True)
    figure = (
        "<figure data-media-block=\"true\">"
        f"<img src=\"{escaped_cover}\" alt=\"{escaped_title}\" loading='eager' decoding='async'/>"
        "</figure>"
    )
    article_open = re.match(r"(?is)^\s*<article\b[^>]*>", current)
    if article_open:
        insert_at = article_open.end()
        return f"{current[:insert_at]}{figure}{current[insert_at:]}", "inserted_cover_after_article"
    return f"{figure}{current}", "inserted_cover_before_content"


def _normalize_publish_content(content: str, cover_image: str, title: str) -> tuple[str, str]:
    current = _clean_source_refs(content)
    has_freeform_html = bool(FREEFORM_HTML_RE.search(current))
    if has_freeform_html:
        body = _html_fragment_to_markdown(current)
        escaped_cover = html.escape(cover_image, quote=True)
        escaped_title = html.escape(title, quote=True)
        if cover_image:
            figure = (
                "<figure data-media-block=\"true\">"
                f"<img src=\"{escaped_cover}\" alt=\"{escaped_title}\" loading='eager' decoding='async'/>"
                "</figure>"
            )
            return f"{figure}\n\n{body}".strip(), "normalized_markdown_with_cover"
        return body, "normalized_markdown_missing_cover"
    return _ensure_one_cover_image(current, cover_image, title)


def _meta_description(content: str) -> str:
    plain = _strip_tags(content)
    return (plain[:270].rstrip() + "...") if len(plain) > 270 else plain


def _publish_description(value: str, *, fallback_content: str) -> str:
    plain = _strip_tags(_clean_source_refs(value))
    if len(plain) < 90:
        plain = _strip_tags(_clean_source_refs(fallback_content))
    if len(plain) < 90:
        plain = (
            plain
            + " 이 글은 사건의 배경, 기록, 단서, 가능한 해석을 구분해 정리한 미스테리아 스토리 기록입니다."
        )
    plain = SPACE_RE.sub(" ", plain).strip()
    if len(plain) > 165:
        plain = plain[:165].rstrip(" ,.;:-")
    return plain


def _cover_alt_text(title: str) -> str:
    base = SPACE_RE.sub(" ", _safe_text(title)).strip() or "미스테리아 스토리 사건 이미지"
    alt = f"{base}의 분위기를 담은 미스테리아 스토리 대표 이미지"
    if len(alt) > 120:
        alt = alt[:120].rstrip(" ,.;:-")
    return alt


def _score_row(*, title: str, slug: str, content: str, cover_image: str, source_refs: bool) -> dict[str, int]:
    plain = _strip_tags(content)
    korean = _korean_count(content)
    img_count = len(IMG_RE.findall(content))
    h2_count = len(H2_RE.findall(content)) + len(MARKDOWN_H2_RE.findall(content))
    has_h1 = bool(H1_RE.search(content) or MARKDOWN_H1_RE.search(content))
    has_md = bool("**" in content)
    has_table = bool(TABLE_RE.search(content))
    title_len = len(title)
    has_analysis_terms = sum(1 for token in ("기록", "단서", "가설", "해석", "의문", "미스터리") if token in plain)

    seo = 45
    seo += 15 if 16 <= title_len <= 58 else 6
    seo += 15 if korean >= 3000 else max(0, int(korean / 3000 * 15))
    seo += 10 if img_count == 1 and bool(cover_image) else 0
    seo += 8 if 4 <= h2_count <= 9 else 3
    seo += 7 if not has_h1 and not has_md and not source_refs else 0
    seo = min(100, seo)

    ctr = 45
    ctr += 18 if 18 <= title_len <= 48 else 8
    ctr += 12 if any(token in title for token in ("미스터리", "실종", "사건", "비극", "정체", "저주")) else 5
    ctr += 10 if ":" in title or "?" in title else 4
    ctr += 10 if img_count == 1 else 0
    ctr += 5 if not source_refs else 0
    ctr = min(100, ctr)

    geo = 45
    geo += 18 if korean >= 3500 else max(0, int(korean / 3500 * 18))
    geo += 15 if has_analysis_terms >= 4 else has_analysis_terms * 3
    geo += 10 if h2_count >= 4 else h2_count * 2
    geo += 7 if not has_table and not has_md and not source_refs else 0
    geo += 5 if "내 생각" in plain or "마무리" in plain else 0
    geo = min(100, geo)
    return {"seo": seo, "ctr": ctr, "geo": geo}


def _category_slug(item: dict[str, Any]) -> str:
    category = item.get("category") if isinstance(item.get("category"), dict) else {}
    return _safe_text(category.get("slug") or item.get("categorySlug") or item.get("category_slug"))


def _category_id(item: dict[str, Any]) -> str:
    category = item.get("category") if isinstance(item.get("category"), dict) else {}
    return _safe_text(category.get("id") or item.get("categoryId") or item.get("category_id"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean Blogger source refs and audit Mysteria posts.")
    parser.add_argument("--from", dest="range_from", type=int, default=1)
    parser.add_argument("--to", dest="range_to", type=int, default=141)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--token", default="")
    parser.add_argument("--api-base-url", default="")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    client = _build_client(args)
    posts = client.list_posts()
    candidates: list[dict[str, Any]] = []
    for post in posts:
        number = _number_from_slug(_safe_text(post.get("slug")))
        if number is None or number < args.range_from or number > args.range_to:
            continue
        candidates.append(post)
    candidates.sort(key=lambda row: (_number_from_slug(_safe_text(row.get("slug"))) or 999999, _safe_text(row.get("slug"))))

    rows: list[dict[str, Any]] = []
    updated = 0
    for post in candidates:
        post_id = _safe_text(post.get("id"))
        detail = client.get_post(post_id)
        slug = _safe_text(detail.get("slug") or post.get("slug"))
        number = _number_from_slug(slug)
        title = _safe_text(detail.get("title") or post.get("title"))
        cover = _safe_text(detail.get("coverImage") or post.get("coverImage"))
        content_before = _safe_text(detail.get("content"))
        excerpt_before = _safe_text(detail.get("excerpt"))
        seo_before = _safe_text(detail.get("seoDescription"))
        meta_before = _safe_text(detail.get("metaDescription"))

        source_refs_before = any(_has_source_ref(value) for value in (content_before, excerpt_before, seo_before, meta_before))
        content_cleaned, image_action = _normalize_publish_content(content_before, cover, title)
        excerpt_cleaned = _clean_source_refs(excerpt_before)
        seo_cleaned = _clean_source_refs(seo_before)
        meta_cleaned = _clean_source_refs(meta_before)
        if not excerpt_cleaned:
            excerpt_cleaned = _meta_description(content_cleaned)[:160]
        if not seo_cleaned:
            seo_cleaned = _meta_description(content_cleaned)
        if not meta_cleaned:
            meta_cleaned = seo_cleaned
        excerpt_cleaned = _publish_description(excerpt_cleaned, fallback_content=content_cleaned)
        seo_cleaned = _publish_description(seo_cleaned, fallback_content=content_cleaned)
        meta_cleaned = _publish_description(meta_cleaned, fallback_content=content_cleaned)

        changed = (
            content_cleaned != content_before
            or excerpt_cleaned != excerpt_before
            or seo_cleaned != seo_before
            or meta_cleaned != meta_before
            or _category_id(detail) != TARGET_CATEGORY_ID
        )

        if args.execute and changed:
            payload = {
                "title": title,
                "slug": slug,
                "content": content_cleaned,
                "coverImage": cover,
                "categoryId": TARGET_CATEGORY_ID,
                "status": "published",
                "excerpt": excerpt_cleaned,
                "seoDescription": seo_cleaned,
                "metaDescription": meta_cleaned,
                "coverAlt": _cover_alt_text(title),
            }
            client.update_post(post_id, payload)
            updated += 1

        source_refs_after = any(_has_source_ref(value) for value in (content_cleaned, excerpt_cleaned, seo_cleaned, meta_cleaned))
        scores = _score_row(
            title=title,
            slug=slug,
            content=content_cleaned,
            cover_image=cover,
            source_refs=source_refs_after,
        )
        img_urls = IMG_RE.findall(content_cleaned)
        rows.append(
            {
                "number": number,
                "title": title,
                "url": f"{PUBLIC_BASE}/{slug}",
                "korean_chars": _korean_count(content_cleaned),
                "image": "있음" if len(img_urls) == 1 and bool(cover) else "없음",
                "image_count": len(img_urls),
                "cover_image": cover,
                "category": TARGET_CATEGORY_SLUG if _category_id(detail) == TARGET_CATEGORY_ID else _category_slug(detail),
                "source_refs_before": source_refs_before,
                "source_refs_after": source_refs_after,
                "image_action": image_action,
                "seo": scores["seo"],
                "ctr": scores["ctr"],
                "geo": scores["geo"],
                "changed": changed,
            }
        )

    summary = {
        "mode": "execute" if args.execute else "dry-run",
        "range": {"from": args.range_from, "to": args.range_to},
        "candidate_count": len(rows),
        "updated_count": updated,
        "source_refs_before_count": sum(1 for row in rows if row["source_refs_before"]),
        "source_refs_after_count": sum(1 for row in rows if row["source_refs_after"]),
        "missing_or_multi_image_count": sum(1 for row in rows if row["image"] != "있음"),
        "below_3000_korean_count": sum(1 for row in rows if row["korean_chars"] < 3000),
    }
    report = {"summary": summary, "rows": rows}
    report_path = REPORT_ROOT / f"{stamp}-{safe_filename('mysteria-clean-audit-1-141')}.json"
    write_json(report_path, report)
    print(json.dumps({"report_path": str(report_path), "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

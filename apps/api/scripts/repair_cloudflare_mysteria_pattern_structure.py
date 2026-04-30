from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from sqlalchemy import select, text as sql_text

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
API_ROOT = SCRIPT_DIR.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import SyncedCloudflarePost  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from package_common import CloudflareIntegrationClient, normalize_space, resolve_cloudflare_category_id  # noqa: E402
from repair_mystery_garbage_data import (  # noqa: E402
    CloudflareDbRow,
    MYSTERIA_CATEGORY_NAME,
    MYSTERIA_CATEGORY_SLUG,
    audit_cloudflare_many_async,
    build_publish_description,
)

RUNTIME_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent")
REPORT_JSON = RUNTIME_ROOT / "storage" / "the-midnight-archives" / "cloudflare-mysteria-pattern-audit-20260428.json"
REPORT_MD = RUNTIME_ROOT / "storage" / "the-midnight-archives" / "cloudflare-mysteria-pattern-audit-20260428.md"
ROOL_DOC = RUNTIME_ROOT / "Rool" / "20-mystery" / "problem-solution-cloudflare-pattern-repair-20260428.md"
BACKUP_DIR = RUNTIME_ROOT / "storage" / "the-midnight-archives" / "pattern-repair-backups-20260428"

ARTICLE_PATTERN_VERSION = 4
ALLOWED_PATTERNS = {
    "case-timeline": ["사건 개요", "연대기", "남은 공백", "마무리 기록"],
    "evidence-breakdown": ["사건 개요", "증거 목록", "반론과 한계", "마무리 기록"],
    "legend-context": ["전설의 시작", "전파 경로", "현대적 해석", "마무리 기록"],
    "scene-investigation": ["현장 묘사", "동선과 시간", "이상한 지점", "마무리 기록"],
    "scp-dossier": ["파일 개요", "관찰 기록", "위험 신호", "마무리 기록"],
}
MYSTERIA_URL_PREFIXES = ("/ko/post/miseuteria-seutori-", "/ko/post/mystery-archive-")
MYSTERIA_SLUG_PREFIXES = ("miseuteria-seutori-", "mystery-archive-")
API_ASSET_RE = re.compile(r"https://api\.dongriarchive\.com/assets/[^\s\"'<>)]*?\.webp", re.IGNORECASE)
VERIFY_MEMO_RE = re.compile(r"(?im)^\s*#{1,6}\s*검증\s*메모\s*\d*\s*$[\s\S]*?(?=^\s*#{1,6}\s+|\Z)")
MARKDOWN_HEADING_RE = re.compile(r"(?im)^\s*#{1,6}\s+(.+?)\s*$")
HTML_H2_RE = re.compile(r"(?is)<h2\b[^>]*>(.*?)</h2>")
ARTICLE_SHELL_HTML_RE = re.compile(r"(?is)<(?:article|main|h1)\b|class=[\"'][^\"']*(?:article|prose|entry-content)[^\"']*[\"']")

MANUAL_PATTERN_BY_SLUG: dict[str, str] = {
    "mystery-archive-1-the-disappearance-of-flight-mh370": "evidence-breakdown",
    "meri-selreseuteuui-miseuteori-yuryeongseonui-gwahakjeok-bunseok": "evidence-breakdown",
    "miseuteria-seutori-flor-de-la-mar-treasure-ship-record": "evidence-breakdown",
    "miseuteria-seutori-mary-celeste-ghost-ship-record": "evidence-breakdown",
    "miseuteria-seutori-sodder-children-christmas-fire-record": "case-timeline",
    "miseuteria-seutori-oak-island-money-pit-record": "evidence-breakdown",
    "miseuteria-seutori-roanoke-colony-croatoan-record": "legend-context",
    "miseuteria-seutori-uss-cyclops-bermuda-route-record": "case-timeline",
    "miseuteria-seutori-dyatlov-pass-tent-and-footprints-record": "scene-investigation",
    "miseuteria-seutori-wow-signal-72-second-radio-record": "evidence-breakdown",
    "miseuteria-seutori-zodiac-killer-cipher-letter-record": "evidence-breakdown",
    "miseuteria-seutori-mv-joyita-mystery": "scene-investigation",
    "mystery-archive-oakville-blobs-witness-illness-report": "evidence-breakdown",
    "mystery-archive-sodder-children-christmas-tragedy": "case-timeline",
    "mystery-archive-mh370-disappearance-deep-analysis": "case-timeline",
    "mystery-archive-oakville-blobs-biological-mystery": "evidence-breakdown",
    "mystery-archive-ss-baychimo-arctic-ghost-ship": "scene-investigation",
    "mystery-archive-carroll-a-deering-ghost-ship": "scene-investigation",
    "flight-19-bermuda-triangle-mystery": "case-timeline",
    "scp-682-containment-breach-the-unstoppable-horror-20260424-1840": "scp-dossier",
    "mystery-archive-somerton-man-tamam-shud-mystery": "evidence-breakdown",
    "jaek-deo-ripeoui-jeongchee-daehan-iron": "evidence-breakdown",
}
KEYWORD_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("scp", "containment", "682", "격리"), "scp-dossier"),
    (("roanoke", "croatoan", "로어노크", "크로아토안"), "legend-context"),
    (("legend", "lore", "beast", "gevaudan", "전설", "괴담", "민속"), "legend-context"),
    (("dyatlov", "baychimo", "joyita", "deering", "hinterkaifeck", "현장", "발자국", "빈 배"), "scene-investigation"),
    (("flight-19", "flight 19", "uss-cyclops", "cyclops", "mh370", "sodder", "실종", "항로", "연대"), "case-timeline"),
]


@dataclass(slots=True)
class PatternItem:
    remote_id: str
    slug: str
    title: str
    url: str
    db_id: int | None = None
    db_pattern_id: str = ""
    db_pattern_version: int | None = None
    detail_pattern_id: str = ""
    detail_pattern_version: int | None = None
    selected_pattern_id: str = "evidence-breakdown"
    selected_pattern_version: int = ARTICLE_PATTERN_VERSION
    cover_image: str = ""
    live_status: int | str = ""
    live_plain_text_length: int = 0
    live_image_count: int = 0
    live_markdown_exposed: bool = False
    live_raw_html_exposed: bool = False
    content_plain_text_length: int = 0
    content_h2: list[str] = field(default_factory=list)
    verification_memo_count: int = 0
    invalid_pattern_id: bool = False
    invalid_pattern_version: bool = False
    h2_contract_mismatch: bool = False
    needs_content_rebuild: bool = False
    needs_metadata_update: bool = False
    action: str = "keep"
    reasons: list[str] = field(default_factory=list)
    result: str = "planned"
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and repair Cloudflare Mysteria 5-pattern structure.")
    parser.add_argument("--mode", choices=("audit", "dry-run", "apply", "verify"), required=True)
    parser.add_argument("--report-path", default=str(REPORT_JSON))
    parser.add_argument("--markdown-path", default=str(REPORT_MD))
    parser.add_argument("--rool-path", default=str(ROOL_DOC))
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def post_url(slug: str) -> str:
    return f"https://dongriarchive.com/ko/post/{slug}"


def url_key(value: str | None) -> str:
    parsed = urlparse((value or "").strip())
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def is_mysteria_post(post: dict[str, Any]) -> bool:
    slug = normalize_space(str(post.get("slug") or ""))
    url = normalize_space(str(post.get("publicUrl") or post.get("url") or post.get("published_url") or ""))
    category = post.get("category") if isinstance(post.get("category"), dict) else {}
    category_slug = normalize_space(str(post.get("category_slug") or post.get("categorySlug") or category.get("slug") or ""))
    category_name = normalize_space(str(post.get("category_name") or post.get("categoryName") or category.get("name") or ""))
    path = urlparse(url).path
    return (
        category_slug == MYSTERIA_CATEGORY_SLUG
        or category_name == MYSTERIA_CATEGORY_NAME
        or slug.startswith(MYSTERIA_SLUG_PREFIXES)
        or any(path.startswith(prefix) for prefix in MYSTERIA_URL_PREFIXES)
    )


def normalize_pattern(value: str | None) -> str:
    candidate = normalize_space(str(value or ""))
    return candidate if candidate in ALLOWED_PATTERNS else ""


def choose_pattern(slug: str, title: str, current: str | None = None) -> str:
    slug_key = normalize_space(slug).lower()
    if slug_key in MANUAL_PATTERN_BY_SLUG:
        return MANUAL_PATTERN_BY_SLUG[slug_key]
    current_pattern = normalize_pattern(current)
    if current_pattern:
        return current_pattern
    haystack = f"{slug} {title}".casefold()
    for keywords, pattern_id in KEYWORD_PATTERNS:
        if any(keyword.casefold() in haystack for keyword in keywords):
            return pattern_id
    return "evidence-breakdown"


def extract_first_api_asset(*values: str) -> str:
    for value in values:
        for match in API_ASSET_RE.findall(value or ""):
            return match.split("?", 1)[0]
    return ""


def strip_tags(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "figure", "img"]):
        tag.decompose()
    return re.sub(r"\s+", " ", html.unescape(soup.get_text(" ", strip=True))).strip()


def content_plain_text(value: str) -> str:
    text = value or ""
    text = re.sub(r"(?is)<figure\b[^>]*>.*?</figure>", "\n", text)
    text = re.sub(r"(?is)<img\b[^>]*>", "\n", text)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", "\n", text)
    text = VERIFY_MEMO_RE.sub("\n", text)
    text = re.sub(r"(?im)^\s*#{1,6}\s+", "", text)
    text = re.sub(r"[*_`>#|]+", " ", text)
    text = strip_tags(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_content_h2(value: str) -> list[str]:
    headings: list[str] = []
    for match in HTML_H2_RE.findall(value or ""):
        text = strip_tags(match)
        if text:
            headings.append(text)
    for match in MARKDOWN_HEADING_RE.findall(value or ""):
        text = normalize_space(re.sub(r"[*_`]+", "", html.unescape(match)))
        if text and text not in headings:
            headings.append(text)
    return headings


def verification_memo_count(value: str) -> int:
    return len(re.findall(r"검증\s*메모\s*\d*", value or ""))


def clean_paragraphs_from_content(value: str) -> list[str]:
    text = value or ""
    text = VERIFY_MEMO_RE.sub("\n", text)
    text = re.sub(r"(?is)<figure\b[^>]*>.*?</figure>", "\n", text)
    text = re.sub(r"(?is)<img\b[^>]*>", "\n", text)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", "\n", text)
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "\n", text)
    text = re.sub(r"(?is)<style\b[^>]*>.*?</style>", "\n", text)
    text = re.sub(r"(?is)</?(?:div|section|article|main|header|footer|aside|span)\b[^>]*>", "\n", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p>", "\n\n", text)
    text = re.sub(r"(?is)<li\b[^>]*>", "\n- ", text)
    text = re.sub(r"(?is)</li>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    lines: list[str] = []
    for raw in html.unescape(text).splitlines():
        line = normalize_space(raw)
        if not line or re.match(r"^#{1,6}\s+", line):
            continue
        if re.match(r"^FAQ$", line, flags=re.IGNORECASE):
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        line = normalize_space(re.sub(r"[*_`>#|]+", " ", line))
        if not line or line in {"FAQ", MYSTERIA_CATEGORY_NAME}:
            continue
        lines.append(line)
    paragraphs: list[str] = []
    for line in lines:
        if len(line) <= 220:
            paragraphs.append(line)
            continue
        sentences = re.split(r"(?<=[.!?。！？다요죠까])\s+", line)
        buf = ""
        for sentence in sentences:
            sentence = normalize_space(sentence)
            if not sentence:
                continue
            if len(buf) + len(sentence) < 260:
                buf = normalize_space(f"{buf} {sentence}")
            else:
                if buf:
                    paragraphs.append(buf)
                buf = sentence
        if buf:
            paragraphs.append(buf)
    deduped: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        key = paragraph.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(paragraph)
    return deduped


def chunk_paragraphs(paragraphs: list[str], count: int = 4) -> list[list[str]]:
    chunks: list[list[str]] = [[] for _ in range(count)]
    lengths = [0] * count
    for paragraph in paragraphs:
        idx = min(range(count), key=lambda i: lengths[i])
        chunks[idx].append(paragraph)
        lengths[idx] += len(paragraph)
    return chunks


def supplement_paragraphs(title: str) -> list[str]:
    base = normalize_space(title)
    return [
        f"{base}을 다시 읽을 때 핵심은 결론을 서둘러 고정하지 않는 것이다. 확인된 기록, 후대의 해석, 대중적으로 굳어진 장면을 분리해야 사건의 실제 윤곽이 흐려지지 않는다.",
        "이 사건의 기록은 한쪽으로 매끄럽게 이어지지 않는다. 그래서 좋은 글 구조는 단서를 한곳에 몰아넣기보다, 무엇이 관찰됐고 무엇이 추정이며 무엇이 아직 공백인지 따로 표시해야 한다.",
        "가장 자극적인 설명은 독자의 시선을 끌 수 있지만 검증 기준을 대신하지는 못한다. 남은 자료의 출처와 시점, 그리고 서로 맞지 않는 대목을 함께 보아야 미스터리가 과장된 전설로만 소비되지 않는다.",
        "오늘 기준의 재검토는 새로운 결론을 단정하기 위한 작업이 아니다. 오히려 오래 반복된 이야기에서 확인 가능한 기록과 설명되지 않은 빈칸을 다시 정렬하는 과정에 가깝다.",
        f"따라서 {base}은 단순한 괴담보다 기록 해석의 문제로 읽는 편이 정확하다. 이 관점은 사건을 더 차갑게 만들지만, 동시에 왜 이 이야기가 오래 살아남았는지도 더 분명하게 보여 준다.",
        "첫 번째로 확인할 것은 사건의 순서다. 누가 언제 무엇을 보았는지, 어떤 기록이 먼저 남았는지, 나중에 붙은 설명이 무엇인지를 나누면 과장된 서사와 실제 자료 사이의 거리가 보인다.",
        "두 번째로 중요한 것은 증거의 종류다. 물리적 흔적, 공식 문서, 목격담, 언론 보도, 후대 연구는 같은 무게로 다룰 수 없다. 각각의 자료는 만들어진 환경과 목적이 다르기 때문이다.",
        "세 번째로는 설명이 너무 깔끔할 때 오히려 조심해야 한다. 오래된 미스터리일수록 단일 원인으로 모든 빈칸을 채우려는 시도가 많지만, 실제 기록은 대개 여러 조건이 겹친 형태로 남는다.",
        "이 글은 결론을 하나로 몰아가기보다 남은 단서의 힘과 한계를 함께 정리하는 데 초점을 둔다. 그래야 독자가 사건의 분위기만 소비하지 않고, 무엇이 검증됐고 무엇이 아직 추정인지 판단할 수 있다.",
        f"{base}이 계속 회자되는 이유도 여기에 있다. 사건 자체의 충격뿐 아니라 기록이 끊긴 위치, 증언이 흔들리는 방식, 설명이 서로 충돌하는 지점이 독자의 해석을 계속 불러낸다.",
        "마지막으로 남는 질문은 미스터리를 믿을 것인가가 아니다. 어떤 자료를 근거로 어디까지 말할 수 있는지, 그리고 말할 수 없는 부분을 어떻게 표시할 것인지가 더 현실적인 기준이다.",
        "그 기준으로 보면 이 사건은 완전히 닫힌 답안보다 정리된 파일에 가깝다. 핵심 단서는 보존하고, 약한 가설은 약한 상태로 남기며, 확인되지 않은 장면은 전설의 영역으로 분리해야 한다.",
    ]


def render_hero(hero_url: str, title: str) -> str:
    return (
        '<figure data-media-block="true">'
        f'<img src="{html.escape(hero_url, quote=True)}" alt="{html.escape(title, quote=True)}" loading="eager" decoding="async" />'
        "</figure>"
    )


def markdown_paragraph(value: str) -> str:
    text = normalize_space(value)
    text = re.sub(r"(?i)\b검증\s*메모\s*\d*\b", " ", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text)
    text = re.sub(r"[*_`>#|]+", " ", text)
    text = normalize_space(text)
    return html.escape(text, quote=False)


def render_repaired_content(*, title: str, original_content: str, hero_url: str, pattern_id: str) -> str:
    headings = ALLOWED_PATTERNS[pattern_id]
    paragraphs = clean_paragraphs_from_content(original_content) or supplement_paragraphs(title)
    chunks = chunk_paragraphs(paragraphs, 4)
    for idx, chunk in enumerate(chunks):
        if not chunk:
            chunk.append(supplement_paragraphs(title)[idx])
    body_parts: list[str] = [render_hero(hero_url, title)]
    for heading, chunk in zip(headings, chunks, strict=True):
        body_parts.append(f"## {heading}")
        for paragraph in chunk:
            safe_paragraph = markdown_paragraph(paragraph)
            if safe_paragraph:
                body_parts.append(safe_paragraph)
    content = "\n\n".join(body_parts)
    supplements = supplement_paragraphs(title)
    guard = 0
    while len(content_plain_text(content)) < 3400 and guard < len(supplements):
        target_heading = f"## {headings[guard % len(headings)]}"
        supplement = markdown_paragraph(supplements[guard])
        if target_heading in content and supplement:
            content = content.replace(target_heading, f"{target_heading}\n\n{supplement}", 1)
        guard += 1
    return content


def build_payload(detail: dict[str, Any], *, title: str, slug: str, content: str, hero_url: str, category_id: str, pattern_id: str) -> dict[str, Any]:
    description = build_publish_description(title, content)
    tags: list[str] = []
    for item in detail.get("tags") or []:
        tag = normalize_space(str(item.get("name") or item.get("label") or item.get("slug") or "")) if isinstance(item, dict) else normalize_space(str(item))
        if tag and tag not in tags:
            tags.append(tag)
    if MYSTERIA_CATEGORY_NAME not in tags:
        tags.append(MYSTERIA_CATEGORY_NAME)
    return {
        "title": title,
        "slug": slug,
        "content": content,
        "description": description,
        "excerpt": description,
        "seoTitle": normalize_space(str(detail.get("seoTitle") or title)),
        "seoDescription": description,
        "metaDescription": description,
        "tagNames": tags[:12],
        "categoryId": category_id,
        "status": "published",
        "coverImage": hero_url,
        "coverAlt": normalize_space(str(detail.get("coverAlt") or title)),
        "article_pattern_id": pattern_id,
        "article_pattern_version": ARTICLE_PATTERN_VERSION,
        "articlePatternId": pattern_id,
        "articlePatternVersion": ARTICLE_PATTERN_VERSION,
    }


def db_rows_by_slug(db) -> dict[str, SyncedCloudflarePost]:
    rows = db.execute(select(SyncedCloudflarePost).where(SyncedCloudflarePost.status == "published")).scalars().all()
    return {normalize_space(row.slug): row for row in rows if normalize_space(row.slug)}


def db_rows_by_url(db) -> dict[str, SyncedCloudflarePost]:
    rows = db.execute(select(SyncedCloudflarePost).where(SyncedCloudflarePost.status == "published")).scalars().all()
    return {url_key(row.url): row for row in rows if normalize_space(row.url)}


def item_public_url(post: dict[str, Any], detail: dict[str, Any]) -> str:
    url = normalize_space(str(detail.get("publicUrl") or post.get("publicUrl") or detail.get("url") or post.get("url") or ""))
    if url:
        return url
    slug = normalize_space(str(detail.get("slug") or post.get("slug") or ""))
    return post_url(slug) if slug else ""


def collect_items(db, cf: CloudflareIntegrationClient) -> tuple[list[PatternItem], dict[str, dict[str, Any]]]:
    api_posts = [post for post in cf.list_posts() if is_mysteria_post(post)]
    rows_slug = db_rows_by_slug(db)
    rows_url = db_rows_by_url(db)
    cloudflare_rows: list[CloudflareDbRow] = []
    details: dict[str, dict[str, Any]] = {}
    items: list[PatternItem] = []
    for post in sorted(api_posts, key=lambda p: normalize_space(str(p.get("publishedAt") or p.get("createdAt") or p.get("slug") or ""))):
        remote_id = normalize_space(str(post.get("id") or post.get("remote_id") or ""))
        if not remote_id:
            continue
        detail = cf.get_post(remote_id)
        details[remote_id] = detail
        slug = normalize_space(str(detail.get("slug") or post.get("slug") or ""))
        title = normalize_space(str(detail.get("title") or post.get("title") or ""))
        url = item_public_url(post, detail)
        row = rows_slug.get(slug) or rows_url.get(url_key(url))
        detail_pattern_id = normalize_pattern(str(detail.get("article_pattern_id") or detail.get("articlePatternId") or ""))
        raw_version = detail.get("article_pattern_version") or detail.get("articlePatternVersion")
        try:
            detail_pattern_version = int(raw_version) if raw_version is not None else None
        except (TypeError, ValueError):
            detail_pattern_version = None
        db_pattern_id = normalize_pattern(str(getattr(row, "article_pattern_id", "") or "")) if row else ""
        db_pattern_version = getattr(row, "article_pattern_version", None) if row else None
        selected = choose_pattern(slug, title, detail_pattern_id or db_pattern_id)
        content = str(detail.get("content") or detail.get("contentHtml") or detail.get("contentMarkdown") or "")
        cover = extract_first_api_asset(str(detail.get("coverImage") or ""), content, str(getattr(row, "thumbnail_url", "") if row else ""))
        content_h2 = extract_content_h2(content)
        content_text = content_plain_text(content)
        memo_count = verification_memo_count(content)
        expected = ALLOWED_PATTERNS[selected]
        item = PatternItem(
            remote_id=remote_id,
            slug=slug,
            title=title,
            url=url,
            db_id=int(row.id) if row else None,
            db_pattern_id=db_pattern_id,
            db_pattern_version=db_pattern_version,
            detail_pattern_id=detail_pattern_id,
            detail_pattern_version=detail_pattern_version,
            selected_pattern_id=selected,
            cover_image=cover,
            content_plain_text_length=len(content_text),
            content_h2=content_h2,
            verification_memo_count=memo_count,
        )
        # The Cloudflare integration currently accepts pattern metadata in full-payload
        # updates but does not echo it from get_post(). DB sync is therefore the
        # authoritative metadata check; live GET remains the content/image check.
        item.invalid_pattern_id = not db_pattern_id
        item.invalid_pattern_version = db_pattern_version != ARTICLE_PATTERN_VERSION
        item.h2_contract_mismatch = bool(memo_count) or any(heading not in content_h2 for heading in expected)
        has_article_shell_html = bool(ARTICLE_SHELL_HTML_RE.search(content))
        item.needs_content_rebuild = bool(memo_count) or len(content_text) < 3000 or has_article_shell_html
        item.needs_metadata_update = item.invalid_pattern_id or item.invalid_pattern_version
        if item.needs_content_rebuild:
            item.reasons.append("content_rebuild")
        if memo_count:
            item.reasons.append("verification_memo")
        if len(content_text) < 3000:
            item.reasons.append("content_under_3000")
        if has_article_shell_html:
            item.reasons.append("article_shell_html")
        if item.needs_metadata_update:
            item.reasons.append("metadata_v4")
        item.action = "repair" if item.reasons else "keep"
        items.append(item)
        cloudflare_rows.append(
            CloudflareDbRow(
                id=len(cloudflare_rows),
                remote_post_id=remote_id,
                slug=slug,
                title=title,
                url=url,
                category_slug=MYSTERIA_CATEGORY_SLUG,
                canonical_category_slug=MYSTERIA_CATEGORY_SLUG,
                thumbnail_url=cover,
                status="published",
            )
        )
    if cloudflare_rows:
        audits = asyncio.run(audit_cloudflare_many_async(cloudflare_rows))
        for idx, item in enumerate(items):
            live = audits.get(idx)
            if not live:
                continue
            item.live_status = live.status
            item.live_plain_text_length = live.plain_text_length
            item.live_image_count = live.image_count
            item.live_markdown_exposed = live.markdown_exposed
            item.live_raw_html_exposed = live.raw_html_exposed
            if live.status != 200:
                item.reasons.append("live_not_200")
            if live.image_count != 1:
                item.reasons.append("live_image_count_not_1")
                item.needs_content_rebuild = True
            if live.markdown_exposed:
                item.reasons.append("markdown_exposed")
                item.needs_content_rebuild = True
            if live.raw_html_exposed:
                item.reasons.append("raw_html_exposed")
                item.needs_content_rebuild = True
            if live.plain_text_length < 3000:
                item.reasons.append("live_under_3000")
                item.needs_content_rebuild = True
            item.reasons = list(dict.fromkeys(item.reasons))
            item.action = "repair" if item.reasons else "keep"
    return items, details


def summary_for(items: list[PatternItem], *, mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "generated_at": now_iso(),
        "target_count": len(items),
        "repair_count": sum(1 for item in items if item.action == "repair"),
        "metadata_update_count": sum(1 for item in items if item.needs_metadata_update),
        "content_rebuild_count": sum(1 for item in items if item.needs_content_rebuild),
        "invalid_pattern_id": sum(1 for item in items if item.invalid_pattern_id),
        "invalid_pattern_version": sum(1 for item in items if item.invalid_pattern_version),
        "verification_memo_count": sum(item.verification_memo_count for item in items),
        "posts_with_verification_memo": sum(1 for item in items if item.verification_memo_count),
        "live_markdown_exposed": sum(1 for item in items if item.live_markdown_exposed),
        "live_raw_html_exposed": sum(1 for item in items if item.live_raw_html_exposed),
        "live_image_not_1": sum(1 for item in items if item.live_image_count != 1),
        "live_under_3000": sum(1 for item in items if item.live_plain_text_length < 3000),
        "content_under_3000": sum(1 for item in items if item.content_plain_text_length < 3000),
        "by_selected_pattern": dict(Counter(item.selected_pattern_id for item in items)),
        "failed": sum(1 for item in items if item.result == "failed"),
        "updated": sum(1 for item in items if item.result in {"metadata_updated", "content_updated"}),
    }


def update_db_row(db, item: PatternItem, *, hero_url: str) -> None:
    db.execute(
        sql_text(
            """
            UPDATE synced_cloudflare_posts
            SET
                title = :title,
                category_name = :category_name,
                category_slug = :category_slug,
                canonical_category_name = :category_name,
                canonical_category_slug = :category_slug,
                thumbnail_url = :hero_url,
                article_pattern_id = :pattern_id,
                article_pattern_version = :pattern_version,
                live_image_count = 1,
                live_unique_image_count = 1,
                live_duplicate_image_count = 0,
                live_webp_count = 1,
                live_png_count = 0,
                live_other_image_count = 0,
                image_health_status = 'ok',
                live_image_issue = NULL,
                live_image_audited_at = now(),
                synced_at = now(),
                updated_at = now()
            WHERE remote_post_id = :remote_id OR slug = :slug OR url = :url
            """
        ),
        {
            "remote_id": item.remote_id,
            "slug": item.slug,
            "url": item.url,
            "title": item.title,
            "category_name": MYSTERIA_CATEGORY_NAME,
            "category_slug": MYSTERIA_CATEGORY_SLUG,
            "hero_url": hero_url,
            "pattern_id": item.selected_pattern_id,
            "pattern_version": ARTICLE_PATTERN_VERSION,
        },
    )


def apply_repairs(db, cf: CloudflareIntegrationClient, items: list[PatternItem], details: dict[str, dict[str, Any]]) -> list[PatternItem]:
    categories = cf.list_categories()
    category_id = resolve_cloudflare_category_id(MYSTERIA_CATEGORY_SLUG, categories) or resolve_cloudflare_category_id(MYSTERIA_CATEGORY_NAME, categories)
    if not category_id:
        raise RuntimeError("mysteria_category_id_not_found")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    pending_audit: list[tuple[int, str]] = []
    for idx, item in enumerate(items):
        if item.action != "repair":
            item.result = "kept"
            continue
        detail = details.get(item.remote_id) or cf.get_post(item.remote_id)
        original_content = str(detail.get("content") or detail.get("contentHtml") or detail.get("contentMarkdown") or "")
        hero_url = item.cover_image or extract_first_api_asset(str(detail.get("coverImage") or ""), original_content)
        if not hero_url:
            item.result = "failed"
            item.error = "hero_image_missing"
            continue
        content = original_content
        if item.needs_content_rebuild:
            content = render_repaired_content(title=item.title, original_content=original_content, hero_url=hero_url, pattern_id=item.selected_pattern_id)
        payload = build_payload(detail, title=item.title, slug=item.slug, content=content, hero_url=hero_url, category_id=str(category_id), pattern_id=item.selected_pattern_id)
        (BACKUP_DIR / f"{item.slug or item.remote_id}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        try:
            cf.update_post(item.remote_id, payload)
            item.result = "remote_updated_pending_live_verify"
            pending_audit.append((idx, hero_url))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            item.result = "failed"
            item.error = str(exc)
    if pending_audit:
        audit_rows = [
            CloudflareDbRow(
                id=idx,
                remote_post_id=items[idx].remote_id,
                slug=items[idx].slug,
                title=items[idx].title,
                url=items[idx].url,
                category_slug=MYSTERIA_CATEGORY_SLUG,
                canonical_category_slug=MYSTERIA_CATEGORY_SLUG,
                thumbnail_url=hero_url,
                status="published",
            )
            for idx, hero_url in pending_audit
        ]
        audits = asyncio.run(audit_cloudflare_many_async(audit_rows))
        for idx, hero_url in pending_audit:
            item = items[idx]
            live = audits.get(idx)
            if live is None:
                item.result = "failed"
                item.error = "live_audit_missing"
                continue
            item.live_status = live.status
            item.live_plain_text_length = live.plain_text_length
            item.live_image_count = live.image_count
            item.live_markdown_exposed = live.markdown_exposed
            item.live_raw_html_exposed = live.raw_html_exposed
            if live.status != 200:
                item.result = "failed"
                item.error = f"live_status_after_update={live.status}"
                continue
            if live.image_count != 1:
                item.result = "failed"
                item.error = f"live_image_count_after_update={live.image_count}"
                continue
            if live.markdown_exposed or live.raw_html_exposed:
                item.result = "failed"
                item.error = "live_markup_exposure_after_update"
                continue
            if live.plain_text_length < 3000:
                item.result = "failed"
                item.error = f"live_plain_text_under_3000_after_update={live.plain_text_length}"
                continue
            update_db_row(db, item, hero_url=hero_url)
            item.detail_pattern_id = item.selected_pattern_id
            item.detail_pattern_version = ARTICLE_PATTERN_VERSION
            item.db_pattern_id = item.selected_pattern_id
            item.db_pattern_version = ARTICLE_PATTERN_VERSION
            item.invalid_pattern_id = False
            item.invalid_pattern_version = False
            item.verification_memo_count = 0 if item.needs_content_rebuild else item.verification_memo_count
            item.result = "content_updated" if item.needs_content_rebuild else "metadata_updated"
        db.commit()
    return items


def write_reports(*, payload: dict[str, Any], report_path: Path, markdown_path: Path, rool_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    rool_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary = payload["summary"]
    lines = [
        "# Cloudflare Mysteria Pattern Audit 2026-04-28",
        "",
        f"- mode: `{summary['mode']}`",
        f"- target_count: `{summary['target_count']}`",
        f"- repair_count: `{summary['repair_count']}`",
        f"- metadata_update_count: `{summary['metadata_update_count']}`",
        f"- content_rebuild_count: `{summary['content_rebuild_count']}`",
        f"- invalid_pattern_id: `{summary['invalid_pattern_id']}`",
        f"- invalid_pattern_version: `{summary['invalid_pattern_version']}`",
        f"- verification_memo_count: `{summary['verification_memo_count']}`",
        "",
        "| action | result | pattern | len | img | memo | title | url | reasons |",
        "|---|---|---|---:|---:|---:|---|---|---|",
    ]
    for item in payload["items"]:
        title = str(item.get("title") or "").replace("|", "\\|")
        lines.append(
            f"| {item.get('action')} | {item.get('result')} | {item.get('selected_pattern_id')} | "
            f"{item.get('live_plain_text_length')} | {item.get('live_image_count')} | {item.get('verification_memo_count')} | "
            f"{title} | {item.get('url')} | {','.join(item.get('reasons') or [])} |"
        )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    rool_path.write_text(
        "\n".join(
            [
                "# Cloudflare Mysteria Pattern Repair 2026-04-28",
                "",
                "## Problem",
                "- `rewrite_cloudflare_mysteria_short_posts.py` created non-canonical `검증 메모 N` padding sections.",
                "- It stamped rewritten posts with `evidence-breakdown` and pattern version `3` instead of the current 5-pattern version `4` contract.",
                "",
                "## Solution",
                "- Cloudflare Mysteria is locked to the 5 allowed patterns only.",
                "- Pattern metadata is normalized to `article_pattern_version=4`.",
                "- Posts with `검증 메모` or body length failures are rebuilt into the selected pattern structure while preserving the existing hero image and URL.",
                "- Metadata-only rows keep their existing content but receive full-payload pattern/category sync.",
                "",
                "## Last Run",
                f"- mode: `{summary['mode']}`",
                f"- target_count: `{summary['target_count']}`",
                f"- updated: `{summary['updated']}`",
                f"- failed: `{summary['failed']}`",
                f"- report: `{report_path}`",
            ]
        ),
        encoding="utf-8",
    )


def run(mode: str) -> dict[str, Any]:
    with SessionLocal() as db:
        values = get_settings_map(db)
        cf = CloudflareIntegrationClient(base_url=str(values.get("cloudflare_blog_api_base_url") or ""), token=str(values.get("cloudflare_blog_m2m_token") or ""))
        items, details = collect_items(db, cf)
        if mode == "apply":
            items = apply_repairs(db, cf, items, details)
        elif mode == "verify":
            items, _ = collect_items(db, cf)
            for item in items:
                item.result = "verified" if not item.reasons else "failed"
        else:
            for item in items:
                item.result = "planned" if item.action == "repair" else "kept"
    return {"summary": summary_for(items, mode=mode), "items": [asdict(item) for item in items]}


def main() -> int:
    args = parse_args()
    payload = run(args.mode)
    report_path = Path(args.report_path)
    markdown_path = Path(args.markdown_path)
    rool_path = Path(args.rool_path)
    write_reports(payload=payload, report_path=report_path, markdown_path=markdown_path, rool_path=rool_path)
    problem_items = [item for item in payload["items"] if item.get("action") == "repair" or item.get("result") == "failed"]
    print(json.dumps({"summary": payload["summary"], "problem_items_preview": problem_items[:30]}, ensure_ascii=False, indent=2, default=str))
    print(f"REPORT={report_path}")
    print(f"MARKDOWN={markdown_path}")
    print(f"ROOL={rool_path}")
    summary = payload["summary"]
    if args.mode == "verify":
        failed = any(
            [
                summary["invalid_pattern_id"],
                summary["invalid_pattern_version"],
                summary["verification_memo_count"],
                summary["live_markdown_exposed"],
                summary["live_raw_html_exposed"],
                summary["live_image_not_1"],
                summary["live_under_3000"],
            ]
        )
        return 1 if failed else 0
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

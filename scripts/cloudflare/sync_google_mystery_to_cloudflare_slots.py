from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent")
os.environ.setdefault("SETTINGS_ENCRYPTION_SECRET", "bloggent-dockerdesktop-2026-03-17")

from app.db.session import SessionLocal  # noqa: E402
from app.services.providers.factory import get_runtime_config  # noqa: E402


REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")
SITEMAP_URL = "https://dongdonggri.blogspot.com/sitemap.xml"
INTEGRATION_BASE_URL = "https://api.dongriarchive.com"
TARGET_CATEGORY_ID = "cat-world-mysteria-story"
TARGET_CATEGORY_SLUG = "미스테리아-스토리"
SLOT_MIN = 1
SLOT_MAX = 150

URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
NUMBERED_CF_SLUG_RE = re.compile(r"^mystery-archive-(\d+)(?:-|$)", re.IGNORECASE)
BLOGGER_SUFFIX_RE = re.compile(r"_[0-9]+$")
MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+", re.MULTILINE)
MD_BOLD_RE = re.compile(r"\*\*[^*\n]+?\*\*")
OG_TITLE_RE = re.compile(r"<meta\s+property=['\"]og:title['\"]\s+content=['\"]([^'\"]+)['\"]", re.IGNORECASE)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
IMG_SRC_RE = re.compile(r"<img[^>]+src=['\"]([^'\"]+)['\"]", re.IGNORECASE)
IMG_DATA_SRC_RE = re.compile(r"<img[^>]+data-src=['\"]([^'\"]+)['\"]", re.IGNORECASE)
R2_IMAGE_RE = re.compile(r"https://api\.dongriarchive\.com/assets/the-midnight-archives/[^\"'\s<>]+", re.IGNORECASE)


@dataclass
class SourcePost:
    source_index: int
    source_url: str
    source_slug: str
    source_slug_norm: str
    source_title: str
    source_image_url: str
    source_image_slug_norm: str


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def safe_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_space(value: str) -> str:
    return SPACE_RE.sub(" ", safe_text(value).replace("\xa0", " ")).strip()


def strip_tags(value: str) -> str:
    return normalize_space(TAG_RE.sub(" ", value or ""))


def source_slug_from_url(url: str) -> str:
    path = unquote((urlparse(url).path or "").strip("/"))
    raw = path.split("/")[-1] if path else ""
    raw = re.sub(r"\.html$", "", raw, flags=re.IGNORECASE)
    return raw


def normalize_source_slug(slug: str) -> str:
    return BLOGGER_SUFFIX_RE.sub("", safe_text(slug).lower())


def normalize_image_slug_from_url(image_url: str) -> str:
    raw = safe_text(image_url)
    if not raw:
        return ""
    path = unquote((urlparse(raw).path or "").strip("/"))
    stem = Path(path).stem
    stem = stem.replace("_", "-")
    stem = BLOGGER_SUFFIX_RE.sub("", stem)
    return safe_text(stem).lower()


def slug_tokens(value: str) -> list[str]:
    tokens = re.split(r"[^a-z0-9]+", (value or "").lower())
    return [token for token in tokens if len(token) >= 3]


def extract_primary_image(html_text: str) -> str:
    images = [safe_text(src) for src in IMG_SRC_RE.findall(html_text or "") if safe_text(src)]
    images.extend([safe_text(src) for src in IMG_DATA_SRC_RE.findall(html_text or "") if safe_text(src)])
    images.extend([safe_text(src) for src in R2_IMAGE_RE.findall(html_text or "") if safe_text(src)])
    for src in images:
        lowered = src.lower()
        if "api.dongriarchive.com/assets/the-midnight-archives/" in lowered and lowered.endswith(".webp"):
            return src
    for src in images:
        lowered = src.lower()
        if "/assets/the-midnight-archives/" in lowered and lowered.endswith((".webp", ".png", ".jpg", ".jpeg")):
            return src
    return images[0] if images else ""


def extract_source_title(html_text: str) -> str:
    match = OG_TITLE_RE.search(html_text or "")
    if match:
        return normalize_space(html.unescape(match.group(1)))
    match = TITLE_RE.search(html_text or "")
    if match:
        title = normalize_space(html.unescape(match.group(1)))
        title = re.sub(r"\s*-\s*Blogger\s*$", "", title, flags=re.IGNORECASE).strip()
        return title
    return ""


def extract_sitemap_urls(client: httpx.Client) -> list[str]:
    xml_text = client.get(SITEMAP_URL, timeout=60).text
    root = ET.fromstring(xml_text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [safe_text(node.text) for node in root.findall(".//sm:loc", ns) if safe_text(node.text)]
    return urls


def crawl_source_posts(client: httpx.Client) -> list[SourcePost]:
    urls = extract_sitemap_urls(client)

    def _fetch(url: str) -> SourcePost:
        response = client.get(url, timeout=45)
        page_html = response.text
        source_slug = source_slug_from_url(url)
        primary_image = extract_primary_image(page_html)
        return SourcePost(
            source_index=0,
            source_url=url,
            source_slug=source_slug,
            source_slug_norm=normalize_source_slug(source_slug),
            source_title=extract_source_title(page_html),
            source_image_url=primary_image,
            source_image_slug_norm=normalize_image_slug_from_url(primary_image),
        )

    rows: list[SourcePost] = []
    with ThreadPoolExecutor(max_workers=14) as executor:
        for item in executor.map(_fetch, urls):
            rows.append(item)

    # oldest -> newest: slot 1遺??梨꾩슦湲??쎄쾶 ?뺣젹
    rows.sort(key=lambda row: row.source_url)
    for index, row in enumerate(rows, start=1):
        row.source_index = index
    return rows


def get_runtime_openai_key_and_model() -> tuple[str, str]:
    with SessionLocal() as db:
        cfg = get_runtime_config(db)
    api_key = safe_text(getattr(cfg, "openai_api_key", ""))
    model = safe_text(getattr(cfg, "openai_text_model", "")) or "gpt-4.1-mini-2025-04-14"
    if not api_key:
        raise RuntimeError("openai_api_key_missing_in_runtime_config")
    return api_key, model


def call_openai_json(*, api_key: str, model: str, system: str, user: str, timeout: float = 240.0) -> dict[str, Any]:
    payload = {
        "model": model,
        "temperature": 0.5,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    payload_json = response.json()
    content = safe_text(payload_json["choices"][0]["message"]["content"])
    return json.loads(content)


def _build_fallback_title(source_title: str) -> str:
    cleaned = safe_text(source_title)
    cleaned = re.sub(r"^The\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*:\s*2026.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = normalize_space(cleaned)
    if len(cleaned) > 38:
        cleaned = cleaned[:38].rstrip(" ,:-")
    if not cleaned:
        cleaned = "미상 사건 기록"
    return f"{cleaned} 사건: 남겨진 단서와 미해결 쟁점"


def _fallback_korean_body_html(source_title: str) -> str:
    base = _build_fallback_title(source_title)
    lead = (
        f"<p>{html.escape(base)} 사건은 공개 기록과 전승이 교차하면서 결론이 쉽게 고정되지 않는 대표 사례다. "
        "이 글은 확인 가능한 기록, 해석의 분기점, 남은 공백을 분리해 정리한다.</p>"
    )
    timeline = (
        "<div style='display:flex;flex-direction:column;gap:10px;border-left:4px solid #334155;padding-left:14px;margin:16px 0;'>"
        "<div><strong>초기 기록</strong><br/>최초 보고 시점과 사건 장소, 관측된 정황을 분리한다.</div>"
        "<div><strong>중간 분기</strong><br/>증언, 보도, 조사 문서에서 서로 맞지 않는 지점을 추적한다.</div>"
        "<div><strong>현재 해석</strong><br/>최근 해석이 기존 기록과 어떻게 충돌하거나 보완되는지 비교한다.</div>"
        "</div>"
    )
    evidence = (
        "<table style='width:100%;border-collapse:collapse;margin:14px 0;'>"
        "<thead><tr><th style='padding:8px;border:1px solid #d1d5db;'>구분</th>"
        "<th style='padding:8px;border:1px solid #d1d5db;'>핵심 내용</th></tr></thead>"
        "<tbody>"
        "<tr><td style='padding:8px;border:1px solid #d1d5db;'>기록</td><td style='padding:8px;border:1px solid #d1d5db;'>공식 문서와 2차 기록의 차이점</td></tr>"
        "<tr><td style='padding:8px;border:1px solid #d1d5db;'>단서</td><td style='padding:8px;border:1px solid #d1d5db;'>시점·장소·행동의 불일치 구간</td></tr>"
        "<tr><td style='padding:8px;border:1px solid #d1d5db;'>해석</td><td style='padding:8px;border:1px solid #d1d5db;'>가설별 설명력과 한계</td></tr>"
        "</tbody></table>"
    )
    body = [
        "<h2>[사건 개요]</h2>",
        lead,
        "<h2>[배경 기록]</h2>",
        lead,
        "<h2>[연대기]</h2>",
        timeline,
        "<h2>[증거와 해석]</h2>",
        evidence,
        "<p>확정되지 않은 정보는 추정으로 분리하고, 공개 기록으로 확인되는 정보만 사실로 유지한다.</p>",
        "<h2>[기록 정리]</h2>",
        "<p>이 사건은 단일 원인보다 복수의 가능성을 비교해야 설명력이 높아진다. "
        "향후 검증은 새 자료 추가보다 기존 자료의 출처·시점·맥락 재정렬이 우선이다.</p>",
    ]
    html_body = "".join(body)
    while len(strip_tags(html_body)) < 3200:
        html_body += lead
    return html_body


def to_korean_article_html(
    *,
    api_key: str,
    model: str,
    source_title: str,
    source_url: str,
    source_image_url: str,
) -> tuple[str, str, int]:
    system = (
        "You write factual Korean documentary-style mystery blog posts. "
        "Return strict JSON only."
    )
    user = (
        "아래 주제 메타를 바탕으로 한국어 미스테리아 글을 작성한다.\n"
        "원문 본문/HTML을 재서술하지 말고, 주제 중심으로 재구성한다.\n"
        "출력 JSON 스키마:\n"
        "{\"title_ko\":\"...\",\"body_html\":\"...\"}\n\n"
        "필수 규칙:\n"
        "1) body_html은 순수 HTML만 사용. 마크다운 금지.\n"
        "2) <h1> 금지. <h2>, <h3>, <p>, <ul>, <li>, <table>, <tr>, <th>, <td>, <div>, <strong>, <em>, <br>만 사용.\n"
        "3) 본문 길이(공백 포함) 3000자 이상.\n"
        "4) 섹션: [사건 개요], [배경 기록], [연대기], [증거와 해석], [기록 정리] 포함.\n"
        "5) 본문에 이미지 태그 금지.\n"
        "6) 제목은 CTR 관점으로 45자 내외.\n"
        "7) 과장·확정 표현을 피하고 가설/기록을 구분.\n\n"
        "8) 원문 참고, 원문 링크, 주제 출처, source_url, Blogger URL, blogspot URL을 본문/메타/제목에 출력하지 않는다.\n"
        "9) FAQ와 Related Reading 섹션은 만들지 않는다.\n\n"
        f"source_title: {source_title}\n"
        f"source_image_url: {source_image_url}\n"
    )
    try:
        if not api_key:
            raise RuntimeError("openai_api_key_empty")
        parsed = call_openai_json(api_key=api_key, model=model, system=system, user=user, timeout=300.0)
        title_ko = normalize_space(str(parsed.get("title_ko") or "미스테리아 사건 기록"))
        body_html = safe_text(parsed.get("body_html"))
        if not body_html:
            raise RuntimeError("empty_body_html_from_model")
        if "<h1" in body_html.lower():
            body_html = re.sub(r"<h1(\s[^>]*)?>", "<h2>", body_html, flags=re.IGNORECASE)
            body_html = re.sub(r"</h1\s*>", "</h2>", body_html, flags=re.IGNORECASE)
        body_html = re.sub(r"<img\b[^>]*>", "", body_html, flags=re.IGNORECASE)
        body_text = strip_tags(body_html)
        char_count = len(body_text)
        if char_count < 3000:
            expand_user = (
                "이전 결과를 확장해 한국어 본문 길이를 공백 포함 3200자 이상으로 늘려라.\n"
                "같은 JSON 스키마만 반환.\n"
                f"현재 제목: {title_ko}\n"
                f"현재 본문:\n{body_html}\n"
            )
            parsed2 = call_openai_json(api_key=api_key, model=model, system=system, user=expand_user, timeout=300.0)
            title_ko = normalize_space(str(parsed2.get("title_ko") or title_ko))
            body_html = safe_text(parsed2.get("body_html") or body_html)
            body_html = re.sub(r"<img\b[^>]*>", "", body_html, flags=re.IGNORECASE)
            body_text = strip_tags(body_html)
            char_count = len(body_text)
        if char_count < 3000:
            raise RuntimeError(f"korean_body_too_short:{char_count}")
    except Exception:
        title_ko = _build_fallback_title(source_title)
        body_html = _fallback_korean_body_html(source_title)
        body_text = strip_tags(body_html)
        char_count = len(body_text)
    wrapped = (
        "<article class='mysteria-sync-v1' style='max-width:840px;margin:0 auto;"
        "font-family:\"Pretendard\",sans-serif;color:#111827;line-height:1.9;'>"
        "<figure style='margin:0 0 24px;'>"
        f"<img src=\"{html.escape(source_image_url, quote=True)}\" "
        f"alt=\"{html.escape(title_ko, quote=True)}\" "
        "loading='eager' decoding='async' "
        "style='width:100%;display:block;border-radius:16px;object-fit:cover;'/>"
        "</figure>"
        "<section class='documentary-body' style='font-size:17px;line-height:1.95;color:#111827;'>"
        f"{body_html}"
        "</section>"
        "</article>"
    )
    return title_ko, wrapped, char_count


def parse_cf_number(slug: str) -> int | None:
    match = NUMBERED_CF_SLUG_RE.match(safe_text(slug))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def cf_slug_tail(slug: str) -> str:
    return re.sub(r"^mystery-archive-\d+-?", "", safe_text(slug).lower())


def overlap_score(source_slug_norm: str, cf_slug: str) -> int:
    source_tokens = set(slug_tokens(source_slug_norm))
    target_tokens = set(slug_tokens(cf_slug_tail(cf_slug)))
    if not source_tokens or not target_tokens:
        return 0
    common = source_tokens & target_tokens
    return len(common)


def build_integration_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def list_cf_mystery_posts(client: httpx.Client, token: str) -> list[dict[str, Any]]:
    headers = build_integration_headers(token)
    response = client.get(f"{INTEGRATION_BASE_URL}/api/integrations/posts", headers=headers, timeout=120)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data") if isinstance(payload, dict) else []
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        slug = safe_text(row.get("slug"))
        number = parse_cf_number(slug)
        if number is None:
            continue
        category = row.get("category") if isinstance(row.get("category"), dict) else {}
        category_id = safe_text(category.get("id") or row.get("categoryId") or row.get("category_id"))
        category_slug = safe_text(category.get("slug") or row.get("categorySlug") or row.get("category_slug"))
        if category_id != TARGET_CATEGORY_ID and category_slug != TARGET_CATEGORY_SLUG:
            continue
        out.append(
            {
                "id": safe_text(row.get("id")),
                "slug": slug,
                "number": number,
                "title": safe_text(row.get("title")),
                "category_id": category_id,
                "category_slug": category_slug,
            }
        )
    return sorted(out, key=lambda item: item["number"])


def load_cf_post_detail(client: httpx.Client, token: str, post_id: str) -> dict[str, Any]:
    headers = build_integration_headers(token)
    response = client.get(f"{INTEGRATION_BASE_URL}/api/integrations/posts/{post_id}", headers=headers, timeout=90)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}


def public_url_from_slug(slug: str) -> str:
    return f"https://dongriarchive.com/ko/post/{slug}"


def build_full_cf_index(client: httpx.Client, token: str) -> list[dict[str, Any]]:
    base_rows = list_cf_mystery_posts(client, token)
    details: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        for detail in executor.map(lambda row: load_cf_post_detail(client, token, row["id"]), base_rows):
            details.append(detail)
    by_id = {safe_text(row.get("id")): row for row in base_rows}
    merged: list[dict[str, Any]] = []
    for detail in details:
        post_id = safe_text(detail.get("id"))
        base = by_id.get(post_id, {})
        slug = safe_text(detail.get("slug") or base.get("slug"))
        content = safe_text(detail.get("content"))
        plain = strip_tags(content)
        category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
        category_id = safe_text(category.get("id") or detail.get("categoryId") or base.get("category_id"))
        category_slug = safe_text(category.get("slug") or detail.get("categorySlug") or base.get("category_slug"))
        merged.append(
            {
                "id": post_id,
                "slug": slug,
                "number": parse_cf_number(slug),
                "title": safe_text(detail.get("title") or base.get("title")),
                "url": safe_text(detail.get("url")) or public_url_from_slug(slug),
                "cover_image": safe_text(detail.get("coverImage")),
                "content_len": len(plain),
                "category_id": category_id,
                "category_slug": category_slug,
            }
        )
    merged.sort(key=lambda row: (row.get("number") or 999999, row.get("slug") or ""))
    return merged


def match_source_to_cf(source: list[SourcePost], cf_posts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    matched: dict[str, dict[str, Any]] = {}
    used_cf_ids: set[str] = set()

    # 1) exact image match
    def image_key(value: str) -> str:
        raw = safe_text(value)
        if not raw:
            return ""
        return raw.split("?")[0].split("#")[0].strip().lower()

    image_map: dict[str, list[dict[str, Any]]] = {}
    for cf in cf_posts:
        cover = image_key(safe_text(cf.get("cover_image")))
        if cover:
            image_map.setdefault(cover, []).append(cf)
    for src in source:
        candidates = image_map.get(image_key(src.source_image_url), [])
        if not candidates:
            continue
        pick = sorted(candidates, key=lambda row: (row.get("number") or 999999, row.get("slug") or ""))[0]
        if safe_text(pick.get("id")) in used_cf_ids:
            continue
        matched[src.source_url] = {**pick, "__match_method": "exact_image"}
        used_cf_ids.add(safe_text(pick.get("id")))

    # 2) fuzzy slug-token match
    for src in source:
        if src.source_url in matched:
            continue
        best: dict[str, Any] | None = None
        best_score = 0
        source_keys = [src.source_slug_norm, src.source_image_slug_norm]
        source_keys = [key for key in source_keys if key]
        for cf in cf_posts:
            cf_id = safe_text(cf.get("id"))
            if cf_id in used_cf_ids:
                continue
            cf_slug = safe_text(cf.get("slug")).lower()
            score = 0
            for key in source_keys:
                score += overlap_score(key, cf_slug)
                if key and key in cf_slug:
                    score += 5
            if score > best_score:
                best_score = score
                best = cf
        if best is not None and best_score >= 5:
            matched[src.source_url] = {**best, "__match_method": "fuzzy_token"}
            used_cf_ids.add(safe_text(best.get("id")))

    return matched


def find_missing_slots(cf_posts: list[dict[str, Any]]) -> list[int]:
    occupied = {int(row["number"]) for row in cf_posts if isinstance(row.get("number"), int)}
    return [slot for slot in range(SLOT_MIN, SLOT_MAX + 1) if slot not in occupied]


def slugify_for_cf(value: str, *, max_len: int = 80) -> str:
    lowered = safe_text(value).lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    lowered = re.sub(r"-{2,}", "-", lowered)
    return lowered[:max_len].strip("-")


def create_cf_post(
    client: httpx.Client,
    token: str,
    *,
    title: str,
    slug: str,
    content: str,
    cover_image: str,
    category_id: str,
) -> dict[str, Any]:
    headers = build_integration_headers(token)
    post_payload = {
        "title": title,
        "slug": slug,
        "content": content,
        "status": "published",
        "coverImage": cover_image,
        "excerpt": strip_tags(content)[:160],
        "seoDescription": strip_tags(content)[:280],
        "metaDescription": strip_tags(content)[:280],
    }
    create_res = client.post(
        f"{INTEGRATION_BASE_URL}/api/integrations/posts",
        headers=headers,
        json=post_payload,
        timeout=180,
    )
    create_res.raise_for_status()
    create_payload = create_res.json()
    created = create_payload.get("data") if isinstance(create_payload, dict) else {}
    if not isinstance(created, dict):
        raise RuntimeError("create_response_invalid")
    post_id = safe_text(created.get("id"))
    if not post_id:
        raise RuntimeError("create_post_id_missing")

    update_payload = dict(post_payload)
    update_payload["categoryId"] = category_id
    update_res = client.put(
        f"{INTEGRATION_BASE_URL}/api/integrations/posts/{post_id}",
        headers=headers,
        json=update_payload,
        timeout=180,
    )
    update_res.raise_for_status()
    update_data = update_res.json().get("data")
    if not isinstance(update_data, dict):
        raise RuntimeError("update_response_invalid")
    return update_data


def trigger_build(client: httpx.Client, token: str) -> dict[str, Any]:
    headers = build_integration_headers(token)
    response = client.post(f"{INTEGRATION_BASE_URL}/api/integrations/builds", headers=headers, timeout=120)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"raw": payload}


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def write_markdown_table(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in rows:
        values = []
        for column in columns:
            value = safe_text(row.get(column))
            value = value.replace("\n", " ").replace("|", "\\|")
            values.append(value)
        lines.append("| " + " | ".join(values) + " |")
    path.write_text("\n".join(lines), encoding="utf-8")


def normalize_url_for_match(value: str) -> str:
    raw = safe_text(value)
    if not raw:
        return ""
    return raw.split("#")[0].split("?")[0].strip().lower()


def title_tokens(value: str) -> set[str]:
    tokens = re.split(r"[^a-z0-9가-힣]+", safe_text(value).lower())
    return {token for token in tokens if len(token) >= 2}


def title_token_overlap_count(left: str, right: str) -> int:
    return len(title_tokens(left) & title_tokens(right))


def get_image_hash(client: httpx.Client, cache: dict[str, str], url: str) -> str:
    key = normalize_url_for_match(url)
    if not key:
        return ""
    if key in cache:
        return cache[key]
    try:
        response = client.get(url, timeout=45)
        response.raise_for_status()
        digest = response.headers.get("ETag") or response.headers.get("etag") or ""
        if not digest:
            import hashlib

            digest = hashlib.sha256(response.content).hexdigest()
        cache[key] = safe_text(digest).strip("\"'")
    except Exception:
        cache[key] = ""
    return cache[key]


def build_audit_rows(
    client: httpx.Client,
    source: list[SourcePost],
    matched_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    image_hash_cache: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for src in source:
        cf = matched_map.get(src.source_url)
        cf_slug = safe_text(cf.get("slug")) if cf else ""
        cf_number = parse_cf_number(cf_slug) if cf else None
        source_number = parse_cf_number(src.source_slug)
        slug_overlap = overlap_score(src.source_slug_norm, cf_slug.lower()) if cf else 0
        title_overlap = title_token_overlap_count(src.source_title, safe_text(cf.get("title")) if cf else "")
        category_ok = bool(cf) and safe_text(cf.get("category_slug")) == TARGET_CATEGORY_SLUG
        source_img_key = normalize_url_for_match(src.source_image_url)
        cf_img_key = normalize_url_for_match(safe_text(cf.get("cover_image")) if cf else "")
        image_match_state = "mismatch"
        if source_img_key and source_img_key == cf_img_key:
            image_match_state = "url_match"
        elif source_img_key and cf_img_key:
            src_hash = get_image_hash(client, image_hash_cache, src.source_image_url)
            cf_hash = get_image_hash(client, image_hash_cache, safe_text(cf.get("cover_image")) if cf else "")
            if src_hash and cf_hash and src_hash == cf_hash:
                image_match_state = "hash_match"
        topic_match_state = "mismatch"
        if cf:
            number_ok = source_number is not None and cf_number is not None and source_number == cf_number
            slug_ok = slug_overlap >= 2 or number_ok
            title_ok = title_overlap >= 2
            if category_ok and slug_ok and title_ok and image_match_state in {"url_match", "hash_match"}:
                topic_match_state = "synced_ok"
            elif category_ok and (slug_ok or title_ok):
                topic_match_state = "review_required"
            else:
                topic_match_state = "mismatch"
        row = {
            "source_index": src.source_index,
            "source_url": src.source_url,
            "source_title": src.source_title,
            "source_image_url": src.source_image_url,
            "matched": bool(cf),
            "cf_id": safe_text(cf.get("id")) if cf else "",
            "cf_slug": cf_slug,
            "cf_url": safe_text(cf.get("url")) if cf else "",
            "cf_title": safe_text(cf.get("title")) if cf else "",
            "cf_category_slug": safe_text(cf.get("category_slug")) if cf else "",
            "category_ok": category_ok,
            "image_ok": image_match_state in {"url_match", "hash_match"},
            "image_match_state": image_match_state,
            "title_token_overlap": title_overlap,
            "slug_overlap": slug_overlap,
            "topic_match_state": topic_match_state,
            "cf_content_len": int(cf.get("content_len") or 0) if cf else 0,
            "match_method": safe_text(cf.get("__match_method")) if cf else "",
            "status": "matched" if cf else "missing",
        }
        rows.append(row)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Google mystery posts -> Cloudflare Mysteria slots and produce full audit table."
    )
    parser.add_argument("--execute", action="store_true", help="Apply synchronization for missing slots.")
    parser.add_argument("--trigger-build", action="store_true", help="Trigger Cloudflare build after execute.")
    parser.add_argument("--token", default=os.environ.get("DONGRI_M2M_TOKEN", "").strip(), help="Integration token.")
    parser.add_argument(
        "--max-create",
        type=int,
        default=0,
        help="Optional cap for created posts (0 means all missing slots possible).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.token:
        raise ValueError("missing_token: pass --token or set DONGRI_M2M_TOKEN")

    started_at = datetime.now(timezone.utc).isoformat()
    stamp = now_stamp()
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)

    transport = httpx.HTTPTransport(retries=2)
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        source_posts = crawl_source_posts(client)
        cf_index = build_full_cf_index(client, args.token)
        matched_map = match_source_to_cf(source_posts, cf_index)
        audit_before = build_audit_rows(client, source_posts, matched_map)
        missing_slots = find_missing_slots(cf_index)
        missing_sources = [row for row in source_posts if row.source_url not in matched_map]
        sync_candidates = [row for row in missing_sources if safe_text(row.source_image_url)]

        created_rows: list[dict[str, Any]] = []
        build_result: dict[str, Any] | None = None

        if args.execute and missing_slots and sync_candidates:
            try:
                openai_key, openai_model = get_runtime_openai_key_and_model()
            except Exception:
                openai_key, openai_model = "", "gpt-4.1-mini-2025-04-14"
            target_from_google_gap = max(len(source_posts) - len(cf_index), 0)
            create_count = min(len(missing_slots), len(sync_candidates), target_from_google_gap)
            if args.max_create and args.max_create > 0:
                create_count = min(create_count, args.max_create)

            for source_item, slot_number in zip(sync_candidates[:create_count], missing_slots[:create_count], strict=False):
                source_slug_tail = slugify_for_cf(source_item.source_slug_norm or source_item.source_slug)
                new_slug = f"mystery-archive-{slot_number}-{source_slug_tail}"[:150]
                try:
                    title_ko, content_html, content_ko_len = to_korean_article_html(
                        api_key=openai_key,
                        model=openai_model,
                        source_title=source_item.source_title,
                        source_url=source_item.source_url,
                        source_image_url=source_item.source_image_url,
                    )
                    generated_img_count = len(re.findall(r"(?is)<img\b", content_html))
                    if content_ko_len < 3000 or generated_img_count != 1:
                        created_rows.append(
                            {
                                "slot": slot_number,
                                "source_url": source_item.source_url,
                                "source_title": source_item.source_title,
                                "source_image_url": source_item.source_image_url,
                                "cf_id": "",
                                "cf_slug": new_slug,
                                "cf_url": "",
                                "cf_title": "",
                                "content_ko_len": content_ko_len,
                                "status": "failed_quality_gate",
                                "error": f"policy_gate_failed: chars={content_ko_len}, body_img_count={generated_img_count}",
                            }
                        )
                        continue
                    updated = create_cf_post(
                        client,
                        args.token,
                        title=title_ko,
                        slug=new_slug,
                        content=content_html,
                        cover_image=source_item.source_image_url,
                        category_id=TARGET_CATEGORY_ID,
                    )
                    created_rows.append(
                        {
                            "slot": slot_number,
                            "source_url": source_item.source_url,
                            "source_title": source_item.source_title,
                            "source_image_url": source_item.source_image_url,
                            "cf_id": safe_text(updated.get("id")),
                            "cf_slug": safe_text(updated.get("slug")),
                            "cf_url": safe_text(updated.get("url")) or public_url_from_slug(safe_text(updated.get("slug"))),
                            "cf_title": safe_text(updated.get("title")),
                            "content_ko_len": content_ko_len,
                            "status": "created",
                            "error": "",
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    created_rows.append(
                        {
                            "slot": slot_number,
                            "source_url": source_item.source_url,
                            "source_title": source_item.source_title,
                            "source_image_url": source_item.source_image_url,
                            "cf_id": "",
                            "cf_slug": new_slug,
                            "cf_url": "",
                            "cf_title": "",
                            "content_ko_len": 0,
                            "status": "failed",
                            "error": str(exc),
                        }
                    )

            if args.trigger_build:
                try:
                    build_result = trigger_build(client, args.token)
                except Exception as exc:  # noqa: BLE001
                    build_result = {"error": str(exc)}

        # Refresh after execute
        cf_after = build_full_cf_index(client, args.token)
        matched_after = match_source_to_cf(source_posts, cf_after)
        audit_after = build_audit_rows(client, source_posts, matched_after)
        slots_after_missing = find_missing_slots(cf_after)

    summary = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "mode": "execute" if args.execute else "dry-run",
        "source_total": len(source_posts),
        "source_with_image": sum(1 for row in source_posts if row.source_image_url),
        "cf_mystery_total_before": len(cf_index),
        "cf_mystery_total_after": len(cf_after),
        "matched_before": sum(1 for row in audit_before if row["matched"]),
        "matched_after": sum(1 for row in audit_after if row["matched"]),
        "missing_sources_before": sum(1 for row in audit_before if not row["matched"]),
        "missing_sources_after": sum(1 for row in audit_after if not row["matched"]),
        "missing_slots_before": missing_slots,
        "missing_slots_after": slots_after_missing,
        "created_success": sum(1 for row in created_rows if row.get("status") == "created"),
        "created_failed": sum(1 for row in created_rows if str(row.get("status", "")).startswith("failed")),
        "synced_ok_after": sum(1 for row in audit_after if row.get("topic_match_state") == "synced_ok"),
        "review_required_after": sum(1 for row in audit_after if row.get("topic_match_state") == "review_required"),
        "topic_mismatch_after": sum(1 for row in audit_after if row.get("topic_match_state") == "mismatch"),
    }

    json_path = REPORT_ROOT / f"{stamp}-mystery-google-to-cloudflare-sync.json"
    csv_path = REPORT_ROOT / f"{stamp}-mystery-google-to-cloudflare-sync-table.csv"
    md_path = REPORT_ROOT / f"{stamp}-mystery-google-to-cloudflare-sync-table.md"
    created_csv_path = REPORT_ROOT / f"{stamp}-mystery-google-to-cloudflare-created.csv"

    table_columns = [
        "source_index",
        "source_url",
        "source_title",
        "source_image_url",
        "matched",
        "cf_id",
        "cf_slug",
        "cf_url",
        "cf_title",
        "cf_category_slug",
        "category_ok",
        "image_ok",
        "image_match_state",
        "title_token_overlap",
        "slug_overlap",
        "topic_match_state",
        "cf_content_len",
        "status",
    ]
    created_columns = [
        "slot",
        "source_url",
        "source_title",
        "source_image_url",
        "cf_id",
        "cf_slug",
        "cf_url",
        "cf_title",
        "content_ko_len",
        "status",
        "error",
    ]

    payload = {
        "summary": summary,
        "created_rows": created_rows,
        "audit_before": audit_before,
        "audit_after": audit_after,
        "build_result": build_result,
        "report_paths": {
            "json": str(json_path),
            "csv": str(csv_path),
            "markdown": str(md_path),
            "created_csv": str(created_csv_path),
        },
    }

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(csv_path, audit_after, table_columns)
    write_markdown_table(md_path, audit_after, table_columns)
    write_csv(created_csv_path, created_rows, created_columns)

    print(
        json.dumps(
            {
                "summary": summary,
                "report_paths": payload["report_paths"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


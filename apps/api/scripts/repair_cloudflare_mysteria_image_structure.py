from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString
from playwright.async_api import async_playwright
from sqlalchemy import select

SCRIPT_DIR = Path(__file__).resolve().parent
API_ROOT = SCRIPT_DIR.parent
RUNTIME_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent")
REPORT_PATH = RUNTIME_ROOT / "storage" / "the-midnight-archives" / "cloudflare-mysteria-repair-20260428.json"
MARKDOWN_PATH = RUNTIME_ROOT / "storage" / "the-midnight-archives" / "cloudflare-mysteria-repair-20260428.md"
TARGET_CATEGORY_SLUG = "미스테리아-스토리"
ALLOWED_IMAGE_PREFIX = "https://api.dongriarchive.com/assets/the-midnight-archives/"
RAW_HTML_MARKERS = ("</div>", "</section>", "<div", "<section", "class=", "style=")

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import SyncedCloudflarePost  # noqa: E402
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from package_common import CloudflareIntegrationClient, normalize_space  # noqa: E402


@dataclass(slots=True)
class MysteriaRow:
    remote_post_id: str
    title: str
    url: str
    slug: str
    thumbnail_url: str
    category_slug: str
    canonical_category_slug: str
    article_pattern_id: str
    article_pattern_version: str


@dataclass(slots=True)
class RenderAudit:
    remote_post_id: str
    title: str
    url: str
    status: int | str
    plain_text_length: int
    image_count: int
    h1_count: int
    h2_count: int
    faq_count: int
    raw_html_exposed: bool
    markdown_exposed: bool
    duplicate_sentence_ratio: float
    top_repeated_sentence_count: int
    hero_url: str
    action: str = "none"
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair Cloudflare Mysteria rendered image/markup structure.")
    parser.add_argument("--mode", choices=("dry-run", "apply", "verify"), required=True)
    parser.add_argument("--report-path", default=str(REPORT_PATH))
    parser.add_argument("--markdown-path", default=str(MARKDOWN_PATH))
    return parser.parse_args()


def is_mysteria(row: SyncedCloudflarePost) -> bool:
    return row.status == "published" and (
        row.category_slug == TARGET_CATEGORY_SLUG or row.canonical_category_slug == TARGET_CATEGORY_SLUG
    )


def load_target_rows() -> list[MysteriaRow]:
    with SessionLocal() as db:
        rows = (
            db.execute(
                select(SyncedCloudflarePost)
                .where(SyncedCloudflarePost.status == "published")
                .order_by(SyncedCloudflarePost.published_at.asc().nulls_last(), SyncedCloudflarePost.id.asc())
            )
            .scalars()
            .all()
        )
    targets: list[MysteriaRow] = []
    for row in rows:
        if not is_mysteria(row):
            continue
        targets.append(
            MysteriaRow(
                remote_post_id=str(row.remote_post_id or "").strip(),
                title=str(row.title or "").strip(),
                url=str(row.url or "").strip(),
                slug=str(row.slug or "").strip(),
                thumbnail_url=str(row.thumbnail_url or "").strip(),
                category_slug=str(row.category_slug or "").strip(),
                canonical_category_slug=str(row.canonical_category_slug or "").strip(),
                article_pattern_id=str(row.article_pattern_id or "").strip(),
                article_pattern_version=str(row.article_pattern_version or "").strip(),
            )
        )
    return targets


def is_markdown_exposed(text: str) -> bool:
    if "**" in text:
        return True
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("- ") or stripped.startswith("* "):
            return True
        if len(stripped) > 3 and stripped[0].isdigit() and ". " in stripped[:5]:
            return True
    return False


def is_faq_text(text: str) -> bool:
    lowered = text.lower()
    return "faq" in lowered or "q&a" in lowered or "자주" in text or "질문" in text


def sentence_metrics(text: str) -> tuple[float, int]:
    sentences = [
        re.sub(r"\s+", " ", item.strip().lower())
        for item in re.split(r"(?<=[.!?。！？])\s+", text)
        if len(item.strip()) >= 35
    ]
    if not sentences:
        return 0.0, 0
    counts = Counter(sentences)
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    return round(duplicate_count / len(sentences), 4), max(counts.values())


async def audit_one(browser: Any, sem: asyncio.Semaphore, row: MysteriaRow) -> RenderAudit:
    async with sem:
        page = await browser.new_page(viewport={"width": 1365, "height": 900})
        try:
            response = await page.goto(row.url, wait_until="networkidle", timeout=45_000)
            await page.wait_for_timeout(700)
            payload = await page.evaluate(
                """() => {
                  const root = document.querySelector('article.detail-article') || document.querySelector('article') || document.querySelector('main') || document.body;
                  const text = root ? root.innerText : '';
                  const imgs = root ? Array.from(root.querySelectorAll('img')).map(img => img.currentSrc || img.src || '').filter(Boolean) : [];
                  const headings = root ? Array.from(root.querySelectorAll('h2,h3,summary')).map(e => e.innerText || '') : [];
                  return {
                    text,
                    imgs,
                    headings,
                    h1: root ? root.querySelectorAll('h1').length : 0,
                    h2: root ? root.querySelectorAll('h2').length : 0
                  };
                }"""
            )
            raw_text = str(payload.get("text") or "")
            text = re.sub(r"\s+", " ", html.unescape(raw_text)).strip()
            images = list(dict.fromkeys(str(src) for src in (payload.get("imgs") or []) if str(src).strip()))
            ratio, top = sentence_metrics(text)
            return RenderAudit(
                remote_post_id=row.remote_post_id,
                title=row.title,
                url=row.url,
                status=response.status if response else 0,
                plain_text_length=len(text),
                image_count=len(images),
                h1_count=int(payload.get("h1") or 0),
                h2_count=int(payload.get("h2") or 0),
                faq_count=sum(1 for heading in payload.get("headings") or [] if is_faq_text(str(heading))),
                raw_html_exposed=any(marker in raw_text for marker in RAW_HTML_MARKERS),
                markdown_exposed=is_markdown_exposed(raw_text),
                duplicate_sentence_ratio=ratio,
                top_repeated_sentence_count=top,
                hero_url=row.thumbnail_url,
            )
        except Exception as exc:  # noqa: BLE001
            return RenderAudit(
                remote_post_id=row.remote_post_id,
                title=row.title,
                url=row.url,
                status="ERR",
                plain_text_length=0,
                image_count=0,
                h1_count=0,
                h2_count=0,
                faq_count=0,
                raw_html_exposed=False,
                markdown_exposed=False,
                duplicate_sentence_ratio=0.0,
                top_repeated_sentence_count=0,
                hero_url=row.thumbnail_url,
                error=str(exc),
            )
        finally:
            await page.close()


async def audit_rows(rows: list[MysteriaRow]) -> list[RenderAudit]:
    sem = asyncio.Semaphore(6)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        audits = await asyncio.gather(*(audit_one(browser, sem, row) for row in rows))
        await browser.close()
    order = {row.url: index for index, row in enumerate(rows)}
    audits.sort(key=lambda item: order.get(item.url, 999_999))
    return audits


def needs_repair(audit: RenderAudit) -> bool:
    return (
        audit.status == 200
        and (
            audit.image_count != 1
            or audit.raw_html_exposed
            or audit.markdown_exposed
            or audit.h1_count > 1
        )
    )


def normalize_image_url(value: str) -> str:
    url = normalize_space(value)
    if not url:
        return ""
    if url.startswith(ALLOWED_IMAGE_PREFIX) and url.lower().split("?", 1)[0].endswith(".webp"):
        return url
    return ""


def strip_raw_html_text(value: str) -> str:
    text = value or ""
    text = re.sub(r"</?(?:div|section|article|main|header|footer|aside)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"\s(?:class|style)=['\"][^'\"]*['\"]", "", text, flags=re.IGNORECASE)
    return text


def markdown_line_to_html(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.startswith("### "):
        return f"<h3>{html.escape(stripped[4:].strip())}</h3>"
    if stripped.startswith("## "):
        return f"<h2>{html.escape(stripped[3:].strip())}</h2>"
    if stripped.startswith("# "):
        return f"<h2>{html.escape(stripped[2:].strip())}</h2>"
    if stripped.startswith("- ") or stripped.startswith("* "):
        return f"<p>{html.escape(stripped[2:].strip())}</p>"
    if len(stripped) > 3 and stripped[0].isdigit() and ". " in stripped[:5]:
        return f"<p>{html.escape(stripped.split('. ', 1)[1].strip())}</p>"
    escaped = html.escape(stripped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return f"<p>{escaped}</p>"


def markdown_to_basic_html(value: str) -> str:
    if "<" in value and ">" in value:
        return value
    converted = [markdown_line_to_html(line) for line in value.splitlines()]
    return "\n".join(line for line in converted if line)


def remove_existing_images(soup: BeautifulSoup) -> None:
    for img in list(soup.find_all("img")):
        parent = img.parent
        if getattr(parent, "name", "") == "figure":
            parent.decompose()
        else:
            img.decompose()


def demote_extra_h1(soup: BeautifulSoup) -> None:
    h1s = soup.find_all("h1")
    for h1 in h1s:
        h1.name = "h2"


def prepend_hero(soup: BeautifulSoup, hero_url: str, title: str) -> None:
    if not hero_url:
        return
    figure = soup.new_tag("figure")
    figure["class"] = "mysteria-hero"
    img = soup.new_tag("img")
    img["src"] = hero_url
    img["alt"] = title or "미스테리아 스토리 대표 이미지"
    img["loading"] = "eager"
    img["decoding"] = "async"
    figure.append(img)
    target = soup.body if soup.body else soup
    target.insert(0, figure)


def sanitize_content(content: str, *, hero_url: str, title: str) -> str:
    source = strip_raw_html_text(content or "")
    source = markdown_to_basic_html(source)
    soup = BeautifulSoup(source or "", "html.parser")
    remove_existing_images(soup)
    demote_extra_h1(soup)
    prepend_hero(soup, hero_url, title)
    for text_node in list(soup.find_all(string=True)):
        if not isinstance(text_node, NavigableString):
            continue
        cleaned = str(text_node)
        for marker in RAW_HTML_MARKERS:
            cleaned = cleaned.replace(marker, " ")
        if cleaned != str(text_node):
            text_node.replace_with(cleaned)
    return str(soup).strip()


def extract_tag_names(detail: dict[str, Any]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in detail.get("tags") or []:
        if isinstance(item, dict):
            name = normalize_space(str(item.get("name") or item.get("label") or item.get("slug") or ""))
        else:
            name = normalize_space(str(item))
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(name)
    return values[:12]


def build_update_payload(detail: dict[str, Any], *, content: str, hero_url: str, fallback_title: str) -> dict[str, Any]:
    title = normalize_space(str(detail.get("title") or fallback_title))
    excerpt = normalize_space(str(detail.get("excerpt") or detail.get("description") or ""))
    if len(excerpt) < 90:
        excerpt = (excerpt + " 미스테리아 스토리의 사건 기록, 핵심 단서, 남은 의문을 정리한 장문 분석입니다.").strip()
    if len(excerpt) < 90:
        excerpt = f"{title}에 대한 사건 기록, 핵심 단서, 남은 의문을 정리한 미스테리아 스토리 장문 분석입니다."
    category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
    category_id = normalize_space(str(category.get("id") or detail.get("categoryId") or ""))
    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "excerpt": excerpt,
        "seoTitle": normalize_space(str(detail.get("seoTitle") or title)),
        "seoDescription": normalize_space(str(detail.get("seoDescription") or excerpt)),
        "tagNames": extract_tag_names(detail),
        "status": "published",
        "coverImage": hero_url,
        "coverAlt": normalize_space(str(detail.get("coverAlt") or title)),
    }
    if len(payload["seoDescription"]) < 90:
        payload["seoDescription"] = excerpt
    if category_id:
        payload["categoryId"] = category_id
    return payload


def write_reports(audits: list[RenderAudit], *, report_path: Path, markdown_path: Path) -> dict[str, Any]:
    rows = [asdict(item) for item in audits]
    summary = {
        "count": len(rows),
        "status": dict(Counter(str(row["status"]) for row in rows)),
        "image_distribution": dict(Counter(str(row["image_count"]) for row in rows)),
        "under_3000": sum(1 for row in rows if int(row["plain_text_length"]) < 3000),
        "raw_html_exposed": sum(1 for row in rows if row["raw_html_exposed"]),
        "markdown_exposed": sum(1 for row in rows if row["markdown_exposed"]),
        "h1_gt_1": sum(1 for row in rows if int(row["h1_count"]) > 1),
        "repeat_ge_050": sum(1 for row in rows if float(row["duplicate_sentence_ratio"]) >= 0.5),
        "repair_candidates": sum(1 for item in audits if needs_repair(item)),
        "rows": rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "| No | title | plain_text_length | image_count | raw_html_exposed | markdown_exposed | status | url |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for index, row in enumerate(rows, 1):
        title = str(row["title"]).replace("|", "\\|")
        lines.append(
            f"| {index} | {title} | {row['plain_text_length']} | {row['image_count']} | "
            f"{str(row['raw_html_exposed']).lower()} | {str(row['markdown_exposed']).lower()} | "
            f"{row['status']} | {row['url']} |"
        )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return summary


def print_summary(summary: dict[str, Any], *, report_path: Path, markdown_path: Path) -> None:
    printable = {key: value for key, value in summary.items() if key != "rows"}
    print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))
    print(f"REPORT={report_path}")
    print(f"MARKDOWN={markdown_path}")


def resolve_remote_detail(client: CloudflareIntegrationClient, row: MysteriaRow) -> dict[str, Any]:
    if row.remote_post_id:
        detail = client.get_post(row.remote_post_id)
        if detail:
            return detail
    slug = row.url.rstrip("/").split("/")[-1]
    for item in client.list_posts():
        if normalize_space(str(item.get("slug") or "")) == slug or normalize_space(str(item.get("published_url") or "")) == row.url:
            remote_id = normalize_space(str(item.get("remote_id") or item.get("id") or ""))
            if remote_id:
                return client.get_post(remote_id)
    return {}


def run_apply(rows: list[MysteriaRow], audits: list[RenderAudit]) -> list[dict[str, Any]]:
    audit_by_url = {audit.url: audit for audit in audits}
    results: list[dict[str, Any]] = []
    with SessionLocal() as db:
        client = CloudflareIntegrationClient.from_db(db)
        for row in rows:
            audit = audit_by_url.get(row.url)
            if audit is None or not needs_repair(audit):
                continue
            hero_url = normalize_image_url(row.thumbnail_url)
            if not hero_url:
                results.append({"url": row.url, "title": row.title, "status": "skipped", "reason": "missing_valid_thumbnail_url"})
                continue
            try:
                detail = resolve_remote_detail(client, row)
                if not detail:
                    raise ValueError("remote_detail_not_found")
                post_id = normalize_space(str(detail.get("remote_id") or detail.get("id") or row.remote_post_id))
                current_content = str(detail.get("content") or "")
                sanitized = sanitize_content(current_content, hero_url=hero_url, title=row.title)
                payload = build_update_payload(detail, content=sanitized, hero_url=hero_url, fallback_title=row.title)
                client.update_post(post_id, payload)
                results.append({"url": row.url, "title": row.title, "status": "updated", "post_id": post_id})
            except Exception as exc:  # noqa: BLE001
                results.append({"url": row.url, "title": row.title, "status": "failed", "error": str(exc)})
        if any(item["status"] == "updated" for item in results):
            sync_cloudflare_posts(db, include_non_published=True)
            db.commit()
    return results


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_path)
    markdown_path = Path(args.markdown_path)
    rows = load_target_rows()
    audits = asyncio.run(audit_rows(rows))
    for audit in audits:
        audit.action = "repair" if needs_repair(audit) else "none"
    if args.mode == "dry-run":
        summary = write_reports(audits, report_path=report_path, markdown_path=markdown_path)
        print_summary(summary, report_path=report_path, markdown_path=markdown_path)
        return 0
    if args.mode == "apply":
        results = run_apply(rows, audits)
        failures = [item for item in results if item.get("status") == "failed"]
        apply_path = report_path.with_name(report_path.stem + "-apply.json")
        apply_path.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"planned": sum(1 for item in audits if needs_repair(item)), "updated": sum(1 for item in results if item.get("status") == "updated"), "failed": len(failures), "apply_report": str(apply_path), "failures": failures[:10]}, ensure_ascii=False, indent=2))
        return 1 if failures else 0
    summary = write_reports(audits, report_path=report_path, markdown_path=markdown_path)
    print_summary(summary, report_path=report_path, markdown_path=markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

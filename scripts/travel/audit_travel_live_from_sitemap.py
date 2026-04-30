from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup


DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
BLOGS = {
    "en": "https://donggri-korea.blogspot.com",
    "ja": "https://donggri-kankoku.blogspot.com",
    "es": "https://donggri-corea.blogspot.com",
}
FEED_PAGE_SIZE = 100
SPACE_RE = re.compile(r"\s+")
NON_SPACE_RE = re.compile(r"\s+", re.UNICODE)
R2_IMAGE_RE = re.compile(r"https://api\.dongriarchive\.com/assets/travel-blogger/[^\"'<>\s)]+?\.webp", re.I)
FORBIDDEN_VISIBLE_TERMS = [
    re.compile(pattern, re.I)
    for pattern in (
        r"\bSEO\b",
        r"\bGEO\b",
        r"\bCTR\b",
        r"\bLighthouse\b",
        r"\bPageSpeed\b",
        r"\barticle_pattern\b",
        r"\bpattern_key\b",
        r"\btravel-0[1-5]\b",
        r"\bhidden-path-route\b",
        r"\bcultural-insider\b",
        r"\blocal-flavor-guide\b",
        r"\bseasonal-secret\b",
        r"\bsmart-traveler-log\b",
    )
]


def _stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _clean_text(value: str | None) -> str:
    return SPACE_RE.sub(" ", str(value or "")).strip()


def _plain_text(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "html.parser")
    for tag in clone(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return _clean_text(clone.get_text(" ", strip=True))


def _plain_non_space_len(soup: BeautifulSoup) -> int:
    return len(NON_SPACE_RE.sub("", _plain_text(soup)))


def _sitemap_urls(client: httpx.Client, base_url: str) -> list[str]:
    response = client.get(f"{base_url.rstrip('/')}/sitemap.xml")
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    urls: list[str] = []
    for loc in root.findall(".//{*}loc"):
        url = (loc.text or "").strip()
        if not url:
            continue
        path = urlparse(url).path
        if re.search(r"/\d{4}/\d{2}/.+\.html$", path):
            urls.append(url)
    return sorted(set(urls))


def _feed_inventory(client: httpx.Client, base_url: str) -> dict[str, Any]:
    posts: list[dict[str, str]] = []
    total_results = 0
    start = 1
    pages: list[dict[str, int]] = []
    while True:
        response = client.get(
            f"{base_url.rstrip('/')}/feeds/posts/default",
            params={"alt": "json", "start-index": start, "max-results": FEED_PAGE_SIZE},
        )
        response.raise_for_status()
        payload = response.json()
        feed = payload.get("feed") if isinstance(payload, dict) else {}
        if not isinstance(feed, dict):
            break
        if not total_results:
            total_results = int(str((feed.get("openSearch$totalResults") or {}).get("$t") or "0"))
        entries = feed.get("entry") or []
        if not isinstance(entries, list) or not entries:
            pages.append({"start": start, "count": 0})
            break
        pages.append({"start": start, "count": len(entries)})
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = str((entry.get("title") or {}).get("$t") or "").strip()
            url = ""
            for link in entry.get("link") or []:
                if isinstance(link, dict) and str(link.get("rel") or "").lower() == "alternate":
                    url = str(link.get("href") or "").strip()
                    break
            if url:
                posts.append({"url": url, "title": title})
        start += len(entries)
        if total_results and start > total_results:
            break
        if len(entries) < FEED_PAGE_SIZE:
            break
    return {
        "total_results": total_results,
        "collected": len(posts),
        "unique_urls": len({post["url"] for post in posts}),
        "pages": pages,
        "missing_vs_total": max(total_results - len({post["url"] for post in posts}), 0),
    }


def _fetch_with_retry(client: httpx.Client, url: str, retries: int) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, retries + 2):
        try:
            response = client.get(url)
            attempts.append({"attempt": attempt, "status": response.status_code, "bytes": len(response.content)})
            if response.status_code == 200:
                return {"ok": True, "status": 200, "html": response.text, "attempts": attempts, "error": ""}
            if response.status_code < 500 and response.status_code not in {408, 429}:
                return {"ok": False, "status": response.status_code, "html": response.text, "attempts": attempts, "error": ""}
        except Exception as exc:  # noqa: BLE001
            attempts.append({"attempt": attempt, "status": None, "bytes": 0, "error": str(exc)})
    return {"ok": False, "status": attempts[-1].get("status") if attempts else None, "html": "", "attempts": attempts, "error": attempts[-1].get("error", "") if attempts else ""}


def _article_scope(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html or "", "html.parser")
    candidates = soup.select("article.post-body, article, .post-body, .article-content")
    if not candidates:
        return soup
    return BeautifulSoup(str(max(candidates, key=lambda node: len(node.get_text(" ", strip=True)))), "html.parser")


def _sentence_repeat_issues(text: str) -> list[dict[str, Any]]:
    parts = [
        _clean_text(part)
        for part in re.split(r"(?<=[.!?。！？])\s+|(?<=다\.)\s+|(?<=요\.)\s+", text)
    ]
    counter: Counter[str] = Counter()
    originals: dict[str, str] = {}
    for part in parts:
        if len(part) < 28:
            continue
        key = part.casefold()
        counter[key] += 1
        originals.setdefault(key, part)
    return [
        {"count": count, "sentence": originals[key][:220]}
        for key, count in counter.most_common()
        if count >= 3
    ]


def _audit_url(client: httpx.Client, lang: str, url: str, retries: int) -> dict[str, Any]:
    fetched = _fetch_with_retry(client, url, retries)
    row: dict[str, Any] = {
        "language": lang,
        "url": url,
        "http_status": fetched["status"],
        "fetch_ok": fetched["ok"],
        "fetch_attempts": fetched["attempts"],
        "issues": [],
    }
    if not fetched["ok"]:
        row["issues"].append("live_fetch_failed_after_retry")
        row["fetch_error"] = fetched.get("error") or ""
        return row

    fragment = _article_scope(fetched["html"])
    text = _plain_text(fragment)
    r2_urls = R2_IMAGE_RE.findall(str(fragment))
    title = _clean_text((fragment.find("h1").get_text(" ", strip=True) if fragment.find("h1") else ""))
    h1_count = len(fragment.find_all("h1"))
    body_chars = _plain_non_space_len(fragment)
    repeat_issues = _sentence_repeat_issues(text)
    forbidden = [pattern.pattern for pattern in FORBIDDEN_VISIBLE_TERMS if pattern.search(text)]
    row.update(
        {
            "title": title,
            "article_h1_count": h1_count,
            "h2_count": len(fragment.find_all("h2")),
            "h3_count": len(fragment.find_all("h3")),
            "table_count": len(fragment.find_all("table")),
            "image_count": len(fragment.find_all("img")),
            "r2_image_count": len(r2_urls),
            "r2_unique_image_count": len(set(r2_urls)),
            "body_non_space_chars": body_chars,
            "repeat_issues": repeat_issues,
            "forbidden_visible_terms": forbidden,
        }
    )
    if h1_count != 1:
        row["issues"].append("article_h1_not_one")
    if body_chars < 3000:
        row["issues"].append("body_under_3000")
    if repeat_issues:
        row["issues"].append("sentence_repeated_3plus")
    if forbidden:
        row["issues"].append("forbidden_internal_terms_visible")
    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit travel live posts from Blogger sitemap URLs.")
    parser.add_argument("--langs", default="en,ja,es")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-live-sitemap-full-audit")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    _stdout_utf8()
    args = parse_args()
    langs = [token.strip() for token in str(args.langs).split(",") if token.strip()]
    report_path = Path(args.report_root) / f"{args.report_prefix}-{_now_stamp()}.json"
    result: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_of_truth": "sitemap.xml",
        "feed_page_size": FEED_PAGE_SIZE,
        "blogs": [],
    }
    with httpx.Client(
        follow_redirects=True,
        timeout=float(args.timeout),
        headers={"User-Agent": "BloggerGentTravelSitemapAudit/1.0"},
    ) as client:
        for lang in langs:
            base_url = BLOGS[lang]
            feed = _feed_inventory(client, base_url)
            sitemap_urls = _sitemap_urls(client, base_url)
            if int(args.limit or 0) > 0:
                sitemap_urls = sitemap_urls[: int(args.limit)]
            rows = [_audit_url(client, lang, url, int(args.retries)) for url in sitemap_urls]
            issue_counts: Counter[str] = Counter()
            for row in rows:
                issue_counts.update(row.get("issues") or [])
            result["blogs"].append(
                {
                    "language": lang,
                    "base_url": base_url,
                    "feed": feed,
                    "sitemap_count": len(sitemap_urls),
                    "audit_summary": {
                        "total": len(rows),
                        "fetch_failed_after_retry": sum(1 for row in rows if not row.get("fetch_ok")),
                        "ok": sum(1 for row in rows if row.get("fetch_ok") and not row.get("issues")),
                        "issue_counts": dict(sorted(issue_counts.items())),
                        "h1_not_one": sum(1 for row in rows if "article_h1_not_one" in row.get("issues", [])),
                        "under_3000": sum(1 for row in rows if "body_under_3000" in row.get("issues", [])),
                        "repeat_3plus": sum(1 for row in rows if "sentence_repeated_3plus" in row.get("issues", [])),
                        "forbidden_internal_terms": sum(1 for row in rows if "forbidden_internal_terms_visible" in row.get("issues", [])),
                    },
                    "problem_rows": [row for row in rows if row.get("issues")],
                    "rows": rows,
                }
            )
    _write_json(report_path, result)
    print(json.dumps({"report_path": str(report_path), "blogs": [
        {
            "language": blog["language"],
            "feed_collected": blog["feed"]["collected"],
            "feed_total": blog["feed"]["total_results"],
            "sitemap_count": blog["sitemap_count"],
            "audit_summary": blog["audit_summary"],
        }
        for blog in result["blogs"]
    ]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

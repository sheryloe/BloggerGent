from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
TRAVEL_BLOG_IDS = (34, 36, 37)
BLOG_LANGUAGE = {34: "en", 36: "es", 37: "ja"}
SPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


_load_runtime_env(RUNTIME_ENV_PATH)
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or os.environ.get("BLOGGENT_DATABASE_URL") or DEFAULT_DATABASE_URL
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article  # noqa: E402
from app.services.blogger.blogger_live_audit_service import extract_best_article_fragment  # noqa: E402


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _norm_text(value: str | None) -> str:
    return SPACE_RE.sub(" ", str(value or "")).strip()


def _norm_key(value: str | None) -> str:
    return PUNCT_RE.sub("", _norm_text(value).casefold())


def _plain_non_space_len(node: Any) -> int:
    if node is None:
        return 0
    soup = BeautifulSoup(str(node), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return len(SPACE_RE.sub("", soup.get_text(" ", strip=True)))


def _img_srcs(node: Any) -> list[str]:
    if node is None:
        return []
    return [str(img.get("src") or "").strip() for img in node.find_all("img") if str(img.get("src") or "").strip()]


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for value in values:
        key = _norm_key(value)
        if not key:
            continue
        if key in seen and value not in dupes:
            dupes.append(value)
        seen.add(key)
    return dupes


def _load_articles(db, blog_ids: tuple[int, ...]) -> list[Article]:
    return (
        db.execute(
            select(Article)
            .where(Article.blog_id.in_(list(blog_ids)))
            .options(
                selectinload(Article.image),
                selectinload(Article.blogger_post),
            )
            .order_by(Article.blog_id.asc(), Article.id.asc())
        )
        .scalars()
        .all()
    )


def _image_result_for_url(client: httpx.Client, cache: dict[str, dict[str, Any]], url: str) -> dict[str, Any]:
    normalized_url = str(url or "").strip()
    if normalized_url in cache:
        return cache[normalized_url]

    result: dict[str, Any] = {
        "url": normalized_url,
        "status": None,
        "content_type": "",
        "ok": False,
        "error": "",
    }
    if not normalized_url.lower().startswith(("http://", "https://")):
        result["error"] = "non_http_image_url"
        cache[normalized_url] = result
        return result

    try:
        response = client.head(normalized_url, follow_redirects=True)
        if response.status_code in {403, 405} or response.status_code >= 500:
            response = client.get(normalized_url, follow_redirects=True, headers={"Range": "bytes=0-0"})
        result["status"] = response.status_code
        result["content_type"] = str(response.headers.get("content-type") or "").split(";")[0].strip().lower()
        result["ok"] = 200 <= response.status_code < 400 and result["content_type"].startswith("image/")
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)

    cache[normalized_url] = result
    return result


def _audit_one(
    client: httpx.Client,
    image_cache: dict[str, dict[str, Any]],
    article: Article,
    *,
    check_images: bool,
) -> dict[str, Any]:
    post = article.blogger_post
    published_url = str(post.published_url if post else "").strip()
    expected_hero_url = str(article.image.public_url if article.image else "").strip()
    row: dict[str, Any] = {
        "article_id": int(article.id),
        "blog_id": int(article.blog_id),
        "language": BLOG_LANGUAGE.get(int(article.blog_id), ""),
        "title": article.title,
        "published_url": published_url,
        "expected_hero_url": expected_hero_url,
        "http_status": None,
        "final_url": "",
        "issues": [],
    }

    if not published_url:
        row["issues"].append("live_publish_missing")
        return row

    try:
        response = client.get(published_url, follow_redirects=True)
        if response.status_code >= 500:
            response = client.get(published_url, follow_redirects=True)
        row["http_status"] = response.status_code
        row["final_url"] = str(response.url)
    except Exception as exc:  # noqa: BLE001
        row["issues"].append("live_fetch_error")
        row["fetch_error"] = str(exc)
        return row

    if row["http_status"] != 200:
        row["issues"].append("http_not_200")
        return row

    fragment = extract_best_article_fragment(
        response.text,
        expected_title=article.title,
        expected_hero_url=expected_hero_url,
    )
    soup = BeautifulSoup(fragment or "", "html.parser")
    article_body = soup.select_one('[data-bloggent-role="article-body"]')
    hero_figure = soup.select_one('[data-bloggent-role="hero-figure"]')
    hero_img = hero_figure.find("img") if hero_figure else None
    live_hero_url = str(hero_img.get("src") or "").strip() if hero_img else ""
    related_section = soup.select_one(".related-posts")

    body_img_srcs = _img_srcs(article_body)
    related_img_srcs = _img_srcs(related_section)
    shell_img_srcs = _img_srcs(soup)
    h1_texts = [_norm_text(tag.get_text(" ", strip=True)) for tag in soup.find_all("h1")]
    h2_texts = [_norm_text(tag.get_text(" ", strip=True)) for tag in soup.find_all("h2")]
    faq_summaries = [_norm_text(tag.get_text(" ", strip=True)) for tag in soup.select("details summary")]
    related_current_hero_duplicates = [src for src in related_img_srcs if live_hero_url and src == live_hero_url]
    article_hero_occurrences = sum(1 for src in shell_img_srcs if live_hero_url and src == live_hero_url)

    image_results: list[dict[str, Any]] = []
    if check_images:
        for src in sorted(set(shell_img_srcs)):
            image_results.append(_image_result_for_url(client, image_cache, src))

    row.update(
        {
            "article_h1_count": len(h1_texts),
            "article_h1_texts": h1_texts,
            "hero_figure_count": len(soup.select('[data-bloggent-role="hero-figure"]')),
            "live_hero_url": live_hero_url,
            "article_body_non_space_chars": _plain_non_space_len(article_body),
            "body_img_count": len(body_img_srcs),
            "related_img_count": len(related_img_srcs),
            "article_shell_img_count": len(shell_img_srcs),
            "article_hero_occurrence_count": article_hero_occurrences,
            "related_current_hero_duplicate_count": len(related_current_hero_duplicates),
            "duplicate_h2_titles": _duplicates(h2_texts),
            "faq_summary_count": len(faq_summaries),
            "duplicate_faq_summaries": _duplicates(faq_summaries),
            "image_results": image_results,
        }
    )

    text = _norm_text(soup.get_text(" ", strip=True))
    if article.title and _norm_key(article.title) not in _norm_key(text):
        row["issues"].append("title_missing_in_article_fragment")
    if row["article_h1_count"] != 1:
        row["issues"].append("article_h1_not_one")
    if row["hero_figure_count"] != 1:
        row["issues"].append("hero_figure_not_one")
    if not live_hero_url:
        row["issues"].append("live_hero_missing")
    if row["article_body_non_space_chars"] <= 1000:
        row["issues"].append("body_text_under_or_equal_1000")
    if row["body_img_count"] != 0:
        row["issues"].append("body_inline_image_not_zero")
    if row["related_img_count"] != 3:
        row["issues"].append("related_image_count_not_three")
    if row["article_shell_img_count"] != 4:
        row["issues"].append("article_shell_image_count_not_four")
    if row["article_hero_occurrence_count"] != 1:
        row["issues"].append("article_hero_repeated")
    if row["related_current_hero_duplicate_count"] > 0:
        row["issues"].append("related_reuses_current_hero")
    if row["duplicate_h2_titles"]:
        row["issues"].append("duplicate_h2_titles")
    if row["duplicate_faq_summaries"]:
        row["issues"].append("duplicate_faq_summaries")
    if check_images:
        broken = [item for item in image_results if not item.get("ok")]
        row["broken_image_count"] = len(broken)
        if broken:
            row["issues"].append("broken_image_url")

    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit live travel article structure and FAQ duplicates.")
    parser.add_argument("--blog-ids", default="34,36,37")
    parser.add_argument("--article-ids", default="")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-live-structure-faq-audit")
    parser.add_argument("--check-images", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    blog_ids = tuple(int(token) for token in str(args.blog_ids).split(",") if token.strip())
    article_ids = {int(token) for token in str(args.article_ids).split(",") if token.strip()}
    report_path = Path(args.report_root) / f"{args.report_prefix}-{_now_stamp()}.json"
    rows: list[dict[str, Any]] = []
    image_cache: dict[str, dict[str, Any]] = {}

    with SessionLocal() as db:
        articles = [
            article
            for article in _load_articles(db, blog_ids)
            if article.blogger_post and str(article.blogger_post.published_url or "").strip()
        ]
        if article_ids:
            articles = [article for article in articles if int(article.id) in article_ids]
        if int(args.limit or 0) > 0:
            articles = articles[: int(args.limit)]

        with httpx.Client(timeout=float(args.timeout), headers={"User-Agent": "BloggerGentTravelAudit/1.0"}) as client:
            for article in articles:
                rows.append(_audit_one(client, image_cache, article, check_images=bool(args.check_images)))

    issue_counts: Counter[str] = Counter()
    for row in rows:
        issue_counts.update(row.get("issues") or [])

    summary = {
        "total": len(rows),
        "ok": sum(1 for row in rows if not row.get("issues")),
        "issue_counts": dict(sorted(issue_counts.items())),
        "h1_distribution": dict(Counter(str(row.get("article_h1_count")) for row in rows if row.get("http_status") == 200)),
        "hero_figure_distribution": dict(Counter(str(row.get("hero_figure_count")) for row in rows if row.get("http_status") == 200)),
        "body_img_distribution": dict(Counter(str(row.get("body_img_count")) for row in rows if row.get("http_status") == 200)),
        "related_img_distribution": dict(Counter(str(row.get("related_img_count")) for row in rows if row.get("http_status") == 200)),
        "article_shell_img_distribution": dict(Counter(str(row.get("article_shell_img_count")) for row in rows if row.get("http_status") == 200)),
        "body_under_or_equal_1000_count": sum(1 for row in rows if row.get("article_body_non_space_chars", 0) <= 1000),
        "duplicate_faq_summary_count": sum(1 for row in rows if row.get("duplicate_faq_summaries")),
        "duplicate_h2_title_count": sum(1 for row in rows if row.get("duplicate_h2_titles")),
        "unique_checked_image_urls": len(image_cache),
        "broken_checked_image_urls": sum(1 for value in image_cache.values() if not value.get("ok")),
    }
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "blog_ids": list(blog_ids),
        "check_images": bool(args.check_images),
        "summary": summary,
        "problem_rows": [row for row in rows if row.get("issues")],
        "rows": rows,
    }
    _write_json(report_path, report)
    print(json.dumps({"report_path": str(report_path), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

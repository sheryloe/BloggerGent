from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
MOJIBAKE_RE = re.compile(r"[占시꺝?|[?]{3,}")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = str(raw_line or "").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'").strip('"')


_load_runtime_env(RUNTIME_ENV_PATH)
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or os.environ.get("BLOGGENT_DATABASE_URL") or DEFAULT_DATABASE_URL
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article  # noqa: E402
from app.services.content.blogger_live_publish_validation_service import validate_blogger_live_publish  # noqa: E402
from app.services.content.travel_blog_policy import travel_public_url_to_object_key  # noqa: E402


STRUCTURAL_ISSUES = (
    "live_publish_missing",
    "missing_live_title",
    "missing_live_hero",
    "missing_live_body",
    "article_h1_missing",
    "article_h1_multiple",
    "article_hero_missing",
    "article_hero_multiple",
    "article_body_snippet_mismatch",
    "invalid_hero_canonical_path",
)

SECONDARY_ISSUES = (
    "under_2500",
    "under_3000",
    "under_3500",
    "live_fetch_error",
    "missing_pattern_metadata",
    "invalid_category_metadata",
    "missing_quality_status",
    "title_raw_topic_like",
    "mojibake_suspect",
)


def _plain_text(value: str | None) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", str(value or ""))).strip()


def _non_space_len(value: str | None) -> int:
    return len(SPACE_RE.sub("", _plain_text(value)))


def _is_invalid_hero_path(url: str | None) -> bool:
    object_key = travel_public_url_to_object_key(url)
    if not object_key:
        return True
    if not object_key.startswith("assets/travel-blogger/"):
        return True
    return not (
        object_key.startswith("assets/travel-blogger/travel/")
        or object_key.startswith("assets/travel-blogger/culture/")
    )


def _is_raw_topic_like_title(title: str | None, slug: str | None) -> bool:
    title_slug = slugify(str(title or "").strip(), separator="-")
    current_slug = str(slug or "").strip().lower()
    if not title_slug or not current_slug:
        return False
    if title_slug == current_slug:
        return True
    return current_slug.startswith(title_slug) or title_slug.startswith(current_slug)


def _is_mojibake_suspect(*values: str | None) -> bool:
    return any(MOJIBAKE_RE.search(str(value or "")) for value in values)


def _row_issue_payload(article: Article, *, live_validation: dict[str, Any] | None = None) -> dict[str, Any]:
    post = article.blogger_post
    hero_url = article.image.public_url if getattr(article, "image", None) else ""
    visible_length = _non_space_len(article.assembled_html or article.html_article)

    issues: list[str] = []
    secondary_issues: list[str] = []

    if not post or not str(post.published_url or "").strip():
        issues.append("live_publish_missing")
    if _is_invalid_hero_path(hero_url):
        issues.append("invalid_hero_canonical_path")

    if live_validation:
        failure_reasons = [str(value or "") for value in live_validation.get("failure_reasons", [])]
        diagnostic_warnings = [str(value or "") for value in live_validation.get("diagnostic_warnings", [])]
        has_live_fetch_error = any(reason.startswith("http_error:") for reason in failure_reasons)

        if has_live_fetch_error:
            secondary_issues.append("live_fetch_error")
        else:
            if not bool(live_validation.get("article_title_present")):
                issues.append("missing_live_title")
            if not bool(live_validation.get("article_hero_present")):
                issues.append("missing_live_hero")
            if not bool(live_validation.get("article_body_present")):
                issues.append("missing_live_body")
            article_h1_count = int(live_validation.get("article_h1_count") or 0)
            article_hero_occurrence_count = int(live_validation.get("article_hero_occurrence_count") or 0)
            if article_h1_count == 0:
                issues.append("article_h1_missing")
            elif article_h1_count > 1:
                issues.append("article_h1_multiple")
            if article_hero_occurrence_count == 0:
                issues.append("article_hero_missing")
            elif article_hero_occurrence_count > 1:
                issues.append("article_hero_multiple")
            if "article_body_snippet_mismatch" in diagnostic_warnings:
                issues.append("article_body_snippet_mismatch")

    if visible_length < 2500:
        secondary_issues.append("under_2500")
    if visible_length < 3000:
        secondary_issues.append("under_3000")
    if visible_length < 3500:
        secondary_issues.append("under_3500")
    pattern_key = str(getattr(article, "article_pattern_key", "") or "").strip()
    pattern_version_key = str(getattr(article, "article_pattern_version_key", "") or "").strip()
    if not pattern_key and not article.article_pattern_id:
        secondary_issues.append("missing_pattern_metadata")
    elif not pattern_version_key and not article.article_pattern_version:
        secondary_issues.append("missing_pattern_metadata")
    if not str(article.editorial_category_key or "").strip():
        secondary_issues.append("invalid_category_metadata")
    if not str(article.quality_status or "").strip():
        secondary_issues.append("missing_quality_status")
    if _is_raw_topic_like_title(article.title, article.slug):
        secondary_issues.append("title_raw_topic_like")
    if _is_mojibake_suspect(article.title, article.meta_description, article.html_article):
        secondary_issues.append("mojibake_suspect")

    return {
        "article_id": int(article.id),
        "blog_id": int(article.blog_id),
        "language": getattr(getattr(article, "blog", None), "primary_language", None),
        "title": article.title,
        "slug": article.slug,
        "published_url": post.published_url if post else None,
        "hero_url": hero_url or None,
        "visible_non_space_chars": visible_length,
        "article_pattern_id": article.article_pattern_id,
        "article_pattern_version": article.article_pattern_version,
        "article_pattern_key": pattern_key or None,
        "article_pattern_version_key": pattern_version_key or None,
        "editorial_category_key": article.editorial_category_key,
        "quality_status": article.quality_status,
        "issues": issues,
        "secondary_issues": secondary_issues,
        "live_validation": live_validation,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Travel Structural Audit",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- live_fetch: {report['live_fetch']}",
        "",
        "## Structural Summary",
        "",
        "| blog_id | language | total | live_publish_missing | missing_live_title | missing_live_hero | missing_live_body | article_h1_missing | article_h1_multiple | article_hero_missing | article_hero_multiple | article_body_snippet_mismatch | invalid_hero_canonical_path |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["summary_by_blog"]:
        lines.append(
            f"| {item['blog_id']} | {item['language']} | {item['total']} | {item['live_publish_missing']} | "
            f"{item['missing_live_title']} | {item['missing_live_hero']} | {item['missing_live_body']} | "
            f"{item['article_h1_missing']} | {item['article_h1_multiple']} | {item['article_hero_missing']} | "
            f"{item['article_hero_multiple']} | {item['article_body_snippet_mismatch']} | {item['invalid_hero_canonical_path']} |"
        )
    lines.extend(
        [
            "",
            "## Secondary Summary",
            "",
            "| blog_id | language | under_2500 | under_3000 | under_3500 | live_fetch_error | missing_pattern_metadata | invalid_category_metadata | missing_quality_status | title_raw_topic_like | mojibake_suspect |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in report["summary_by_blog"]:
        lines.append(
            f"| {item['blog_id']} | {item['language']} | {item['under_2500']} | {item['under_3000']} | {item['under_3500']} | {item['live_fetch_error']} | "
            f"{item['missing_pattern_metadata']} | {item['invalid_category_metadata']} | {item['missing_quality_status']} | "
            f"{item['title_raw_topic_like']} | {item['mojibake_suspect']} |"
        )
    lines.extend(["", "## Structural Issue Items", ""])
    for row in report["items"]:
        if not row["issues"]:
            continue
        lines.append(f"- [{row['blog_id']}] {row['title']} :: {', '.join(row['issues'])} :: {row.get('published_url') or 'no-url'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Blogger travel content with structural live validation.")
    parser.add_argument("--blog-ids", default="34,36,37")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-full-content-audit")
    parser.add_argument("--write-json", action="store_true")
    parser.add_argument("--write-markdown", action="store_true")
    parser.add_argument("--live-fetch", action="store_true")
    parser.add_argument("--live-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--max-workers", type=int, default=12)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    blog_ids = tuple(int(token) for token in str(args.blog_ids).split(",") if token.strip())
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_root = Path(str(args.report_root)).resolve()
    json_path = report_root / "reports" / f"{args.report_prefix}-{stamp}.json"
    md_path = report_root / "reports" / f"{args.report_prefix}-{stamp}.md"

    with SessionLocal() as db:
        rows = (
            db.execute(
                select(Article)
                .where(Article.blog_id.in_(list(blog_ids)))
                .options(
                    selectinload(Article.blog),
                    selectinload(Article.blogger_post),
                    selectinload(Article.image),
                )
                .order_by(Article.blog_id.asc(), Article.id.asc())
            )
            .scalars()
            .all()
        )

    live_results: dict[int, dict[str, Any]] = {}
    if args.live_fetch:
        live_candidates = [
            article
            for article in rows
            if getattr(article, "blogger_post", None) and str(article.blogger_post.published_url or "").strip()
        ]

        def _run_live_validation(article: Article) -> tuple[int, dict[str, Any]]:
            return (
                int(article.id),
                validate_blogger_live_publish(
                    published_url=article.blogger_post.published_url,
                    expected_title=article.title,
                    expected_hero_url=article.image.public_url if getattr(article, "image", None) else "",
                    assembled_html=article.assembled_html or article.html_article,
                    timeout_seconds=float(args.live_timeout_seconds),
                    required_article_h1_count=1,
                ),
            )

        max_workers = max(1, int(args.max_workers or 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_run_live_validation, article): int(article.id) for article in live_candidates}
            for future in as_completed(future_map):
                article_id = future_map[future]
                try:
                    resolved_article_id, payload = future.result()
                    live_results[int(resolved_article_id)] = payload
                except Exception as exc:
                    live_results[int(article_id)] = {
                        "status": "failed",
                        "failure_reasons": [f"audit_executor_error:{exc}"],
                    }

    items: list[dict[str, Any]] = []
    for article in rows:
        items.append(_row_issue_payload(article, live_validation=live_results.get(int(article.id))))

    summary_by_blog: list[dict[str, Any]] = []
    for blog_id in blog_ids:
        blog_items = [item for item in items if int(item["blog_id"]) == int(blog_id)]
        structural_counter = Counter(issue for item in blog_items for issue in item["issues"])
        secondary_counter = Counter(issue for item in blog_items for issue in item["secondary_issues"])
        summary_row = {
            "blog_id": int(blog_id),
            "language": blog_items[0]["language"] if blog_items else None,
            "total": len(blog_items),
        }
        for issue in STRUCTURAL_ISSUES:
            summary_row[issue] = structural_counter[issue]
        for issue in SECONDARY_ISSUES:
            summary_row[issue] = secondary_counter[issue]
        summary_by_blog.append(summary_row)

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "live_fetch": bool(args.live_fetch),
        "blog_ids": list(blog_ids),
        "summary_by_blog": summary_by_blog,
        "items": items,
    }

    if args.write_json:
        _write_json(json_path, report)
    if args.write_markdown:
        _write_markdown(md_path, report)

    print(
        json.dumps(
            {
                "json_report_path": str(json_path) if args.write_json else None,
                "markdown_report_path": str(md_path) if args.write_markdown else None,
                "summary_by_blog": summary_by_blog,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

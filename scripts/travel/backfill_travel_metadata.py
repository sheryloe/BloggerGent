from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
TRAVEL_BLOG_IDS = (34, 36, 37)
SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")


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
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article  # noqa: E402
from app.services.content.article_service import resolve_article_editorial_labels  # noqa: E402
from app.services.content.content_ops_service import refresh_content_overview_cache  # noqa: E402
from app.services.content.travel_blog_policy import TRAVEL_PATTERN_VERSION  # noqa: E402


def _plain_text(value: str | None) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", str(value or ""))).strip()


def _suggest_pattern(article: Article, resolved_category_key: str | None) -> str:
    haystack = " ".join(
        [
            str(article.title or ""),
            str(article.slug or ""),
            _plain_text(article.assembled_html or article.html_article)[:1500],
        ]
    ).lower()
    category_key = str(resolved_category_key or article.editorial_category_key or "").strip().lower()

    if category_key == "food" or any(token in haystack for token in ("food", "market", "restaurant", "menu", "cafe", "dakgalbi", "seafood", "street food")):
        return "travel-03-local-flavor-guide"
    if category_key == "culture" or any(
        token in haystack
        for token in ("museum", "festival", "palace", "hanok", "heritage", "opera", "lantern", "exhibition", "history", "cultural")
    ):
        return "travel-02-cultural-insider"
    if any(token in haystack for token in ("cherry blossom", "blossom", "spring", "tulip", "autumn", "seasonal", "night market")):
        return "travel-04-seasonal-secret"
    if any(token in haystack for token in ("how to", "first visit", "practical", "transport", "subway", "booking", "tips", "guide")):
        return "travel-05-smart-traveler-log"
    return "travel-01-hidden-path-route"


def _load_articles(db, *, blog_ids: tuple[int, ...]) -> list[Article]:
    return (
        db.execute(
            select(Article)
            .where(Article.blog_id.in_(list(blog_ids)))
            .options(
                selectinload(Article.blog),
                selectinload(Article.blogger_post),
            )
            .order_by(Article.blog_id.asc(), Article.id.asc())
        )
        .scalars()
        .unique()
        .all()
    )


def _build_item(article: Article) -> dict[str, Any]:
    resolved_key, resolved_label, target_labels = resolve_article_editorial_labels(article)
    current_labels = list(article.labels or [])
    category_fix_required = (
        (str(article.editorial_category_key or "").strip() != str(resolved_key or "").strip())
        or (str(article.editorial_category_label or "").strip() != str(resolved_label or "").strip())
    )
    label_fix_required = current_labels != target_labels
    missing_pattern = not article.article_pattern_id or not article.article_pattern_version
    missing_quality = not str(article.quality_status or "").strip()
    return {
        "article_id": int(article.id),
        "blog_id": int(article.blog_id),
        "language": getattr(getattr(article, "blog", None), "primary_language", None),
        "title": article.title,
        "slug": article.slug,
        "published_url": article.blogger_post.published_url if article.blogger_post else None,
        "current_editorial_category_key": article.editorial_category_key,
        "resolved_editorial_category_key": resolved_key,
        "current_editorial_category_label": article.editorial_category_label,
        "resolved_editorial_category_label": resolved_label,
        "current_labels": current_labels,
        "target_labels": target_labels,
        "quality_status_before": article.quality_status,
        "label_fix_required": label_fix_required,
        "category_fix_required": category_fix_required,
        "missing_quality_status": missing_quality,
        "missing_pattern_metadata": missing_pattern,
        "suggested_pattern_id": _suggest_pattern(article, resolved_key) if missing_pattern else article.article_pattern_id,
        "suggested_pattern_version": TRAVEL_PATTERN_VERSION if missing_pattern else article.article_pattern_version,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill safe travel metadata and emit a pattern repair queue.")
    parser.add_argument("--blog-ids", default="34,36,37")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-metadata-backfill")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    blog_ids = tuple(int(token) for token in str(args.blog_ids).split(",") if token.strip())
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_root = Path(str(args.report_root)).resolve()
    report_path = report_root / "reports" / f"{args.report_prefix}-{stamp}.json"

    with SessionLocal() as db:
        before_articles = _load_articles(db, blog_ids=blog_ids)
        before_items = [_build_item(article) for article in before_articles]

        category_updates = 0
        label_updates = 0
        if args.execute:
            for article in before_articles:
                resolved_key, resolved_label, target_labels = resolve_article_editorial_labels(article)
                changed = False
                if list(article.labels or []) != target_labels:
                    article.labels = target_labels
                    label_updates += 1
                    changed = True
                if (str(article.editorial_category_key or "").strip() != str(resolved_key or "").strip()) or (
                    str(article.editorial_category_label or "").strip() != str(resolved_label or "").strip()
                ):
                    article.editorial_category_key = str(resolved_key or "").strip() or None
                    article.editorial_category_label = str(resolved_label or "").strip() or None
                    category_updates += 1
                    changed = True
                if changed:
                    db.add(article)
            db.commit()
            quality_refresh = refresh_content_overview_cache(db, profile="korea_travel", published_only=False)
        else:
            quality_refresh = None

        after_articles = _load_articles(db, blog_ids=blog_ids)
        after_items = [_build_item(article) for article in after_articles]

    summary = {
        "blog_ids": list(blog_ids),
        "candidate_count": len(before_items),
        "category_fix_required_before": sum(1 for item in before_items if item["category_fix_required"]),
        "label_fix_required_before": sum(1 for item in before_items if item["label_fix_required"]),
        "missing_quality_status_before": sum(1 for item in before_items if item["missing_quality_status"]),
        "missing_pattern_metadata_before": sum(1 for item in before_items if item["missing_pattern_metadata"]),
        "category_fix_required_after": sum(1 for item in after_items if item["category_fix_required"]),
        "label_fix_required_after": sum(1 for item in after_items if item["label_fix_required"]),
        "missing_quality_status_after": sum(1 for item in after_items if item["missing_quality_status"]),
        "missing_pattern_metadata_after": sum(1 for item in after_items if item["missing_pattern_metadata"]),
        "category_updates": category_updates,
        "label_updates": label_updates,
        "quality_refresh": quality_refresh,
        "mode": "execute" if args.execute else "dry_run",
    }

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": summary,
        "items": after_items if args.execute else before_items,
    }

    if args.write_report:
        _write_json(report_path, report)

    print(
        json.dumps(
            {
                "report_path": str(report_path) if args.write_report else None,
                "summary": summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

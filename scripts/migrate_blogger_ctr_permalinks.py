from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
STORAGE_ROOT = REPO_ROOT / "storage"
REPORT_ROOT = STORAGE_ROOT / "reports"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
KST = ZoneInfo("Asia/Seoul")
GENERIC_PERMALINK_RE = re.compile(r"/\d{4}/\d{2}/blog-post(?:_[^./]+)?\.html$", re.IGNORECASE)


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and ((value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"'))):
            value = value[1:-1]
        os.environ[key] = value


_load_runtime_env(RUNTIME_ENV_PATH)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(STORAGE_ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, PostStatus, PublishMode  # noqa: E402
from app.services.platform.publishing_service import (  # noqa: E402
    build_ctr_permalink_title,
    sanitize_blogger_labels_for_article,
    upsert_article_blogger_post,
)
from app.services.providers.factory import get_blogger_provider  # noqa: E402


@dataclass(slots=True)
class MigrationCandidate:
    article_id: int
    job_id: int
    blogger_post_row_id: int
    old_post_id: str
    old_url: str
    old_status: str
    old_title: str
    new_title: str


@dataclass(slots=True)
class MigrationResult:
    article_id: int
    old_post_id: str
    old_url: str
    new_post_id: str
    new_url: str
    new_title: str
    status: str
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate Blogger generic permalinks (blog-post*.html) by re-publishing posts "
            "with CTR-friendly English titles."
        )
    )
    parser.add_argument("--blog-id", type=int, default=37, help="Target Blogger blog id. Defaults to 37 (Japanese channel).")
    parser.add_argument("--execute", action="store_true", help="Apply live mutation. Default is dry-run.")
    parser.add_argument("--report-prefix", default="ja-ctr-permalink-migration", help="Report filename prefix.")
    return parser.parse_args()


def now_kst_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def report_stamp() -> str:
    return datetime.now(KST).strftime("%Y%m%d-%H%M%S")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=lambda value: value.isoformat() if hasattr(value, "isoformat") else str(value),
        ),
        encoding="utf-8",
    )


def is_generic_blogger_permalink(url: str | None) -> bool:
    return bool(GENERIC_PERMALINK_RE.search(str(url or "").strip()))


def _load_blog(db: Session, blog_id: int) -> Blog | None:
    return db.get(Blog, blog_id)


def _load_candidates(db: Session, blog_id: int) -> list[MigrationCandidate]:
    rows = (
        db.execute(
            select(Article)
            .where(Article.blog_id == blog_id)
            .options(
                selectinload(Article.blog),
                selectinload(Article.blogger_post),
            )
            .order_by(Article.id.asc())
        )
        .scalars()
        .all()
    )
    candidates: list[MigrationCandidate] = []
    for article in rows:
        post = article.blogger_post
        if post is None:
            continue
        if post.post_status not in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
            continue
        if not is_generic_blogger_permalink(post.published_url):
            continue
        candidates.append(
            MigrationCandidate(
                article_id=article.id,
                job_id=article.job_id,
                blogger_post_row_id=post.id,
                old_post_id=post.blogger_post_id,
                old_url=post.published_url,
                old_status=post.post_status.value if hasattr(post.post_status, "value") else str(post.post_status),
                old_title=article.title,
                new_title=build_ctr_permalink_title(article),
            )
        )
    return candidates


def _call_with_rate_limit_retry(fn, *, max_attempts: int = 5, base_sleep_seconds: float = 4.0):
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            if attempt >= max_attempts or "429" not in str(exc):
                raise
            wait_seconds = base_sleep_seconds * (2 ** (attempt - 1))
            time.sleep(wait_seconds)


def run(args: argparse.Namespace) -> dict[str, Any]:
    stamp = report_stamp()
    report_path = REPORT_ROOT / f"{args.report_prefix}-{stamp}.json"
    started_at = now_kst_iso()

    with SessionLocal() as db:
        blog = _load_blog(db, args.blog_id)
        if blog is None:
            raise ValueError(f"Blog not found: {args.blog_id}")

        candidates = _load_candidates(db, args.blog_id)
        provider = get_blogger_provider(db, blog)
        provider_type = type(provider).__name__
        provider_is_mock = provider_type.startswith("Mock")
        has_publish = hasattr(provider, "publish")
        has_delete = hasattr(provider, "delete_post")

        results: list[MigrationResult] = []
        migrated_count = 0
        trashed_count = 0
        failed_count = 0

        for candidate in candidates:
            article = db.get(Article, candidate.article_id)
            if article is None or article.blogger_post is None:
                failed_count += 1
                results.append(
                    MigrationResult(
                        article_id=candidate.article_id,
                        old_post_id=candidate.old_post_id,
                        old_url=candidate.old_url,
                        new_post_id="",
                        new_url="",
                        new_title=candidate.new_title,
                        status="failed:article-not-found",
                        error="article_or_blogger_post_missing",
                    )
                )
                continue

            if not args.execute:
                results.append(
                    MigrationResult(
                        article_id=candidate.article_id,
                        old_post_id=candidate.old_post_id,
                        old_url=candidate.old_url,
                        new_post_id="",
                        new_url="",
                        new_title=candidate.new_title,
                        status="dry-run",
                    )
                )
                continue

            if provider_is_mock or not has_publish or not has_delete:
                failed_count += 1
                results.append(
                    MigrationResult(
                        article_id=candidate.article_id,
                        old_post_id=candidate.old_post_id,
                        old_url=candidate.old_url,
                        new_post_id="",
                        new_url="",
                        new_title=candidate.new_title,
                        status="failed:provider-unavailable",
                        error=f"provider={provider_type}",
                    )
                )
                continue

            try:
                sanitized_labels = sanitize_blogger_labels_for_article(article, list(article.labels or []))
                publish_summary, publish_payload = _call_with_rate_limit_retry(
                    lambda: provider.publish(
                        title=candidate.new_title,
                        content=article.assembled_html or article.html_article,
                        labels=sanitized_labels,
                        meta_description=article.meta_description or "",
                        slug=article.slug,
                        publish_mode=PublishMode.PUBLISH,
                    )
                )
                article.title = candidate.new_title
                article.labels = sanitized_labels
                db.add(article)
                upsert_article_blogger_post(
                    db,
                    article=article,
                    summary=publish_summary,
                    raw_payload={
                        "migration_publish": publish_payload if isinstance(publish_payload, dict) else {},
                        "migration_old_post_id": candidate.old_post_id,
                        "migration_old_url": candidate.old_url,
                    },
                )
                migrated_count += 1

                try:
                    _call_with_rate_limit_retry(lambda: provider.delete_post(candidate.old_post_id))
                    trashed_count += 1
                    status = "migrated+trashed"
                    error = ""
                except Exception as delete_exc:  # noqa: BLE001
                    status = "migrated+trash-failed"
                    error = str(delete_exc)

                refreshed_post = article.blogger_post
                results.append(
                    MigrationResult(
                        article_id=candidate.article_id,
                        old_post_id=candidate.old_post_id,
                        old_url=candidate.old_url,
                        new_post_id=str(refreshed_post.blogger_post_id if refreshed_post else ""),
                        new_url=str(refreshed_post.published_url if refreshed_post else ""),
                        new_title=candidate.new_title,
                        status=status,
                        error=error,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                failed_count += 1
                results.append(
                    MigrationResult(
                        article_id=candidate.article_id,
                        old_post_id=candidate.old_post_id,
                        old_url=candidate.old_url,
                        new_post_id="",
                        new_url="",
                        new_title=candidate.new_title,
                        status="failed",
                        error=str(exc),
                    )
                )

    payload = {
        "run_started_at_kst": started_at,
        "run_finished_at_kst": now_kst_iso(),
        "run_mode": "execute" if args.execute else "dry-run",
        "blog_id": args.blog_id,
        "candidate_count": len(candidates),
        "migrated_count": migrated_count,
        "trashed_count": trashed_count,
        "failed_count": failed_count,
        "provider": provider_type,
        "items": [asdict(item) for item in results],
    }
    write_json(report_path, payload)
    return {
        "report_path": str(report_path),
        "summary": {
            "candidate_count": payload["candidate_count"],
            "migrated_count": payload["migrated_count"],
            "trashed_count": payload["trashed_count"],
            "failed_count": payload["failed_count"],
        },
        "run_mode": payload["run_mode"],
        "blog_id": payload["blog_id"],
    }


def main() -> int:
    args = parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

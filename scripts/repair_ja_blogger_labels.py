from __future__ import annotations

import argparse
import json
import os
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
from app.models.entities import Article, Blog, PostStatus  # noqa: E402
from app.services.platform.publishing_service import sanitize_blogger_labels_for_article, upsert_article_blogger_post  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402


@dataclass(slots=True)
class LabelFixItem:
    article_id: int
    blogger_post_id: str
    url: str
    old_labels: list[str]
    new_labels: list[str]
    status: str
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair mojibake labels for Japanese Blogger posts.")
    parser.add_argument("--blog-id", type=int, default=37, help="Target blog id. Defaults to 37.")
    parser.add_argument("--execute", action="store_true", help="Apply live mutations. Default is dry-run.")
    parser.add_argument("--report-prefix", default="ja-label-repair", help="Report filename prefix.")
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


def _call_with_rate_limit_retry(fn, *, max_attempts: int = 5, base_sleep_seconds: float = 4.0):
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            if attempt >= max_attempts or "429" not in str(exc):
                raise
            time.sleep(base_sleep_seconds * (2 ** (attempt - 1)))


def _load_blog(db: Session, blog_id: int) -> Blog | None:
    return db.get(Blog, blog_id)


def _load_targets(db: Session, blog_id: int) -> list[Article]:
    return (
        db.execute(
            select(Article)
            .where(Article.blog_id == blog_id)
            .options(selectinload(Article.blog), selectinload(Article.blogger_post))
            .order_by(Article.id.asc())
        )
        .scalars()
        .all()
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = now_kst_iso()
    report_path = REPORT_ROOT / f"{args.report_prefix}-{report_stamp()}.json"

    with SessionLocal() as db:
        blog = _load_blog(db, args.blog_id)
        if blog is None:
            raise ValueError(f"Blog not found: {args.blog_id}")

        provider = get_blogger_provider(db, blog)
        provider_type = type(provider).__name__
        provider_is_mock = provider_type.startswith("Mock")

        targets: list[Article] = []
        for article in _load_targets(db, args.blog_id):
            post = article.blogger_post
            if post is None:
                continue
            if post.post_status not in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
                continue
            old_labels = [str(item).strip() for item in list(article.labels or []) if str(item).strip()]
            new_labels = sanitize_blogger_labels_for_article(article, old_labels)
            if new_labels != old_labels:
                targets.append(article)

        items: list[LabelFixItem] = []
        fixed_count = 0
        failed_count = 0

        for article in targets:
            post = article.blogger_post
            if post is None:
                continue
            old_labels = [str(item).strip() for item in list(article.labels or []) if str(item).strip()]
            new_labels = sanitize_blogger_labels_for_article(article, old_labels)
            if not args.execute:
                items.append(
                    LabelFixItem(
                        article_id=article.id,
                        blogger_post_id=post.blogger_post_id,
                        url=post.published_url,
                        old_labels=old_labels,
                        new_labels=new_labels,
                        status="dry-run",
                    )
                )
                continue

            if provider_is_mock or not hasattr(provider, "update_post"):
                failed_count += 1
                items.append(
                    LabelFixItem(
                        article_id=article.id,
                        blogger_post_id=post.blogger_post_id,
                        url=post.published_url,
                        old_labels=old_labels,
                        new_labels=new_labels,
                        status="failed:provider-unavailable",
                        error=provider_type,
                    )
                )
                continue

            try:
                summary, raw_payload = _call_with_rate_limit_retry(
                    lambda: provider.update_post(
                        post_id=post.blogger_post_id,
                        title=article.title,
                        content=article.assembled_html or article.html_article,
                        labels=new_labels,
                        meta_description=article.meta_description or "",
                    )
                )
                article.labels = new_labels
                db.add(article)
                upsert_article_blogger_post(
                    db,
                    article=article,
                    summary=summary,
                    raw_payload={
                        "label_repair": raw_payload if isinstance(raw_payload, dict) else {},
                        "old_labels": old_labels,
                    },
                )
                fixed_count += 1
                refreshed = article.blogger_post
                items.append(
                    LabelFixItem(
                        article_id=article.id,
                        blogger_post_id=str(refreshed.blogger_post_id if refreshed else post.blogger_post_id),
                        url=str(refreshed.published_url if refreshed else post.published_url),
                        old_labels=old_labels,
                        new_labels=new_labels,
                        status="updated",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                failed_count += 1
                items.append(
                    LabelFixItem(
                        article_id=article.id,
                        blogger_post_id=post.blogger_post_id,
                        url=post.published_url,
                        old_labels=old_labels,
                        new_labels=new_labels,
                        status="failed",
                        error=str(exc),
                    )
                )

    payload = {
        "run_started_at_kst": started_at,
        "run_finished_at_kst": now_kst_iso(),
        "run_mode": "execute" if args.execute else "dry-run",
        "blog_id": args.blog_id,
        "provider": provider_type,
        "target_count": len(targets),
        "fixed_count": fixed_count,
        "failed_count": failed_count,
        "items": [asdict(item) for item in items],
    }
    write_json(report_path, payload)
    return {
        "report_path": str(report_path),
        "summary": {
            "target_count": payload["target_count"],
            "fixed_count": payload["fixed_count"],
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

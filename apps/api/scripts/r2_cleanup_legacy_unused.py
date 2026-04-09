from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@postgres:5432/bloggent",
    )
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import R2AssetRelayoutMapping, SyncedBloggerPost  # noqa: E402
from app.services.cloudflare_channel_service import _integration_data_or_raise, _integration_request, _list_integration_posts  # noqa: E402
from app.services.storage_service import (  # noqa: E402
    cloudflare_r2_object_size,
    delete_cloudflare_r2_asset,
    normalize_r2_url_to_key,
)

HTML_IMG_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
SRCSET_RE = re.compile(r"\bsrcset=['\"]([^'\"]+)['\"]", re.IGNORECASE)
MD_IMG_RE = re.compile(r"!\[[^\]]*]\(([^)\s]+)\)")
URL_RE = re.compile(r"https?://[^\s'\"<>)\]]+")
LIVE_STATUSES = {"live", "published"}
DELETABLE_EXTENSIONS = (".webp", ".png", ".jpg", ".jpeg")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cleanup legacy unmapped R2 keys after grace period.")
    parser.add_argument("--apply", action="store_true", help="Delete eligible keys. Default is dry-run.")
    parser.add_argument("--grace-days", type=int, default=14, help="Grace period in days.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max mappings to inspect.")
    parser.add_argument("--report-path", default="", help="Optional JSON report path.")
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _extract_srcset_urls(srcset_value: str) -> list[str]:
    urls: list[str] = []
    for part in (srcset_value or "").split(","):
        candidate = part.strip().split(" ")[0].strip()
        if candidate:
            urls.append(candidate)
    return urls


def _extract_image_urls(content: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for pattern in (HTML_IMG_RE, MD_IMG_RE, URL_RE):
        for match in pattern.finditer(content or ""):
            value = _safe_str(match.group(1) if pattern is MD_IMG_RE else match.group(0) if pattern is URL_RE else match.group(1))
            if not value or value in seen:
                continue
            seen.add(value)
            urls.append(value)
    for match in SRCSET_RE.finditer(content or ""):
        for value in _extract_srcset_urls(match.group(1)):
            if not value or value in seen:
                continue
            seen.add(value)
            urls.append(value)
    return urls


def _is_live_status(value: Any) -> bool:
    return _safe_str(value).lower() in LIVE_STATUSES


def _key_is_deletable(key: str) -> bool:
    lowered = key.lower()
    return any(lowered.endswith(ext) for ext in DELETABLE_EXTENSIONS)


def _fetch_cloudflare_post_detail(db, post_id: str) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="GET",
        path=f"/api/integrations/posts/{post_id}",
        timeout=60.0,
    )
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _collect_live_r2_keys(db) -> set[str]:
    keys: set[str] = set()
    blogger_posts = (
        db.execute(
            select(SyncedBloggerPost)
            .where(SyncedBloggerPost.status.in_(["live", "LIVE", "published", "PUBLISHED"]))
            .options(selectinload(SyncedBloggerPost.blog))
            .order_by(SyncedBloggerPost.id.desc())
        )
        .scalars()
        .all()
    )
    for post in blogger_posts:
        urls = _extract_image_urls(post.content_html or "")
        if post.thumbnail_url:
            urls.append(post.thumbnail_url)
        for url in urls:
            key = normalize_r2_url_to_key(url)
            if key and _key_is_deletable(key):
                keys.add(key)

    cloudflare_posts = _list_integration_posts(db)
    for row in cloudflare_posts:
        if not _is_live_status(row.get("status")):
            continue
        post_id = _safe_str(row.get("id"))
        if not post_id:
            continue
        detail = _fetch_cloudflare_post_detail(db, post_id)
        content = _safe_str(detail.get("content") or detail.get("contentMarkdown") or detail.get("content_markdown"))
        cover_image = _safe_str(detail.get("coverImage"))
        urls = _extract_image_urls(content)
        if cover_image:
            urls.append(cover_image)
        for url in urls:
            key = normalize_r2_url_to_key(url)
            if key and _key_is_deletable(key):
                keys.add(key)
    return keys


def main() -> int:
    args = parse_args()
    apply_mode = bool(args.apply)
    grace_days = max(int(args.grace_days or 14), 1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=grace_days)
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "apply": apply_mode,
        "grace_days": grace_days,
        "cutoff": cutoff.isoformat(),
        "summary": {
            "live_keys": 0,
            "mappings_scanned": 0,
            "candidates": 0,
            "deleted": 0,
            "already_missing": 0,
            "skipped_live_reference": 0,
            "failed": 0,
            "deleted_bytes": 0,
        },
        "items": [],
    }

    with SessionLocal() as db:
        live_keys = _collect_live_r2_keys(db)
        report["summary"]["live_keys"] = len(live_keys)

        query = (
            select(R2AssetRelayoutMapping)
            .where(
                R2AssetRelayoutMapping.cleaned_at.is_(None),
                R2AssetRelayoutMapping.created_at <= cutoff,
                R2AssetRelayoutMapping.legacy_key.is_not(None),
            )
            .order_by(R2AssetRelayoutMapping.created_at.asc(), R2AssetRelayoutMapping.id.asc())
        )
        mappings = db.execute(query).scalars().all()
        if args.limit and args.limit > 0:
            mappings = mappings[: int(args.limit)]
        report["summary"]["mappings_scanned"] = len(mappings)

        for mapping in mappings:
            legacy_key = _safe_str(mapping.legacy_key)
            if not legacy_key or not _key_is_deletable(legacy_key):
                continue
            if legacy_key in live_keys:
                report["summary"]["skipped_live_reference"] += 1
                report["items"].append(
                    {
                        "id": mapping.id,
                        "legacy_key": legacy_key,
                        "status": "skipped_live_reference",
                    }
                )
                continue

            report["summary"]["candidates"] += 1
            object_size = cloudflare_r2_object_size(db, public_key="", key=legacy_key)
            if not apply_mode:
                report["items"].append(
                    {
                        "id": mapping.id,
                        "legacy_key": legacy_key,
                        "status": "candidate",
                        "size": object_size,
                    }
                )
                continue

            try:
                if object_size is None:
                    mapping.status = "deleted_missing"
                    mapping.cleaned_at = datetime.now(timezone.utc)
                    db.add(mapping)
                    report["summary"]["already_missing"] += 1
                    report["items"].append(
                        {
                            "id": mapping.id,
                            "legacy_key": legacy_key,
                            "status": "deleted_missing",
                        }
                    )
                    continue

                delete_cloudflare_r2_asset(db, object_key=legacy_key)
                mapping.status = "deleted"
                mapping.cleaned_at = datetime.now(timezone.utc)
                db.add(mapping)
                report["summary"]["deleted"] += 1
                report["summary"]["deleted_bytes"] += int(object_size or 0)
                report["items"].append(
                    {
                        "id": mapping.id,
                        "legacy_key": legacy_key,
                        "status": "deleted",
                        "size": int(object_size or 0),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                mapping.status = "delete_failed"
                mapping.notes = str(exc)
                db.add(mapping)
                report["summary"]["failed"] += 1
                report["items"].append(
                    {
                        "id": mapping.id,
                        "legacy_key": legacy_key,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        db.commit()

    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    print(report_text)
    if args.report_path:
        report_path = Path(args.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

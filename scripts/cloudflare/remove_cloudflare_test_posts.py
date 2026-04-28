from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = None
for candidate in [SCRIPT_PATH] + list(SCRIPT_PATH.parents):
    if (candidate / "apps" / "api" / "app").is_dir():
        REPO_ROOT = candidate
        break
    if (candidate / "app" / "main.py").is_file() and (candidate / "scripts").is_dir():
        REPO_ROOT = candidate.parent
        break
if REPO_ROOT is None:
    if len(SCRIPT_PATH.parents) >= 2:
        REPO_ROOT = SCRIPT_PATH.parents[1]
    else:
        REPO_ROOT = SCRIPT_PATH.parent
API_ROOT = REPO_ROOT / "apps" / "api"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")


def _bootstrap_local_runtime_env() -> None:
    """Load runtime settings file if the process env is missing required values."""
    env_path = REPO_ROOT / "env" / "runtime.settings.env"
    if not env_path.exists():
        return
    raw = env_path.read_text(encoding="utf-8")
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if key not in os.environ or os.environ.get(key) == "":
            os.environ[key] = value.strip()


_bootstrap_local_runtime_env()
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://bloggent:bloggent@127.0.0.1:15432/bloggent")
os.environ.setdefault("SETTINGS_ENCRYPTION_SECRET", "cloudflare-bootstrap-20260418")

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.models.entities import ManagedChannel, SyncedCloudflarePost  # noqa: E402
from app.services.cloudflare.cloudflare_asset_policy import CLOUDFLARE_MANAGED_CHANNEL_ID  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (
    _integration_data_or_raise,
    _integration_request,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


BASE_TEST_PATTERN = re.compile(r"(?:^|[^a-z0-9가-힣])test([^a-z0-9가-힣]|$)", re.IGNORECASE)


DEFAULT_KEYWORDS = ("test", "테스트")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove Cloudflare posts that appear to be test posts.")
    parser.add_argument("--mode", default="dry_run", choices=("dry_run", "execute"))
    parser.add_argument("--channel-id", default=CLOUDFLARE_MANAGED_CHANNEL_ID)
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help="Comma-separated keywords. default: test,테스트",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run remote delete/archive actions immediately. ignored unless mode=execute.",
    )
    parser.add_argument(
        "--archive-on-delete-fail",
        action="store_true",
        default=True,
        help="Fallback to archive when DELETE is blocked.",
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Skip pre/post sync_cloudflare_posts calls. Use for quick execution and run refresh separately.",
    )
    return parser.parse_args()


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _normalize(value: Any) -> str:
    return _safe_text(value).lower()


def _parse_keywords(raw: str) -> list[str]:
    parts = {str(item).strip().lower() for item in raw.replace(";", ",").split(",")}
    return [item for item in sorted(parts) if item]


def _field_hits(post: SyncedCloudflarePost, keyword: str) -> bool:
    fields = [
        _normalize(post.title),
        _normalize(post.slug),
        _normalize(post.url),
        _normalize(post.remote_post_id),
    ]
    if keyword == "test":
        return any(BASE_TEST_PATTERN.search(value) for value in fields)
    if keyword == "테스트":
        return any("테스트" in value for value in fields)
    return any(keyword in value for value in fields)


def _collect_candidates(
    db: Session,
    channel: ManagedChannel,
    keywords: tuple[str, ...],
) -> list[SyncedCloudflarePost]:
    rows = db.execute(
        select(SyncedCloudflarePost).where(
            SyncedCloudflarePost.managed_channel_id == channel.id,
            SyncedCloudflarePost.status.in_(["published", "live", "draft", "pending", "archived", "deleted"]),
        )
    ).scalars().all()

    candidates: list[SyncedCloudflarePost] = []
    for row in rows:
        if any(_field_hits(row, kw) for kw in keywords):
            candidates.append(row)

    candidates.sort(
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return candidates


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _safe_json(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(payload)
    if len(text) > 5000:
        text = text[:5000] + "..."
    return text


def _find_channel(db: Session, channel_id: str) -> ManagedChannel:
    query = select(ManagedChannel).where(
        ManagedChannel.channel_id == channel_id,
        ManagedChannel.provider == "cloudflare",
    )
    channel = db.execute(query).scalar_one_or_none()
    if channel is None:
        raise ValueError(f"Cloudflare channel not found: {channel_id}")
    return channel


def _integration_get_detail(db: Session, remote_post_id: str) -> dict[str, Any] | None:
    response = _integration_request(
        db, method="GET", path=f"/api/integrations/posts/{quote(remote_post_id)}", timeout=45.0
    )
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise ValueError(_safe_json(_integration_data_or_raise(response)))
    payload = _integration_data_or_raise(response)
    return payload if isinstance(payload, dict) else {}


def _delete_post(db: Session, remote_post_id: str, fallback_archive: bool) -> tuple[str, Any]:
    path = f"/api/integrations/posts/{quote(remote_post_id)}"

    delete_response = _integration_request(db, method="DELETE", path=path, timeout=60.0)
    if delete_response.status_code in (200, 204, 202):
        detail: Any = {}
        if delete_response.status_code != 204:
            detail = _integration_data_or_raise(delete_response)
        return ("deleted", detail)

    if delete_response.status_code == 404:
        return ("already_missing", {})

    payload = _safe_json(_integration_data_or_raise(delete_response)) if delete_response.status_code else ""

    if not fallback_archive:
        raise ValueError(f"DELETE failed ({delete_response.status_code}): {payload}")

    archive_response = _integration_request(
        db,
        method="PUT",
        path=path,
        json_payload={"status": "archived"},
        timeout=45.0,
    )
    if archive_response.status_code in (200, 204, 202):
        archive_payload = _integration_data_or_raise(archive_response)
        return ("archived_fallback_after_delete_error", archive_payload)
    if archive_response.status_code == 404:
        return ("already_missing", {})

    archive_error = _safe_json(_integration_data_or_raise(archive_response)) if archive_response else ""
    raise ValueError(
        f"DELETE({delete_response.status_code})={payload}; "
        f"ARCHIVE({archive_response.status_code})={archive_error}"
    )


def _verify_removed(db: Session, remote_post_id: str) -> tuple[bool, str]:
    detail = _integration_get_detail(db, remote_post_id)
    if detail is None:
        return True, "missing"
    status = _normalize(detail.get("status"))
    return status in {"archived", "deleted"}, status or "present"


def _uncategorized_ids(db: Session, channel: ManagedChannel) -> list[str]:
    rows = db.execute(
        select(SyncedCloudflarePost.remote_post_id)
        .where(
            SyncedCloudflarePost.managed_channel_id == channel.id,
            sa.or_(
                SyncedCloudflarePost.canonical_category_slug.is_(None),
                sa.func.trim(SyncedCloudflarePost.canonical_category_slug) == "",
            ),
        )
    ).scalars().all()
    return [str(item) for item in rows]


def main() -> int:
    args = parse_args()
    if args.mode != "execute":
        args.force = False

    mode = _safe_text(args.mode).lower() or "dry_run"
    report_root = Path(args.report_root).resolve()
    report_root.mkdir(parents=True, exist_ok=True)
    keywords = tuple(_parse_keywords(_safe_text(args.keywords)))
    if not keywords:
        raise ValueError("No keywords specified.")

    report_ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_csv = report_root / f"cloudflare-test-cleanup-{report_ts}.csv"
    report_json = report_root / f"cloudflare-test-cleanup-{report_ts}.json"

    summary_rows: list[dict[str, Any]] = []
    execute_actions: Counter[str] = Counter()
    removed_count = 0
    failed_count = 0
    verify_removed_count = 0
    verify_still_exists_count = 0
    before_sync_total = 0
    after_sync_total = 0
    uncategorized_before: list[str] = []
    uncategorized_after: list[str] = []

    with SessionLocal() as db:
        channel = _find_channel(db, args.channel_id)

        if args.skip_sync:
            pre_sync_total = 0
        else:
            pre_sync = sync_cloudflare_posts(db, include_non_published=True)
            before_sync_total = int(pre_sync.get("count") or 0)
        uncategorized_before = _uncategorized_ids(db, channel)

        candidates = _collect_candidates(db, channel, keywords)
        print(f"Cloudflare candidate count: {len(candidates)}")

        for post in candidates:
            matched_keywords = [kw for kw in keywords if _field_hits(post, kw)]
            row = {
                "remote_post_id": _safe_text(post.remote_post_id),
                "slug": _safe_text(post.slug),
                "title": _safe_text(post.title),
                "url": _safe_text(post.url),
                "status": _safe_text(post.status),
                "canonical_category_slug": _safe_text(post.canonical_category_slug),
                "published_at": _safe_text(post.published_at),
                "match_keywords": ",".join(matched_keywords),
                "action": "skip-dry-run",
                "api_status": "",
                "api_error": "",
                "verified": "",
                "verified_status": "",
            }

            if not args.force or mode != "execute":
                summary_rows.append(row)
                continue

            try:
                action, payload = _delete_post(db, row["remote_post_id"], args.archive_on_delete_fail)
                row["action"] = action
                row["api_status"] = "ok"
                row["api_error"] = _safe_json(payload)
                execute_actions[action] += 1

                removed, current_status = _verify_removed(db, row["remote_post_id"])
                row["verified"] = "true" if removed else "false"
                row["verified_status"] = current_status

                if removed:
                    removed_count += 1
                    verify_removed_count += 1
                else:
                    verify_still_exists_count += 1
            except Exception as exc:  # noqa: BLE001
                failed_count += 1
                row["action"] = "error"
                row["api_status"] = "error"
                row["api_error"] = str(exc)
                row["verified"] = "false"
                execute_actions["error"] += 1

            summary_rows.append(row)

        if args.skip_sync:
            after_sync_total = 0
        else:
            post_sync = sync_cloudflare_posts(db, include_non_published=True)
            after_sync_total = int(post_sync.get("count") or 0)
        uncategorized_after = _uncategorized_ids(db, channel)

    _write_csv(
        report_csv,
        summary_rows,
        [
            "remote_post_id",
            "slug",
            "title",
            "url",
            "status",
            "canonical_category_slug",
            "published_at",
            "match_keywords",
            "action",
            "api_status",
            "api_error",
            "verified",
            "verified_status",
        ],
    )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "channel_id": args.channel_id,
        "mode": mode,
        "forced": bool(args.force),
        "keywords": list(keywords),
        "candidate_count": len(summary_rows),
        "pre_sync_total": before_sync_total,
        "post_sync_total": after_sync_total,
        "uncategorized_before_count": len(uncategorized_before),
        "uncategorized_after_count": len(uncategorized_after),
        "removed_or_archived_count": removed_count,
        "failed_count": failed_count,
        "verify_removed_count": verify_removed_count,
        "verify_still_exists_count": verify_still_exists_count,
        "actions": dict(execute_actions),
        "uncategorized_before_ids": uncategorized_before,
        "uncategorized_after_ids": uncategorized_after,
        "report_csv": str(report_csv),
    }
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ManagedChannel, SyncedCloudflarePost
from app.services.cloudflare.cloudflare_asset_policy import (
    CLOUDFLARE_MANAGED_CHANNEL_ID,
    CloudflareAssetPolicy,
    get_cloudflare_asset_policy,
    resolve_cloudflare_local_asset_root,
)
from app.services.cloudflare.cloudflare_channel_service import (
    _integration_data_or_raise,
    _integration_request,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts
from app.services.ops.dedupe_utils import normalize_title
from app.services.platform.platform_service import ensure_managed_channels

LIVE_STATUSES = {"published", "live"}
DELETE_SCOPE_VALUES = {"remote_and_synced", "synced_only"}
KEEP_RULE_VALUES = {"latest_published"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _manifest_dir(policy: CloudflareAssetPolicy) -> Path:
    return resolve_cloudflare_local_asset_root(policy) / "_manifests"


def _coerce_report_item(row: SyncedCloudflarePost, *, normalized_title: str, action: str, keeper_remote_post_id: str | None = None) -> dict[str, Any]:
    return {
        "action": action,
        "id": int(row.id or 0),
        "remote_post_id": str(row.remote_post_id or "").strip(),
        "slug": str(row.slug or "").strip() or None,
        "title": str(row.title or "").strip() or None,
        "category_slug": str(row.canonical_category_slug or row.category_slug or "").strip() or None,
        "status": str(row.status or "").strip() or None,
        "url": str(row.url or "").strip() or None,
        "published_at": row.published_at,
        "normalized_title": normalized_title,
        "keeper_remote_post_id": keeper_remote_post_id,
        "error": None,
    }


def _row_sort_key(row: SyncedCloudflarePost) -> tuple[int, datetime, int]:
    status_rank = 1 if str(row.status or "").strip().lower() in LIVE_STATUSES else 0
    return (status_rank, _as_utc(row.published_at), int(row.id or 0))


def _load_live_rows(db: Session, *, managed_channel_id: int) -> list[SyncedCloudflarePost]:
    return (
        db.execute(
            select(SyncedCloudflarePost)
            .where(
                SyncedCloudflarePost.managed_channel_id == managed_channel_id,
                SyncedCloudflarePost.status.in_(tuple(sorted(LIVE_STATUSES))),
            )
            .order_by(SyncedCloudflarePost.published_at.desc().nullslast(), SyncedCloudflarePost.id.desc())
        )
        .scalars()
        .all()
    )


def _build_duplicate_groups(rows: list[SyncedCloudflarePost]) -> list[dict[str, Any]]:
    grouped: dict[str, list[SyncedCloudflarePost]] = defaultdict(list)
    for row in rows:
        normalized = normalize_title(row.title or row.slug or "")
        if not normalized:
            continue
        grouped[normalized].append(row)

    groups: list[dict[str, Any]] = []
    for normalized_title, items in grouped.items():
        if len(items) <= 1:
            continue
        ordered = sorted(items, key=_row_sort_key, reverse=True)
        keeper = ordered[0]
        losers = ordered[1:]
        groups.append(
            {
                "normalized_title": normalized_title,
                "group_size": len(items),
                "keeper": keeper,
                "losers": losers,
            }
        )
    groups.sort(
        key=lambda item: (
            _as_utc(item["keeper"].published_at),
            int(item["keeper"].id or 0),
            str(item["normalized_title"]),
        ),
        reverse=True,
    )
    return groups


def _delete_remote_post_best_effort(db: Session, *, remote_post_id: str) -> dict[str, Any]:
    delete_payload: dict[str, Any] = {}
    try:
        response = _integration_request(
            db,
            method="DELETE",
            path=f"/api/integrations/posts/{remote_post_id}",
            timeout=60.0,
        )
        try:
            payload = _integration_data_or_raise(response)
        except Exception:
            payload = {}
        delete_payload = payload if isinstance(payload, dict) else {}
    except Exception as exc:  # noqa: BLE001
        return {"deleted": False, "response": {}, "error": str(exc)}

    def _response_status_code(response: Any) -> int | None:
        status = getattr(response, "status_code", None)
        if status is not None:
            try:
                return int(status)
            except (TypeError, ValueError):
                return None
        if isinstance(response, dict):
            for key in ("status_code", "statusCode", "status"):
                raw = response.get(key)
                try:
                    return int(str(raw))
                except (TypeError, ValueError):
                    continue
        return None

    if _response_status_code(response) is None and delete_payload:
        return {"deleted": True, "response": delete_payload, "error": None}

    # Treat delete as successful only when the post becomes unreadable by id.
    # Test/integration doubles may return a plain dict without status_code; in
    # that case a successful delete payload is accepted and the following sync
    # remains responsible for removing the local row.
    verify_deleted = False
    verify_error: str | None = None
    try:
        verify_response = _integration_request(
            db,
            method="GET",
            path=f"/api/integrations/posts/{remote_post_id}",
            timeout=30.0,
        )
        verify_status = _response_status_code(verify_response)
        if verify_status == 404:
            verify_deleted = True
        elif verify_status is None and delete_payload:
            verify_deleted = True
        else:
            verify_error = f"Post still readable after delete (status={verify_status})."
    except Exception as exc:  # noqa: BLE001
        if "(404)" in str(exc):
            verify_deleted = True
        else:
            verify_error = str(exc)

    if verify_deleted:
        return {"deleted": True, "response": delete_payload, "error": None}
    return {
        "deleted": False,
        "response": delete_payload,
        "error": verify_error or "Post still readable after delete request.",
    }


def _write_report_artifacts(*, policy: CloudflareAssetPolicy, report: dict[str, Any]) -> tuple[str, str]:
    manifest_dir = _manifest_dir(policy)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = manifest_dir / f"dedupe-{timestamp}.json"
    csv_path = manifest_dir / f"dedupe-{timestamp}.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")

    rows: list[dict[str, Any]] = []
    rows.extend(report.get("keep_items") or [])
    rows.extend(report.get("delete_candidates") or [])
    rows.extend(report.get("failed_items") or [])
    fieldnames = [
        "action",
        "id",
        "remote_post_id",
        "slug",
        "title",
        "category_slug",
        "status",
        "url",
        "published_at",
        "normalized_title",
        "keeper_remote_post_id",
        "error",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            if isinstance(row, dict):
                writer.writerow(row)
    return str(json_path), str(csv_path)


def dedupe_cloudflare_posts(
    db: Session,
    *,
    mode: str = "dry_run",
    channel_id: str = CLOUDFLARE_MANAGED_CHANNEL_ID,
    delete_scope: str = "remote_and_synced",
    keep_rule: str = "latest_published",
) -> dict[str, Any]:
    normalized_mode = str(mode or "dry_run").strip().lower()
    if normalized_mode not in {"dry_run", "execute"}:
        raise ValueError(f"Unsupported dedupe mode: {mode}")

    normalized_delete_scope = str(delete_scope or "remote_and_synced").strip().lower()
    if normalized_delete_scope not in DELETE_SCOPE_VALUES:
        raise ValueError(f"Unsupported delete_scope: {delete_scope}")

    normalized_keep_rule = str(keep_rule or "latest_published").strip().lower()
    if normalized_keep_rule not in KEEP_RULE_VALUES:
        raise ValueError(f"Unsupported keep_rule: {keep_rule}")

    ensure_managed_channels(db)
    channel = db.execute(select(ManagedChannel).where(ManagedChannel.channel_id == channel_id)).scalar_one_or_none()
    if channel is None or str(channel.provider or "").strip().lower() != "cloudflare":
        raise ValueError(f"Cloudflare channel not found for {channel_id}")
    policy = get_cloudflare_asset_policy(channel)

    initial_sync_result = sync_cloudflare_posts(db, include_non_published=True)
    live_rows = _load_live_rows(db, managed_channel_id=channel.id)
    duplicate_groups = _build_duplicate_groups(live_rows)

    keep_items: list[dict[str, Any]] = []
    delete_candidates: list[dict[str, Any]] = []
    loser_rows: list[SyncedCloudflarePost] = []
    for group in duplicate_groups:
        normalized_title = str(group["normalized_title"])
        keeper = group["keeper"]
        losers = list(group["losers"])
        keep_items.append(_coerce_report_item(keeper, normalized_title=normalized_title, action="keep"))
        for loser in losers:
            loser_rows.append(loser)
            delete_candidates.append(
                _coerce_report_item(
                    loser,
                    normalized_title=normalized_title,
                    action="delete_candidate",
                    keeper_remote_post_id=str(keeper.remote_post_id or "").strip(),
                )
            )

    deleted_count = 0
    delete_failed_count = 0
    failed_items: list[dict[str, Any]] = []
    final_sync_result: dict[str, Any] | None = None

    if normalized_mode == "execute":
        if normalized_delete_scope == "remote_and_synced":
            for row, item in zip(loser_rows, delete_candidates, strict=False):
                delete_result = _delete_remote_post_best_effort(db, remote_post_id=str(row.remote_post_id or "").strip())
                item["delete_result"] = delete_result
                if delete_result["deleted"]:
                    item["action"] = "deleted"
                    deleted_count += 1
                    continue
                item["action"] = "delete_failed"
                item["error"] = delete_result["error"]
                delete_failed_count += 1
                failed_items.append(dict(item))
            final_sync_result = sync_cloudflare_posts(db, include_non_published=True)
        else:
            for row, item in zip(loser_rows, delete_candidates, strict=False):
                db.delete(row)
                item["action"] = "deleted"
                deleted_count += 1
            db.commit()

    remaining_live_count = len(_load_live_rows(db, managed_channel_id=channel.id))
    status = "ok"
    if normalized_mode == "execute":
        if delete_failed_count and deleted_count:
            status = "partial"
        elif delete_failed_count and not deleted_count:
            status = "failed"

    report = {
        "status": status,
        "mode": normalized_mode,
        "channel_id": policy.channel_id,
        "delete_scope": normalized_delete_scope,
        "keep_rule": normalized_keep_rule,
        "generated_at": _utc_now_iso(),
        "initial_sync_result": initial_sync_result,
        "final_sync_result": final_sync_result,
        "total_live_count": len(live_rows),
        "duplicate_group_count": len(duplicate_groups),
        "keep_count": len(keep_items),
        "delete_candidate_count": len(delete_candidates),
        "deleted_count": deleted_count,
        "delete_failed_count": delete_failed_count,
        "remaining_live_count": remaining_live_count,
        "keep_items": keep_items,
        "delete_candidates": delete_candidates,
        "failed_items": failed_items,
    }
    json_path, csv_path = _write_report_artifacts(policy=policy, report=report)
    report["report_path"] = json_path
    report["manifest_path"] = json_path
    report["csv_path"] = csv_path
    return report

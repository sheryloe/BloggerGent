from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ManagedChannel
from app.services.cloudflare.cloudflare_asset_policy import (
    CLOUDFLARE_MANAGED_CHANNEL_ID,
    ensure_cloudflare_channel_metadata,
    get_cloudflare_asset_policy,
    resolve_cloudflare_local_asset_root,
)
from app.services.integrations.storage_service import ensure_cloudflare_r2_bucket
from app.services.platform.platform_service import ensure_managed_channels


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_dir(channel: ManagedChannel) -> Path:
    policy = get_cloudflare_asset_policy(channel)
    return resolve_cloudflare_local_asset_root(policy, prefer_existing=False) / "_manifests"


def _write_bootstrap_report(channel: ManagedChannel, report: dict[str, Any]) -> tuple[str, str]:
    manifest_dir = _manifest_dir(channel)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = manifest_dir / f"bootstrap-{timestamp}.json"
    csv_path = manifest_dir / f"bootstrap-{timestamp}.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    rows: list[dict[str, str]] = []
    for category_slug in report.get("created_categories") or []:
        rows.append({"kind": "category", "value": str(category_slug), "status": "created"})
    for object_key in report.get("sample_uploaded_keys") or []:
        rows.append({"kind": "sample_object_key", "value": str(object_key), "status": "verified"})
    if not rows:
        rows.append({"kind": "summary", "value": str(report.get("bucket_name") or ""), "status": str(report.get("status") or "")})

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["kind", "value", "status"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return str(json_path), str(csv_path)


def bootstrap_cloudflare_assets(
    db: Session,
    *,
    channel_id: str = CLOUDFLARE_MANAGED_CHANNEL_ID,
    bucket_name: str = "dongriarchive-cloudflare",
    create_missing_categories: bool = True,
    backfill_channel_metadata: bool = True,
    verify_bucket: bool = True,
    create_if_missing: bool = False,
) -> dict[str, Any]:
    ensure_managed_channels(db)
    channel = db.execute(select(ManagedChannel).where(ManagedChannel.channel_id == channel_id)).scalar_one_or_none()
    if channel is None:
        raise ValueError(f"Cloudflare managed channel not found: {channel_id}")

    metadata_updated = False
    if backfill_channel_metadata:
        merged_metadata = ensure_cloudflare_channel_metadata(dict(channel.channel_metadata or {}))
        if dict(channel.channel_metadata or {}) != merged_metadata:
            channel.channel_metadata = merged_metadata
            db.add(channel)
            metadata_updated = True
    if metadata_updated:
        db.commit()
        db.refresh(channel)

    policy = get_cloudflare_asset_policy(channel)
    local_root = resolve_cloudflare_local_asset_root(policy, prefer_existing=False)
    local_root.mkdir(parents=True, exist_ok=True)
    (local_root / "_manifests").mkdir(parents=True, exist_ok=True)

    created_categories: list[str] = []
    if create_missing_categories:
        for category_slug in policy.allowed_category_slugs:
            target_dir = local_root / category_slug
            if not target_dir.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                created_categories.append(category_slug)

    bucket_result = ensure_cloudflare_r2_bucket(
        db,
        bucket_name=bucket_name,
        verify=verify_bucket,
        create_if_missing=create_if_missing,
    )

    report = {
        "status": "ok",
        "channel_id": channel_id,
        "generated_at": _utc_now_iso(),
        "bucket_name": str(bucket_result.get("bucket_name") or bucket_name),
        "bucket_created": bool(bucket_result.get("bucket_created")),
        "bucket_verified": bool(bucket_result.get("bucket_verified")),
        "created_categories": created_categories,
        "backfilled_metadata": backfill_channel_metadata,
        "metadata_updated": metadata_updated,
        "local_asset_root": str(local_root),
        "sample_uploaded_keys": list(bucket_result.get("sample_uploaded_keys") or []),
    }
    json_path, csv_path = _write_bootstrap_report(channel, report)
    report["report_path"] = json_path
    report["manifest_path"] = json_path
    report["csv_path"] = csv_path
    return report

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from typing import Any

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ManagedChannel
from app.services.cloudflare.cloudflare_asset_policy import (
    CLOUDFLARE_MANAGED_CHANNEL_ID,
    ensure_cloudflare_channel_metadata,
    get_cloudflare_asset_policy,
    resolve_cloudflare_local_asset_root,
)
from app.services.integrations.settings_service import get_settings_map
from app.services.integrations.storage_service import (
    delete_cloudflare_r2_asset,
    ensure_cloudflare_r2_bucket,
    upload_binary_to_cloudflare_r2,
)
from app.services.platform.platform_service import ensure_managed_channels


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_dir(channel: ManagedChannel) -> Path:
    policy = get_cloudflare_asset_policy(channel)
    return resolve_cloudflare_local_asset_root(policy, prefer_existing=False) / "_manifests"


def _probe_image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (2, 2), color=(24, 120, 220)).save(output, format="WEBP", quality=80, method=6)
    return output.getvalue()


def _resolve_integration_assets_public_base_url(db: Session) -> str:
    values = get_settings_map(db)
    integration_base_url = str(values.get("cloudflare_blog_api_base_url") or "").strip().rstrip("/")
    if not integration_base_url:
        raise ValueError("cloudflare_blog_api_base_url must be configured for integration_proxy verification.")
    return f"{integration_base_url}/assets"


def _verify_public_probe_url(url: str) -> tuple[bool, int | None, str]:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return False, None, ""
    try:
        response = httpx.head(normalized_url, follow_redirects=True, timeout=20.0)
        content_type = str(response.headers.get("Content-Type") or response.headers.get("content-type") or "").strip()
        if response.status_code == 405 or response.status_code >= 400 or not content_type.lower().startswith("image/"):
            response = httpx.get(
                normalized_url,
                headers={"Range": "bytes=0-0"},
                follow_redirects=True,
                timeout=20.0,
            )
            content_type = str(response.headers.get("Content-Type") or response.headers.get("content-type") or "").strip()
        return response.status_code < 400 and content_type.lower().startswith("image/"), int(response.status_code), content_type
    except Exception:  # noqa: BLE001
        return False, None, ""


def _verify_integration_proxy_transport(db: Session) -> dict[str, Any]:
    public_base_url = _resolve_integration_assets_public_base_url(db)
    probe_key = f"assets/media/cloudflare/dongri-archive/bootstrap/{int(datetime.now(timezone.utc).timestamp())}-integration-probe.webp"
    upload_payload: dict[str, Any] = {}
    public_url = ""
    try:
        public_url, upload_payload, _delivery_meta = upload_binary_to_cloudflare_r2(
            db,
            object_key=probe_key,
            filename=Path(probe_key).name,
            content=_probe_image_bytes(),
            public_base_url_override=public_base_url,
            force_integration_proxy=True,
        )
        verified, status_code, content_type = _verify_public_probe_url(public_url)
        if not verified:
            raise ValueError(
                f"integration_proxy_public_url_unreachable status={status_code or 'error'} content_type={content_type or 'unknown'} url={public_url}"
            )
        return {
            "transport_verified": True,
            "sample_uploaded_keys": [str(upload_payload.get("object_key") or probe_key).strip()],
            "sample_public_urls": [public_url],
            "public_base_url": str(upload_payload.get("public_base_url") or public_base_url).strip(),
        }
    finally:
        resolved_object_key = str(upload_payload.get("object_key") or probe_key).strip()
        if resolved_object_key:
            try:
                delete_cloudflare_r2_asset(db, object_key=resolved_object_key)
            except Exception:  # noqa: BLE001
                pass


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
    verify_transport: str = "direct_bucket",
) -> dict[str, Any]:
    normalized_verify_transport = str(verify_transport or "direct_bucket").strip().lower()
    if normalized_verify_transport not in {"direct_bucket", "integration_proxy"}:
        raise ValueError(f"Unsupported verify_transport: {verify_transport}")

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
        verify=verify_bucket and normalized_verify_transport == "direct_bucket",
        create_if_missing=create_if_missing,
    )
    transport_verified = bool(bucket_result.get("bucket_verified")) if normalized_verify_transport == "direct_bucket" else False
    sample_uploaded_keys = list(bucket_result.get("sample_uploaded_keys") or [])
    sample_public_urls: list[str] = []
    public_base_url = str(bucket_result.get("public_base_url") or "").strip()
    if verify_bucket and normalized_verify_transport == "integration_proxy":
        transport_result = _verify_integration_proxy_transport(db)
        transport_verified = bool(transport_result.get("transport_verified"))
        sample_uploaded_keys = list(transport_result.get("sample_uploaded_keys") or [])
        sample_public_urls = list(transport_result.get("sample_public_urls") or [])
        public_base_url = str(transport_result.get("public_base_url") or public_base_url).strip()

    report = {
        "status": "ok",
        "channel_id": channel_id,
        "generated_at": _utc_now_iso(),
        "verify_transport": normalized_verify_transport,
        "bucket_name": str(bucket_result.get("bucket_name") or bucket_name),
        "bucket_exists": bool(bucket_result.get("bucket_exists")),
        "bucket_created": bool(bucket_result.get("bucket_created")),
        "bucket_verified": bool(bucket_result.get("bucket_verified")),
        "transport_verified": transport_verified,
        "created_categories": created_categories,
        "backfilled_metadata": backfill_channel_metadata,
        "metadata_updated": metadata_updated,
        "local_asset_root": str(local_root),
        "public_base_url": public_base_url,
        "sample_uploaded_keys": sample_uploaded_keys,
        "sample_public_urls": sample_public_urls,
    }
    json_path, csv_path = _write_bootstrap_report(channel, report)
    report["report_path"] = json_path
    report["manifest_path"] = json_path
    report["csv_path"] = csv_path
    return report

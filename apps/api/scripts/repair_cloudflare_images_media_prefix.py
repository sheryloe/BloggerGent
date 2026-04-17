from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


def _repo_root() -> Path:
    configured = os.environ.get("BLOGGENT_REPO_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    cursor = Path(__file__).resolve().parent
    for candidate in [cursor, *cursor.parents]:
        if (candidate / "apps" / "api").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _bootstrap_runtime_env() -> None:
    if RUNTIME_ENV_PATH.exists():
        for line in RUNTIME_ENV_PATH.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value
    os.environ.setdefault(
        "DATABASE_URL",
        os.environ.get("BLOGGENT_DATABASE_URL", "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"),
    )
    os.environ.setdefault("STORAGE_ROOT", str(REPO_ROOT / "storage"))


_bootstrap_runtime_env()

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import SyncedCloudflarePost  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _fetch_integration_post_detail,
    _integration_data_or_raise,
    _integration_request,
    list_cloudflare_categories,
)
from app.services.cloudflare.cloudflare_codex_write_service import (  # noqa: E402
    CLOUDFLARE_MEDIA_URL_PREFIX,
    _asset_key_from_url,
    _build_backup_json_index,
    _build_local_backup_image_index,
    _collect_live_image_inventory,
    _disallowed_source_images,
    _extract_existing_image_urls,
    _extract_tag_names,
    _insert_inline_image_before_faq_or_closing,
    _is_cloudflare_media_asset,
    _normalize_space,
    _normalize_source_post_snapshot,
    _report_path,
    _resolve_cloudflare_r2_configuration,
    _resolve_payload_images,
    _resolve_reachable_asset_url,
    _seed_package_from_post,
    get_codex_write_root,
)
from app.services.integrations.settings_service import get_settings_map  # noqa: E402

LIVE_STATUSES = {"published", "live"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repair Cloudflare live posts whose image URLs regressed to "
            "'/assets/assets/images/...'."
        ),
    )
    parser.add_argument(
        "--where-images-prefix-only",
        action="store_true",
        help="Only target rows where thumbnail_url uses /assets/assets/images/ prefix.",
    )
    parser.add_argument(
        "--mode",
        choices=("restore_or_generate",),
        default="restore_or_generate",
        help="Image resolution policy.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of rows to process.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve and validate without PUT update.")
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _list_targets(db: Session, *, images_prefix_only: bool, limit: int) -> list[SyncedCloudflarePost]:
    stmt = (
        select(SyncedCloudflarePost)
        .where(SyncedCloudflarePost.status.in_(list(LIVE_STATUSES)))
        .order_by(SyncedCloudflarePost.updated_at.desc().nullslast(), SyncedCloudflarePost.id.desc())
    )
    if images_prefix_only:
        stmt = stmt.where(SyncedCloudflarePost.thumbnail_url.like("%/assets/assets/images/%"))
    rows = db.execute(stmt).scalars().all()
    return rows[:limit] if limit > 0 else rows


def _replace_inline_image_url(content: str, *, old_url: str, new_url: str, alt: str) -> str:
    body = str(content or "")
    old_candidate = _normalize_space(old_url)
    new_candidate = _normalize_space(new_url)
    if not body or not new_candidate:
        return body
    if old_candidate and old_candidate != new_candidate and old_candidate in body:
        return body.replace(old_candidate, new_candidate)
    existing = _extract_existing_image_urls(body)
    if existing:
        first = _normalize_space(existing[0])
        if first and first != new_candidate and first in body:
            return body.replace(first, new_candidate, 1)
    if new_candidate in body:
        return body
    return _insert_inline_image_before_faq_or_closing(body, inline_url=new_candidate, inline_alt=alt)


def _validate_repaired_images(
    *,
    cover_url: str,
    cover_key: str,
    inline_url: str,
    inline_key: str,
    public_base_url: str,
) -> list[str]:
    errors: list[str] = []
    normalized_cover = _normalize_space(cover_url)
    normalized_inline = _normalize_space(inline_url)
    if not normalized_cover:
        errors.append("cover_image_missing")
    if not normalized_inline:
        errors.append("inline_image_missing")
    if normalized_cover == normalized_inline and normalized_cover:
        errors.append("duplicate_image_within_post")
    if normalized_cover and not _is_cloudflare_media_asset(
        normalized_cover,
        asset_key=cover_key,
        public_base_url=public_base_url,
    ):
        errors.append("invalid_image_prefix")
    if normalized_inline and not _is_cloudflare_media_asset(
        normalized_inline,
        asset_key=inline_key,
        public_base_url=public_base_url,
    ):
        errors.append("invalid_image_prefix")
    return errors


def _build_update_payload(
    *,
    row: SyncedCloudflarePost,
    detail: dict[str, Any],
    category_id: str,
    cover_url: str,
    cover_alt: str,
    inline_url: str,
    inline_alt: str,
    old_inline_url: str,
) -> dict[str, Any]:
    title = _normalize_space(detail.get("title") or row.title)
    excerpt = _normalize_space(detail.get("excerpt") or row.excerpt_text)
    seo_title = _normalize_space(detail.get("seoTitle") or row.seo_title or title)
    seo_description = _normalize_space(detail.get("seoDescription") or row.meta_description or excerpt or title)
    status = _normalize_space(detail.get("status") or row.status or "published").lower()
    content = str(detail.get("content") or detail.get("contentMarkdown") or row.content_html or "")
    patched_content = _replace_inline_image_url(
        content,
        old_url=old_inline_url,
        new_url=inline_url,
        alt=inline_alt or title,
    )
    tag_names = detail.get("tagNames")
    if not isinstance(tag_names, list) or not tag_names:
        tag_names = _extract_tag_names(detail, row)
    payload: dict[str, Any] = {
        "title": title,
        "content": patched_content,
        "excerpt": excerpt,
        "seoTitle": seo_title,
        "seoDescription": seo_description,
        "tagNames": tag_names,
        "categoryId": category_id,
        "status": status if status in LIVE_STATUSES else "published",
        "coverImage": cover_url,
        "coverAlt": cover_alt or seo_description or title,
        "slug": _normalize_space(detail.get("slug") or row.slug),
    }
    metadata = detail.get("metadata")
    if isinstance(metadata, dict) and metadata:
        payload["metadata"] = metadata
    return payload


def main() -> int:
    args = parse_args()
    root = get_codex_write_root()
    with SessionLocal() as db:
        settings_map = get_settings_map(db)
        (
            account_id,
            bucket,
            access_key_id,
            secret_access_key,
            public_base_url,
            _,
        ) = _resolve_cloudflare_r2_configuration(settings_map)
        r2_listing_context = None
        if account_id and bucket and access_key_id and secret_access_key:
            r2_listing_context = {
                "account_id": account_id,
                "bucket": bucket,
                "access_key_id": access_key_id,
                "secret_access_key": secret_access_key,
            }
        r2_unused_cache: dict[str, list[dict[str, Any]]] = {}
        backup_index = _build_backup_json_index(REPO_ROOT)
        local_index = _build_local_backup_image_index(REPO_ROOT)
        live_inventory = _collect_live_image_inventory(
            db,
            public_base_url=public_base_url,
            backup_index=backup_index,
        )
        batch_used_urls = set(live_inventory["urls"])
        batch_used_asset_keys = set(live_inventory["asset_keys"])
        category_map = {
            _normalize_space(item.get("slug")): _normalize_space(item.get("id"))
            for item in list_cloudflare_categories(db)
            if bool(item.get("isLeaf"))
        }

        rows = _list_targets(
            db,
            images_prefix_only=bool(args.where_images_prefix_only),
            limit=int(args.limit or 0),
        )
        items: list[dict[str, Any]] = []
        updated_count = 0
        failed_count = 0
        skipped_count = 0

        for row in rows:
            remote_post_id = _normalize_space(row.remote_post_id)
            if not remote_post_id:
                skipped_count += 1
                items.append(
                    {
                        "status": "skipped",
                        "reason": "missing_remote_post_id",
                        "remote_post_id": "",
                        "slug": _normalize_space(row.slug),
                    },
                )
                continue
            detail = _fetch_integration_post_detail(db, remote_post_id=remote_post_id)
            payload = _seed_package_from_post(row, detail)
            payload["target_slug"] = _normalize_space(payload.get("original_slug") or payload.get("slug"))
            old_cover = _normalize_space(payload.get("cover_image", {}).get("url"))
            old_inline = _normalize_space(payload.get("inline_image", {}).get("url"))
            _normalize_source_post_snapshot(
                payload,
                cover_image_url=old_cover,
                inline_image_url=old_inline,
            )
            current_urls, current_asset_keys = _disallowed_source_images(payload, public_base_url=public_base_url)
            working_used_urls = {item for item in batch_used_urls if item not in current_urls}
            working_used_asset_keys = {item for item in batch_used_asset_keys if item not in current_asset_keys}
            _resolve_payload_images(
                db,
                payload=payload,
                public_base_url=public_base_url,
                used_urls=working_used_urls,
                used_asset_keys=working_used_asset_keys,
                backup_index=backup_index,
                local_index=local_index,
                r2_listing_context=r2_listing_context,
                r2_unused_cache=r2_unused_cache,
            )
            cover_image = payload.get("cover_image") if isinstance(payload.get("cover_image"), dict) else {}
            inline_image = payload.get("inline_image") if isinstance(payload.get("inline_image"), dict) else {}
            resolved_cover = _resolve_reachable_asset_url(cover_image.get("url"), public_base_url=public_base_url) or _normalize_space(cover_image.get("url"))
            resolved_inline = _resolve_reachable_asset_url(inline_image.get("url"), public_base_url=public_base_url) or _normalize_space(inline_image.get("url"))
            cover_key = _normalize_space(cover_image.get("asset_key")) or _asset_key_from_url(resolved_cover, public_base_url=public_base_url)
            inline_key = _normalize_space(inline_image.get("asset_key")) or _asset_key_from_url(resolved_inline, public_base_url=public_base_url)
            errors = _validate_repaired_images(
                cover_url=resolved_cover,
                cover_key=cover_key,
                inline_url=resolved_inline,
                inline_key=inline_key,
                public_base_url=public_base_url,
            )
            category_slug = _normalize_space(payload.get("category_slug"))
            category_id = category_map.get(category_slug) or _normalize_space(detail.get("categoryId"))
            if not category_id:
                errors.append(f"unknown_category:{category_slug}")
            mode = "generated" if {
                _normalize_space(cover_image.get("source")),
                _normalize_space(inline_image.get("source")),
            } & {"generated_collage"} else "restored"
            item: dict[str, Any] = {
                "remote_post_id": remote_post_id,
                "slug": _normalize_space(row.slug),
                "old_cover": old_cover,
                "new_cover": resolved_cover,
                "old_inline": old_inline,
                "new_inline": resolved_inline,
                "mode": mode,
                "errors": errors,
            }
            if errors:
                failed_count += 1
                item["status"] = "failed"
                items.append(item)
                continue
            if args.dry_run:
                skipped_count += 1
                item["status"] = "dry_run_ready"
                items.append(item)
                continue
            update_payload = _build_update_payload(
                row=row,
                detail=detail,
                category_id=category_id,
                cover_url=resolved_cover,
                cover_alt=_normalize_space(cover_image.get("alt")),
                inline_url=resolved_inline,
                inline_alt=_normalize_space(inline_image.get("alt")),
                old_inline_url=old_inline,
            )
            response = _integration_request(
                db,
                method="PUT",
                path=f"/api/integrations/posts/{remote_post_id}",
                json_payload=update_payload,
                timeout=120.0,
            )
            updated_post = _integration_data_or_raise(response)
            item["status"] = "updated"
            item["publish_url"] = _normalize_space(updated_post.get("publicUrl") if isinstance(updated_post, dict) else "")
            updated_count += 1
            batch_used_urls.update(
                {
                    _normalize_space(resolved_cover),
                    _normalize_space(resolved_inline),
                },
            )
            if cover_key:
                batch_used_asset_keys.add(cover_key)
            if inline_key:
                batch_used_asset_keys.add(inline_key)
            items.append(item)

        report_path = _report_path(root, "repair-images-media-prefix")
        report = {
            "generated_at": _utc_now_iso(),
            "dry_run": bool(args.dry_run),
            "mode": _normalize_space(args.mode),
            "filter_images_prefix_only": bool(args.where_images_prefix_only),
            "target_count": len(rows),
            "updated_count": updated_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "expected_prefix": CLOUDFLARE_MEDIA_URL_PREFIX,
            "items": items,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "ok" if failed_count == 0 else "partial", "report_path": str(report_path), **{k: report[k] for k in ("target_count", "updated_count", "failed_count", "skipped_count")}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

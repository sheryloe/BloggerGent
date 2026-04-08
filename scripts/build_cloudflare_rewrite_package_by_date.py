#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent",
    )
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from package_common import (  # noqa: E402
    CloudflareIntegrationClient,
    REWRITE_PACKAGE_ROOT,
    SessionLocal,
    cloudflare_slug_from_url,
    collect_markdown_asset_refs,
    detect_broken_text,
    extract_tag_names,
    normalize_space,
    safe_filename,
    write_csv_utf8,
    write_json,
    write_text_utf8,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a Cloudflare rewrite package for published posts in a local date range. "
            "This script does not generate new content; it exports snapshots + drafts for manual rewrite."
        )
    )
    parser.add_argument("--start-date", required=True, help="Local start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", required=True, help="Local end date (YYYY-MM-DD).")
    parser.add_argument("--timezone", default="Asia/Seoul", help="IANA timezone name. Default: Asia/Seoul.")
    parser.add_argument(
        "--package-date",
        required=True,
        help="Package folder name under storage/rewrite-packages (e.g. 2026-04-07-cloudflare-rewrite).",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of posts to export.")
    return parser.parse_args()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    raw = normalize_space(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_local_date(value: str | None, tz: ZoneInfo) -> str:
    dt = _parse_iso_datetime(value)
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date().isoformat()


def _resolve_range(args: argparse.Namespace) -> tuple[date, date]:
    try:
        start_date = date.fromisoformat(normalize_space(args.start_date))
        end_date = date.fromisoformat(normalize_space(args.end_date))
    except ValueError as exc:  # noqa: BLE001
        raise ValueError("Date format must be YYYY-MM-DD.") from exc
    if start_date > end_date:
        raise ValueError("--start-date must be less than or equal to --end-date.")
    return start_date, end_date


def build_manifest_row(
    *,
    detail: dict[str, Any],
    markdown_path: Path,
    snapshot_path: Path,
    published_local_date: str,
) -> dict[str, Any]:
    category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
    tags = extract_tag_names(detail)
    content = str(detail.get("content") or "")
    title = normalize_space(str(detail.get("title") or ""))
    excerpt = normalize_space(str(detail.get("excerpt") or ""))
    seo_title = normalize_space(str(detail.get("seoTitle") or ""))
    seo_description = normalize_space(str(detail.get("seoDescription") or ""))
    slug = normalize_space(str(detail.get("slug") or ""))
    url = normalize_space(str(detail.get("publicUrl") or detail.get("url") or ""))
    post_id = normalize_space(str(detail.get("id") or ""))
    return {
        "review_status": "draft",
        "published_local_date": published_local_date,
        "source_slug": slug,
        "source_url": url,
        "post_id": post_id,
        "current_title": title,
        "new_title": title,
        "current_excerpt": excerpt,
        "new_excerpt": excerpt,
        "current_seo_title": seo_title,
        "new_seo_title": seo_title,
        "current_seo_description": seo_description,
        "new_seo_description": seo_description,
        "current_category": normalize_space(str(category.get("name") or category.get("slug") or "")),
        "target_category": normalize_space(str(category.get("name") or category.get("slug") or "")),
        "action": "range_rewrite",
        "tags": "|".join(tags),
        "published_at": normalize_space(str(detail.get("publishedAt") or detail.get("published_at") or "")),
        "status": normalize_space(str(detail.get("status") or "")),
        "cover_image": normalize_space(str(detail.get("coverImage") or "")),
        "inline_asset_count": len(collect_markdown_asset_refs(content)),
        "notes": (
            "Rewrite full article for CTR/SEO while preserving slug, cover image, and all inline assets. "
            "Update title/excerpt/seoDescription/tagNames as needed."
        ),
        "markdown_path": str(markdown_path),
        "snapshot_json_path": str(snapshot_path),
    }


def run() -> int:
    args = parse_args()
    start_date, end_date = _resolve_range(args)
    tz = ZoneInfo(args.timezone)

    package_root = (REWRITE_PACKAGE_ROOT / args.package_date).resolve()
    channel_root = package_root / "dongri-archive"
    drafts_root = channel_root / "drafts"
    snapshots_root = channel_root / "snapshots"
    channel_root.mkdir(parents=True, exist_ok=True)
    drafts_root.mkdir(parents=True, exist_ok=True)
    snapshots_root.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, Any]] = []
    manifest_json: list[dict[str, Any]] = []

    with SessionLocal() as db:
        client = CloudflareIntegrationClient.from_db(db)
        summaries = client.list_posts()

        targets: list[dict[str, Any]] = []
        for item in summaries:
            if not isinstance(item, dict):
                continue
            if normalize_space(str(item.get("status") or "")).lower() != "published":
                continue
            local_date = _to_local_date(
                str(
                    item.get("publishedAt")
                    or item.get("published_at")
                    or item.get("updatedAt")
                    or item.get("createdAt")
                    or ""
                ),
                tz,
            )
            if not local_date:
                continue
            try:
                candidate = date.fromisoformat(local_date)
            except ValueError:
                continue
            if not (start_date <= candidate <= end_date):
                continue
            targets.append(item)

        targets.sort(key=lambda row: str(row.get("publishedAt") or row.get("published_at") or row.get("updatedAt") or ""))
        if args.limit > 0:
            targets = targets[: max(int(args.limit), 1)]

        if not targets:
            raise RuntimeError(
                f"No published Cloudflare posts found in range {start_date.isoformat()}~{end_date.isoformat()} ({args.timezone})."
            )

        for item in targets:
            post_id = normalize_space(str(item.get("id") or ""))
            if not post_id:
                continue
            detail = client.get_post(post_id)
            if not isinstance(detail, dict) or not detail:
                continue

            content = str(detail.get("content") or "")
            title = normalize_space(str(detail.get("title") or ""))
            if detect_broken_text(title) or detect_broken_text(content):
                slug_hint = normalize_space(str(detail.get("slug") or item.get("slug") or ""))
                raise RuntimeError(f"Detected broken text in Cloudflare source snapshot: {slug_hint or post_id}")

            slug = normalize_space(str(detail.get("slug") or item.get("slug") or ""))
            if not slug:
                slug = cloudflare_slug_from_url(str(detail.get("publicUrl") or item.get("publicUrl") or item.get("url") or ""))
            if not slug:
                slug = f"post-{post_id}"

            file_stem = safe_filename(f"{post_id}-{slug}", fallback=post_id or slug)
            markdown_path = drafts_root / f"{file_stem}.md"
            snapshot_path = snapshots_root / f"{file_stem}.json"

            if content.strip():
                write_text_utf8(markdown_path, content)
            else:
                write_text_utf8(markdown_path, f"# {title or slug}\n")
            write_json(snapshot_path, detail)

            published_local_date = _to_local_date(
                str(
                    detail.get("publishedAt")
                    or detail.get("published_at")
                    or item.get("publishedAt")
                    or item.get("published_at")
                    or item.get("updatedAt")
                    or ""
                ),
                tz,
            )

            row = build_manifest_row(
                detail=detail,
                markdown_path=markdown_path,
                snapshot_path=snapshot_path,
                published_local_date=published_local_date,
            )
            manifest_rows.append(row)
            manifest_json.append(row)

    manifest_path = channel_root / "manifest.csv"
    manifest_json_path = channel_root / "manifest.json"
    write_csv_utf8(
        manifest_path,
        manifest_rows,
        [
            "review_status",
            "published_local_date",
            "source_slug",
            "source_url",
            "post_id",
            "current_title",
            "new_title",
            "current_excerpt",
            "new_excerpt",
            "current_seo_title",
            "new_seo_title",
            "current_seo_description",
            "new_seo_description",
            "current_category",
            "target_category",
            "action",
            "tags",
            "published_at",
            "status",
            "cover_image",
            "inline_asset_count",
            "notes",
            "markdown_path",
            "snapshot_json_path",
        ],
    )
    write_json(manifest_json_path, manifest_json)

    metadata_path = package_root / "package-metadata.json"
    write_json(
        metadata_path,
        {
            "kind": "cloudflare-range-rewrite",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "timezone": args.timezone,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "target_count": len(manifest_rows),
        },
    )

    print(
        json.dumps(
            {
                "package_root": str(package_root),
                "kind": "cloudflare-range-rewrite",
                "timezone": args.timezone,
                "range": f"{start_date.isoformat()}~{end_date.isoformat()}",
                "target_count": len(manifest_rows),
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())


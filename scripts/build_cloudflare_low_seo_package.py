from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from package_common import (
    DEFAULT_LOW_SEO_REPORT,
    REWRITE_PACKAGE_ROOT,
    SessionLocal,
    CloudflareIntegrationClient,
    cloudflare_slug_from_url,
    collect_markdown_asset_refs,
    detect_broken_text,
    extract_tag_names,
    load_low_seo_rows,
    normalize_space,
    safe_filename,
    write_csv_utf8,
    write_json,
    write_text_utf8,
)


DEFAULT_PACKAGE_DATE = "2026-04-02-cloudflare-low-seo"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Cloudflare-only package for posts listed in the low-SEO report.")
    parser.add_argument("--package-date", default=DEFAULT_PACKAGE_DATE)
    parser.add_argument("--low-seo-report", default=str(DEFAULT_LOW_SEO_REPORT))
    return parser.parse_args()


def build_row(detail: dict[str, Any], markdown_path: Path, snapshot_path: Path) -> dict[str, Any]:
    category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
    tags = extract_tag_names(detail)
    content = str(detail.get("content") or "")
    return {
        "review_status": "draft",
        "source_slug": normalize_space(str(detail.get("slug") or "")),
        "source_url": normalize_space(str(detail.get("publicUrl") or "")),
        "post_id": normalize_space(str(detail.get("id") or "")),
        "current_title": normalize_space(str(detail.get("title") or "")),
        "new_title": normalize_space(str(detail.get("title") or "")),
        "current_excerpt": normalize_space(str(detail.get("excerpt") or "")),
        "new_excerpt": normalize_space(str(detail.get("excerpt") or "")),
        "current_seo_title": normalize_space(str(detail.get("seoTitle") or "")),
        "new_seo_title": normalize_space(str(detail.get("seoTitle") or "")),
        "current_seo_description": normalize_space(str(detail.get("seoDescription") or "")),
        "new_seo_description": normalize_space(str(detail.get("seoDescription") or "")),
        "current_category": normalize_space(str(category.get("name") or category.get("slug") or "")),
        "target_category": normalize_space(str(category.get("name") or category.get("slug") or "")),
        "action": "seo_patch",
        "tags": "|".join(tags),
        "published_at": normalize_space(str(detail.get("publishedAt") or "")),
        "status": normalize_space(str(detail.get("status") or "")),
        "cover_image": normalize_space(str(detail.get("coverImage") or "")),
        "inline_asset_count": len(collect_markdown_asset_refs(content)),
        "notes": "Preserve slug, cover image, inline assets, related links, and overall structure. Edit only SEO/CTR text.",
        "markdown_path": str(markdown_path),
        "snapshot_json_path": str(snapshot_path),
    }


def run() -> int:
    args = parse_args()
    report_path = Path(args.low_seo_report).resolve()
    report_rows = load_low_seo_rows(report_path)
    if len(report_rows) != 77:
        raise ValueError(f"Expected 77 Cloudflare rows in low SEO report, got {len(report_rows)}")

    output_root = REWRITE_PACKAGE_ROOT / args.package_date
    drafts_root = output_root / "dongri-archive" / "drafts"
    snapshots_root = output_root / "dongri-archive" / "snapshots"
    output_root.mkdir(parents=True, exist_ok=True)
    drafts_root.mkdir(parents=True, exist_ok=True)
    snapshots_root.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, Any]] = []
    manifest_json: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    with SessionLocal() as db:
        client = CloudflareIntegrationClient.from_db(db)
        summaries = client.list_posts()
        summary_by_slug = {
            cloudflare_slug_from_url(str(item.get("publicUrl") or item.get("published_url") or "")): item
            for item in summaries
            if cloudflare_slug_from_url(str(item.get("publicUrl") or item.get("published_url") or ""))
        }

        for report_row in report_rows:
            slug = cloudflare_slug_from_url(str(report_row.get("url") or ""))
            summary = summary_by_slug.get(slug)
            if not summary:
                raise ValueError(f"Could not map Cloudflare post by slug: {slug}")
            detail = client.get_post(str(summary.get("id") or ""))
            content = str(detail.get("content") or "")
            title = normalize_space(str(detail.get("title") or ""))
            if detect_broken_text(title) or detect_broken_text(content):
                raise ValueError(f"Detected broken text in live source snapshot: {slug}")

            post_id = normalize_space(str(detail.get("id") or summary.get("id") or "post"))
            file_stem = safe_filename(f"{post_id}-{slug}", fallback=post_id)
            markdown_path = drafts_root / f"{file_stem}.md"
            snapshot_path = snapshots_root / f"{file_stem}.json"
            write_text_utf8(markdown_path, content)
            write_json(snapshot_path, detail)

            row = build_row(detail, markdown_path, snapshot_path)
            manifest_rows.append(row)
            manifest_json.append(row)
            summary_rows.append(
                {
                    "slug": row["source_slug"],
                    "url": row["source_url"],
                    "seo_score": report_row.get("seo_score", ""),
                    "category": row["current_category"],
                }
            )

    metadata = {
        "kind": "cloudflare-low-seo-patch",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "report_path": str(report_path),
        "channel": "dongri-archive",
        "target_provider": "cloudflare",
        "target_count": len(manifest_rows),
        "preservation_contract": {
            "preserve_slug": True,
            "preserve_cover_image": True,
            "preserve_inline_assets": True,
            "preserve_related_links": True,
            "preserve_structure": True,
            "block_category_changes": True,
        },
    }
    write_json(output_root / "package-metadata.json", metadata)
    write_json(output_root / "summary.json", summary_rows)
    write_json(output_root / "dongri-archive" / "manifest.json", manifest_json)
    write_csv_utf8(
        output_root / "dongri-archive" / "manifest.csv",
        manifest_rows,
        [
            "review_status",
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
    print(
        json.dumps(
            {
            "package_root": str(output_root),
            "target_count": len(manifest_rows),
            "report_path": str(report_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

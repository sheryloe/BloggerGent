from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
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
    load_low_seo_rows,
    normalize_space,
    parse_tag_string,
    read_csv_utf8,
    read_text_utf8,
    write_csv_utf8,
    write_json,
)


DEFAULT_PACKAGE_DATE = "2026-04-02-cloudflare-low-seo"
CHANNEL_CHOICES = ("travel", "midnight-archives", "dongri-archive")
DEFAULT_CHANNELS = "dongri-archive"
ALLOWED_PACKAGE_KINDS = ("cloudflare-low-seo-patch", "cloudflare-range-rewrite")

MARKDOWN_H2_RE = re.compile(r"^\s*##\s+(.+?)\s*$", re.MULTILINE)
MARKDOWN_H3_RE = re.compile(r"^\s*###\s+(.+?)\s*$", re.MULTILINE)
HTML_H2_RE = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
HTML_H3_RE = re.compile(r"<h3\b[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]+>")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)]\([^)]+\)")
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]+`")
WHITESPACE_RE = re.compile(r"\s+")

BLOCKED_HEADINGS = (
    "기준 시각",
    "핵심 요약",
    "확인된 사실",
    "미확인 정보",
    "출처/확인 경로",
    "전개 시나리오",
    "행동 체크리스트",
    "sources / verification path",
    "confirmed facts",
    "unverified",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy Cloudflare low-SEO patch packages. Blogger live deploy is intentionally blocked."
    )
    parser.add_argument(
        "--package-date",
        default=DEFAULT_PACKAGE_DATE,
        help="Package folder name under storage/rewrite-packages",
    )
    parser.add_argument(
        "--channels",
        default=DEFAULT_CHANNELS,
        help="Comma separated channels. This flow only allows dongri-archive.",
    )
    parser.add_argument(
        "--allow-blogger",
        action="store_true",
        help="Explicit opt-in flag. Still blocked here because Blogger work is patch-draft only in this flow.",
    )
    parser.add_argument(
        "--low-seo-report",
        default=str(DEFAULT_LOW_SEO_REPORT),
        help="CSV report used to define the exact live deployment scope.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate mapping and safeguards without live updates")
    parser.add_argument("--apply", action="store_true", help="Execute live updates for the validated Cloudflare scope")
    args = parser.parse_args()
    if args.dry_run == args.apply:
        raise ValueError("Choose exactly one mode: --dry-run or --apply")
    return args


def parse_channels(raw_value: str) -> list[str]:
    channels: list[str] = []
    seen: set[str] = set()
    for token in (raw_value or "").split(","):
        channel = token.strip()
        if not channel:
            continue
        if channel not in CHANNEL_CHOICES:
            raise ValueError(f"Unsupported channel: {channel}")
        if channel in seen:
            continue
        seen.add(channel)
        channels.append(channel)
    if not channels:
        raise ValueError("No channels selected.")
    return channels


def _heading_texts(markdown: str) -> list[str]:
    headings: list[str] = []
    for match in MARKDOWN_H2_RE.finditer(markdown or ""):
        headings.append(normalize_space(match.group(1)))
    for match in MARKDOWN_H3_RE.finditer(markdown or ""):
        headings.append(normalize_space(match.group(1)))

    for match in HTML_H2_RE.finditer(markdown or ""):
        headings.append(normalize_space(HTML_TAG_RE.sub(" ", match.group(1))))
    for match in HTML_H3_RE.finditer(markdown or ""):
        headings.append(normalize_space(HTML_TAG_RE.sub(" ", match.group(1))))
    return [item for item in headings if item]


def _has_blocked_heading(markdown: str) -> bool:
    lowered = [heading.casefold() for heading in _heading_texts(markdown)]
    return any(token.casefold() in heading for token in BLOCKED_HEADINGS for heading in lowered)


def _count_headings(markdown: str) -> tuple[int, int]:
    h2 = len(MARKDOWN_H2_RE.findall(markdown or "")) + len(HTML_H2_RE.findall(markdown or ""))
    h3 = len(MARKDOWN_H3_RE.findall(markdown or "")) + len(HTML_H3_RE.findall(markdown or ""))
    return h2, h3


def _compact_plain_text(markdown: str) -> str:
    text = markdown or ""
    text = CODE_FENCE_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    text = MARKDOWN_IMAGE_RE.sub(" ", text)
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = WHITESPACE_RE.sub("", text)
    return text.strip()


def _count_faq_questions(markdown: str) -> int:
    text = markdown or ""
    marker_md = re.search(r"^\s*##\s*(FAQ|자주\s*묻는\s*질문)\s*$", text, flags=re.MULTILINE | re.IGNORECASE)
    marker_html = re.search(r"<h2\b[^>]*>\s*(FAQ|자주\s*묻는\s*질문)\s*</h2>", text, flags=re.IGNORECASE)
    start = None
    if marker_md:
        start = marker_md.end()
    elif marker_html:
        start = marker_html.end()
    if start is None:
        return 0
    tail = text[start:]
    return len(MARKDOWN_H3_RE.findall(tail)) + len(HTML_H3_RE.findall(tail))


def validate_range_rewrite_candidate(
    *,
    markdown: str,
    excerpt: str,
    seo_description: str,
    tags: list[str],
) -> tuple[bool, str]:
    if _has_blocked_heading(markdown):
        return False, "blocked_heading"

    compact_len = len(_compact_plain_text(markdown))
    if compact_len < 3000:
        return False, f"body_too_short_no_ws:{compact_len}"

    h2_count, h3_count = _count_headings(markdown)
    if h2_count < 5:
        return False, f"insufficient_h2:{h2_count}"
    if h3_count < 2:
        return False, f"insufficient_h3:{h3_count}"

    faq_q = _count_faq_questions(markdown)
    if faq_q < 3:
        return False, f"faq_too_short:{faq_q}"

    excerpt_value = normalize_space(excerpt)
    if len(excerpt_value) < 60:
        return False, f"excerpt_too_short:{len(excerpt_value)}"

    meta_value = normalize_space(seo_description)
    if not (120 <= len(meta_value) <= 160):
        return False, f"meta_len_out_of_range:{len(meta_value)}"

    if len(tags) < 5:
        return False, f"tags_too_few:{len(tags)}"
    if len(tags) > 8:
        return False, f"tags_too_many:{len(tags)}"

    return True, "ok"


def load_package_metadata(package_root: Path) -> dict[str, Any]:
    metadata_path = package_root / "package-metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"package-metadata.json not found in {package_root}. "
            "Use scripts/build_cloudflare_low_seo_package.py first."
        )
    import json

    return json.loads(metadata_path.read_text(encoding="utf-8"))


def extract_tag_names(detail: dict[str, Any]) -> list[str]:
    raw_tags = detail.get("tags")
    if not isinstance(raw_tags, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in raw_tags:
        if isinstance(item, dict):
            candidate = normalize_space(str(item.get("name") or item.get("label") or item.get("slug") or ""))
        else:
            candidate = normalize_space(str(item))
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(candidate)
    return values


def validate_cloudflare_scope(
    *,
    manifest_rows: list[dict[str, str]],
    report_rows: list[dict[str, str]],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    rows_by_slug: dict[str, dict[str, str]] = {}
    markdown_paths: set[str] = set()
    for row in manifest_rows:
        slug = normalize_space(row.get("source_slug")) or cloudflare_slug_from_url(str(row.get("source_url") or ""))
        if not slug:
            raise ValueError("Manifest row without source_slug/source_url slug.")
        if slug in rows_by_slug:
            raise ValueError(f"Duplicate source_slug in manifest: {slug}")
        markdown_path = normalize_space(row.get("markdown_path"))
        if not markdown_path:
            raise ValueError(f"Manifest row missing markdown_path: {slug}")
        if markdown_path in markdown_paths:
            raise ValueError(f"Duplicate markdown_path in manifest: {markdown_path}")
        markdown_paths.add(markdown_path)
        rows_by_slug[slug] = row

    report_slugs = []
    for row in report_rows:
        slug = cloudflare_slug_from_url(str(row.get("url") or ""))
        if not slug:
            raise ValueError(f"Low SEO report row has no slug: {row.get('url')}")
        report_slugs.append(slug)

    report_slug_set = set(report_slugs)
    manifest_slug_set = set(rows_by_slug)
    if manifest_slug_set != report_slug_set:
        missing = sorted(report_slug_set - manifest_slug_set)[:10]
        extra = sorted(manifest_slug_set - report_slug_set)[:10]
        raise ValueError(
            "Manifest scope does not match the low SEO report. "
            f"missing={missing} extra={extra} "
            f"report_count={len(report_slug_set)} manifest_count={len(manifest_slug_set)}"
        )
    return rows_by_slug, report_slugs


def validate_manifest_only(manifest_rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], list[str]]:
    rows_by_slug: dict[str, dict[str, str]] = {}
    ordered_slugs: list[str] = []
    markdown_paths: set[str] = set()
    for row in manifest_rows:
        slug = normalize_space(row.get("source_slug")) or cloudflare_slug_from_url(str(row.get("source_url") or ""))
        if not slug:
            raise ValueError("Manifest row without source_slug/source_url slug.")
        if slug in rows_by_slug:
            raise ValueError(f"Duplicate source_slug in manifest: {slug}")
        markdown_path = normalize_space(row.get("markdown_path"))
        if not markdown_path:
            raise ValueError(f"Manifest row missing markdown_path: {slug}")
        if markdown_path in markdown_paths:
            raise ValueError(f"Duplicate markdown_path in manifest: {markdown_path}")
        markdown_paths.add(markdown_path)
        rows_by_slug[slug] = row
        ordered_slugs.append(slug)
    if not ordered_slugs:
        raise ValueError("Manifest has no rows.")
    return rows_by_slug, ordered_slugs


def build_retry_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in results:
        if item.get("status") != "failed":
            continue
        rows.append(
            {
                "channel": item.get("channel", ""),
                "source_slug": item.get("source_slug", ""),
                "source_url": item.get("source_url", ""),
                "reason": item.get("reason", ""),
                "markdown_path": item.get("markdown_path", ""),
            }
        )
    return rows


def run() -> int:
    args = parse_args()
    channels = parse_channels(args.channels)
    if any(channel != "dongri-archive" for channel in channels):
        if not args.allow_blogger:
            raise ValueError("This deploy flow is Cloudflare-only. Blogger channels are excluded from live deployment.")
        raise ValueError(
            "Blogger live deploy is disabled in this flow. "
            "Use scripts/build_blogger_patch_package.py to generate reviewable patch drafts first."
        )

    package_root = REWRITE_PACKAGE_ROOT / args.package_date
    if not package_root.exists():
        raise FileNotFoundError(f"Package path does not exist: {package_root}")

    metadata = load_package_metadata(package_root)
    package_kind = normalize_space(str(metadata.get("kind") or ""))
    if package_kind not in ALLOWED_PACKAGE_KINDS:
        raise ValueError(
            f"Unsupported package kind: {package_kind or '<empty>'}. "
            f"Only {', '.join(ALLOWED_PACKAGE_KINDS)} packages are deployable in this flow."
        )

    manifest_path = package_root / "dongri-archive" / "manifest.csv"
    manifest_rows = read_csv_utf8(manifest_path)
    report_path = Path(args.low_seo_report).resolve()
    report_rows: list[dict[str, str]] = []
    if package_kind == "cloudflare-low-seo-patch":
        report_rows = load_low_seo_rows(report_path)
        rows_by_slug, ordered_slugs = validate_cloudflare_scope(manifest_rows=manifest_rows, report_rows=report_rows)
    else:
        rows_by_slug, ordered_slugs = validate_manifest_only(manifest_rows)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mode = "apply" if args.apply else "dry-run"
    results: list[dict[str, Any]] = []
    backup_payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "package_date": args.package_date,
        "package_kind": package_kind,
        "report_path": str(report_path) if report_rows else "",
        "target_count": len(ordered_slugs),
        "posts": [],
    }
    stats = defaultdict(int)

    with SessionLocal() as db:
        client = CloudflareIntegrationClient.from_db(db)
        summaries = client.list_posts()
        summary_by_slug: dict[str, dict[str, Any]] = {}
        for item in summaries:
            slug = cloudflare_slug_from_url(str(item.get("publicUrl") or item.get("published_url") or ""))
            if slug:
                summary_by_slug[slug] = item

        for slug in ordered_slugs:
            row = rows_by_slug[slug]
            summary = summary_by_slug.get(slug)
            source_url = normalize_space(row.get("source_url"))
            markdown_path = Path(str(row.get("markdown_path") or package_root / "dongri-archive" / "drafts" / f"{slug}.md"))
            if not summary:
                stats["failed"] += 1
                results.append(
                    {
                        "channel": "dongri-archive",
                        "status": "failed",
                        "source_slug": slug,
                        "source_url": source_url,
                        "reason": "mapping_not_found_by_slug",
                        "markdown_path": str(markdown_path),
                    }
                )
                continue

            row_post_id = normalize_space(row.get("post_id"))
            post_id = normalize_space(str(summary.get("id") or ""))
            if row_post_id and post_id and row_post_id != post_id:
                stats["failed"] += 1
                results.append(
                    {
                        "channel": "dongri-archive",
                        "status": "failed",
                        "source_slug": slug,
                        "source_url": source_url,
                        "post_id": row_post_id,
                        "reason": f"post_id_mismatch:{row_post_id}!={post_id}",
                        "markdown_path": str(markdown_path),
                    }
                )
                continue
            if row_post_id:
                post_id = row_post_id

            review_status = normalize_space(row.get("review_status")).lower()
            if review_status != "approved":
                stats["failed"] += 1
                stats["not_approved"] += 1
                results.append(
                    {
                        "channel": "dongri-archive",
                        "status": "failed",
                        "source_slug": slug,
                        "source_url": source_url,
                        "post_id": post_id,
                        "reason": f"not_approved:{review_status or '<empty>'}",
                        "markdown_path": str(markdown_path),
                    }
                )
                continue

            detail = client.get_post(post_id)
            current_title = normalize_space(str(detail.get("title") or summary.get("title") or ""))
            current_excerpt = normalize_space(str(detail.get("excerpt") or ""))
            current_seo_title = normalize_space(str(detail.get("seoTitle") or ""))
            current_seo_description = normalize_space(str(detail.get("seoDescription") or ""))
            current_content = str(detail.get("content") or "")
            current_category = normalize_space(
                str((detail.get("category") or {}).get("name") or (detail.get("category") or {}).get("slug") or "")
            )
            current_tags = extract_tag_names(detail)
            current_status = normalize_space(str(detail.get("status") or ""))
            current_cover_image = normalize_space(str(detail.get("coverImage") or ""))
            current_asset_refs = collect_markdown_asset_refs(current_content)

            try:
                next_content = read_text_utf8(markdown_path).strip()
            except Exception as exc:  # noqa: BLE001
                stats["failed"] += 1
                results.append(
                    {
                        "channel": "dongri-archive",
                        "status": "failed",
                        "source_slug": slug,
                        "source_url": source_url,
                        "post_id": post_id,
                        "reason": f"markdown_read_failed:{exc}",
                        "markdown_path": str(markdown_path),
                    }
                )
                continue

            next_title = normalize_space(row.get("new_title")) or current_title
            next_excerpt = normalize_space(row.get("new_excerpt")) or current_excerpt
            next_seo_title = normalize_space(row.get("new_seo_title")) or current_seo_title
            next_seo_description = normalize_space(row.get("new_seo_description")) or current_seo_description
            next_category = normalize_space(row.get("target_category")) or current_category
            next_tags = parse_tag_string(row.get("tags")) or current_tags

            if package_kind == "cloudflare-range-rewrite":
                ok, reason = validate_range_rewrite_candidate(
                    markdown=next_content,
                    excerpt=next_excerpt,
                    seo_description=next_seo_description,
                    tags=next_tags,
                )
                if not ok:
                    stats["failed"] += 1
                    stats["quality_blocked"] += 1
                    results.append(
                        {
                            "channel": "dongri-archive",
                            "status": "failed",
                            "source_slug": slug,
                            "source_url": source_url,
                            "post_id": post_id,
                            "reason": f"quality_gate_failed:{reason}",
                            "markdown_path": str(markdown_path),
                        }
                    )
                    continue

            if detect_broken_text(next_title) or detect_broken_text(next_excerpt) or detect_broken_text(next_content):
                stats["failed"] += 1
                stats["encoding_blocked"] += 1
                results.append(
                    {
                        "channel": "dongri-archive",
                        "status": "failed",
                        "source_slug": slug,
                        "source_url": source_url,
                        "post_id": post_id,
                        "reason": "encoding_blocked_detected_broken_text",
                        "markdown_path": str(markdown_path),
                    }
                )
                continue

            if normalize_space(current_category) != normalize_space(next_category):
                stats["failed"] += 1
                results.append(
                    {
                        "channel": "dongri-archive",
                        "status": "failed",
                        "source_slug": slug,
                        "source_url": source_url,
                        "post_id": post_id,
                        "reason": f"category_change_blocked:{current_category}->{next_category}",
                        "markdown_path": str(markdown_path),
                    }
                )
                continue

            missing_assets = [asset for asset in current_asset_refs if asset not in next_content]
            if missing_assets:
                stats["failed"] += 1
                results.append(
                    {
                        "channel": "dongri-archive",
                        "status": "failed",
                        "source_slug": slug,
                        "source_url": source_url,
                        "post_id": post_id,
                        "reason": f"inline_asset_preservation_failed:{len(missing_assets)}",
                        "missing_assets": missing_assets,
                        "markdown_path": str(markdown_path),
                    }
                )
                continue

            backup_payload["posts"].append(detail)
            update_payload: dict[str, Any] = {
                "title": next_title,
                "content": next_content,
                "excerpt": next_excerpt,
                "tagNames": next_tags,
            }
            if next_seo_title:
                update_payload["seoTitle"] = next_seo_title
            if next_seo_description:
                update_payload["seoDescription"] = next_seo_description

            if args.apply:
                client.update_post(post_id, update_payload)
                status = "updated"
                stats["updated"] += 1
            else:
                status = "planned"
                stats["planned"] += 1

            results.append(
                {
                    "channel": "dongri-archive",
                    "status": status,
                    "source_slug": slug,
                    "source_url": source_url,
                    "post_id": post_id,
                    "cover_image_present": bool(current_cover_image),
                    "inline_asset_count": len(current_asset_refs),
                    "current_status": current_status,
                    "markdown_path": str(markdown_path),
                }
            )

    backup_path = package_root / f"deploy-backup-{timestamp}-cloudflare.json"
    report_path = package_root / f"deploy-report-{timestamp}.json"
    retry_path = package_root / f"deploy-retry-{timestamp}.csv"

    write_json(backup_path, backup_payload)
    write_json(
        report_path,
        {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": mode,
            "package_date": args.package_date,
            "package_kind": package_kind,
            "target_count": len(ordered_slugs),
            "stats": dict(stats),
            "results": results,
        },
    )
    write_csv_utf8(
        retry_path,
        build_retry_rows(results),
        ["channel", "source_slug", "source_url", "reason", "markdown_path"],
    )
    print(
        json.dumps(
            {
            "mode": mode,
            "package_root": str(package_root),
            "target_count": len(ordered_slugs),
            "stats": dict(stats),
            "report": str(report_path),
            "retry": str(retry_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

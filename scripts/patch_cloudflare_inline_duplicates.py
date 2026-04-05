#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from package_common import (
    CloudflareIntegrationClient,
    REPORT_ROOT,
    SessionLocal,
    collect_markdown_asset_refs,
    now_iso,
)


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from exc


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


def normalize_channel(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def download_bytes(client: httpx.Client, url: str) -> bytes:
    response = client.get(url, timeout=30.0)
    response.raise_for_status()
    return response.content


def remove_markdown_image(body: str, url: str) -> str:
    escaped = re.escape(url)
    cleaned = re.sub(rf"(?m)^\s*!\[[^\]]*\]\({escaped}\)\s*$", "", body)
    cleaned = re.sub(rf"!\[[^\]]*\]\({escaped}\)", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def build_report_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return REPORT_ROOT / f"cloudflare-inline-dedupe-{timestamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove inline images that duplicate cover images for Cloudflare posts."
    )
    parser.add_argument("--from-date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--to-date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--channel", default="dongri-archive", help="Channel key (default: dongri-archive)")
    parser.add_argument("--apply", action="store_true", help="Apply changes")
    return parser.parse_args()


def run() -> int:
    args = parse_args()
    start_date = parse_date(args.from_date)
    end_date = parse_date(args.to_date)
    if end_date < start_date:
        raise ValueError("to-date must be >= from-date")

    report_path = build_report_path()
    channel_key = normalize_channel(args.channel)

    with SessionLocal() as db:
        client = CloudflareIntegrationClient.from_db(db)

    posts = client.list_posts()
    http_client = httpx.Client(follow_redirects=True)

    report: dict[str, Any] = {
        "generated_at": now_iso(),
        "from_date": args.from_date,
        "to_date": args.to_date,
        "channel": args.channel,
        "apply": bool(args.apply),
        "total_posts": len(posts),
        "patched": 0,
        "skipped": 0,
        "errors": 0,
        "items": [],
    }

    for post in posts:
        if not isinstance(post, dict):
            continue

        channel_name = normalize_channel(str(post.get("channelName") or ""))
        channel_id = normalize_channel(str(post.get("channelId") or ""))
        channel_slug = normalize_channel(str(post.get("channelSlug") or ""))
        if channel_key and channel_key not in {channel_name, channel_id, channel_slug}:
            continue

        created_at = parse_iso_datetime(str(post.get("createdAt") or ""))
        if not created_at:
            continue
        created_date = created_at.date()
        if created_date < start_date or created_date > end_date:
            continue

        post_id = str(post.get("id") or "").strip()
        detail = client.get_post(post_id) if post_id else {}
        if not isinstance(detail, dict):
            detail = {}

        title = str(detail.get("title") or post.get("title") or "")
        content = str(detail.get("content") or detail.get("contentMarkdown") or post.get("content") or post.get("contentMarkdown") or "")
        cover_image = str(detail.get("coverImage") or post.get("coverImage") or "").strip()

        item_report: dict[str, Any] = {
            "id": post_id,
            "title": title,
            "publicUrl": post.get("publicUrl"),
            "createdAt": post.get("createdAt"),
            "coverImage": cover_image,
            "status": "skipped",
            "removed": [],
            "error": None,
        }

        if not post_id or not content or not cover_image:
            report["skipped"] += 1
            report["items"].append(item_report)
            continue

        inline_urls = collect_markdown_asset_refs(content)
        if not inline_urls:
            report["skipped"] += 1
            report["items"].append(item_report)
            continue

        try:
            cover_bytes = download_bytes(http_client, cover_image)
            cover_hash = hash_bytes(cover_bytes)
        except Exception as exc:  # noqa: BLE001
            item_report["status"] = "failed"
            item_report["error"] = f"cover_download_failed: {exc}"
            report["errors"] += 1
            report["items"].append(item_report)
            continue

        updated_content = content
        removed_urls: list[str] = []
        for url in inline_urls:
            try:
                inline_bytes = download_bytes(http_client, url)
            except Exception as exc:  # noqa: BLE001
                item_report["error"] = f"inline_download_failed: {exc}"
                continue
            if hash_bytes(inline_bytes) == cover_hash:
                updated_content = remove_markdown_image(updated_content, url)
                removed_urls.append(url)

        if not removed_urls:
            report["skipped"] += 1
            report["items"].append(item_report)
            continue

        item_report["removed"] = removed_urls

        if args.apply:
            try:
                client.update_post(post_id, {"content": updated_content})
                item_report["status"] = "patched"
                report["patched"] += 1
            except Exception as exc:  # noqa: BLE001
                item_report["status"] = "failed"
                item_report["error"] = f"update_failed: {exc}"
                report["errors"] += 1
        else:
            item_report["status"] = "dry-run"
            report["skipped"] += 1

        report["items"].append(item_report)

    http_client.close()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = (
        f"Report: {report_path}\n"
        f"Patched: {report['patched']} | Skipped: {report['skipped']} | Errors: {report['errors']}"
    )
    print(summary)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@postgres:5432/bloggent"
LIVE_STATUSES = {"live", "published", "LIVE", "PUBLISHED"}

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import SyncedBloggerPost, SyncedCloudflarePost  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify live pages for a legacy URL prefix/reference.")
    parser.add_argument("--needle", default="/assets/media/posts/2026/", help="String to detect in live HTML.")
    parser.add_argument("--timeout", type=float, default=25.0, help="HTTP timeout in seconds.")
    parser.add_argument("--report-path", default="", help="Optional JSON report path.")
    return parser.parse_args(argv)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def run_verify(*, needle: str, timeout: float) -> dict[str, Any]:
    normalized_needle = _safe_str(needle)
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "needle": normalized_needle,
        "summary": {
            "posts_scanned": 0,
            "fetch_failed": 0,
            "live_hits_total": 0,
            "blogger_scanned": 0,
            "cloudflare_scanned": 0,
            "blogger_hits": 0,
            "cloudflare_hits": 0,
        },
        "offending_urls": [],
        "fetch_failures": [],
    }

    with SessionLocal() as db:
        blogger_rows = db.execute(
            select(
                SyncedBloggerPost.blog_id,
                SyncedBloggerPost.remote_post_id,
                SyncedBloggerPost.url,
                SyncedBloggerPost.title,
            ).where(
                SyncedBloggerPost.status.in_(sorted(LIVE_STATUSES)),
                SyncedBloggerPost.url.is_not(None),
            )
        ).all()
        cloudflare_rows = db.execute(
            select(
                SyncedCloudflarePost.managed_channel_id,
                SyncedCloudflarePost.remote_post_id,
                SyncedCloudflarePost.url,
                SyncedCloudflarePost.title,
            ).where(
                SyncedCloudflarePost.status.in_(sorted(LIVE_STATUSES)),
                SyncedCloudflarePost.url.is_not(None),
            )
        ).all()

    targets: list[dict[str, str]] = []
    for blog_id, remote_post_id, url, title in blogger_rows:
        targets.append(
            {
                "source": "blogger",
                "group_id": _safe_str(blog_id),
                "remote_post_id": _safe_str(remote_post_id),
                "url": _safe_str(url),
                "title": _safe_str(title),
            }
        )
    for channel_id, remote_post_id, url, title in cloudflare_rows:
        targets.append(
            {
                "source": "cloudflare",
                "group_id": _safe_str(channel_id),
                "remote_post_id": _safe_str(remote_post_id),
                "url": _safe_str(url),
                "title": _safe_str(title),
            }
        )

    with httpx.Client(timeout=max(float(timeout), 5.0), follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for target in targets:
            report["summary"]["posts_scanned"] += 1
            if target["source"] == "blogger":
                report["summary"]["blogger_scanned"] += 1
            else:
                report["summary"]["cloudflare_scanned"] += 1

            page_url = _safe_str(target["url"])
            try:
                response = client.get(page_url)
                response.raise_for_status()
                html = response.text
            except Exception as exc:  # noqa: BLE001
                report["summary"]["fetch_failed"] += 1
                report["fetch_failures"].append(
                    {
                        "source": target["source"],
                        "group_id": target["group_id"],
                        "remote_post_id": target["remote_post_id"],
                        "url": page_url,
                        "error": str(exc),
                    }
                )
                continue

            if normalized_needle and normalized_needle in html:
                report["summary"]["live_hits_total"] += 1
                if target["source"] == "blogger":
                    report["summary"]["blogger_hits"] += 1
                else:
                    report["summary"]["cloudflare_hits"] += 1
                report["offending_urls"].append(
                    {
                        "source": target["source"],
                        "group_id": target["group_id"],
                        "remote_post_id": target["remote_post_id"],
                        "url": page_url,
                        "title": target["title"],
                    }
                )

    return report


def main() -> int:
    args = parse_args()
    report = run_verify(
        needle=_safe_str(args.needle),
        timeout=float(args.timeout or 25.0),
    )
    report_path = (
        Path(args.report_path)
        if _safe_str(args.report_path)
        else REPO_ROOT / "storage" / "reports" / f"verify-legacy-prefix-live-refs-{_timestamp()}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(report_path))
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
API_ROOT = SCRIPT_DIR.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"

from sqlalchemy import text as sql_text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from package_common import CloudflareIntegrationClient, normalize_space, resolve_cloudflare_category_id  # noqa: E402
from repair_mystery_garbage_data import (  # noqa: E402
    MYSTERIA_CATEGORY_NAME,
    MYSTERIA_CATEGORY_SLUG,
    PATTERN_ID,
    PATTERN_VERSION,
    audit_cloudflare_url,
    build_publish_description,
)

RUNTIME_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent")
REPORT_PATH = RUNTIME_ROOT / "storage" / "the-midnight-archives" / "cloudflare-mysteria-final-slug-cleanup-20260428.json"
ROOL_PATH = RUNTIME_ROOT / "Rool" / "20-mystery" / "problem-solution-final-slug-cleanup-20260428.md"

SLUG_MAP: dict[str, str] = {
    "miseuteria-seutori-sodder-children-final": "miseuteria-seutori-sodder-children-christmas-fire-record",
    "miseuteria-seutori-dyatlov-pass-final": "miseuteria-seutori-dyatlov-pass-tent-and-footprints-record",
    "miseuteria-seutori-roanoke-colony-final": "miseuteria-seutori-roanoke-colony-croatoan-record",
    "miseuteria-seutori-oak-island-money-pit-final": "miseuteria-seutori-oak-island-money-pit-record",
    "miseuteria-seutori-flor-de-la-mar-final": "miseuteria-seutori-flor-de-la-mar-treasure-ship-record",
    "miseuteria-seutori-mary-celeste-final": "miseuteria-seutori-mary-celeste-ghost-ship-record",
    "miseuteria-seutori-uss-cyclops-final": "miseuteria-seutori-uss-cyclops-bermuda-route-record",
    "miseuteria-seutori-wow-signal-final": "miseuteria-seutori-wow-signal-72-second-radio-record",
    "miseuteria-seutori-zodiac-killer-final": "miseuteria-seutori-zodiac-killer-cipher-letter-record",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rename Cloudflare Mysteria legacy -final slugs.")
    parser.add_argument("--mode", choices=("dry-run", "apply", "verify"), required=True)
    parser.add_argument("--report-path", default=str(REPORT_PATH))
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cf_client_from_db(db) -> CloudflareIntegrationClient:
    values = get_settings_map(db)
    return CloudflareIntegrationClient(
        base_url=str(values.get("cloudflare_blog_api_base_url") or ""),
        token=str(values.get("cloudflare_blog_m2m_token") or ""),
    )


def get_category_id(cf: CloudflareIntegrationClient) -> str:
    categories = cf.list_categories()
    category_id = resolve_cloudflare_category_id(MYSTERIA_CATEGORY_SLUG, categories) or resolve_cloudflare_category_id(
        MYSTERIA_CATEGORY_NAME,
        categories,
    )
    if not category_id:
        raise RuntimeError("mysteria_category_id_not_found")
    return str(category_id)


def post_url(slug: str) -> str:
    return f"https://dongriarchive.com/ko/post/{slug}"


def direct_status(url: str) -> tuple[int, str]:
    try:
        response = httpx.get(url, timeout=20.0, follow_redirects=False)
        return response.status_code, str(response.headers.get("location") or "")
    except Exception:
        return 0, ""


def build_payload(detail: dict[str, Any], *, new_slug: str, category_id: str) -> dict[str, Any]:
    title = normalize_space(str(detail.get("title") or ""))
    content = str(detail.get("content") or "")
    cover = normalize_space(str(detail.get("coverImage") or ""))
    description = build_publish_description(title, content)
    return {
        "title": title,
        "slug": new_slug,
        "content": content,
        "description": description,
        "excerpt": description,
        "seoTitle": normalize_space(str(detail.get("seoTitle") or title)),
        "seoDescription": description,
        "metaDescription": description,
        "tagNames": [MYSTERIA_CATEGORY_NAME, "미스터리", "사건기록"],
        "categoryId": category_id,
        "status": "published",
        "coverImage": cover,
        "coverAlt": normalize_space(str(detail.get("coverAlt") or title)),
        "article_pattern_id": normalize_space(str(detail.get("article_pattern_id") or PATTERN_ID)),
        "article_pattern_version": int(detail.get("article_pattern_version") or PATTERN_VERSION),
        "articlePatternId": normalize_space(str(detail.get("articlePatternId") or detail.get("article_pattern_id") or PATTERN_ID)),
        "articlePatternVersion": int(detail.get("articlePatternVersion") or detail.get("article_pattern_version") or PATTERN_VERSION),
    }


def update_db_slug(db, *, old_slug: str, new_slug: str, title: str, url: str) -> None:
    db.execute(
        sql_text(
            """
            UPDATE synced_cloudflare_posts
            SET
                slug = :new_slug,
                url = :url,
                title = :title,
                category_name = :category_name,
                category_slug = :category_slug,
                canonical_category_name = :category_name,
                canonical_category_slug = :category_slug,
                synced_at = now(),
                updated_at = now()
            WHERE slug = :old_slug
            """
        ),
        {
            "old_slug": old_slug,
            "new_slug": new_slug,
            "url": url,
            "title": title,
            "category_name": MYSTERIA_CATEGORY_NAME,
            "category_slug": MYSTERIA_CATEGORY_SLUG,
        },
    )


def main() -> int:
    args = parse_args()
    rows: list[dict[str, Any]] = []
    with SessionLocal() as db:
        cf = cf_client_from_db(db)
        category_id = get_category_id(cf)
        posts = cf.list_posts()
        by_slug = {normalize_space(str(post.get("slug") or "")): post for post in posts}
        for old_slug, new_slug in SLUG_MAP.items():
            row: dict[str, Any] = {
                "old_slug": old_slug,
                "new_slug": new_slug,
                "old_url": post_url(old_slug),
                "new_url": post_url(new_slug),
                "result": "planned",
                "error": "",
            }
            if args.mode != "verify" and new_slug in by_slug:
                row["result"] = "blocked_slug_exists"
                rows.append(row)
                continue
            post = by_slug.get(old_slug)
            if args.mode == "verify":
                post = by_slug.get(new_slug)
                if not post:
                    row["result"] = "missing_new_slug"
                    rows.append(row)
                    continue
                audit = audit_cloudflare_url(post_url(new_slug))
                old_status, old_location = direct_status(post_url(old_slug))
                row.update(
                    {
                        "result": "verified",
                        "new_live_status": audit.status,
                        "old_direct_status": old_status,
                        "old_redirect_location": old_location,
                        "plain_text_length": audit.plain_text_length,
                        "image_count": audit.image_count,
                        "markdown_exposed": audit.markdown_exposed,
                        "raw_html_exposed": audit.raw_html_exposed,
                    }
                )
                rows.append(row)
                continue
            if not post:
                row["result"] = "missing_old_slug"
                rows.append(row)
                continue
            detail = cf.get_post(str(post.get("id") or post.get("remote_id") or ""))
            if args.mode == "dry-run":
                row["title"] = normalize_space(str(detail.get("title") or post.get("title") or ""))
                rows.append(row)
                continue
            if args.mode == "apply":
                post_id = normalize_space(str(detail.get("remote_id") or detail.get("id") or post.get("id") or ""))
                payload = build_payload(detail, new_slug=new_slug, category_id=category_id)
                backup_dir = REPORT_PATH.parent / "final-slug-backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                (backup_dir / f"{old_slug}.json").write_text(
                    json.dumps(detail, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                try:
                    cf.update_post(post_id, payload)
                    audit = audit_cloudflare_url(post_url(new_slug))
                    update_db_slug(db, old_slug=old_slug, new_slug=new_slug, title=str(payload["title"]), url=post_url(new_slug))
                    db.commit()
                    row.update(
                        {
                            "result": "renamed",
                            "title": payload["title"],
                            "live_status": audit.status,
                            "plain_text_length": audit.plain_text_length,
                            "image_count": audit.image_count,
                            "markdown_exposed": audit.markdown_exposed,
                            "raw_html_exposed": audit.raw_html_exposed,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    row["result"] = "failed"
                    row["error"] = str(exc)
                rows.append(row)
                continue
    summary = {
        "mode": args.mode,
        "generated_at": now_iso(),
        "target_count": len(SLUG_MAP),
        "renamed": sum(1 for row in rows if row.get("result") == "renamed"),
        "verified": sum(1 for row in rows if row.get("result") == "verified"),
        "blocked": sum(1 for row in rows if str(row.get("result") or "").startswith("blocked")),
        "failed": sum(1 for row in rows if row.get("result") == "failed"),
        "missing": sum(1 for row in rows if row.get("result") == "missing_old_slug"),
        "new_url_not_200": sum(1 for row in rows if "new_live_status" in row and row.get("new_live_status") != 200),
        "old_url_still_200": sum(1 for row in rows if "old_direct_status" in row and row.get("old_direct_status") == 200),
        "old_url_redirected": sum(1 for row in rows if "old_direct_status" in row and row.get("old_direct_status") in {301, 302, 307, 308}),
    }
    payload = {"summary": summary, "items": rows}
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    ROOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Cloudflare Mysteria Final Slug Cleanup 2026-04-28",
        "",
        f"- mode: `{args.mode}`",
        f"- target_count: `{summary['target_count']}`",
        f"- renamed: `{summary['renamed']}`",
        f"- failed: `{summary['failed']}`",
        "",
        "| result | title | old_url | new_url |",
        "|---|---|---|---|",
    ]
    for row in rows:
        title = str(row.get("title") or "").replace("|", "\\|")
        lines.append(f"| {row.get('result')} | {title} | {row.get('old_url')} | {row.get('new_url')} |")
    ROOL_PATH.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"REPORT={report_path}")
    print(f"ROOL={ROOL_PATH}")
    return 1 if summary["failed"] or summary["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

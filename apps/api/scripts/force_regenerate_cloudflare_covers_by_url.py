#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT
REPORT_DIR = REPO_ROOT / "storage" / "reports"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@localhost:15432/bloggent"
FALLBACK_NOTICE_TOKENS = (
    "image restored by automated fallback",
    "automated fallback",
)
IMAGE_URL_RE = re.compile(
    r"""(?:!\[[^\]]*]\(([^)\s]+)\))|(?:<img\b[^>]*\bsrc=['"]([^'"]+)['"])""",
    re.IGNORECASE,
)
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str((REPO_ROOT / "storage").resolve())

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.services.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
    _safe_fallback_image_prompt,
    _upload_integration_asset,
)
from app.services.providers.factory import get_image_provider  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Force regenerate Cloudflare cover images for selected post URLs.")
    parser.add_argument("--url", action="append", required=True, help="Target post URL. Repeat for multiple.")
    parser.add_argument("--apply", action="store_true", help="Apply update via integration PUT.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--report-prefix",
        default="cloudflare-force-cover-regenerate",
        help="Report filename prefix.",
    )
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _report_path(prefix: str, stamp: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR / f"{prefix}-{stamp}.json"


def _normalize_url(value: str) -> str:
    raw = _safe_str(value).rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def _extract_slug_from_url(url: str) -> str:
    parsed = urlparse(_safe_str(url))
    path = _safe_str(parsed.path)
    marker = "/post/"
    if marker not in path:
        return ""
    tail = path.split(marker, 1)[1]
    slug = unquote(tail).strip("/")
    return slug


def _contains_fallback_notice(*parts: str) -> bool:
    lowered = " ".join(_safe_str(part).lower() for part in parts)
    return any(token in lowered for token in FALLBACK_NOTICE_TOKENS)


def _content_of(post: dict[str, Any]) -> str:
    return _safe_str(post.get("content") or post.get("contentMarkdown") or post.get("content_markdown") or "")


def _extract_image_urls(content: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in IMAGE_URL_RE.finditer(content or ""):
        candidate = _safe_str(match.group(1) or match.group(2))
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _build_cover_alt(detail: dict[str, Any]) -> str:
    title = _safe_str(detail.get("title"))
    current = _safe_str(detail.get("coverAlt") or detail.get("coverImageAlt"))
    if current and not _contains_fallback_notice(current):
        return current[:180]
    if title:
        return f"{title} 대표 이미지"[:180]
    slug = _safe_str(detail.get("slug"))
    return f"{slug} 대표 이미지"[:180] if slug else "대표 이미지"


def _build_visual_prompt(detail: dict[str, Any]) -> str:
    title = _safe_str(detail.get("title"))
    excerpt = _safe_str(detail.get("excerpt"))
    category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
    category_name = _safe_str(category.get("name")) or "General"
    seed = title or _safe_str(detail.get("slug")) or "blog post"
    fallback = _safe_fallback_image_prompt(category_name, seed)
    if excerpt:
        return (
            f"{fallback} Keep scene relevance to this excerpt: {excerpt}. "
            "No text overlays, no logos, no watermark, no black background."
        )
    return f"{fallback} No text overlays, no logos, no watermark, no black background."


def _integration_list_posts(db) -> list[dict[str, Any]]:
    response = _integration_request(db, method="GET", path="/api/integrations/posts", timeout=60.0)
    data = _integration_data_or_raise(response)
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _integration_get_post(db, post_id: str) -> dict[str, Any]:
    response = _integration_request(db, method="GET", path=f"/api/integrations/posts/{post_id}", timeout=60.0)
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _integration_update_post(db, post_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="PUT",
        path=f"/api/integrations/posts/{post_id}",
        json_payload=payload,
        timeout=120.0,
    )
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _find_post_summary(posts: list[dict[str, Any]], *, target_url: str, slug: str) -> dict[str, Any] | None:
    normalized_target = _normalize_url(target_url)
    slug_key = slug.casefold()
    for item in posts:
        post_slug = _safe_str(item.get("slug"))
        if post_slug and post_slug.casefold() == slug_key:
            return item
        candidates = (
            _safe_str(item.get("publicUrl")),
            _safe_str(item.get("url")),
        )
        if any(_normalize_url(value) == normalized_target for value in candidates if value):
            return item
    return None


def _verify_public_html(*, public_url: str, expected_cover: str, timeout: float) -> dict[str, Any]:
    if not public_url:
        return {"status": "skipped", "error": "public_url_missing"}
    try:
        request = Request(public_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=float(timeout)) as response:  # noqa: S310
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": f"public_fetch_failed:{exc}"}
    match = OG_IMAGE_RE.search(html)
    og_image = _safe_str(match.group(1) if match else "")
    return {
        "status": "ok" if og_image == expected_cover else "partial",
        "og_image": og_image,
        "expected_cover": expected_cover,
        "match": og_image == expected_cover,
    }


def main() -> int:
    args = parse_args()
    stamp = _timestamp()
    rows: list[dict[str, Any]] = []

    with SessionLocal() as db:
        posts = _integration_list_posts(db)
        image_provider = get_image_provider(db)

        for raw_url in args.url:
            target_url = _safe_str(raw_url)
            slug = _extract_slug_from_url(target_url)
            result: dict[str, Any] = {
                "target_url": target_url,
                "slug_from_url": slug,
                "apply": bool(args.apply),
            }

            if not slug:
                result["status"] = "failed"
                result["error"] = "slug_parse_failed"
                rows.append(result)
                continue

            summary = _find_post_summary(posts, target_url=target_url, slug=slug)
            if not summary:
                result["status"] = "failed"
                result["error"] = "post_not_found"
                rows.append(result)
                continue

            post_id = _safe_str(summary.get("id"))
            detail = _integration_get_post(db, post_id)
            if not detail:
                result["status"] = "failed"
                result["error"] = "detail_fetch_failed"
                result["post_id"] = post_id
                rows.append(result)
                continue

            actual_slug = _safe_str(detail.get("slug")) or slug
            title = _safe_str(detail.get("title"))
            old_cover = _safe_str(detail.get("coverImage"))
            old_cover_alt = _safe_str(detail.get("coverAlt") or detail.get("coverImageAlt"))
            content = _content_of(detail)

            result["post_id"] = post_id
            result["title"] = title
            result["old_cover"] = old_cover

            if not args.apply:
                result["status"] = "dry_run"
                rows.append(result)
                continue

            try:
                prompt = _build_visual_prompt(detail)
                generated_bytes, image_raw = image_provider.generate_image(prompt, actual_slug or post_id)
                new_cover = _upload_integration_asset(
                    db,
                    post_slug=actual_slug or post_id,
                    alt_text=_build_cover_alt(detail),
                    filename=f"{(actual_slug or post_id)}-cover.png",
                    image_bytes=generated_bytes,
                )
            except Exception as exc:  # noqa: BLE001
                result["status"] = "failed"
                result["error"] = f"cover_generate_or_upload_failed:{exc}"
                rows.append(result)
                continue

            image_urls = _extract_image_urls(content)
            replacements: dict[str, str] = {}
            if old_cover:
                replacements[old_cover] = new_cover
            for image_url in image_urls:
                lowered = image_url.lower()
                if image_url == new_cover:
                    continue
                if "/assets/media/posts/" in lowered and f"/{actual_slug.lower()}/" not in lowered:
                    replacements[image_url] = new_cover
                if _contains_fallback_notice(image_url):
                    replacements[image_url] = new_cover

            updated_content = content
            for old_url, new_url in replacements.items():
                if old_url and new_url and old_url != new_url:
                    updated_content = updated_content.replace(old_url, new_url)

            update_payload: dict[str, Any] = {
                "coverImage": new_cover,
                "coverAlt": _build_cover_alt(detail),
            }
            if updated_content and updated_content != content:
                update_payload["content"] = updated_content
            elif content:
                update_payload["content"] = content

            try:
                updated = _integration_update_post(db, post_id, update_payload)
            except Exception as exc:  # noqa: BLE001
                result["status"] = "failed"
                result["error"] = f"update_failed:{exc}"
                result["new_cover"] = new_cover
                rows.append(result)
                continue

            public_url = _safe_str(updated.get("publicUrl") or updated.get("url") or target_url)
            verify_url = target_url
            verify = _verify_public_html(public_url=verify_url, expected_cover=new_cover, timeout=float(args.timeout))

            result["status"] = "repaired" if verify.get("match") else "updated_unverified"
            result["new_cover"] = new_cover
            result["public_url"] = public_url
            result["verify_url"] = verify_url
            result["old_cover_alt"] = old_cover_alt
            result["new_cover_alt"] = _safe_str(update_payload.get("coverAlt"))
            result["replaced_url_count"] = sum(1 for key in replacements if key and key in content)
            result["verify"] = verify
            result["image_provider"] = _safe_str(image_raw.get("provider"))
            rows.append(result)

    repaired = [row for row in rows if row.get("status") == "repaired"]
    failed = [row for row in rows if row.get("status") == "failed"]
    payload = {
        "generated_at": _utc_now_iso(),
        "apply": bool(args.apply),
        "total": len(rows),
        "repaired_count": len(repaired),
        "failed_count": len(failed),
        "items": rows,
    }
    report_path = _report_path(args.report_prefix, stamp)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "ok",
                "apply": bool(args.apply),
                "total": len(rows),
                "repaired_count": len(repaired),
                "failed_count": len(failed),
                "report": str(report_path.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

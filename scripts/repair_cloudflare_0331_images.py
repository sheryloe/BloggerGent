#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageStat
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
REPORT_DIR = REPO_ROOT / "storage" / "reports"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@localhost:15432/bloggent"
KST = ZoneInfo("Asia/Seoul")
FALLBACK_NOTICE_TOKENS = (
    "image restored by automated fallback",
    "automated fallback",
)
IMAGE_URL_RE = re.compile(
    r"""(?:!\[[^\]]*]\(([^)\s]+)\))|(?:<img\b[^>]*\bsrc=['"]([^'"]+)['"])""",
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
    parser = argparse.ArgumentParser(description="Repair Cloudflare cover/body image consistency for 2026-03-31 (KST).")
    parser.add_argument("--target-date", default="2026-03-31", help="Target published date in KST (YYYY-MM-DD).")
    parser.add_argument("--exclude-date", default="2026-03-29", help="Date in KST to exclude (YYYY-MM-DD).")
    parser.add_argument("--luma-threshold", type=float, default=55.0, help="Cover luma threshold (<= is dark).")
    parser.add_argument("--apply", action="store_true", help="Apply update via PUT. Default is audit-only.")
    parser.add_argument("--verify-live-sample", type=int, default=3, help="Number of updated posts to verify from public HTML.")
    parser.add_argument("--report-prefix-audit", default="cloudflare-0331-image-audit", help="Audit report prefix.")
    parser.add_argument("--report-prefix-repair", default="cloudflare-0331-image-repair", help="Repair report prefix.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds for image/html fetch.")
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_yyyy_mm_dd(value: str) -> date:
    return date.fromisoformat(_safe_str(value))


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _report_path(prefix: str, stamp: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR / f"{prefix}-{stamp}.json"


def _iso_to_kst_date(value: str) -> date | None:
    raw = _safe_str(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(KST).date()


def _content_of(post: dict[str, Any]) -> str:
    return _safe_str(
        post.get("content")
        or post.get("contentMarkdown")
        or post.get("content_markdown")
        or ""
    )


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


def _looks_like_image_url(url: str) -> bool:
    lowered = url.lower()
    if any(lowered.endswith(ext) for ext in (".png", ".webp", ".jpg", ".jpeg", ".gif", ".avif", ".svg")):
        return True
    return "/assets/media/" in lowered


def _is_inline_mismatch_url(*, url: str, cover_image: str, slug: str) -> bool:
    candidate = _safe_str(url)
    cover = _safe_str(cover_image)
    if not candidate or not _looks_like_image_url(candidate):
        return False
    if cover and candidate == cover:
        return False
    lowered = candidate.lower()
    if "/assets/media/posts/2026/03/" in lowered:
        return True
    if "/assets/media/posts/" in lowered:
        slug_token = f"/{slug.lower()}/" if slug else ""
        if slug_token and slug_token not in lowered:
            return True
        return not bool(cover)
    return False


def _replace_content_urls(content: str, replacements: dict[str, str]) -> str:
    updated = content
    for old, new in replacements.items():
        if old and new and old != new:
            updated = updated.replace(old, new)
    return updated


def _contains_fallback_notice(*parts: str) -> bool:
    text = " ".join(_safe_str(part).lower() for part in parts)
    return any(token in text for token in FALLBACK_NOTICE_TOKENS)


def _download_image_luma(url: str, *, timeout: float) -> tuple[float | None, str]:
    target = _safe_str(url)
    if not target:
        return None, "cover_missing"
    try:
        response = httpx.get(target, timeout=timeout)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return None, f"cover_fetch_failed:{exc}"
    try:
        with Image.open(BytesIO(response.content)) as image:
            rgb = image.convert("RGB")
            stat = ImageStat.Stat(rgb)
            r, g, b = stat.mean
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            return round(float(luma), 2), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"cover_decode_failed:{exc}"


def _build_cover_alt(detail: dict[str, Any]) -> str:
    title = _safe_str(detail.get("title"))
    current = _safe_str(detail.get("coverAlt") or detail.get("coverImageAlt"))
    if current and not _contains_fallback_notice(current):
        return current[:180]
    if title:
        return f"{title} cover image"[:180]
    slug = _safe_str(detail.get("slug"))
    return f"{slug} cover image"[:180] if slug else "cover image"


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
            "Do not produce black background. Keep bright balanced lighting and realistic editorial details."
        )
    return f"{fallback} Do not produce black background. Keep bright balanced lighting and realistic editorial details."


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


def _sample_live_verification(items: list[dict[str, Any]], *, timeout: float, sample_size: int) -> list[dict[str, Any]]:
    if sample_size <= 0:
        return []
    checks: list[dict[str, Any]] = []
    for row in items[:sample_size]:
        public_url = _safe_str(row.get("public_url"))
        cover_image = _safe_str(row.get("final_cover_image"))
        if not public_url:
            checks.append(
                {
                    "post_id": row.get("post_id"),
                    "slug": row.get("slug"),
                    "status": "skipped",
                    "error": "public_url_missing",
                }
            )
            continue
        try:
            response = httpx.get(public_url, timeout=timeout)
            response.raise_for_status()
            html = response.text
            og_ok = bool(cover_image and f'content="{cover_image}"' in html and 'property="og:image"' in html)
            body_ok = bool(cover_image and cover_image in html)
            checks.append(
                {
                    "post_id": row.get("post_id"),
                    "slug": row.get("slug"),
                    "status": "ok" if (og_ok and body_ok) else "partial",
                    "og_image_match": og_ok,
                    "body_image_match": body_ok,
                    "public_url": public_url,
                }
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                {
                    "post_id": row.get("post_id"),
                    "slug": row.get("slug"),
                    "status": "failed",
                    "error": str(exc),
                    "public_url": public_url,
                }
            )
    return checks


def main() -> int:
    args = parse_args()
    target_date = _parse_yyyy_mm_dd(args.target_date)
    exclude_date = _parse_yyyy_mm_dd(args.exclude_date)
    stamp = _timestamp()

    audit_items: list[dict[str, Any]] = []
    repair_items: list[dict[str, Any]] = []

    with SessionLocal() as db:
        posts = _integration_list_posts(db)
        image_provider = get_image_provider(db)

        for item in posts:
            post_id = _safe_str(item.get("id"))
            if not post_id:
                continue

            detail = _integration_get_post(db, post_id)
            if not detail:
                continue

            published_at = _safe_str(detail.get("publishedAt"))
            published_kst_date = _iso_to_kst_date(published_at)
            if published_kst_date != target_date:
                continue
            if published_kst_date == exclude_date:
                continue

            slug = _safe_str(detail.get("slug"))
            title = _safe_str(detail.get("title") or slug)
            public_url = _safe_str(detail.get("publicUrl") or detail.get("url"))
            content = _content_of(detail)
            excerpt = _safe_str(detail.get("excerpt"))
            cover_image = _safe_str(detail.get("coverImage"))
            cover_alt = _safe_str(detail.get("coverAlt") or detail.get("coverImageAlt"))

            image_urls = _extract_image_urls(content)
            stale_urls = [url for url in image_urls if _is_inline_mismatch_url(url=url, cover_image=cover_image, slug=slug)]
            luma, luma_error = _download_image_luma(cover_image, timeout=float(args.timeout))
            dark_cover = (luma is None and bool(luma_error)) or (luma is not None and float(luma) <= float(args.luma_threshold))
            fallback_notice = _contains_fallback_notice(cover_alt, excerpt, content)

            issue_types: list[str] = []
            if not cover_image:
                issue_types.append("cover_missing")
            if dark_cover:
                issue_types.append("cover_dark_or_invalid")
            if stale_urls:
                issue_types.append("content_image_mismatch")
            if fallback_notice:
                issue_types.append("fallback_notice_detected")

            audit_items.append(
                {
                    "post_id": post_id,
                    "slug": slug,
                    "title": title,
                    "post_url": public_url,
                    "published_at": published_at,
                    "published_kst_date": str(published_kst_date),
                    "issue_type": issue_types,
                    "cover_image": cover_image,
                    "cover_luma": luma,
                    "cover_luma_error": luma_error,
                    "image_url_count": len(image_urls),
                    "stale_url_count": len(stale_urls),
                    "stale_urls": stale_urls,
                    "fallback_notice_detected": fallback_notice,
                    "result": "issue" if issue_types else "ok",
                }
            )

            if not args.apply:
                continue
            if not issue_types:
                continue

            repair_action: list[str] = []
            update_payload: dict[str, Any] = {}
            error_text = ""
            regenerated_cover = ""

            if stale_urls and cover_image:
                replacements = {url: cover_image for url in stale_urls}
                updated_content = _replace_content_urls(content, replacements)
                if updated_content != content:
                    update_payload["content"] = updated_content
                    repair_action.append("replace_stale_content_urls")

            if fallback_notice:
                next_alt = _build_cover_alt(detail)
                if next_alt and next_alt != cover_alt:
                    update_payload["coverAlt"] = next_alt
                    repair_action.append("clean_cover_alt")

            if dark_cover:
                try:
                    visual_prompt = _build_visual_prompt(detail)
                    generated_bytes, _raw = image_provider.generate_image(visual_prompt, slug or post_id)
                    regenerated_cover = _upload_integration_asset(
                        db,
                        post_slug=slug or post_id,
                        alt_text=_build_cover_alt(detail),
                        filename=f"{(slug or post_id)}-cover.png",
                        image_bytes=generated_bytes,
                    )
                    update_payload["coverImage"] = regenerated_cover
                    update_payload["coverAlt"] = _build_cover_alt(detail)
                    if "content" in update_payload:
                        # 본문 정합성 규칙: 최신 coverImage 기준 치환
                        update_payload["content"] = _replace_content_urls(
                            _safe_str(update_payload["content"]),
                            {url: regenerated_cover for url in stale_urls},
                        )
                    repair_action.append("regenerate_cover")
                except Exception as exc:  # noqa: BLE001
                    error_text = f"cover_regeneration_failed:{exc}"

            result = "skipped"
            updated_post: dict[str, Any] = detail

            if error_text and not update_payload:
                result = "failed"
            elif update_payload:
                try:
                    updated_post = _integration_update_post(db, post_id, update_payload)
                    result = "repaired"
                except Exception as exc:  # noqa: BLE001
                    result = "failed"
                    error_text = f"update_failed:{exc}"
            else:
                result = "partial" if error_text else "skipped"

            final_content = _content_of(updated_post)
            final_cover = _safe_str(updated_post.get("coverImage")) or regenerated_cover or cover_image
            final_luma, final_luma_error = _download_image_luma(final_cover, timeout=float(args.timeout))
            remaining_urls = [url for url in stale_urls if url in final_content]

            repair_items.append(
                {
                    "post_id": post_id,
                    "slug": slug,
                    "title": title,
                    "post_url": _safe_str(updated_post.get("publicUrl") or updated_post.get("url") or public_url),
                    "published_at": published_at,
                    "published_kst_date": str(published_kst_date),
                    "issue_type": issue_types,
                    "repair_action": repair_action or ["none"],
                    "payload_keys": sorted(update_payload.keys()),
                    "result": result,
                    "error": error_text,
                    "replaced_url_count": len(stale_urls),
                    "remaining_stale_url_count": len(remaining_urls),
                    "remaining_stale_urls": remaining_urls,
                    "final_cover_image": final_cover,
                    "final_cover_luma": final_luma,
                    "final_cover_luma_error": final_luma_error,
                    "final_cover_dark": (final_luma is None and bool(final_luma_error))
                    or (final_luma is not None and float(final_luma) <= float(args.luma_threshold)),
                }
            )

    repair_target_items = [row for row in repair_items if row.get("result") != "skipped"]
    live_checks = _sample_live_verification(
        [row for row in repair_items if row.get("result") == "repaired"],
        timeout=float(args.timeout),
        sample_size=max(int(args.verify_live_sample), 0),
    )

    audit_payload = {
        "generated_at": _utc_now_iso(),
        "target_date_kst": str(target_date),
        "exclude_date_kst": str(exclude_date),
        "luma_threshold": float(args.luma_threshold),
        "total_target_posts": len(audit_items),
        "issue_count": len([row for row in audit_items if row.get("result") == "issue"]),
        "items": audit_items,
    }
    repair_payload = {
        "generated_at": _utc_now_iso(),
        "target_date_kst": str(target_date),
        "exclude_date_kst": str(exclude_date),
        "apply": bool(args.apply),
        "luma_threshold": float(args.luma_threshold),
        "total_target_posts": len(audit_items),
        "repair_attempt_count": len(repair_target_items),
        "repaired_count": len([row for row in repair_items if row.get("result") == "repaired"]),
        "failed_count": len([row for row in repair_items if row.get("result") == "failed"]),
        "remaining_stale_url_total": sum(int(row.get("remaining_stale_url_count") or 0) for row in repair_items),
        "dark_cover_remaining_count": len([row for row in repair_items if row.get("final_cover_dark")]),
        "live_verification_sample": live_checks,
        "items": repair_items,
    }

    audit_path = _report_path(args.report_prefix_audit, stamp)
    repair_path = _report_path(args.report_prefix_repair, stamp)
    audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    repair_path.write_text(json.dumps(repair_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "ok",
                "apply": bool(args.apply),
                "target_date_kst": str(target_date),
                "exclude_date_kst": str(exclude_date),
                "total_target_posts": len(audit_items),
                "issue_count": audit_payload["issue_count"],
                "repair_attempt_count": repair_payload["repair_attempt_count"],
                "repaired_count": repair_payload["repaired_count"],
                "failed_count": repair_payload["failed_count"],
                "remaining_stale_url_total": repair_payload["remaining_stale_url_total"],
                "dark_cover_remaining_count": repair_payload["dark_cover_remaining_count"],
                "audit_report": str(audit_path.resolve()),
                "repair_report": str(repair_path.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

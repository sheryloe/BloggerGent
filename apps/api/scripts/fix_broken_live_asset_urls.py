from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse, urlunparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@postgres:5432/bloggent",
    )
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Blog, SyncedBloggerPost  # noqa: E402
from app.services.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
    _list_integration_posts,
)
from app.services.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402

LIVE_STATUSES = {"live", "published"}
IMG_URL_RE = re.compile(
    r"https?://[^\s'\"<>)\]]+",
    re.IGNORECASE,
)


@dataclass
class BloggerTarget:
    source: str
    post_id: str
    title: str
    post_url: str
    content: str
    cover_url: str
    blog_id: int
    labels: list[str]
    excerpt: str


@dataclass
class CloudflareTarget:
    source: str
    post_id: str
    title: str
    post_url: str
    content: str
    cover_url: str
    cover_alt: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fix broken live post asset URLs (Blogger + Cloudflare).",
    )
    parser.add_argument("--mode", choices=("dry-run", "canary", "full"), default="dry-run")
    parser.add_argument("--canary-count", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--report-path", default="")
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _is_live_status(value: Any) -> bool:
    return _safe_str(value).lower() in LIVE_STATUSES


def _collect_image_urls(content: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in IMG_URL_RE.finditer(content or ""):
        url = _safe_str(match.group(0))
        if not url:
            continue
        if "/assets/" not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _quote_path(path: str) -> str:
    return quote(unquote(path), safe="/-_.~")


def _normalize_url(url: str) -> str:
    parsed = urlparse(_safe_str(url))
    if not parsed.scheme or not parsed.netloc:
        return _safe_str(url)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            _quote_path(parsed.path),
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _build_candidate_url(url: str, from_token: str, to_token: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    if from_token not in path:
        return ""
    replaced = path.replace(from_token, to_token, 1)
    if replaced == path:
        return ""
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            _quote_path(replaced),
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _switch_ext(url: str, ext: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    dot = path.rfind(".")
    if dot <= path.rfind("/"):
        return ""
    replaced = f"{path[:dot]}{ext}"
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            _quote_path(replaced),
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _candidate_urls(url: str) -> list[str]:
    base = _normalize_url(url)
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        return []

    candidates: list[str] = []
    replacements = [
        ("/assets/media/", "/assets/assets/media/"),
        ("/assets/assets/media/", "/assets/media/"),
    ]
    for from_token, to_token in replacements:
        candidate = _build_candidate_url(base, from_token, to_token)
        if candidate:
            candidates.append(candidate)

    ext_candidates: list[str] = []
    for item in [base, *candidates]:
        lower_path = urlparse(item).path.lower()
        if lower_path.endswith(".webp"):
            for ext in (".png", ".jpg", ".jpeg"):
                switched = _switch_ext(item, ext)
                if switched:
                    ext_candidates.append(switched)
        elif lower_path.endswith(".png"):
            switched = _switch_ext(item, ".webp")
            if switched:
                ext_candidates.append(switched)

    all_candidates: list[str] = []
    seen: set[str] = set()
    for item in [*candidates, *ext_candidates]:
        normalized = _normalize_url(item)
        if normalized and normalized != base and normalized not in seen:
            seen.add(normalized)
            all_candidates.append(normalized)
    return all_candidates


def _probe_url(client: httpx.Client, url: str, timeout: float, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    normalized = _normalize_url(url)
    cached = cache.get(normalized)
    if cached is not None:
        return cached
    result: dict[str, Any]
    try:
        response = client.get(normalized, timeout=timeout, follow_redirects=True)
        status_code = int(response.status_code)
        content_type = _safe_str(response.headers.get("content-type")).lower()
        ok = status_code < 400 and ("image/" in content_type or status_code == 200)
        result = {
            "url": normalized,
            "status_code": status_code,
            "ok": bool(ok),
            "content_type": content_type,
        }
    except Exception as exc:  # noqa: BLE001
        result = {
            "url": normalized,
            "status_code": 0,
            "ok": False,
            "error": str(exc),
        }
    cache[normalized] = result
    return result


def _resolve_url(
    *,
    client: httpx.Client,
    url: str,
    timeout: float,
    cache: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    probe = _probe_url(client, url, timeout, cache)
    if probe.get("ok"):
        return _normalize_url(url), probe, []

    candidates = _candidate_urls(url)
    candidate_probes: list[dict[str, Any]] = []
    for candidate in candidates:
        c_probe = _probe_url(client, candidate, timeout, cache)
        candidate_probes.append(c_probe)
        if c_probe.get("ok"):
            return candidate, probe, candidate_probes
    return _normalize_url(url), probe, candidate_probes


def _fetch_cloudflare_detail(db, post_id: str) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="GET",
        path=f"/api/integrations/posts/{post_id}",
        timeout=90.0,
    )
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _collect_targets(db) -> tuple[list[BloggerTarget], list[CloudflareTarget]]:
    blogger_targets: list[BloggerTarget] = []
    cloudflare_targets: list[CloudflareTarget] = []

    blogger_posts = (
        db.execute(
            select(SyncedBloggerPost)
            .join(Blog, Blog.id == SyncedBloggerPost.blog_id)
            .options(selectinload(SyncedBloggerPost.blog))
            .where(Blog.is_active.is_(True))
            .order_by(SyncedBloggerPost.blog_id.asc(), SyncedBloggerPost.id.asc())
        )
        .scalars()
        .all()
    )

    for post in blogger_posts:
        if not _is_live_status(post.status):
            continue
        blog_id = int(post.blog_id)
        blogger_targets.append(
            BloggerTarget(
                source="blogger",
                post_id=_safe_str(post.remote_post_id),
                title=_safe_str(post.title) or "Untitled",
                post_url=_safe_str(post.url),
                content=_safe_str(post.content_html),
                cover_url=_safe_str(post.thumbnail_url),
                blog_id=blog_id,
                labels=list(post.labels or []),
                excerpt=_safe_str(post.excerpt_text),
            )
        )

    cloudflare_rows = _list_integration_posts(db)
    for row in cloudflare_rows:
        if not _is_live_status(row.get("status")):
            continue
        post_id = _safe_str(row.get("id"))
        if not post_id:
            continue
        detail = _fetch_cloudflare_detail(db, post_id)
        if not detail:
            continue
        content = _safe_str(detail.get("content") or detail.get("contentMarkdown") or detail.get("content_markdown"))
        cloudflare_targets.append(
            CloudflareTarget(
                source="cloudflare",
                post_id=post_id,
                title=_safe_str(detail.get("title")) or "Untitled",
                post_url=_safe_str(detail.get("publicUrl") or detail.get("url")),
                content=content,
                cover_url=_safe_str(detail.get("coverImage")),
                cover_alt=_safe_str(detail.get("coverAlt") or detail.get("coverImageAlt") or detail.get("title")),
            )
        )

    return blogger_targets, cloudflare_targets


def _update_blogger(
    db,
    *,
    target: BloggerTarget,
    updated_content: str,
    updated_cover_url: str,
) -> tuple[bool, str]:
    blog = db.get(Blog, target.blog_id)
    if blog is None:
        return False, "blog_not_found"

    provider = get_blogger_provider(db, blog)
    try:
        provider.update_post(
            post_id=target.post_id,
            title=target.title,
            content=updated_content,
            labels=list(target.labels or []),
            meta_description=target.excerpt[:300],
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"blogger_update_failed:{exc}"

    row = db.execute(
        select(SyncedBloggerPost).where(
            SyncedBloggerPost.blog_id == target.blog_id,
            SyncedBloggerPost.remote_post_id == target.post_id,
        )
    ).scalar_one_or_none()
    if row is not None:
        row.content_html = updated_content
        row.thumbnail_url = updated_cover_url
        row.synced_at = datetime.now(timezone.utc)
        db.add(row)
    db.commit()
    return True, "ok"


def _update_cloudflare(
    db,
    *,
    target: CloudflareTarget,
    updated_content: str,
    updated_cover_url: str,
) -> tuple[bool, str]:
    payload = {
        "content": updated_content,
        "coverImage": updated_cover_url,
        "coverAlt": target.cover_alt or target.title,
    }
    try:
        response = _integration_request(
            db,
            method="PUT",
            path=f"/api/integrations/posts/{target.post_id}",
            json_payload=payload,
            timeout=120.0,
        )
        _integration_data_or_raise(response)
    except Exception as exc:  # noqa: BLE001
        return False, f"cloudflare_update_failed:{exc}"
    return True, "ok"


def _report_base(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "canary_count": int(args.canary_count),
        "summary": {
            "scanned_blogger_posts": 0,
            "scanned_cloudflare_posts": 0,
            "broken_urls_found": 0,
            "resolved_urls": 0,
            "unresolved_urls": 0,
            "candidate_swaps_applied": 0,
            "updated_posts": 0,
            "failed_posts": 0,
        },
        "items": [],
    }


def _resolve_post_urls(
    *,
    client: httpx.Client,
    content: str,
    cover_url: str,
    timeout: float,
    cache: dict[str, dict[str, Any]],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    replacements: dict[str, str] = {}
    traces: list[dict[str, Any]] = []

    urls = _collect_image_urls(content)
    if _safe_str(cover_url):
        urls.append(_safe_str(cover_url))
    unique_urls = sorted(set(urls))

    for original_url in unique_urls:
        resolved, original_probe, candidate_probes = _resolve_url(
            client=client,
            url=original_url,
            timeout=timeout,
            cache=cache,
        )
        traces.append(
            {
                "original_url": original_url,
                "original_probe": original_probe,
                "resolved_url": resolved,
                "candidate_probes": candidate_probes,
                "resolved": bool(resolved != _normalize_url(original_url)),
            }
        )
        if resolved != _normalize_url(original_url):
            replacements[original_url] = resolved
    return replacements, traces


def _apply_replacements(content: str, replacements: dict[str, str]) -> str:
    updated = content
    for old, new in replacements.items():
        updated = updated.replace(old, new)
    return updated


def main() -> int:
    args = parse_args()
    apply_mode = args.mode in {"canary", "full"}
    report = _report_base(args)

    with SessionLocal() as db:
        blogger_targets, cloudflare_targets = _collect_targets(db)
        report["summary"]["scanned_blogger_posts"] = len(blogger_targets)
        report["summary"]["scanned_cloudflare_posts"] = len(cloudflare_targets)

        combined: list[BloggerTarget | CloudflareTarget] = [*blogger_targets, *cloudflare_targets]
        if args.mode == "canary":
            combined = combined[: max(int(args.canary_count or 1), 1)]

        touched_blogs: set[int] = set()
        touched_cloudflare = False
        url_probe_cache: dict[str, dict[str, Any]] = {}

        with httpx.Client(timeout=max(float(args.timeout), 5.0), follow_redirects=True) as client:
            for target in combined:
                replacements, traces = _resolve_post_urls(
                    client=client,
                    content=target.content,
                    cover_url=target.cover_url,
                    timeout=float(args.timeout),
                    cache=url_probe_cache,
                )

                broken_count = 0
                unresolved_count = 0
                for trace in traces:
                    original_ok = bool((trace.get("original_probe") or {}).get("ok"))
                    if not original_ok:
                        broken_count += 1
                    if (not original_ok) and (not bool(trace.get("resolved"))):
                        unresolved_count += 1

                report["summary"]["broken_urls_found"] += broken_count
                report["summary"]["resolved_urls"] += len(replacements)
                report["summary"]["unresolved_urls"] += unresolved_count

                if not replacements:
                    continue

                updated_content = _apply_replacements(target.content, replacements)
                updated_cover_url = replacements.get(target.cover_url, target.cover_url)
                changed = (updated_content != target.content) or (updated_cover_url != target.cover_url)
                if not changed:
                    continue

                report["summary"]["candidate_swaps_applied"] += 1

                item: dict[str, Any] = {
                    "source": target.source,
                    "post_id": target.post_id,
                    "post_url": target.post_url,
                    "title": target.title,
                    "replacements": replacements,
                    "trace": traces,
                    "status": "planned",
                }

                if apply_mode:
                    if isinstance(target, BloggerTarget):
                        ok, reason = _update_blogger(
                            db,
                            target=target,
                            updated_content=updated_content,
                            updated_cover_url=updated_cover_url,
                        )
                        if ok:
                            touched_blogs.add(target.blog_id)
                    else:
                        ok, reason = _update_cloudflare(
                            db,
                            target=target,
                            updated_content=updated_content,
                            updated_cover_url=updated_cover_url,
                        )
                        if ok:
                            touched_cloudflare = True

                    if ok:
                        item["status"] = "updated"
                        item["reason"] = "ok"
                        report["summary"]["updated_posts"] += 1
                    else:
                        item["status"] = "failed"
                        item["reason"] = reason
                        report["summary"]["failed_posts"] += 1

                report["items"].append(item)

        if apply_mode:
            for blog_id in sorted(touched_blogs):
                blog = db.get(Blog, blog_id)
                if blog is None:
                    continue
                try:
                    sync_blogger_posts_for_blog(db, blog)
                except Exception as exc:  # noqa: BLE001
                    report["summary"]["failed_posts"] += 1
                    report["items"].append(
                        {
                            "source": "blogger",
                            "post_id": "",
                            "status": "failed",
                            "reason": f"sync_blogger_failed:{blog_id}:{exc}",
                        }
                    )
            if touched_cloudflare:
                try:
                    sync_cloudflare_posts(db, include_non_published=False)
                except Exception as exc:  # noqa: BLE001
                    report["summary"]["failed_posts"] += 1
                    report["items"].append(
                        {
                            "source": "cloudflare",
                            "post_id": "",
                            "status": "failed",
                            "reason": f"sync_cloudflare_failed:{exc}",
                        }
                    )

    stamp = _timestamp()
    default_report = REPO_ROOT / "storage" / "reports" / f"fix-broken-live-asset-urls-{stamp}.json"
    report_path = Path(args.report_path) if _safe_str(args.report_path) else default_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "report_path": str(report_path),
                "summary": report["summary"],
                "mode": args.mode,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

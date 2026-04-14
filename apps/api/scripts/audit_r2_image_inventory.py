from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

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
from app.models.entities import Article, Image, R2AssetRelayoutMapping, SyncedBloggerPost, SyncedCloudflarePost  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import _integration_data_or_raise, _integration_request, _list_integration_posts  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import _resolve_cloudflare_r2_configuration, normalize_r2_url_to_key  # noqa: E402

IMG_SRC_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
SRCSET_RE = re.compile(r"\bsrcset=['\"]([^'\"]+)['\"]", re.IGNORECASE)
MD_IMG_RE = re.compile(r"!\[[^\]]*]\(([^)\s]+)\)")
URL_RE = re.compile(r"https?://[^\s'\"<>)\]]+")
LIVE_STATUSES = {"live", "published", "LIVE", "PUBLISHED"}
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


@dataclass
class RefItem:
    source: str
    post_id: str
    title: str
    url: str
    role: str
    ref_url: str
    key: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Cloudflare R2 object inventory and content references.")
    parser.add_argument("--report-path", default="")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--sample-size", type=int, default=200)
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _s3_quote(value: str) -> str:
    return quote(value, safe="-_.~")


def _canonical_query(params: dict[str, str]) -> str:
    return "&".join(f"{_s3_quote(str(key))}={_s3_quote(str(params[key]))}" for key in sorted(params))


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_access_key: str, date_stamp: str) -> bytes:
    k_date = _sign(("AWS4" + secret_access_key).encode("utf-8"), date_stamp)
    k_region = hmac.new(k_date, b"auto", hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


def _list_r2_objects(
    *,
    account_id: str,
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
) -> list[dict[str, Any]]:
    host = f"{account_id}.r2.cloudflarestorage.com"
    continuation_token = ""
    objects: list[dict[str, Any]] = []

    with httpx.Client(timeout=120.0) as client:
        while True:
            now = datetime.now(timezone.utc)
            amz_date = now.strftime("%Y%m%dT%H%M%SZ")
            date_stamp = now.strftime("%Y%m%d")
            payload_hash = hashlib.sha256(b"").hexdigest()
            params: dict[str, str] = {"list-type": "2", "max-keys": "1000"}
            if continuation_token:
                params["continuation-token"] = continuation_token
            canonical_query = _canonical_query(params)
            canonical_uri = "/" + quote(bucket, safe="-_.~/")
            canonical_headers = (
                f"host:{host}\n"
                f"x-amz-content-sha256:{payload_hash}\n"
                f"x-amz-date:{amz_date}\n"
            )
            signed_headers = "host;x-amz-content-sha256;x-amz-date"
            canonical_request = "\n".join(
                ["GET", canonical_uri, canonical_query, canonical_headers, signed_headers, payload_hash]
            )
            credential_scope = f"{date_stamp}/auto/s3/aws4_request"
            string_to_sign = "\n".join(
                [
                    "AWS4-HMAC-SHA256",
                    amz_date,
                    credential_scope,
                    hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
                ]
            )
            signature = hmac.new(
                _signing_key(secret_access_key, date_stamp),
                string_to_sign.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            authorization = (
                f"AWS4-HMAC-SHA256 Credential={access_key_id}/{credential_scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            )
            headers = {
                "Host": host,
                "x-amz-content-sha256": payload_hash,
                "x-amz-date": amz_date,
                "Authorization": authorization,
            }
            url = f"https://{host}/{quote(bucket, safe='-_.~/')}?{canonical_query}"
            response = client.get(url, headers=headers)
            response.raise_for_status()
            root = ET.fromstring(response.text)

            for node in root.findall(f".//{S3_NS}Contents"):
                key = _safe_str(node.findtext(f"{S3_NS}Key"))
                if not key:
                    continue
                size_text = _safe_str(node.findtext(f"{S3_NS}Size"))
                etag = _safe_str(node.findtext(f"{S3_NS}ETag")).strip('"')
                try:
                    size = int(size_text)
                except ValueError:
                    size = 0
                objects.append({"key": key, "size": size, "etag": etag})

            truncated = _safe_str(root.findtext(f".//{S3_NS}IsTruncated")).lower() == "true"
            if not truncated:
                break
            continuation_token = _safe_str(root.findtext(f".//{S3_NS}NextContinuationToken"))
            if not continuation_token:
                break
    return objects


def _normalize_key_from_url(url: str) -> str:
    key = _safe_str(normalize_r2_url_to_key(url)).lstrip("/")
    while key.startswith("assets/assets/"):
        key = key[len("assets/") :]
    return key


def _extract_srcset_urls(srcset_value: str) -> list[str]:
    urls: list[str] = []
    for part in (srcset_value or "").split(","):
        candidate = _safe_str(part.split(" ")[0])
        if candidate:
            urls.append(candidate)
    return urls


def _extract_image_urls(content: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in IMG_SRC_RE.finditer(content or ""):
        value = _safe_str(match.group(1))
        if value and value not in seen:
            seen.add(value)
            urls.append(value)
    for match in SRCSET_RE.finditer(content or ""):
        for value in _extract_srcset_urls(match.group(1)):
            if value and value not in seen:
                seen.add(value)
                urls.append(value)
    for match in MD_IMG_RE.finditer(content or ""):
        value = _safe_str(match.group(1))
        if value and value not in seen:
            seen.add(value)
            urls.append(value)
    for match in URL_RE.finditer(content or ""):
        value = _safe_str(match.group(0))
        lowered = value.lower()
        if value and value not in seen and any(token in lowered for token in ("/assets/", ".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif")):
            seen.add(value)
            urls.append(value)
    return urls


def _collect_article_refs(db) -> list[RefItem]:
    refs: list[RefItem] = []
    articles = (
        db.execute(select(Article).options(selectinload(Article.image)).order_by(Article.id.asc()))
        .scalars()
        .all()
    )
    for article in articles:
        if article.image and _safe_str(article.image.public_url):
            key = _normalize_key_from_url(article.image.public_url)
            if key:
                refs.append(
                    RefItem(
                        source="article",
                        post_id=str(article.id),
                        title=_safe_str(article.title),
                        url="",
                        role="cover",
                        ref_url=_safe_str(article.image.public_url),
                        key=key,
                    )
                )
        for media in list(article.inline_media or []):
            if isinstance(media, dict):
                raw_url = _safe_str(media.get("url") or media.get("public_url") or media.get("src"))
            else:
                raw_url = _safe_str(media)
            key = _normalize_key_from_url(raw_url)
            if key:
                refs.append(
                    RefItem(
                        source="article",
                        post_id=str(article.id),
                        title=_safe_str(article.title),
                        url="",
                        role="inline",
                        ref_url=raw_url,
                        key=key,
                    )
                )
        for raw_url in _extract_image_urls(_safe_str(article.assembled_html) or _safe_str(article.html_article)):
            key = _normalize_key_from_url(raw_url)
            if key:
                refs.append(
                    RefItem(
                        source="article",
                        post_id=str(article.id),
                        title=_safe_str(article.title),
                        url="",
                        role="inline_html",
                        ref_url=raw_url,
                        key=key,
                    )
                )
    return refs


def _collect_blogger_refs(db) -> tuple[list[RefItem], list[dict[str, Any]]]:
    refs: list[RefItem] = []
    zero_inline_with_refs: list[dict[str, Any]] = []
    posts = (
        db.execute(
            select(SyncedBloggerPost)
            .where(SyncedBloggerPost.status.in_(sorted(LIVE_STATUSES)))
            .options(selectinload(SyncedBloggerPost.blog))
            .order_by(SyncedBloggerPost.blog_id.asc(), SyncedBloggerPost.id.asc())
        )
        .scalars()
        .all()
    )
    for post in posts:
        title = _safe_str(post.title)
        post_url = _safe_str(post.url)
        inline_keys: list[str] = []
        if _safe_str(post.thumbnail_url):
            key = _normalize_key_from_url(post.thumbnail_url)
            if key:
                refs.append(
                    RefItem(
                        source=f"blogger:{post.blog_id}",
                        post_id=_safe_str(post.remote_post_id),
                        title=title,
                        url=post_url,
                        role="cover",
                        ref_url=_safe_str(post.thumbnail_url),
                        key=key,
                    )
                )
        for raw_url in _extract_image_urls(_safe_str(post.content_html)):
            key = _normalize_key_from_url(raw_url)
            if not key:
                continue
            inline_keys.append(key)
            refs.append(
                RefItem(
                    source=f"blogger:{post.blog_id}",
                    post_id=_safe_str(post.remote_post_id),
                    title=title,
                    url=post_url,
                    role="inline",
                    ref_url=raw_url,
                    key=key,
                )
            )
        if int(post.live_image_count or 0) == 0 and inline_keys:
            zero_inline_with_refs.append(
                {
                    "source": f"blogger:{post.blog_id}",
                    "post_id": _safe_str(post.remote_post_id),
                    "title": title,
                    "url": post_url,
                    "inline_keys": sorted(set(inline_keys))[:5],
                }
            )
    return refs, zero_inline_with_refs


def _fetch_cloudflare_detail(db, post_id: str) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="GET",
        path=f"/api/integrations/posts/{post_id}",
        timeout=90.0,
    )
    payload = _integration_data_or_raise(response)
    return payload if isinstance(payload, dict) else {}


def _collect_cloudflare_refs(db) -> tuple[list[RefItem], list[dict[str, Any]], list[dict[str, Any]]]:
    refs: list[RefItem] = []
    zero_inline_with_refs: list[dict[str, Any]] = []
    metadata_failures: list[dict[str, Any]] = []
    synced_map = {
        _safe_str(item.remote_post_id): item
        for item in db.execute(
            select(SyncedCloudflarePost).where(SyncedCloudflarePost.status.in_(sorted(LIVE_STATUSES)))
        ).scalars()
    }
    for row in _list_integration_posts(db):
        if _safe_str(row.get("status")).lower() not in {"live", "published"}:
            continue
        post_id = _safe_str(row.get("id"))
        if not post_id:
            continue
        detail = _fetch_cloudflare_detail(db, post_id)
        title = _safe_str(detail.get("title"))
        post_url = _safe_str(detail.get("publicUrl") or detail.get("url"))
        cover_url = _safe_str(detail.get("coverImage"))
        if cover_url:
            key = _normalize_key_from_url(cover_url)
            if key:
                refs.append(
                    RefItem(
                        source="cloudflare",
                        post_id=post_id,
                        title=title,
                        url=post_url,
                        role="cover",
                        ref_url=cover_url,
                        key=key,
                    )
                )
        inline_keys: list[str] = []
        content = _safe_str(detail.get("content") or detail.get("contentMarkdown") or detail.get("content_markdown"))
        for raw_url in _extract_image_urls(content):
            key = _normalize_key_from_url(raw_url)
            if not key:
                continue
            inline_keys.append(key)
            refs.append(
                RefItem(
                    source="cloudflare",
                    post_id=post_id,
                    title=title,
                    url=post_url,
                    role="inline",
                    ref_url=raw_url,
                    key=key,
                )
            )
        synced = synced_map.get(post_id)
        if synced and int(synced.live_image_count or 0) == 0 and inline_keys:
            zero_inline_with_refs.append(
                {
                    "source": "cloudflare",
                    "post_id": post_id,
                    "title": title,
                    "url": post_url,
                    "inline_keys": sorted(set(inline_keys))[:5],
                }
            )
        render_metadata = detail.get("metadata")
        if synced and synced.render_metadata and not render_metadata:
            metadata_failures.append(
                {
                    "post_id": post_id,
                    "title": title,
                    "url": post_url,
                    "local_render_metadata_keys": sorted((synced.render_metadata or {}).keys()),
                }
            )
    return refs, zero_inline_with_refs, metadata_failures


def _extension_for_key(key: str) -> str:
    suffix = Path(_safe_str(key)).suffix.lower()
    return suffix or "(none)"


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_path) if _safe_str(args.report_path) else REPO_ROOT.parent / "storage" / "reports" / f"r2-image-audit-{_timestamp()}.json"

    with SessionLocal() as db:
        settings_map = get_settings_map(db)
        account_id, bucket, access_key_id, secret_access_key, public_base_url, _prefix = _resolve_cloudflare_r2_configuration(settings_map)
        if not account_id or not bucket or not access_key_id or not secret_access_key:
            raise SystemExit("Cloudflare R2 credentials are required.")
        r2_objects = _list_r2_objects(
            account_id=account_id,
            bucket=bucket,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )

        article_refs = _collect_article_refs(db)
        blogger_refs, blogger_zero_inline = _collect_blogger_refs(db)
        cloudflare_refs, cloudflare_zero_inline, metadata_failures = _collect_cloudflare_refs(db)
        mappings = db.execute(select(R2AssetRelayoutMapping)).scalars().all()

    ext_counter = Counter()
    object_key_set: set[str] = set()
    etag_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in r2_objects:
        key = _safe_str(obj.get("key")).lstrip("/")
        object_key_set.add(key)
        ext_counter[_extension_for_key(key)] += 1
        etag = _safe_str(obj.get("etag"))
        if etag:
            etag_buckets[etag].append(obj)

    all_refs = [*article_refs, *blogger_refs, *cloudflare_refs]
    ref_counter: Counter[str] = Counter(item.key for item in all_refs if item.key)
    missing_refs = [
        {
            "source": item.source,
            "post_id": item.post_id,
            "title": item.title,
            "url": item.url,
            "role": item.role,
            "ref_url": item.ref_url,
            "key": item.key,
        }
        for item in all_refs
        if item.key and item.key not in object_key_set
    ]
    orphan_candidates = sorted(object_key_set - set(ref_counter.keys()))
    duplicate_candidates = [
        {
            "etag": etag,
            "count": len(items),
            "keys": sorted(_safe_str(item.get("key")) for item in items)[:10],
        }
        for etag, items in etag_buckets.items()
        if len(items) > 1
    ]
    duplicate_candidates.sort(key=lambda item: (-int(item["count"]), item["etag"]))

    report: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "public_base_url": _safe_str(public_base_url),
        "summary": {
            "r2_object_total": len(r2_objects),
            "r2_mapping_rows": len(mappings),
            "article_refs_total": len(article_refs),
            "blogger_refs_total": len(blogger_refs),
            "cloudflare_refs_total": len(cloudflare_refs),
            "unique_referenced_keys": len(ref_counter),
            "missing_ref_total": len(missing_refs),
            "orphan_candidate_total": len(orphan_candidates),
            "duplicate_candidate_total": len(duplicate_candidates),
            "blogger_zero_inline_but_has_refs": len(blogger_zero_inline),
            "cloudflare_zero_inline_but_has_refs": len(cloudflare_zero_inline),
            "cloudflare_metadata_persistence_failures": len(metadata_failures),
        },
        "extensions": dict(sorted(ext_counter.items())),
        "mapping_summary": {
            "status_counts": dict(Counter(_safe_str(item.status) or "unknown" for item in mappings)),
            "source_type_counts": dict(Counter(_safe_str(item.source_type) or "unknown" for item in mappings)),
        },
        "samples": {
            "missing_refs": missing_refs[: args.sample_size],
            "orphan_candidates": orphan_candidates[: args.sample_size],
            "duplicate_candidates": duplicate_candidates[: args.sample_size],
            "blogger_zero_inline_but_has_refs": blogger_zero_inline[: args.sample_size],
            "cloudflare_zero_inline_but_has_refs": cloudflare_zero_inline[: args.sample_size],
            "cloudflare_metadata_persistence_failures": metadata_failures[: args.sample_size],
            "top_referenced_keys": [
                {"key": key, "count": count}
                for key, count in ref_counter.most_common(args.sample_size)
            ],
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(report_path))
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

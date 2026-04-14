from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx
from slugify import slugify
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
from app.models.entities import Blog, R2AssetRelayoutMapping, SyncedBloggerPost  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
    _list_integration_posts,
    _safe_fallback_image_prompt,
    _upload_integration_asset,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.providers.factory import get_blogger_provider, get_image_provider  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import _resolve_cloudflare_r2_configuration  # noqa: E402

LIVE_STATUSES = {"live", "published"}
HTML_IMG_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
SRCSET_RE = re.compile(r"\bsrcset=['\"]([^'\"]+)['\"]", re.IGNORECASE)
MD_IMG_RE = re.compile(r"!\[[^\]]*]\(([^)\s]+)\)")
URL_RE = re.compile(r"https?://[^\s'\"<>)\]]+")
YEAR_MONTH_URL_RE = re.compile(r"/([0-9]{4})/([0-9]{2})/")
BLOGGER_SLUG_SUFFIX_RE = re.compile(r"_[0-9]+$")
WHITESPACE_RE = re.compile(r"\s+")
P_END_RE = re.compile(r"</p>", re.IGNORECASE)
SEO_META_DIV_RE = re.compile(r"<div\b[^>]*id=['\"]bloggent-seo-meta['\"][^>]*>.*?</div>", re.IGNORECASE | re.DOTALL)
HEADER_END_RE = re.compile(r"</header>", re.IGNORECASE)
RESTORE_FIGURE_RE = r"<figure\b[^>]*data-bloggent-restore-slot=['\"]{slot}['\"][^>]*>.*?</figure>"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

BLOGGENT_RESTORE_COVER = "<!--BLOGGENT_RESTORE_COVER-->"
BLOGGENT_RESTORE_INLINE_1 = "<!--BLOGGENT_RESTORE_INLINE_1-->"
BLOGGENT_RESTORE_INLINE_2 = "<!--BLOGGENT_RESTORE_INLINE_2-->"


@dataclass
class TargetPost:
    source: str
    post_id: str
    title: str
    post_url: str
    content: str
    month_key: str
    slug_seed: str
    group_name: str
    category_hint: str
    category_key: str
    cover_alt: str
    blog_id: int | None = None
    cloudflare_slug: str = ""
    labels: list[str] | None = None
    excerpt: str = ""
    blogger_thumbnail_url: str = ""


@dataclass
class MatchDecision:
    matched: bool
    reason: str
    cover_url: str = ""
    inline1_url: str = ""
    folder: str = ""
    score: float = 0.0
    candidates: list[dict[str, Any]] | None = None


def _normalize_slug_token(value: Any, fallback: str = "") -> str:
    token = slugify(_safe_str(value), separator="-")
    return token or fallback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore missing images for live Blogger/Cloudflare posts (none-only).",
    )
    parser.add_argument("--mode", choices=("dry-run", "canary", "full"), default="dry-run")
    parser.add_argument("--scope", choices=("none-only",), default="none-only")
    parser.add_argument("--match-policy", choices=("strict",), default="strict")
    parser.add_argument("--generate-slots", type=int, default=1)
    parser.add_argument("--generation-policy", choices=("existing-only", "generate"), default="existing-only")
    parser.add_argument("--model", default="gpt-image-1")
    parser.add_argument("--canary-count", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report-path", default="")
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _is_live_status(value: Any) -> bool:
    return _safe_str(value).lower() in LIVE_STATUSES


def _extract_srcset_urls(srcset_value: str) -> list[str]:
    urls: list[str] = []
    for part in (srcset_value or "").split(","):
        candidate = part.strip().split(" ")[0].strip()
        if candidate:
            urls.append(candidate)
    return urls


def _looks_like_image_url(url: str) -> bool:
    lowered = _safe_str(url).lower()
    if any(lowered.endswith(ext) for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif", ".svg")):
        return True
    return "/assets/media/" in lowered or "/cdn-cgi/image/" in lowered


def _extract_image_urls(content: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    for match in HTML_IMG_RE.finditer(content or ""):
        value = _safe_str(match.group(1))
        if value and value not in seen and _looks_like_image_url(value):
            seen.add(value)
            out.append(value)

    for match in SRCSET_RE.finditer(content or ""):
        for value in _extract_srcset_urls(match.group(1)):
            if value and value not in seen and _looks_like_image_url(value):
                seen.add(value)
                out.append(value)

    for match in MD_IMG_RE.finditer(content or ""):
        value = _safe_str(match.group(1))
        if value and value not in seen and _looks_like_image_url(value):
            seen.add(value)
            out.append(value)

    for match in URL_RE.finditer(content or ""):
        value = _safe_str(match.group(0))
        if value and value not in seen and _looks_like_image_url(value):
            seen.add(value)
            out.append(value)
    return out


def _classify_post(main_url: str, body_urls: list[str]) -> str:
    has_main = bool(_safe_str(main_url))
    body_count = len([url for url in body_urls if _safe_str(url)])
    if has_main and body_count >= 2:
        return "main+body2"
    if has_main and body_count == 1:
        return "main+body1"
    if (has_main and body_count == 0) or ((not has_main) and body_count == 1):
        return "one_only"
    return "none"


def _year_month_from_url(url: str) -> str:
    match = YEAR_MONTH_URL_RE.search(urlparse(_safe_str(url)).path or "")
    if not match:
        return ""
    return f"{match.group(1)}/{match.group(2)}"


def _year_month_from_iso(value: str) -> str:
    text = _safe_str(value)
    if not text:
        return ""
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return f"{parsed:%Y}/{parsed:%m}"


def _slug_seed_from_blogger(post_url: str, title: str) -> str:
    parsed = urlparse(_safe_str(post_url))
    token = _safe_str(unquote(parsed.path or "")).strip("/").split("/")[-1]
    token = token.replace(".html", "").strip()
    token = BLOGGER_SLUG_SUFFIX_RE.sub("", token).strip("-_")
    slug = slugify(token, separator="-") if token else ""
    if slug:
        return slug
    return slugify(title, separator="-") or "post"


def _slug_seed_from_cloudflare(slug: str, title: str) -> str:
    seeded = slugify(_safe_str(slug), separator="-")
    if seeded:
        return seeded
    return slugify(title, separator="-") or "post"


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
                [
                    "GET",
                    canonical_uri,
                    canonical_query,
                    canonical_headers,
                    signed_headers,
                    payload_hash,
                ]
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


def _strip_assets_prefix(key: str) -> str:
    normalized = _safe_str(unquote(key)).lstrip("/")
    if normalized.startswith("assets/"):
        return normalized[len("assets/") :]
    return normalized


def _public_origin_from_base(base_url: str) -> str:
    parsed = urlparse(_safe_str(base_url))
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_public_url_from_canonical_key(*, origin: str, canonical_key: str) -> str:
    key = _safe_str(canonical_key).lstrip("/")
    if not key:
        return ""
    return f"{origin}/assets/{key}"


def _extract_month_and_folder(canonical_key: str) -> tuple[str, str]:
    parts = _safe_str(canonical_key).split("/")
    if len(parts) < 6:
        return "", ""
    if parts[0] != "media" or parts[1] != "posts":
        return "", ""
    month_key = f"{parts[2]}/{parts[3]}"
    folder = parts[4]
    return month_key, folder


def _index_r2_objects(objects: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    indexed: dict[str, dict[str, list[str]]] = {}
    for item in objects:
        canonical = _strip_assets_prefix(_safe_str(item.get("key")))
        month_key, folder = _extract_month_and_folder(canonical)
        if not month_key or not folder:
            continue
        month_bucket = indexed.setdefault(month_key, {})
        folder_bucket = month_bucket.setdefault(folder, [])
        folder_bucket.append(canonical)
    for month_bucket in indexed.values():
        for folder, keys in month_bucket.items():
            month_bucket[folder] = sorted(set(keys))
    return indexed


def _score_folder_match(*, slug_seed: str, folder: str) -> tuple[float, bool]:
    seed = _safe_str(slug_seed)
    candidate = _safe_str(folder)
    if not seed or not candidate:
        return 0.0, False
    exact_prefix = seed == candidate or seed.startswith(candidate) or candidate.startswith(seed)
    if exact_prefix:
        return 1.0, True
    return SequenceMatcher(None, seed, candidate).ratio(), False


def _rank_folder_keys(keys: list[str]) -> tuple[str, str]:
    def ext_rank(path: str) -> int:
        lower = path.lower()
        if lower.endswith(".webp"):
            return 0
        if lower.endswith(".png"):
            return 1
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            return 2
        return 3

    def is_cover(path: str) -> int:
        name = Path(path).name.lower()
        return 0 if ("cover" in name or "hero" in name) else 1

    def is_inline(path: str) -> int:
        name = Path(path).name.lower()
        if "inline-1" in name:
            return 0
        if "inline" in name or "body" in name:
            return 1
        return 2

    unique_keys = sorted(set(keys))
    if not unique_keys:
        return "", ""
    cover_sorted = sorted(unique_keys, key=lambda item: (is_cover(item), ext_rank(item), item))
    cover_key = cover_sorted[0]
    inline_candidates = [item for item in unique_keys if item != cover_key]
    if inline_candidates:
        inline_sorted = sorted(inline_candidates, key=lambda item: (is_inline(item), ext_rank(item), item))
        inline1_key = inline_sorted[0]
    else:
        inline1_key = cover_key
    return cover_key, inline1_key


def _strict_match_existing_urls(
    *,
    target: TargetPost,
    r2_index: dict[str, dict[str, list[str]]],
    public_origin: str,
) -> MatchDecision:
    month_key = _safe_str(target.month_key)
    if not month_key:
        return MatchDecision(matched=False, reason="month_missing")
    month_bucket = r2_index.get(month_key) or {}
    if not month_bucket:
        return MatchDecision(matched=False, reason="month_bucket_missing")

    scored: list[tuple[float, bool, str]] = []
    for folder in month_bucket:
        score, is_prefix = _score_folder_match(slug_seed=target.slug_seed, folder=folder)
        if is_prefix or score >= 0.90:
            scored.append((score, is_prefix, folder))
    if not scored:
        return MatchDecision(matched=False, reason="strict_no_candidate")

    scored.sort(key=lambda item: (-item[0], item[2]))
    top_score, _top_prefix, top_folder = scored[0]
    if len(scored) >= 2:
        gap = top_score - scored[1][0]
        if gap < 0.08:
            return MatchDecision(
                matched=False,
                reason="strict_ambiguous",
                candidates=[
                    {"folder": folder, "score": round(score, 4), "prefix": bool(prefix)}
                    for score, prefix, folder in scored[:5]
                ],
            )

    folder_keys = month_bucket.get(top_folder) or []
    cover_key, inline1_key = _rank_folder_keys(folder_keys)
    if not cover_key:
        return MatchDecision(matched=False, reason="strict_folder_empty")
    cover_url = _build_public_url_from_canonical_key(origin=public_origin, canonical_key=cover_key)
    inline1_url = _build_public_url_from_canonical_key(origin=public_origin, canonical_key=inline1_key or cover_key)
    return MatchDecision(
        matched=True,
        reason="strict_matched",
        cover_url=cover_url,
        inline1_url=inline1_url,
        folder=top_folder,
        score=round(float(top_score), 4),
        candidates=[
            {"folder": folder, "score": round(score, 4), "prefix": bool(prefix)}
            for score, prefix, folder in scored[:5]
        ],
    )


def _month_from_migrated_key(key: str) -> str:
    canonical = _strip_assets_prefix(_safe_str(key))
    month_key, _folder = _extract_month_and_folder(canonical)
    return month_key


def _target_group_candidates(target: TargetPost) -> list[str]:
    candidates: list[str] = []
    if target.source == "cloudflare":
        candidates.extend(["cloudflare/dongri-archive", "archive", "dongri-archive"])
    else:
        profile_key = ""
        if ":" in _safe_str(target.category_hint):
            profile_key = _safe_str(target.category_hint.split(":", 1)[1])
        normalized_profile = _normalize_slug_token(profile_key, fallback="")
        normalized_group = _normalize_slug_token(target.group_name, fallback="")
        for item in (
            profile_key,
            normalized_profile,
            f"google-blogger/{profile_key}" if profile_key else "",
            f"google-blogger/{normalized_profile}" if normalized_profile else "",
            target.group_name,
            normalized_group,
        ):
            value = _safe_str(item)
            if value and value not in candidates:
                candidates.append(value)
    return candidates


def _target_category_candidates(target: TargetPost) -> list[str]:
    candidates: list[str] = []
    explicit = _safe_str(target.category_key)
    if explicit:
        candidates.append(explicit)
    inferred = _normalize_slug_token(target.category_hint, fallback="")
    if inferred and inferred not in candidates:
        candidates.append(inferred)
    if target.source == "blogger":
        profile_key = ""
        if ":" in _safe_str(target.category_hint):
            profile_key = _safe_str(target.category_hint.split(":", 1)[1])
        if "midnight" in profile_key or "mystery" in profile_key:
            if "mystery" not in candidates:
                candidates.append("mystery")
        for label in list(target.labels or []):
            normalized = _normalize_slug_token(label, fallback="")
            if normalized in {"travel", "culture", "food", "mystery"} and normalized not in candidates:
                candidates.append(normalized)
    return candidates


def _rank_mapping_keys(keys: list[str], *, desired_role: str) -> str:
    def ext_rank(path: str) -> int:
        lower = path.lower()
        if lower.endswith(".webp"):
            return 0
        if lower.endswith(".png"):
            return 1
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            return 2
        return 3

    def role_rank(path: str) -> int:
        name = Path(path).name.lower()
        if desired_role == "cover":
            return 0 if "cover" in name or "hero" in name else 1
        if "inline-1" in name:
            return 0
        if "inline" in name or "body" in name:
            return 1
        return 2

    unique = sorted({_strip_assets_prefix(_safe_str(item)) for item in keys if _safe_str(item)})
    if not unique:
        return ""
    return sorted(unique, key=lambda item: (role_rank(item), ext_rank(item), item))[0]


def _mapping_family_from_key(key: str) -> str:
    canonical = _strip_assets_prefix(_safe_str(key))
    parts = canonical.split("/")
    if len(parts) < 5:
        return ""
    folder = parts[4]
    family = re.sub(r"-(cover|hero|inline-\d+|inline)$", "", folder)
    return family or folder


def _fallback_match_existing_urls(
    *,
    target: TargetPost,
    mapping_rows: list[R2AssetRelayoutMapping],
    public_origin: str,
) -> MatchDecision:
    month_key = _safe_str(target.month_key)
    if not month_key:
        return MatchDecision(matched=False, reason="fallback_month_missing")

    group_candidates = set(_target_group_candidates(target))
    category_candidates = set(_target_category_candidates(target))
    if not group_candidates or not category_candidates:
        return MatchDecision(matched=False, reason="fallback_target_metadata_missing")

    family_buckets: dict[str, dict[str, list[str]]] = {}
    candidate_meta: list[dict[str, Any]] = []
    for row in mapping_rows:
        if _safe_str(row.source_type) != target.source:
            continue
        if _safe_str(row.blog_group) not in group_candidates:
            continue
        if _safe_str(row.category_key) not in category_candidates:
            continue
        migrated_key = _safe_str(row.migrated_key)
        if not migrated_key:
            continue
        if _month_from_migrated_key(migrated_key) != month_key:
            continue
        asset_role = _safe_str(row.asset_role)
        candidate_meta.append(
            {
                "blog_group": _safe_str(row.blog_group),
                "category_key": _safe_str(row.category_key),
                "asset_role": asset_role,
                "migrated_key": migrated_key,
            }
        )
        family = _mapping_family_from_key(migrated_key)
        bucket = family_buckets.setdefault(family, {"cover": [], "inline": []})
        if asset_role == "cover":
            bucket["cover"].append(migrated_key)
        elif asset_role.startswith("inline"):
            bucket["inline"].append(migrated_key)

    ranked_families: list[tuple[float, str]] = []
    for family, bucket in family_buckets.items():
        if not bucket["cover"] or not bucket["inline"]:
            continue
        score, is_prefix = _score_folder_match(slug_seed=target.slug_seed, folder=family)
        ranked_families.append((1.0 if is_prefix else score, family))
    ranked_families.sort(key=lambda item: (-item[0], item[1]))
    if not ranked_families:
        return MatchDecision(
            matched=False,
            reason="fallback_insufficient_assets",
            candidates=candidate_meta[:10],
        )

    selected_family = ranked_families[0][1]
    selected_bucket = family_buckets[selected_family]
    cover_key = _rank_mapping_keys(selected_bucket["cover"], desired_role="cover")
    inline1_key = _rank_mapping_keys(selected_bucket["inline"], desired_role="inline")
    if not cover_key or not inline1_key:
        return MatchDecision(
            matched=False,
            reason="fallback_insufficient_assets",
            candidates=candidate_meta[:10],
        )

    return MatchDecision(
        matched=True,
        reason="category_fallback_matched",
        cover_url=_build_public_url_from_canonical_key(origin=public_origin, canonical_key=cover_key),
        inline1_url=_build_public_url_from_canonical_key(origin=public_origin, canonical_key=inline1_key),
        folder=selected_family,
        score=ranked_families[0][0],
        candidates=candidate_meta[:10],
    )


def _escape_attr(value: str) -> str:
    return html.escape(_safe_str(value), quote=True)


def _make_cover_block(*, url: str, title: str, alt: str) -> str:
    alt_text = _escape_attr(alt or title)
    image_url = _escape_attr(url)
    return (
        f'{BLOGGENT_RESTORE_COVER}\n'
        '<figure data-bloggent-restore-slot="cover" style="margin:0 0 32px;">'
        f'<img src="{image_url}" alt="{alt_text}" loading="eager" decoding="async" '
        'style="width:100%;border-radius:28px;display:block;object-fit:cover;" />'
        "</figure>"
    )


def _make_inline_block(*, marker: str, slot: str, url: str, title: str, alt_suffix: str) -> str:
    alt_text = _escape_attr(f"{title} {alt_suffix}".strip())
    image_url = _escape_attr(url)
    return (
        f"{marker}\n"
        f'<figure data-bloggent-restore-slot="{slot}" style="margin:30px 0 30px;">'
        f'<img src="{image_url}" alt="{alt_text}" loading="lazy" decoding="async" '
        'style="width:100%;border-radius:20px;display:block;object-fit:cover;" />'
        "</figure>"
    )


def _remove_existing_restore_slot(content: str, *, marker: str, slot: str) -> str:
    cleaned = content
    cleaned = re.sub(re.escape(marker), "", cleaned)
    figure_re = re.compile(RESTORE_FIGURE_RE.format(slot=re.escape(slot)), re.IGNORECASE | re.DOTALL)
    cleaned = figure_re.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _insert_cover_block(content: str, block: str) -> str:
    seo_match = SEO_META_DIV_RE.search(content)
    if seo_match:
        index = seo_match.end()
        return f"{content[:index]}\n{block}\n{content[index:]}"
    header_match = HEADER_END_RE.search(content)
    if header_match:
        index = header_match.end()
        return f"{content[:index]}\n{block}\n{content[index:]}"
    return f"{block}\n{content}"


def _insert_inline_after_ratio(content: str, block: str, ratio: float) -> str:
    paragraph_matches = list(P_END_RE.finditer(content))
    if not paragraph_matches:
        return f"{content}\n{block}"
    target_index = int((len(paragraph_matches) - 1) * max(0.0, min(1.0, ratio)))
    insertion_point = paragraph_matches[target_index].end()
    return f"{content[:insertion_point]}\n{block}\n{content[insertion_point:]}"


def _apply_restore_markers(
    *,
    original_content: str,
    cover_url: str,
    inline1_url: str,
    title: str,
    cover_alt: str,
) -> str:
    content = original_content or ""
    content = _remove_existing_restore_slot(content, marker=BLOGGENT_RESTORE_COVER, slot="cover")
    content = _remove_existing_restore_slot(content, marker=BLOGGENT_RESTORE_INLINE_1, slot="inline-1")
    content = _remove_existing_restore_slot(content, marker=BLOGGENT_RESTORE_INLINE_2, slot="inline-2")

    cover_block = _make_cover_block(url=cover_url, title=title, alt=cover_alt)
    inline1_block = _make_inline_block(
        marker=BLOGGENT_RESTORE_INLINE_1,
        slot="inline-1",
        url=inline1_url,
        title=title,
        alt_suffix="supporting collage",
    )

    content = _insert_cover_block(content, cover_block)
    content = _insert_inline_after_ratio(content, inline1_block, 1 / 3)
    return content


def _first_content_paragraph(content: str) -> str:
    plain = WHITESPACE_RE.sub(" ", re.sub(r"<[^>]+>", " ", content or "")).strip()
    return plain[:300]


def _build_generation_prompt(*, category_name: str, title: str, slot: str, summary: str) -> str:
    base = _safe_fallback_image_prompt(category_name, title)
    summary_hint = _safe_str(summary)
    if slot == "cover":
        extra = (
            " Keep this as a hero cover. "
            "Use visually clear subject hierarchy with the center panel most dominant."
        )
    else:
        extra = (
            " Create a distinct supporting collage variant for in-article context. "
            "Do not duplicate the exact camera framing of the hero."
        )
    if summary_hint:
        extra += f" Context summary: {summary_hint}."
    return f"{base} {extra}"


def _check_url_health(url: str, timeout: float) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        return {
            "url": url,
            "status_code": response.status_code,
            "ok": bool(response.status_code < 400),
            "content_type": _safe_str(response.headers.get("content-type")),
        }
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "status_code": 0, "ok": False, "error": str(exc)}


def _fetch_cloudflare_detail(db, post_id: str) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="GET",
        path=f"/api/integrations/posts/{post_id}",
        timeout=90.0,
    )
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _collect_targets(db, *, scope: str) -> list[TargetPost]:
    if scope != "none-only":
        raise ValueError("Only none-only scope is supported.")

    targets: list[TargetPost] = []
    active_blogs = (
        db.execute(
            select(Blog)
            .where(Blog.is_active.is_(True), Blog.blogger_blog_id.is_not(None))
            .order_by(Blog.id.asc())
        )
        .scalars()
        .all()
    )

    for blog in active_blogs:
        try:
            sync_blogger_posts_for_blog(db, blog)
        except Exception:
            db.rollback()

    blogger_posts = (
        db.execute(
            select(SyncedBloggerPost)
            .where(SyncedBloggerPost.blog_id.in_([blog.id for blog in active_blogs]))
            .options(selectinload(SyncedBloggerPost.blog))
            .order_by(SyncedBloggerPost.blog_id.asc(), SyncedBloggerPost.id.asc())
        )
        .scalars()
        .all()
    )
    for post in blogger_posts:
        if not _is_live_status(post.status):
            continue
        content = _safe_str(post.content_html)
        image_urls = _extract_image_urls(content)
        main_url = _safe_str(post.thumbnail_url) or (image_urls[0] if image_urls else "")
        body_urls = [url for url in image_urls if _safe_str(url) and _safe_str(url) != _safe_str(main_url)][:2]
        post_class = _classify_post(main_url, body_urls)
        if post_class != "none":
            continue
        blog = post.blog
        if blog is None:
            continue
        targets.append(
            TargetPost(
                source="blogger",
                blog_id=blog.id,
                post_id=_safe_str(post.remote_post_id),
                title=_safe_str(post.title) or "Untitled",
                post_url=_safe_str(post.url),
                content=content,
                month_key=_year_month_from_url(_safe_str(post.url)),
                slug_seed=_slug_seed_from_blogger(_safe_str(post.url), _safe_str(post.title)),
                group_name=_safe_str(blog.name),
                category_hint=f"{_safe_str(blog.primary_language)}:{_safe_str(blog.profile_key)}",
                category_key=_normalize_slug_token((list(post.labels or [])[:1] or [""])[0], fallback="travel"),
                cover_alt=_safe_str(post.title) or "cover image",
                labels=list(post.labels or []),
                excerpt=_safe_str(post.excerpt_text),
                blogger_thumbnail_url=_safe_str(post.thumbnail_url),
            )
        )

    cloudflare_rows = _list_integration_posts(db)
    cloudflare_live = [
        row
        for row in cloudflare_rows
        if _is_live_status(row.get("status")) and _safe_str(row.get("id"))
    ]
    for row in cloudflare_live:
        post_id = _safe_str(row.get("id"))
        detail = _fetch_cloudflare_detail(db, post_id)
        if not detail:
            continue
        content = _safe_str(detail.get("content") or detail.get("contentMarkdown") or detail.get("content_markdown"))
        image_urls = _extract_image_urls(content)
        main_url = _safe_str(detail.get("coverImage")) or (image_urls[0] if image_urls else "")
        body_urls = [url for url in image_urls if _safe_str(url) and _safe_str(url) != _safe_str(main_url)][:2]
        post_class = _classify_post(main_url, body_urls)
        if post_class != "none":
            continue
        cloudflare_slug = _safe_str(detail.get("slug"))
        category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
        category_name = _safe_str(category.get("name")) or _safe_str(category.get("slug")) or "Cloudflare"
        category_slug = _safe_str(category.get("slug")) or _normalize_slug_token(category_name, fallback="")
        targets.append(
            TargetPost(
                source="cloudflare",
                post_id=post_id,
                title=_safe_str(detail.get("title")) or "Untitled",
                post_url=_safe_str(detail.get("publicUrl") or detail.get("url")),
                content=content,
                month_key=_year_month_from_url(_safe_str(detail.get("publicUrl")))
                or _year_month_from_iso(_safe_str(detail.get("publishedAt"))),
                slug_seed=_slug_seed_from_cloudflare(cloudflare_slug, _safe_str(detail.get("title"))),
                group_name="Dongri Archive",
                category_hint=category_name,
                category_key=category_slug,
                cover_alt=_safe_str(detail.get("coverAlt") or detail.get("coverImageAlt") or detail.get("title")),
                cloudflare_slug=cloudflare_slug,
                excerpt=_safe_str(detail.get("excerpt")),
            )
        )

    targets.sort(key=lambda item: (item.source, item.post_url, item.post_id))
    return targets


def _update_blogger_post(
    db,
    *,
    target: TargetPost,
    updated_content: str,
    cover_url: str,
) -> tuple[bool, str]:
    blog_id = target.blog_id
    if blog_id is None:
        return False, "blog_id_missing"
    blog = db.get(Blog, blog_id)
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

    post = db.execute(
        select(SyncedBloggerPost).where(
            SyncedBloggerPost.blog_id == blog.id,
            SyncedBloggerPost.remote_post_id == target.post_id,
        )
    ).scalar_one_or_none()
    if post is not None:
        post.content_html = updated_content
        post.thumbnail_url = cover_url
        post.synced_at = datetime.now(timezone.utc)
        db.add(post)
        db.commit()
    else:
        db.rollback()
    return True, "ok"


def _update_cloudflare_post(
    db,
    *,
    target: TargetPost,
    updated_content: str,
    cover_url: str,
) -> tuple[bool, str]:
    payload = {
        "content": updated_content,
        "coverImage": cover_url,
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


def _generate_and_upload_urls(
    db,
    *,
    target: TargetPost,
    model: str,
    generate_slots: int,
) -> tuple[bool, dict[str, str], str]:
    if generate_slots != 1:
        return False, {}, "generate_slots_must_be_1"
    slug_for_upload = _safe_str(target.cloudflare_slug) or target.slug_seed or slugify(target.title, separator="-") or target.post_id
    image_provider = get_image_provider(db, model_override=model)

    try:
        cover_prompt = _build_generation_prompt(
            category_name=target.category_hint or target.group_name,
            title=target.title,
            slot="cover",
            summary=target.excerpt or _first_content_paragraph(target.content),
        )
        cover_bytes, _cover_raw = image_provider.generate_image(cover_prompt, f"{slug_for_upload}-restore-cover")
        cover_url = _upload_integration_asset(
            db,
            post_slug=slug_for_upload,
            alt_text=target.cover_alt or target.title,
            filename=f"{slug_for_upload}-restore-cover.webp",
            image_bytes=cover_bytes,
        )

        inline_prompt = _build_generation_prompt(
            category_name=target.category_hint or target.group_name,
            title=target.title,
            slot="inline",
            summary=target.excerpt or _first_content_paragraph(target.content),
        )
        inline_bytes, _inline_raw = image_provider.generate_image(inline_prompt, f"{slug_for_upload}-restore-inline-1")
        inline1_url = _upload_integration_asset(
            db,
            post_slug=slug_for_upload,
            alt_text=f"{target.title} supporting collage",
            filename=f"{slug_for_upload}-restore-inline-1.webp",
            image_bytes=inline_bytes,
        )
    except Exception as exc:  # noqa: BLE001
        return False, {}, f"generation_or_upload_failed:{exc}"

    return True, {"cover": cover_url, "inline1": inline1_url}, "ok"


def _build_report_base(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "generated_at": _utc_now_iso(),
        "mode": args.mode,
        "scope": args.scope,
        "match_policy": args.match_policy,
        "generate_slots": int(args.generate_slots),
        "generation_policy": _safe_str(getattr(args, "generation_policy", "existing-only")) or "existing-only",
        "model": args.model,
        "canary_count": int(args.canary_count),
        "summary": {
            "targets": 0,
            "processed": 0,
            "matched_existing": 0,
            "generated": 0,
            "updated": 0,
            "failed": 0,
            "skipped": 0,
            "manual_review_required": 0,
        },
        "items": [],
    }


def main() -> int:
    args = parse_args()
    apply_mode = args.mode in {"canary", "full"}
    generation_policy = _safe_str(getattr(args, "generation_policy", "existing-only")) or "existing-only"
    report = _build_report_base(args)

    with SessionLocal() as db:
        settings_map = get_settings_map(db)
        account_id, bucket, access_key_id, secret_access_key, public_base_url, _prefix = _resolve_cloudflare_r2_configuration(
            settings_map
        )
        if not account_id or not bucket or not access_key_id or not secret_access_key:
            raise SystemExit("Cloudflare R2 credentials are required.")
        public_origin = _public_origin_from_base(public_base_url)
        if not public_origin:
            raise SystemExit("cloudflare_r2_public_base_url is required.")

        targets = _collect_targets(db, scope=args.scope)
        report["summary"]["targets"] = len(targets)
        mapping_rows = db.execute(select(R2AssetRelayoutMapping)).scalars().all()

        if args.mode == "canary":
            targets = targets[: max(int(args.canary_count or 1), 1)]

        r2_objects = _list_r2_objects(
            account_id=account_id,
            bucket=bucket,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )
        r2_index = _index_r2_objects(r2_objects)

        touched_blog_ids: set[int] = set()
        touched_cloudflare = False

        for target in targets:
            row: dict[str, Any] = {
                "source": target.source,
                "post_id": target.post_id,
                "post_url": target.post_url,
                "title": target.title,
                "slug_seed": target.slug_seed,
                "month_key": target.month_key,
                "mode": args.mode,
                "backup": {
                    "content": target.content,
                    "cover": target.blogger_thumbnail_url if target.source == "blogger" else "",
                },
            }
            report["summary"]["processed"] += 1

            decision = _strict_match_existing_urls(
                target=target,
                r2_index=r2_index,
                public_origin=public_origin,
            )
            row["match"] = {
                "matched": decision.matched,
                "reason": decision.reason,
                "folder": decision.folder,
                "score": decision.score,
                "candidates": decision.candidates or [],
            }

            resolved_urls: dict[str, str] = {}
            if not decision.matched:
                decision = _fallback_match_existing_urls(
                    target=target,
                    mapping_rows=mapping_rows,
                    public_origin=public_origin,
                )
                row["fallback_match"] = {
                    "matched": decision.matched,
                    "reason": decision.reason,
                    "folder": decision.folder,
                    "score": decision.score,
                    "candidates": decision.candidates or [],
                }
            if decision.matched:
                resolved_urls = {
                    "cover": decision.cover_url,
                    "inline1": decision.inline1_url,
                }
                report["summary"]["matched_existing"] += 1
            else:
                if generation_policy == "existing-only":
                    row["status"] = "manual_review_required" if apply_mode else "planned_manual_review_required"
                    row["reason"] = "existing_asset_match_missing"
                    report["summary"]["manual_review_required"] += 1
                    report["items"].append(row)
                    continue
                if not apply_mode:
                    report["summary"]["generated"] += 1
                    row["status"] = "planned_generate"
                    report["items"].append(row)
                    continue
                ok, generated_urls, reason = _generate_and_upload_urls(
                    db,
                    target=target,
                    model=args.model,
                    generate_slots=int(args.generate_slots),
                )
                if not ok:
                    row["status"] = "failed"
                    row["reason"] = reason
                    report["summary"]["failed"] += 1
                    report["items"].append(row)
                    continue
                resolved_urls = generated_urls
                report["summary"]["generated"] += 1

            updated_content = _apply_restore_markers(
                original_content=target.content,
                cover_url=resolved_urls["cover"],
                inline1_url=resolved_urls["inline1"],
                title=target.title,
                cover_alt=target.cover_alt or target.title,
            )
            row["resolved_urls"] = resolved_urls
            row["health"] = [
                _check_url_health(resolved_urls["cover"], timeout=args.timeout),
                _check_url_health(resolved_urls["inline1"], timeout=args.timeout),
            ]

            if not apply_mode:
                row["status"] = "planned_matched" if decision.matched else "planned_generate"
                report["items"].append(row)
                continue

            if target.source == "blogger":
                ok, reason = _update_blogger_post(
                    db,
                    target=target,
                    updated_content=updated_content,
                    cover_url=resolved_urls["cover"],
                )
                if ok and target.blog_id is not None:
                    touched_blog_ids.add(target.blog_id)
            else:
                ok, reason = _update_cloudflare_post(
                    db,
                    target=target,
                    updated_content=updated_content,
                    cover_url=resolved_urls["cover"],
                )
                if ok:
                    touched_cloudflare = True

            if ok:
                row["status"] = "updated"
                row["reason"] = "ok"
                report["summary"]["updated"] += 1
            else:
                row["status"] = "failed"
                row["reason"] = reason
                report["summary"]["failed"] += 1
            report["items"].append(row)

        if apply_mode:
            for blog_id in sorted(touched_blog_ids):
                blog = db.get(Blog, blog_id)
                if blog is None:
                    continue
                try:
                    sync_blogger_posts_for_blog(db, blog)
                except Exception as exc:  # noqa: BLE001
                    report["summary"]["failed"] += 1
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
                    report["summary"]["failed"] += 1
                    report["items"].append(
                        {
                            "source": "cloudflare",
                            "post_id": "",
                            "status": "failed",
                            "reason": f"sync_cloudflare_failed:{exc}",
                        }
                    )

    stamp = _timestamp()
    default_report_path = REPO_ROOT / "storage" / "reports" / f"restore-missing-live-images-{stamp}.json"
    report_path = Path(args.report_path) if _safe_str(args.report_path) else default_report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    report_path.write_text(report_text, encoding="utf-8")
    print(
        json.dumps(
            {
                "report_path": str(report_path),
                "summary": report.get("summary", {}),
                "mode": args.mode,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

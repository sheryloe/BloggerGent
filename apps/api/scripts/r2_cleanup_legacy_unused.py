from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

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
from app.models.entities import R2AssetRelayoutMapping, SyncedBloggerPost  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import _integration_data_or_raise, _integration_request, _list_integration_posts  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import (  # noqa: E402
    _resolve_cloudflare_r2_configuration,
    cloudflare_r2_object_size,
    delete_cloudflare_r2_asset,
    normalize_r2_url_to_key,
)

HTML_IMG_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
SRCSET_RE = re.compile(r"\bsrcset=['\"]([^'\"]+)['\"]", re.IGNORECASE)
MD_IMG_RE = re.compile(r"!\[[^\]]*]\(([^)\s]+)\)")
LIVE_STATUSES = {"live", "published"}
DELETABLE_EXTENSIONS = (".webp", ".png", ".jpg", ".jpeg")
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cleanup legacy unmapped R2 keys after grace period.")
    parser.add_argument("--apply", action="store_true", help="Delete eligible keys. Default is dry-run.")
    parser.add_argument("--grace-days", type=int, default=14, help="Grace period in days.")
    parser.add_argument("--ignore-grace", action="store_true", help="Ignore grace period cutoff.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max mappings to inspect.")
    parser.add_argument("--legacy-prefix", default="", help="Limit cleanup to keys under this legacy prefix.")
    parser.add_argument("--existing-only", action="store_true", help="Delete only keys confirmed by live R2 listing.")
    parser.add_argument("--abort-if-live-hit", action="store_true", help="Abort deletion when live-hit report indicates legacy references.")
    parser.add_argument("--live-check-report-path", default="", help="Path to live verification report JSON.")
    parser.add_argument("--report-path", default="", help="Optional JSON report path.")
    return parser.parse_args(argv)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_legacy_prefix(value: str) -> str:
    return _safe_str(value).strip().strip("/")


def _normalize_candidate_url(raw: str) -> str:
    candidate = unescape(_safe_str(raw))
    if not candidate:
        return ""
    candidate = candidate.strip().strip("()[]<>")
    for splitter in ("'", '"', "<", ">", "\r", "\n", "\t", " "):
        index = candidate.find(splitter)
        if index > 0:
            candidate = candidate[:index]
    candidate = candidate.strip().rstrip(".,);")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if "javascript:" in candidate.lower() or "data:" in candidate.lower():
        return ""
    return candidate


def _extract_srcset_urls(srcset_value: str) -> list[str]:
    urls: list[str] = []
    for part in (srcset_value or "").split(","):
        candidate = _normalize_candidate_url(part.strip().split(" ")[0].strip())
        if candidate:
            urls.append(candidate)
    return urls


def _extract_image_urls(content: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in HTML_IMG_RE.finditer(content or ""):
        value = _normalize_candidate_url(match.group(1))
        if not value or value in seen:
            continue
        seen.add(value)
        urls.append(value)
    for match in MD_IMG_RE.finditer(content or ""):
        value = _normalize_candidate_url(match.group(1))
        if not value or value in seen:
            continue
        seen.add(value)
        urls.append(value)
    for match in SRCSET_RE.finditer(content or ""):
        for value in _extract_srcset_urls(match.group(1)):
            if not value or value in seen:
                continue
            seen.add(value)
            urls.append(value)
    return urls


def _is_live_status(value: Any) -> bool:
    return _safe_str(value).lower() in LIVE_STATUSES


def _key_is_deletable(key: str) -> bool:
    lowered = key.lower()
    return any(lowered.endswith(ext) for ext in DELETABLE_EXTENSIONS)


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


def _list_r2_keys_by_prefix(
    *,
    account_id: str,
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
    prefix: str,
) -> set[str]:
    host = f"{account_id}.r2.cloudflarestorage.com"
    continuation_token = ""
    normalized_prefix = _normalize_legacy_prefix(prefix)
    keys: set[str] = set()

    with httpx.Client(timeout=120.0) as client:
        while True:
            now = datetime.now(timezone.utc)
            amz_date = now.strftime("%Y%m%dT%H%M%SZ")
            date_stamp = now.strftime("%Y%m%d")
            payload_hash = hashlib.sha256(b"").hexdigest()
            params: dict[str, str] = {"list-type": "2", "max-keys": "1000"}
            if normalized_prefix:
                params["prefix"] = normalized_prefix
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
                if key:
                    keys.add(key)

            truncated = _safe_str(root.findtext(f".//{S3_NS}IsTruncated")).lower() == "true"
            if not truncated:
                break
            continuation_token = _safe_str(root.findtext(f".//{S3_NS}NextContinuationToken"))
            if not continuation_token:
                break
    return keys


def _fetch_cloudflare_post_detail(db, post_id: str) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="GET",
        path=f"/api/integrations/posts/{post_id}",
        timeout=60.0,
    )
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _collect_live_r2_keys(db) -> set[str]:
    keys: set[str] = set()
    blogger_posts = (
        db.execute(
            select(SyncedBloggerPost)
            .where(SyncedBloggerPost.status.in_(["live", "LIVE", "published", "PUBLISHED"]))
            .options(selectinload(SyncedBloggerPost.blog))
            .order_by(SyncedBloggerPost.id.desc())
        )
        .scalars()
        .all()
    )
    for post in blogger_posts:
        urls = _extract_image_urls(post.content_html or "")
        if post.thumbnail_url:
            urls.append(post.thumbnail_url)
        for url in urls:
            key = normalize_r2_url_to_key(url)
            if key and _key_is_deletable(key):
                keys.add(key)

    cloudflare_posts = _list_integration_posts(db)
    for row in cloudflare_posts:
        if not _is_live_status(row.get("status")):
            continue
        post_id = _safe_str(row.get("id"))
        if not post_id:
            continue
        detail = _fetch_cloudflare_post_detail(db, post_id)
        content = _safe_str(detail.get("content") or detail.get("contentMarkdown") or detail.get("content_markdown"))
        cover_image = _safe_str(detail.get("coverImage"))
        urls = _extract_image_urls(content)
        if cover_image:
            urls.append(cover_image)
        for url in urls:
            key = normalize_r2_url_to_key(url)
            if key and _key_is_deletable(key):
                keys.add(key)
    return keys


def _extract_live_hits_total(payload: dict[str, Any]) -> int:
    summary = payload.get("summary")
    if isinstance(summary, dict):
        for key in ("live_hits_total", "with_needle"):
            value = summary.get(key)
            if value is not None:
                try:
                    return max(int(value), 0)
                except Exception:  # noqa: BLE001
                    continue
    value = payload.get("live_hits_total")
    if value is not None:
        try:
            return max(int(value), 0)
        except Exception:  # noqa: BLE001
            return 0
    return 0


def _load_live_hits_total(path: str) -> int:
    report_path = Path(path)
    if not report_path.exists():
        raise FileNotFoundError(f"live_check_report_missing:{report_path}")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("live_check_report_invalid_payload")
    return _extract_live_hits_total(payload)


def main() -> int:
    args = parse_args()
    apply_mode = bool(args.apply)
    normalized_prefix = _normalize_legacy_prefix(args.legacy_prefix)
    grace_days = max(int(args.grace_days or 14), 1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=grace_days)
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "apply": apply_mode,
        "grace_days": grace_days,
        "ignore_grace": bool(args.ignore_grace),
        "cutoff": cutoff.isoformat(),
        "legacy_prefix": normalized_prefix,
        "existing_only": bool(args.existing_only),
        "abort_if_live_hit": bool(args.abort_if_live_hit),
        "live_check_report_path": _safe_str(args.live_check_report_path),
        "summary": {
            "live_keys": 0,
            "live_hits_total": 0,
            "prefix_existing_keys": 0,
            "mappings_scanned": 0,
            "candidates": 0,
            "deleted": 0,
            "already_missing": 0,
            "skipped_live_reference": 0,
            "failed": 0,
            "deleted_bytes": 0,
        },
        "aborted": False,
        "items": [],
    }

    with SessionLocal() as db:
        live_keys = _collect_live_r2_keys(db)
        report["summary"]["live_keys"] = len(live_keys)

        if args.abort_if_live_hit:
            live_hits_total = 0
            if _safe_str(args.live_check_report_path):
                live_hits_total = _load_live_hits_total(_safe_str(args.live_check_report_path))
            elif normalized_prefix:
                live_hits_total = sum(1 for key in live_keys if key.startswith(normalized_prefix))
            report["summary"]["live_hits_total"] = int(live_hits_total)
            if live_hits_total > 0:
                report["aborted"] = True
                report["abort_reason"] = "live_hits_detected"
                report_text = json.dumps(report, ensure_ascii=False, indent=2)
                print(report_text)
                if args.report_path:
                    report_path = Path(args.report_path)
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(report_text, encoding="utf-8")
                return 2

        query = select(R2AssetRelayoutMapping).where(
            R2AssetRelayoutMapping.cleaned_at.is_(None),
            R2AssetRelayoutMapping.legacy_key.is_not(None),
        )
        if not args.ignore_grace:
            query = query.where(R2AssetRelayoutMapping.created_at <= cutoff)
        if normalized_prefix:
            query = query.where(R2AssetRelayoutMapping.legacy_key.like(f"{normalized_prefix}%"))
        query = query.order_by(R2AssetRelayoutMapping.created_at.asc(), R2AssetRelayoutMapping.id.asc())

        mappings = db.execute(query).scalars().all()
        if args.limit and args.limit > 0:
            mappings = mappings[: int(args.limit)]
        report["summary"]["mappings_scanned"] = len(mappings)

        mapping_by_key: dict[str, list[R2AssetRelayoutMapping]] = {}
        for mapping in mappings:
            key = _safe_str(mapping.legacy_key)
            if not key:
                continue
            mapping_by_key.setdefault(key, []).append(mapping)

        existing_prefix_keys: set[str] = set()
        if normalized_prefix:
            settings_map = get_settings_map(db)
            account_id, bucket, access_key_id, secret_access_key, _public_base_url, _prefix = _resolve_cloudflare_r2_configuration(settings_map)
            if not account_id or not bucket or not access_key_id or not secret_access_key:
                raise RuntimeError("cloudflare_r2_configuration_missing")
            existing_prefix_keys = _list_r2_keys_by_prefix(
                account_id=account_id,
                bucket=bucket,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                prefix=normalized_prefix,
            )
        report["summary"]["prefix_existing_keys"] = len(existing_prefix_keys)

        if args.existing_only and normalized_prefix:
            candidate_keys = sorted(existing_prefix_keys)
            mapped_missing_keys = {key for key in mapping_by_key if key not in existing_prefix_keys}
        else:
            candidate_keys = sorted(mapping_by_key)
            mapped_missing_keys = set()

        deleted_keys: set[str] = set()
        missing_keys: set[str] = set()

        for legacy_key in candidate_keys:
            if not _key_is_deletable(legacy_key):
                continue
            if legacy_key in live_keys:
                report["summary"]["skipped_live_reference"] += 1
                report["items"].append(
                    {
                        "legacy_key": legacy_key,
                        "status": "skipped_live_reference",
                    }
                )
                continue

            report["summary"]["candidates"] += 1
            object_size = cloudflare_r2_object_size(db, public_key="", key=legacy_key)
            if object_size is None:
                missing_keys.add(legacy_key)
                report["summary"]["already_missing"] += 1
                report["items"].append(
                    {
                        "legacy_key": legacy_key,
                        "status": "already_missing",
                    }
                )
                continue

            if not apply_mode:
                report["items"].append(
                    {
                        "legacy_key": legacy_key,
                        "status": "candidate",
                        "size": int(object_size or 0),
                    }
                )
                continue

            try:
                delete_cloudflare_r2_asset(db, object_key=legacy_key)
                deleted_keys.add(legacy_key)
                report["summary"]["deleted"] += 1
                report["summary"]["deleted_bytes"] += int(object_size or 0)
                report["items"].append(
                    {
                        "legacy_key": legacy_key,
                        "status": "deleted",
                        "size": int(object_size or 0),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                report["summary"]["failed"] += 1
                report["items"].append(
                    {
                        "legacy_key": legacy_key,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        if mapped_missing_keys:
            for key in sorted(mapped_missing_keys):
                if key in live_keys:
                    report["summary"]["skipped_live_reference"] += 1
                    report["items"].append(
                        {
                            "legacy_key": key,
                            "status": "skipped_live_reference",
                        }
                    )
                    continue
                missing_keys.add(key)
                report["summary"]["already_missing"] += 1
                report["items"].append(
                    {
                        "legacy_key": key,
                        "status": "already_missing",
                    }
                )

        if apply_mode:
            now = datetime.now(timezone.utc)
            for key, rows in mapping_by_key.items():
                if key in deleted_keys:
                    for mapping in rows:
                        mapping.status = "deleted"
                        mapping.cleaned_at = now
                        db.add(mapping)
                elif key in missing_keys:
                    for mapping in rows:
                        mapping.status = "deleted_missing"
                        mapping.cleaned_at = now
                        db.add(mapping)
            db.commit()

    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    print(report_text)
    if args.report_path:
        report_path = Path(args.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

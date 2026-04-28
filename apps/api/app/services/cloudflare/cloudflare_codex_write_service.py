from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote, unquote, urlparse, urlunparse
from urllib.request import Request, urlopen

import httpx

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ManagedChannel, SyncedCloudflarePost
from app.services.cloudflare.cloudflare_channel_service import (
    _fetch_integration_post_detail,
    _insert_markdown_inline_image,
    _integration_data_or_raise,
    _integration_request,
    _prepare_markdown_body,
    _sanitize_cloudflare_public_body,
    _strip_generated_body_images,
    get_cloudflare_prompt_category_relative_path,
    list_cloudflare_categories,
    validate_no_adsense_tokens_in_body,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts
from app.services.content.prompt_service import render_prompt_template
from app.services.integrations.settings_service import get_settings_map
from app.services.integrations.storage_service import (
    _normalize_binary_for_filename,
    _resolve_cloudflare_r2_configuration,
    upload_binary_to_cloudflare_r2,
)
from app.services.providers.factory import get_image_provider

CODEX_WRITE_PROMPT_VERSION = "0414"
CODEX_WRITE_STATUS_SEEDED = "seeded"
CODEX_WRITE_STATUS_READY = "ready"
CODEX_WRITE_STATUS_PUBLISHED = "published"
CODEX_WRITE_STATUS_FAILED = "failed"
CODEX_WRITE_STATUS_SKIPPED = "skipped"

HTML_TAG_RE = re.compile(r"<[^>]+>")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_IMAGE_RE = re.compile(r"(?is)<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']")
HTML_HEADING_RE = re.compile(r"<h([23])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
MD_HEADING_RE = re.compile(r"^\s*##+\s+(.+?)\s*$", re.MULTILINE)
WS_RE = re.compile(r"\s+")
TOPIC_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]{3,}")

FAKE_ENTITY_TOKENS = (
    "dongriarchive", "dongri archive", "dongrimokpan", "dongrimokjang",
    "동리아카이브", "동그리 아카이브", "동그리아카이브", "동그리",
)
PUBLIC_BANNED_TOKENS = (
    "quick brief", "core focus", "key entities", "internal archive", "기준 시각", "재정리했다", "품질 개선", *FAKE_ENTITY_TOKENS,
)
FACTUAL_ENTITY_CATEGORIES = {
    "여행과-기록", "축제와-현장", "문화와-공간", "미스테리아-스토리", "개발과-프로그래밍", "삶의-기름칠", "주식의-흐름", "나스닥의-흐름", "크립토의-흐름",
}
ENTITY_TYPE_BY_CATEGORY = {
    "여행과-기록": "place", "축제와-현장": "event", "문화와-공간": "venue", "미스테리아-스토리": "case", "개발과-프로그래밍": "tool", "삶의-기름칠": "venue",
    "주식의-흐름": "company", "나스닥의-흐름": "company", "크립토의-흐름": "company", "동그리의-생각": "reflection", "일상과-메모": "reflection", "삶을-유용하게": "reflection",
}
DEFAULT_LAYOUT_TEMPLATE = "single-layout-0415"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
BACKUP_IMAGE_SEARCH_ROOTS = ("backup", "storage", "storage-clone")
TOPIC_TOKEN_STOPWORDS = {
    "2024", "2025", "2026", "guide", "tips", "half", "route", "travel", "dongri", "archive", "blog", "post", "story",
    "practical", "review", "after", "before", "update", "latest", "best", "with", "from", "into",
}
DAILY_MEMO_REQUIRED_MODEL = "gpt-5.4-mini-2026-03-17"
DAILY_MEMO_SIMILARITY_THRESHOLD = 0.90
DAILY_MEMO_OFFTOPIC_STRONG_TOKENS = {
    "미스터리",
    "단서",
    "수사",
    "미제",
    "용의자",
    "실종",
    "살인",
    "범죄",
    "forensic",
    "cold case",
    "unsolved",
    "evidence",
    "mystery",
    "clue",
    "investigation",
    "detective",
    "suspect",
    "missing",
    "murder",
    "homicide",
    "crime",
}
DAILY_MEMO_OFFTOPIC_WEAK_TOKENS = {
    "사건",
    "추적",
}
DAILY_MEMO_AXIS_TOKENS: dict[str, tuple[str, ...]] = {
    "todo_memory": ("할 일", "to-do", "투두", "기억", "놓치지", "체크", "메모"),
    "health_habit": ("건강", "습관", "수면", "운동", "스트레칭", "호흡", "물 마시기"),
    "commute_5min": ("출퇴근", "통근", "5분", "짬", "이동", "버스", "지하철", "걷기"),
    "daily_observation": ("심심한 일상", "일상 관찰", "사소한", "장면", "관찰", "저녁", "아침", "기록"),
}
MYSTERIA_CATEGORY_SLUG = "미스테리아-스토리"


def _is_mysteria_category_slug(category_slug: str | None) -> bool:
    return _normalize_space(category_slug) in {MYSTERIA_CATEGORY_SLUG, "미스테리아 스토리", "miseuteria-seutori"}


CLOSING_RECORD_INLINE_STYLE = (
    "display:block;"
    "margin:12px 0 0 0;"
    "padding:14px 16px;"
    "text-align:left;"
    "background:#f8fafc;"
    "border:1px solid #e2e8f0;"
    "border-left:4px solid #94a3b8;"
    "border-radius:10px;"
    "box-shadow:none;"
)
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
CLOUDFLARE_MEDIA_KEY_PREFIX = "assets/media/cloudflare/dongri-archive/"
CLOUDFLARE_MEDIA_URL_PREFIX = "/assets/media/cloudflare/dongri-archive/"


def _repo_root() -> Path:
    configured = os.environ.get("BLOGGENT_REPO_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    cursor = Path(__file__).resolve().parent
    for candidate in [cursor, *cursor.parents]:
        if (candidate / "apps" / "api").exists():
            return candidate
    return Path(__file__).resolve().parents[3]


def get_codex_write_root(*, base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir).resolve()
    configured = os.environ.get("BLOGGENT_CODEX_WRITE_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    return _repo_root() / "codex_write" / "cloudflare"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_space(value: Any) -> str:
    return WS_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip()


def _normalize_casefold(value: Any) -> str:
    text = _normalize_space(value)
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).casefold()


def _plain_text(value: str | None) -> str:
    return _normalize_space(HTML_TAG_RE.sub(" ", value or ""))


def _body_char_length(value: str | None) -> int:
    return len(_plain_text(value))


def _extract_headings(value: str | None) -> list[str]:
    text = str(value or "")
    matches: list[tuple[int, str]] = []
    for match in HTML_HEADING_RE.finditer(text):
        heading = _normalize_space(HTML_TAG_RE.sub(" ", match.group(2) or ""))
        if heading:
            matches.append((match.start(), heading))
    for match in MD_HEADING_RE.finditer(text):
        heading = _normalize_space(match.group(1))
        if heading:
            matches.append((match.start(), heading))
    matches.sort(key=lambda item: item[0])
    return [heading for _, heading in matches]


def _extract_existing_image_urls(content: str | None) -> list[str]:
    text = str(content or "").strip()
    if not text:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for match in MARKDOWN_IMAGE_RE.findall(text):
        candidate = _normalize_space(match)
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    for match in HTML_IMAGE_RE.findall(text):
        candidate = _normalize_space(match)
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _extract_slug_from_url(url: str | None) -> str:
    raw_url = _normalize_space(url)
    if not raw_url:
        return ""
    path = urlparse(raw_url).path.rstrip("/")
    return _normalize_space(path.split("/")[-1]) if path else ""


def _sanitize_filename_token(value: str, fallback: str) -> str:
    token = re.sub(r"[^0-9A-Za-z._-]+", "-", _normalize_space(value))
    token = re.sub(r"-{2,}", "-", token).strip("-._")
    return token[:120] or fallback


def _prompt_paths_for_category(category_slug: str) -> list[str]:
    relative_dir = get_cloudflare_prompt_category_relative_path(category_slug).as_posix()
    base = f"prompts/channels/cloudflare/dongri-archive/{relative_dir}"
    return [f"{base}/topic_discovery.md", f"{base}/article_generation.md", f"{base}/image_prompt_generation.md"]


def _find_channel(db: Session) -> ManagedChannel:
    channel = db.execute(select(ManagedChannel).where(ManagedChannel.provider == "cloudflare").order_by(ManagedChannel.id.desc())).scalar_one_or_none()
    if channel is None:
        raise ValueError("Cloudflare managed channel is not configured.")
    return channel


def _list_target_posts(db: Session, *, category_slugs: Sequence[str] | None = None, slug: str | None = None, limit: int | None = None) -> list[SyncedCloudflarePost]:
    channel = _find_channel(db)
    stmt = select(SyncedCloudflarePost).where(SyncedCloudflarePost.managed_channel_id == channel.id, SyncedCloudflarePost.status.in_(["published", "live"])).order_by(SyncedCloudflarePost.published_at.desc().nullslast(), SyncedCloudflarePost.id.desc())
    rows = db.execute(stmt).scalars().all()
    normalized_categories = {_normalize_space(item) for item in (category_slugs or []) if _normalize_space(item)}
    normalized_slug = _normalize_space(slug)
    filtered: list[SyncedCloudflarePost] = []
    for row in rows:
        canonical_slug = _normalize_space(row.canonical_category_slug or row.category_slug)
        row_slug = _normalize_space(row.slug)
        if normalized_categories and canonical_slug not in normalized_categories:
            continue
        if normalized_slug and row_slug != normalized_slug:
            continue
        filtered.append(row)
    return filtered[:limit] if limit is not None and limit > 0 else filtered


def _extract_tag_names(detail: dict[str, Any], row: SyncedCloudflarePost) -> list[str]:
    raw_tags = detail.get("tags")
    values: list[str] = []
    seen: set[str] = set()
    if isinstance(raw_tags, list):
        for item in raw_tags:
            candidate = _normalize_space(item.get("name") or item.get("label") or item.get("slug")) if isinstance(item, dict) else _normalize_space(item)
            if candidate and candidate.casefold() not in seen:
                seen.add(candidate.casefold())
                values.append(candidate)
    for raw_label in row.labels or []:
        candidate = _normalize_space(raw_label)
        if candidate and candidate.casefold() not in seen:
            seen.add(candidate.casefold())
            values.append(candidate)
    return values


def _category_root_parts(category_slug: str) -> tuple[str, str]:
    parts = list(get_cloudflare_prompt_category_relative_path(category_slug).parts)
    if not parts:
        return ("미분류", "general")
    if len(parts) == 1:
        return ("미분류", parts[0])
    return (parts[0], parts[-1])


def _package_path(*, base_dir: Path, category_slug: str, slug: str, remote_post_id: str) -> Path:
    relative_dir = get_cloudflare_prompt_category_relative_path(category_slug)
    return base_dir / relative_dir / f"{_sanitize_filename_token(slug, remote_post_id or 'post')}.json"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"codex_write JSON must be an object: {path}")
    return payload


def _report_path(base_dir: Path, prefix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return base_dir / "reports" / datetime.now().strftime("%Y%m%d") / f"{prefix}-{stamp}.json"

def _display_name_from_title(title: str, *, category_slug: str) -> str:
    candidate = _normalize_space(title)
    if "|" in candidate:
        candidate = _normalize_space(candidate.split("|", 1)[0])
    candidate = re.sub(r"\b20\d{2}(?:[-./]\d{1,2}(?:[-./]\d{1,2})?)?\b", "", candidate).strip()
    candidate = re.sub(r"\s{2,}", " ", candidate).strip(" |-–")
    if category_slug in {"개발과-프로그래밍", "나스닥의-흐름", "주식의-흐름", "크립토의-흐름"}:
        for token in re.split(r"[:|,·/]", candidate):
            normalized = _normalize_space(token)
            if normalized:
                return normalized
    return candidate or _normalize_space(title)


def _layout_template_for_category(category_slug: str) -> str:
    return DEFAULT_LAYOUT_TEMPLATE


def _seed_entity_validation(*, category_slug: str, title: str) -> dict[str, Any]:
    factual = category_slug in FACTUAL_ENTITY_CATEGORIES
    return {
        "status": "manual_review_required" if factual else "not_applicable",
        "entity_type": ENTITY_TYPE_BY_CATEGORY.get(category_slug, "reflection"),
        "display_name": _display_name_from_title(title, category_slug=category_slug),
        "evidence_urls": [],
        "evidence_note": "",
    }


def _inline_image_from_detail(detail: dict[str, Any], *, cover_image_url: str) -> tuple[str, str]:
    current_content = str(detail.get("content") or detail.get("contentMarkdown") or detail.get("markdown") or "")
    image_urls = _extract_existing_image_urls(current_content)
    inline_url = ""
    for candidate in image_urls:
        if candidate and candidate != cover_image_url:
            inline_url = candidate
            break
    return inline_url, _normalize_space(detail.get("title") or "")


def _asset_key_from_url(url: str | None, *, public_base_url: str = "") -> str:
    raw_url = _normalize_space(url)
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    path = unquote(parsed.path or "").strip()
    if "/assets/assets/" in path:
        path = path.replace("/assets/assets/", "/assets/", 1)
    if "/assets/" in path:
        return f"assets/{path.split('/assets/', 1)[1].lstrip('/')}"
    normalized_base = _normalize_space(public_base_url)
    if normalized_base and raw_url.startswith(normalized_base):
        base_path = urlparse(normalized_base).path.rstrip("/")
        if base_path and path.startswith(base_path):
            path = path[len(base_path):]
            if path.strip("/"):
                return f"assets/{path.strip('/')}"
    return Path(path).name.strip()


def _canonicalize_cloudflare_asset_url(url: str | None, *, public_base_url: str = "") -> str:
    raw_url = _normalize_space(url)
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    path = unquote(parsed.path or "").strip()
    if not path:
        return raw_url
    normalized_base = _normalize_space(public_base_url)
    if "/assets/assets/" in path:
        canonical_path = path.replace("/assets/assets/", "/assets/", 1)
    elif "/assets/media/" in path:
        canonical_path = path
    elif normalized_base and raw_url.startswith(normalized_base.rstrip("/")) and "/media/" in path and "/assets/" not in path:
        canonical_path = path.replace("/media/", "/assets/media/", 1)
    else:
        canonical_path = path
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            canonical_path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _asset_url_candidates(url: str | None, *, public_base_url: str = "") -> list[str]:
    raw_url = _normalize_space(url)
    if not raw_url:
        return []
    candidates: list[str] = []
    seen: set[str] = set()
    for candidate in (
        _canonicalize_cloudflare_asset_url(raw_url, public_base_url=public_base_url),
        raw_url,
    ):
        normalized = _normalize_space(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    return candidates


def _url_is_reachable(url: str | None) -> bool:
    target = _normalize_space(url)
    if not target or not target.lower().startswith(("http://", "https://")):
        return False
    try:
        request = Request(target, headers={"User-Agent": "Bloggent-CodexWrite/0415"})
        with urlopen(request, timeout=30) as response:  # noqa: S310
            return int(getattr(response, "status", 200) or 200) < 400
    except Exception:
        return False


def _resolve_reachable_asset_url(url: str | None, *, public_base_url: str = "") -> str:
    for candidate in _asset_url_candidates(url, public_base_url=public_base_url):
        if _url_is_reachable(candidate):
            return candidate
    return ""


def _is_cloudflare_media_asset(url: str | None, *, asset_key: str = "", public_base_url: str = "") -> bool:
    canonical_url = _canonicalize_cloudflare_asset_url(url, public_base_url=public_base_url)
    normalized_key = _normalize_space(asset_key) or _asset_key_from_url(canonical_url, public_base_url=public_base_url)
    return bool(
        (canonical_url and CLOUDFLARE_MEDIA_URL_PREFIX in canonical_url)
        or (normalized_key and normalized_key.startswith(CLOUDFLARE_MEDIA_KEY_PREFIX))
    )


def _cloudflare_category_media_key(category_slug: str) -> str:
    parts = list(get_cloudflare_prompt_category_relative_path(category_slug).parts)
    raw = parts[-1] if parts else category_slug
    return _sanitize_filename_token(raw, "general").lower() or "general"


def _build_cloudflare_media_object_key(
    *,
    category_slug: str,
    target_slug: str,
    slot: str,
    content_hash: str,
    timestamp: datetime | None = None,
) -> str:
    resolved_time = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc)
    category_key = _cloudflare_category_media_key(category_slug)
    slug_token = _sanitize_filename_token(target_slug, "post").lower()
    slot_token = _sanitize_filename_token(slot, "asset").lower()
    hash_token = _sanitize_filename_token(content_hash[:12], "hash").lower()
    return (
        f"{CLOUDFLARE_MEDIA_KEY_PREFIX}{category_key}/"
        f"{resolved_time:%Y}/{resolved_time:%m}/{slug_token}/"
        f"{slot_token}-{hash_token}.webp"
    )


def _canonical_query(params: dict[str, str]) -> str:
    return "&".join(f"{quote(str(key), safe='-_.~')}={quote(str(params[key]), safe='-_.~')}" for key in sorted(params))


def _r2_sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _r2_signing_key(secret_access_key: str, date_stamp: str) -> bytes:
    k_date = _r2_sign(("AWS4" + secret_access_key).encode("utf-8"), date_stamp)
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
    normalized_prefix = _normalize_space(prefix).strip("/")
    if normalized_prefix:
        normalized_prefix = f"{normalized_prefix}/"
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
                _r2_signing_key(secret_access_key, date_stamp),
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
                key = _normalize_space(node.findtext(f"{S3_NS}Key"))
                if key:
                    keys.add(key)
            is_truncated = _normalize_space(root.findtext(f"{S3_NS}IsTruncated")).lower() == "true"
            continuation_token = _normalize_space(root.findtext(f"{S3_NS}NextContinuationToken"))
            if not is_truncated or not continuation_token:
                break
    return keys


def _build_r2_unused_candidates_for_category(
    *,
    category_slug: str,
    payload: dict[str, Any],
    public_base_url: str,
    account_id: str,
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
) -> list[dict[str, Any]]:
    category_key = _cloudflare_category_media_key(category_slug)
    prefix = f"{CLOUDFLARE_MEDIA_KEY_PREFIX}{category_key}/"
    keys = _list_r2_keys_by_prefix(
        account_id=account_id,
        bucket=bucket,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        prefix=prefix,
    )
    topic_tokens = _payload_search_tokens(payload)
    candidates: list[dict[str, Any]] = []
    for key in sorted(keys):
        lowered = key.lower()
        if not lowered.endswith((".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif")):
            continue
        filename = Path(key).name.lower()
        if "cover" in filename:
            role_hint = "cover"
        elif "inline" in filename:
            role_hint = "inline"
        else:
            role_hint = "generic"
        score = 200
        score += sum(5 for token in topic_tokens if token in lowered)
        public_url = f"{_normalize_space(public_base_url).rstrip('/')}/{key.lstrip('/')}"
        candidates.append(
            {
                "candidate_id": f"r2:{key}",
                "score": score,
                "role_hint": role_hint,
                "source_type": "r2_unused",
                "url": _canonicalize_cloudflare_asset_url(public_url, public_base_url=public_base_url),
                "asset_key": key,
                "source_ref": key,
            }
        )
    return candidates


def _source_type_priority(source_type: str) -> int:
    normalized = _normalize_space(source_type)
    return {
        "existing_media_restore": 0,
        "r2_unused": 1,
        "local_backup_file": 2,
        "backup_json_url": 3,
        "generated_collage": 4,
    }.get(normalized, 9)


def _image_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalize_topic_tokens(*values: Any) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for raw in values:
        for token in TOPIC_TOKEN_RE.findall(str(raw or "").lower()):
            if token in TOPIC_TOKEN_STOPWORDS:
                continue
            if token.isdigit():
                continue
            if token not in seen:
                seen.add(token)
                items.append(token)
    return items


def _is_cloudflare_asset_url(url: str | None, *, public_base_url: str = "") -> bool:
    raw_url = _normalize_space(url)
    if not raw_url:
        return False
    if "/assets/" in raw_url:
        return True
    normalized_base = _normalize_space(public_base_url)
    return bool(normalized_base and raw_url.startswith(normalized_base))


def _normalize_image_field(image: Any, *, fallback_alt: str, public_base_url: str) -> dict[str, Any]:
    raw = image if isinstance(image, dict) else {}
    url = _canonicalize_cloudflare_asset_url(raw.get("url"), public_base_url=public_base_url)
    return {
        "url": url,
        "alt": _normalize_space(raw.get("alt") or fallback_alt),
        "source": _normalize_space(raw.get("source")),
        "asset_key": _normalize_space(raw.get("asset_key")) or _asset_key_from_url(url, public_base_url=public_base_url),
    }


def _normalize_image_uniqueness(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("image_uniqueness") if isinstance(payload.get("image_uniqueness"), dict) else {}
    normalized = {
        "cover_hash_or_key": _normalize_space(raw.get("cover_hash_or_key")),
        "inline_hash_or_key": _normalize_space(raw.get("inline_hash_or_key")),
        "is_distinct_within_post": bool(raw.get("is_distinct_within_post")),
        "is_distinct_across_blog": bool(raw.get("is_distinct_across_blog")),
    }
    payload["image_uniqueness"] = normalized
    return normalized


def _normalize_backup_image_resolution(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("backup_image_resolution") if isinstance(payload.get("backup_image_resolution"), dict) else {}
    normalized = {
        "status": _normalize_space(raw.get("status")) or "pending",
        "searched_roots": [str(item) for item in (raw.get("searched_roots") if isinstance(raw.get("searched_roots"), list) else list(BACKUP_IMAGE_SEARCH_ROOTS))],
        "candidate_count": int(raw.get("candidate_count") or 0),
        "cover": raw.get("cover") if isinstance(raw.get("cover"), dict) else {},
        "inline": raw.get("inline") if isinstance(raw.get("inline"), dict) else {},
        "notes": [str(item) for item in (raw.get("notes") if isinstance(raw.get("notes"), list) else [])],
    }
    payload["backup_image_resolution"] = normalized
    return normalized


def _render_inline_faq_section(faq_section: Any) -> str:
    if not isinstance(faq_section, list):
        return ""
    items: list[str] = []
    for raw_item in faq_section:
        if not isinstance(raw_item, dict):
            continue
        question = _normalize_space(
            raw_item.get("question") or raw_item.get("q") or raw_item.get("title")
        )
        answer = _normalize_space(
            raw_item.get("answer") or raw_item.get("a") or raw_item.get("text")
        )
        if not question or not answer:
            continue
        items.append(f"<h3>{question}</h3>\n<p>{answer}</p>")
    if not items:
        return ""
    return "<h2>자주 묻는 질문</h2>\n" + "\n\n".join(items)


def _insert_inline_faq_before_closing_record(content_body: str, faq_section: Any) -> str:
    body = str(content_body or "").strip()
    faq_block = _render_inline_faq_section(faq_section)
    if not body or not faq_block:
        return body
    if "## 자주 묻는 질문" in body or "<h2>자주 묻는 질문</h2>" in body:
        return body
    closing_patterns = [
        re.compile(r"(?m)^\s*##\s+마무리 기록\s*$"),
        re.compile(r"(?is)<h2[^>]*>\s*마무리 기록\s*</h2>"),
    ]
    for pattern in closing_patterns:
        match = pattern.search(body)
        if match:
            return f"{body[:match.start()].rstrip()}\n\n{faq_block}\n\n{body[match.start():].lstrip()}"
    return f"{body.rstrip()}\n\n{faq_block}"


def _strip_leading_title_heading(content: str) -> str:
    body = str(content or "").strip()
    body = re.sub(r"^\s*#\s+.+?(?:\r?\n){1,2}", "", body, count=1, flags=re.DOTALL)
    body = re.sub(r"^\s*<h1[^>]*>.*?</h1>\s*", "", body, count=1, flags=re.IGNORECASE | re.DOTALL)
    return body.strip()


def _strip_all_inline_images(content: str) -> str:
    body = MARKDOWN_IMAGE_RE.sub("", str(content or ""))
    body = re.sub(r"(?is)<p>\s*<img\b[^>]*>\s*</p>", "", body)
    body = re.sub(r"(?is)<img\b[^>]*>", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _render_inline_image_html(*, url: str, alt: str) -> str:
    return f'<p><img src="{_normalize_space(url)}" alt="{_normalize_space(alt)}" /></p>'


def _insert_inline_image_before_faq_or_closing(content_body: str, *, inline_url: str, inline_alt: str) -> str:
    body = str(content_body or "").strip()
    if not body or not _normalize_space(inline_url):
        return body
    image_block = _render_inline_image_html(url=inline_url, alt=inline_alt)
    if HTML_IMAGE_RE.search(body):
        return body
    faq_match = re.search(r"(?is)<h2[^>]*>\s*자주 묻는 질문\s*</h2>", body)
    if faq_match:
        return f"{body[:faq_match.start()].rstrip()}\n\n{image_block}\n\n{body[faq_match.start():].lstrip()}"
    closing_match = re.search(r"(?is)<h2[^>]*>\s*마무리 기록\s*</h2>", body)
    if closing_match:
        return f"{body[:closing_match.start()].rstrip()}\n\n{image_block}\n\n{body[closing_match.start():].lstrip()}"
    return f"{body.rstrip()}\n\n{image_block}"


def _normalize_single_live_section(content_body: str) -> str:
    body = str(content_body or "").strip()
    if not body:
        return body
    body = re.sub(r"(?is)</?section\b[^>]*>", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    closing_patterns = [
        re.compile(r"(?is)<h2[^>]*>\s*마무리 기록\s*</h2>"),
        re.compile(r"(?m)^\s*##\s+마무리 기록\s*$"),
    ]
    for pattern in closing_patterns:
        match = pattern.search(body)
        if not match:
            continue
        lead = body[:match.start()].rstrip()
        closing = body[match.start():].lstrip()
        if not lead:
            return closing
        return f"<section>\n{lead}\n</section>\n\n{closing}".strip()
    return f"<section>\n{body}\n</section>".strip()


def _wrap_closing_record_block(content_body: str) -> str:
    body = str(content_body or "").strip()
    if not body:
        return body
    opening_tag = f'<aside class="note-aside closing-record" style="{CLOSING_RECORD_INLINE_STYLE}">'
    if re.search(r'(?is)<aside\b[^>]*class="[^"]*\bclosing-record\b[^"]*"', body):
        return re.sub(
            r'(?is)<aside\b[^>]*class="[^"]*\bclosing-record\b[^"]*"[^>]*>',
            opening_tag,
            body,
            count=1,
        ).strip()
    return re.sub(
        r"(?is)(<h2[^>]*>\s*마무리 기록\s*</h2>)\s*(<p>.*?</p>)",
        r"\1" + "\n" + opening_tag + r"\2</aside>",
        body,
        count=1,
    ).strip()


def _canonical_content_body(payload: dict[str, Any]) -> str:
    title = _normalize_space(payload.get("title"))
    category_slug = _normalize_space(payload.get("category_slug"))
    is_mysteria = _is_mysteria_category_slug(category_slug)
    inline_image = payload.get("inline_image") if isinstance(payload.get("inline_image"), dict) else {}
    inline_url = _normalize_space(inline_image.get("url"))
    inline_alt = _normalize_space(inline_image.get("alt") or title)
    content_body = str(payload.get("content_body") or "").strip()
    if content_body:
        normalized = _strip_leading_title_heading(content_body)
        normalized = _strip_all_inline_images(normalized)
        if not is_mysteria:
            normalized = _insert_inline_image_before_faq_or_closing(
                normalized,
                inline_url=inline_url,
                inline_alt=inline_alt,
            )
        normalized = _insert_inline_faq_before_closing_record(normalized, payload.get("faq_section"))
        normalized = _normalize_single_live_section(normalized)
        normalized = _wrap_closing_record_block(normalized)
        payload["content_body"] = normalized.strip() if is_mysteria else f"# {title}\n\n{normalized}".strip()
        return payload["content_body"]

    legacy_body = _strip_all_inline_images(str(payload.get("html_article") or ""))
    legacy_body = _strip_leading_title_heading(legacy_body)
    if not is_mysteria:
        legacy_body = _insert_inline_image_before_faq_or_closing(
            legacy_body,
            inline_url=inline_url,
            inline_alt=inline_alt,
        )
    legacy_body = _insert_inline_faq_before_closing_record(legacy_body, payload.get("faq_section"))
    legacy_body = _normalize_single_live_section(legacy_body)
    legacy_body = _wrap_closing_record_block(legacy_body)
    payload["content_body"] = legacy_body.strip() if is_mysteria else f"# {title}\n\n{legacy_body}".strip()
    return payload["content_body"]


def _inline_faq_heading_count(content_body: str) -> int:
    body = str(content_body or "")
    markdown_count = len(re.findall(r"(?m)^\s*##\s+자주 묻는 질문\s*$", body))
    html_count = len(re.findall(r"(?is)<h2[^>]*>\s*자주 묻는 질문\s*</h2>", body))
    return markdown_count + html_count


def _inline_image_count(content_body: str) -> int:
    return len(_extract_existing_image_urls(content_body))


def _body_h1_count(content_body: str) -> int:
    body = str(content_body or "")
    markdown_count = len(re.findall(r"(?m)^\s*#\s+.+$", body))
    html_count = len(re.findall(r"(?is)<h1[^>]*>.*?</h1>", body))
    return markdown_count + html_count


def _h2_count(content_body: str) -> int:
    body = str(content_body or "")
    markdown_count = len(re.findall(r"(?m)^\s*##\s+.+$", body))
    html_count = len(re.findall(r"(?is)<h2[^>]*>.*?</h2>", body))
    return markdown_count + html_count


def _extract_closing_record_paragraph(content_body: str) -> str:
    body = str(content_body or "")
    match = re.search(
        r'(?is)<h2[^>]*>\s*마무리 기록\s*</h2>\s*(?:<aside\b[^>]*class="[^"]*\bclosing-record\b[^"]*"[^>]*>\s*)?(<p>.*?</p>)(?:\s*</aside>)?',
        body,
    )
    return match.group(1) if match else ""


def _extract_closing_record_block(content_body: str) -> str:
    body = str(content_body or "")
    match = re.search(
        r'(?is)<aside\b[^>]*class="[^"]*\bclosing-record\b[^"]*"[^>]*>.*?</aside>',
        body,
    )
    return match.group(0) if match else ""


def _count_sentences(paragraph_html: str) -> int:
    plain = _plain_text(paragraph_html)
    if not plain:
        return 0
    period_count = plain.count(".")
    if period_count:
        return period_count
    sentences = [item.strip() for item in re.findall(r"[^.!?]+[.!?]", plain) if item.strip()]
    if sentences:
        return len(sentences)
    return 1


def _extract_h2_headings(content_body: str) -> list[str]:
    headings: list[str] = []
    for match in re.finditer(r"(?is)<h2[^>]*>(.*?)</h2>", str(content_body or "")):
        heading = _normalize_space(HTML_TAG_RE.sub(" ", match.group(1) or ""))
        if heading:
            headings.append(heading)
    return headings


def _extract_table_headers(content_body: str) -> list[str]:
    headers: list[str] = []
    for match in re.finditer(r"(?is)<th[^>]*>(.*?)</th>", str(content_body or "")):
        header = _normalize_space(HTML_TAG_RE.sub(" ", match.group(1) or ""))
        if header:
            headers.append(header)
    return headers


def _extract_inline_faq_questions(content_body: str) -> list[str]:
    body = str(content_body or "")
    faq_match = re.search(r"(?is)<h2[^>]*>\s*자주 묻는 질문\s*</h2>", body)
    if not faq_match:
        return []
    trailing = body[faq_match.end():]
    questions: list[str] = []
    for match in re.finditer(r"(?is)<h3[^>]*>(.*?)</h3>", trailing):
        question = _normalize_space(HTML_TAG_RE.sub(" ", match.group(1) or ""))
        if question:
            questions.append(question)
    return questions


def _token_set_for_similarity(*parts: str) -> set[str]:
    combined = " ".join(_normalize_space(part) for part in parts if _normalize_space(part))
    tokens: set[str] = set()
    for token in TOPIC_TOKEN_RE.findall(_normalize_casefold(combined)):
        if token in TOPIC_TOKEN_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _daily_memo_axis_hits(*parts: str) -> list[str]:
    text = _normalize_casefold(" ".join(_normalize_space(part) for part in parts if _normalize_space(part)))
    hits: list[str] = []
    for axis, keywords in DAILY_MEMO_AXIS_TOKENS.items():
        if any(_normalize_casefold(keyword) in text for keyword in keywords if _normalize_casefold(keyword)):
            hits.append(axis)
    return hits


def _validate_daily_memo_topic_fit(payload: dict[str, Any], *, content_body: str, headings: Sequence[str]) -> list[str]:
    if _normalize_space(payload.get("category_slug")) != "일상과-메모":
        return []
    errors: list[str] = []
    model_name = _normalize_space(payload.get("generation_model"))
    if model_name != DAILY_MEMO_REQUIRED_MODEL:
        errors.append("generation_model_mismatch")
    title = _normalize_space(payload.get("title"))
    excerpt = _normalize_space(payload.get("excerpt"))
    slug_scope = _normalize_space(payload.get("target_slug"))
    combined = _normalize_casefold(" ".join([title, excerpt, " ".join(headings), _plain_text(content_body), slug_scope]))
    title_headings = _normalize_casefold(" ".join([title, " ".join(headings), slug_scope]))
    normalized_strong_tokens = [_normalize_casefold(token) for token in DAILY_MEMO_OFFTOPIC_STRONG_TOKENS if _normalize_casefold(token)]
    normalized_weak_tokens = [_normalize_casefold(token) for token in DAILY_MEMO_OFFTOPIC_WEAK_TOKENS if _normalize_casefold(token)]
    strong_hits = [token for token in normalized_strong_tokens if token in combined]
    weak_hits = [token for token in normalized_weak_tokens if token in combined]
    if strong_hits and (
        any(token in title_headings for token in normalized_strong_tokens)
        or len(set(strong_hits)) >= 2
        or bool(weak_hits)
    ):
        errors.append("daily_offtopic_mystery")
    axis_hits = _daily_memo_axis_hits(title, excerpt, " ".join(headings), content_body)
    payload["daily_topic_axes"] = axis_hits
    if not axis_hits:
        errors.append("daily_topic_axis_missing")
    return errors


def _build_daily_similarity_signature(payload: dict[str, Any], *, content_body: str) -> dict[str, Any]:
    title = _normalize_space(payload.get("title"))
    h2_headings = _extract_h2_headings(content_body)
    faq_questions = _extract_inline_faq_questions(content_body)
    table_headers = _extract_table_headers(content_body)
    token_set = _token_set_for_similarity(
        title,
        " ".join(h2_headings),
        " ".join(faq_questions),
        " ".join(table_headers),
    )
    return {
        "remote_post_id": _normalize_space(payload.get("remote_post_id")),
        "target_slug": _normalize_space(payload.get("target_slug") or payload.get("slug")),
        "title": title,
        "h2_headings": h2_headings,
        "faq_questions": faq_questions,
        "table_headers": table_headers,
        "token_set": token_set,
    }


def _daily_similarity_error(
    current_signature: dict[str, Any],
    existing_signatures: Sequence[dict[str, Any]],
) -> str | None:
    current_h2 = current_signature.get("h2_headings", [])
    current_faq = current_signature.get("faq_questions", [])
    current_tokens = current_signature.get("token_set", set())
    for existing in existing_signatures:
        same_h2 = bool(current_h2) and current_h2 == existing.get("h2_headings", [])
        same_faq = bool(current_faq) and current_faq == existing.get("faq_questions", [])
        title_similarity = _jaccard_similarity(
            _token_set_for_similarity(str(current_signature.get("title", ""))),
            _token_set_for_similarity(str(existing.get("title", ""))),
        )
        body_similarity = _jaccard_similarity(current_tokens, existing.get("token_set", set()))
        blended = (title_similarity * 0.35) + (body_similarity * 0.65)
        if same_h2 and same_faq:
            return f"daily_batch_duplicate_structure:{existing.get('target_slug') or existing.get('remote_post_id')}"
        if blended >= DAILY_MEMO_SIMILARITY_THRESHOLD:
            return f"daily_batch_similarity_exceeded:{existing.get('target_slug') or existing.get('remote_post_id')}"
    return None


def _image_is_available_for_post(url: str, asset_key: str, *, used_urls: set[str], used_asset_keys: set[str]) -> bool:
    normalized_url = _normalize_space(url)
    normalized_key = _normalize_space(asset_key)
    if not normalized_url:
        return False
    if normalized_url in used_urls:
        return False
    if normalized_key and normalized_key in used_asset_keys:
        return False
    return True


def _images_are_distinct(
    left_url: str,
    left_key: str,
    right_url: str,
    right_key: str,
) -> bool:
    normalized_left_url = _normalize_space(left_url)
    normalized_right_url = _normalize_space(right_url)
    normalized_left_key = _normalize_space(left_key)
    normalized_right_key = _normalize_space(right_key)
    if not normalized_left_url or not normalized_right_url:
        return False
    if normalized_left_url == normalized_right_url:
        return False
    if normalized_left_key and normalized_right_key and normalized_left_key == normalized_right_key:
        return False
    return True


def _normalize_source_post_snapshot(payload: dict[str, Any], *, cover_image_url: str, inline_image_url: str) -> dict[str, Any]:
    raw = payload.get("source_post") if isinstance(payload.get("source_post"), dict) else {}
    content_markdown = str(raw.get("content_markdown") or raw.get("contentMarkdown") or "")
    inline_urls = raw.get("current_inline_image_urls") if isinstance(raw.get("current_inline_image_urls"), list) else _extract_existing_image_urls(content_markdown)
    normalized = dict(raw)
    normalized["current_cover_image_url"] = _normalize_space(raw.get("current_cover_image_url") or cover_image_url)
    normalized["current_inline_image_urls"] = [_normalize_space(item) for item in inline_urls if _normalize_space(item)]
    normalized["content_markdown"] = content_markdown
    payload["source_post"] = normalized
    return normalized


def _disallowed_source_images(payload: dict[str, Any], *, public_base_url: str) -> tuple[set[str], set[str]]:
    cover_image = payload.get("cover_image") if isinstance(payload.get("cover_image"), dict) else {}
    inline_image = payload.get("inline_image") if isinstance(payload.get("inline_image"), dict) else {}
    urls: set[str] = set()
    keys: set[str] = set()
    for raw in [
        cover_image.get("url"),
        inline_image.get("url"),
    ]:
        candidate = _normalize_space(raw)
        if not candidate:
            continue
        urls.add(candidate)
        asset_key = _asset_key_from_url(candidate, public_base_url=public_base_url)
        if asset_key:
            keys.add(asset_key)
    for raw_key in [cover_image.get("asset_key"), inline_image.get("asset_key")]:
        candidate_key = _normalize_space(raw_key)
        if candidate_key:
            keys.add(candidate_key)
    return urls, keys


def _download_binary(url: str) -> bytes:
    request = Request(_normalize_space(url), headers={"User-Agent": "Bloggent-CodexWrite/0414"})
    with urlopen(request, timeout=45) as response:  # noqa: S310
        return response.read()


def _load_local_binary(path: Path) -> bytes:
    return path.read_bytes()


def _build_backup_json_index(repo_root: Path) -> list[dict[str, Any]]:
    backup_root = repo_root / "backup"
    if not backup_root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(backup_root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        records: list[dict[str, Any]]
        if isinstance(payload, dict) and isinstance(payload.get("posts"), list):
            records = [item for item in payload.get("posts", []) if isinstance(item, dict)]
        elif isinstance(payload, dict):
            records = [payload]
        else:
            continue
        for record in records:
            content = str(record.get("content") or record.get("contentMarkdown") or record.get("html_article") or "")
            item = {
                "backup_path": str(path),
                "slug": _normalize_space(record.get("slug")),
                "title": _normalize_space(record.get("title")),
                "cover_url": _normalize_space(record.get("coverImage") or record.get("cover_image")),
                "inline_urls": _extract_existing_image_urls(content),
            }
            if item["slug"] or item["title"] or item["cover_url"] or item["inline_urls"]:
                items.append(item)
    return items


def _build_local_backup_image_index(repo_root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for relative in BACKUP_IMAGE_SEARCH_ROOTS:
        root = repo_root / relative
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            items.append({"path": str(path), "stem": path.stem.lower(), "name": path.name.lower()})
    return items


def _payload_search_tokens(payload: dict[str, Any]) -> list[str]:
    entity_validation = payload.get("entity_validation") if isinstance(payload.get("entity_validation"), dict) else {}
    return _normalize_topic_tokens(
        payload.get("original_slug"),
        payload.get("target_slug"),
        payload.get("slug"),
        payload.get("title"),
        entity_validation.get("display_name"),
    )


def _backup_entry_score(entry: dict[str, Any], *, payload: dict[str, Any], tokens: Sequence[str]) -> int:
    haystack = " ".join([
        _normalize_space(entry.get("slug")),
        _normalize_space(entry.get("title")),
        _normalize_space(entry.get("backup_path")),
    ]).lower()
    score = 0
    for slug_value in (
        _normalize_space(payload.get("original_slug")),
        _normalize_space(payload.get("target_slug")),
        _normalize_space(payload.get("slug")),
    ):
        if slug_value and slug_value.lower() == _normalize_space(entry.get("slug")).lower():
            score += 100
        elif slug_value and slug_value.lower() in haystack:
            score += 40
    score += sum(4 for token in tokens if token in haystack)
    return score


def _collect_backup_json_candidates(
    payload: dict[str, Any],
    *,
    backup_index: Sequence[dict[str, Any]],
    used_urls: set[str],
    used_asset_keys: set[str],
    disallowed_urls: set[str],
    disallowed_asset_keys: set[str],
    public_base_url: str,
) -> list[dict[str, Any]]:
    tokens = _payload_search_tokens(payload)
    category_slug = _normalize_space(payload.get("category_slug"))
    scored_entries = [
        (entry, _backup_entry_score(entry, payload=payload, tokens=tokens))
        for entry in backup_index
    ]
    scored_entries = [(entry, score) for entry, score in scored_entries if score > 0]
    scored_entries.sort(key=lambda item: item[1], reverse=True)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry, score in scored_entries[:30]:
        for role_hint, raw_url in [("cover", entry.get("cover_url")), *[("inline", item) for item in entry.get("inline_urls", [])]]:
            url = _normalize_space(raw_url)
            if not url or url in seen or url in disallowed_urls:
                continue
            asset_key = _asset_key_from_url(url, public_base_url=public_base_url)
            if asset_key and asset_key in disallowed_asset_keys:
                continue
            seen.add(url)
            candidates.append(
                {
                    "candidate_id": f"url:{url}",
                    "score": score,
                    "role_hint": role_hint,
                    "source_type": "backup_json_url",
                    "url": url,
                    "asset_key": asset_key,
                    "source_ref": entry.get("backup_path"),
                    "category_slug": category_slug,
                }
            )
    return candidates


def _collect_local_backup_file_candidates(
    payload: dict[str, Any],
    *,
    local_index: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    tokens = _payload_search_tokens(payload)
    category_slug = _normalize_space(payload.get("category_slug"))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in local_index:
        haystack = f"{entry.get('stem', '')} {entry.get('name', '')}"
        overlap = sum(1 for token in tokens if token in haystack)
        if overlap <= 0:
            continue
        path = str(entry.get("path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        role_hint = "inline" if "inline" in haystack else ("cover" if "cover" in haystack else "generic")
        candidates.append(
            {
                "candidate_id": f"file:{path}",
                "score": 20 + overlap,
                "role_hint": role_hint,
                "source_type": "local_backup_file",
                "path": path,
                "source_ref": path,
                "category_slug": category_slug,
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:20]


def _collect_source_snapshot_media_candidates(
    payload: dict[str, Any],
    *,
    used_urls: set[str],
    used_asset_keys: set[str],
    public_base_url: str,
) -> list[dict[str, Any]]:
    source_post = payload.get("source_post") if isinstance(payload.get("source_post"), dict) else {}
    content_markdown = str(source_post.get("content_markdown") or "")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    category_slug = _normalize_space(payload.get("category_slug"))
    raw_items: list[tuple[str, str]] = []
    raw_items.append(("cover", _normalize_space(source_post.get("current_cover_image_url"))))
    for url in source_post.get("current_inline_image_urls") if isinstance(source_post.get("current_inline_image_urls"), list) else []:
        raw_items.append(("inline", _normalize_space(url)))
    for url in _extract_existing_image_urls(content_markdown):
        role_hint = "inline"
        lowered = str(url).lower()
        if "cover" in lowered and "inline" not in lowered:
            role_hint = "cover"
        raw_items.append((role_hint, _normalize_space(url)))
    for role_hint, raw_url in raw_items:
        normalized_url = _canonicalize_cloudflare_asset_url(raw_url, public_base_url=public_base_url)
        if not normalized_url or normalized_url in seen:
            continue
        seen.add(normalized_url)
        asset_key = _asset_key_from_url(normalized_url, public_base_url=public_base_url)
        if not _is_cloudflare_media_asset(normalized_url, asset_key=asset_key, public_base_url=public_base_url):
            continue
        if not _image_is_available_for_post(
            normalized_url,
            asset_key,
            used_urls=used_urls,
            used_asset_keys=used_asset_keys,
        ):
            continue
        score = 4000 if role_hint == "cover" else 3900
        candidates.append(
            {
                "candidate_id": f"source_snapshot:{role_hint}:{normalized_url}",
                "score": score,
                "role_hint": role_hint,
                "source_type": "existing_media_restore",
                "url": normalized_url,
                "asset_key": asset_key,
                "source_ref": "source_post_snapshot",
                "category_slug": category_slug,
            }
        )
    return candidates


def _collect_r2_unused_candidates_for_payload(
    payload: dict[str, Any],
    *,
    used_urls: set[str],
    used_asset_keys: set[str],
    disallowed_urls: set[str],
    disallowed_asset_keys: set[str],
    public_base_url: str,
    r2_listing_context: dict[str, str] | None,
    r2_unused_cache: dict[str, list[dict[str, Any]]] | None,
) -> list[dict[str, Any]]:
    if not r2_listing_context or r2_unused_cache is None:
        return []
    category_slug = _normalize_space(payload.get("category_slug"))
    if not category_slug:
        return []
    cache_key = _cloudflare_category_media_key(category_slug)
    if cache_key not in r2_unused_cache:
        try:
            r2_unused_cache[cache_key] = _build_r2_unused_candidates_for_category(
                category_slug=category_slug,
                payload=payload,
                public_base_url=public_base_url,
                account_id=_normalize_space(r2_listing_context.get("account_id")),
                bucket=_normalize_space(r2_listing_context.get("bucket")),
                access_key_id=_normalize_space(r2_listing_context.get("access_key_id")),
                secret_access_key=_normalize_space(r2_listing_context.get("secret_access_key")),
            )
        except Exception:
            r2_unused_cache[cache_key] = []
    filtered: list[dict[str, Any]] = []
    for item in r2_unused_cache.get(cache_key, []):
        url = _normalize_space(item.get("url"))
        asset_key = _normalize_space(item.get("asset_key"))
        if not url:
            continue
        if url in disallowed_urls:
            continue
        if asset_key and asset_key in disallowed_asset_keys:
            continue
        if not _image_is_available_for_post(url, asset_key, used_urls=used_urls, used_asset_keys=used_asset_keys):
            continue
        filtered.append(dict(item))
    filtered.sort(key=lambda entry: int(entry.get("score") or 0), reverse=True)
    return filtered[:80]


def _image_prompt_template_path_for_category(category_slug: str) -> Path:
    relative = get_cloudflare_prompt_category_relative_path(category_slug)
    return _repo_root() / "prompts" / "channels" / "cloudflare" / "dongri-archive" / relative / "image_prompt_generation.md"


def _build_generated_collage_prompt(
    payload: dict[str, Any],
    *,
    slot: str,
) -> tuple[str, str]:
    title = _normalize_space(payload.get("title"))
    excerpt = _normalize_space(payload.get("excerpt"))
    category_slug = _normalize_space(payload.get("category_slug"))
    body = _plain_text(str(payload.get("content_body") or ""))[:1200]
    template_path = _image_prompt_template_path_for_category(category_slug)
    rendered = ""
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
        rendered = render_prompt_template(
            template,
            keyword=title,
            primary_language="ko",
            target_audience="Korean blog readers",
            planner_brief="",
            editorial_category_label=category_slug,
            article_title=title,
            article_excerpt=excerpt,
            article_context=body,
            current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        ).strip()
    is_mysteria = _is_mysteria_category_slug(category_slug)
    if slot == "cover":
        directive = (
            "Create one single flattened 5x4 panel grid collage hero image, "
            "realistic documentary style, visible white gutters, clean grid layout, no text, no logo."
            if is_mysteria
            else "Create one hero-cover editorial 3x3 collage with exactly 9 distinct panels, realistic photography style, visible white gutters, center panel dominant, no text, no logo."
        )
    else:
        directive = (
            "Do not request or generate any inline image for this category."
            if is_mysteria
            else "Create one supporting inline editorial 3x2 collage with exactly 6 distinct panels, realistic photography style, no text, no logo, clearly different from cover."
        )
    prompt = "\n\n".join(part for part in [rendered, directive] if part).strip()
    if not prompt:
        prompt = f"{directive} Article: {title}. Category: {category_slug}. Context: {body[:500]}"
    return prompt, str(template_path)


def _generate_collage_image_candidate(
    db: Session,
    *,
    payload: dict[str, Any],
    target_slug: str,
    slot: str,
    public_base_url: str,
) -> dict[str, Any]:
    category_slug = _normalize_space(payload.get("category_slug"))
    prompt, prompt_path = _build_generated_collage_prompt(payload, slot=slot)
    image_provider = get_image_provider(db)
    image_bytes, _raw = image_provider.generate_image(prompt, f"{target_slug}-{slot}-collage")
    normalized_binary = _normalize_binary_for_filename(
        content=image_bytes,
        filename=f"{target_slug}-{slot}.webp",
        force_webp=True,
    )
    content_hash = _image_content_hash(normalized_binary)
    filename = f"{_sanitize_filename_token(target_slug, 'post')}-{slot}-{content_hash[:12]}.webp"
    object_key = _build_cloudflare_media_object_key(
        category_slug=category_slug,
        target_slug=target_slug,
        slot=slot,
        content_hash=content_hash,
    )
    public_url, upload_payload, _delivery_meta = upload_binary_to_cloudflare_r2(
        db,
        object_key=object_key,
        filename=filename,
        content=normalized_binary,
    )
    resolved_public_url = _resolve_reachable_asset_url(public_url, public_base_url=public_base_url)
    if not resolved_public_url:
        raise ValueError("generated_collage_image_unreachable")
    return {
        "url": resolved_public_url,
        "asset_key": _normalize_space(upload_payload.get("object_key")) or _asset_key_from_url(resolved_public_url, public_base_url=public_base_url),
        "hash_or_key": content_hash,
        "source": "generated_collage",
        "source_ref": prompt_path,
        "category_slug": category_slug,
    }


def _collect_preferred_image_candidates(
    payload: dict[str, Any],
    *,
    used_urls: set[str],
    used_asset_keys: set[str],
    disallowed_urls: set[str],
    disallowed_asset_keys: set[str],
    public_base_url: str,
) -> list[dict[str, Any]]:
    raw = payload.get("preferred_image_candidates") if isinstance(payload.get("preferred_image_candidates"), dict) else {}
    category_slug = _normalize_space(payload.get("category_slug"))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for role_hint in ("cover", "inline"):
        items = raw.get(role_hint)
        normalized_items = items if isinstance(items, list) else ([items] if isinstance(items, dict) else [])
        for index, item in enumerate(normalized_items, start=1):
            source_type = _normalize_space(item.get("source_type"))
            if source_type not in {"existing_media_restore", "r2_unused", "backup_json_url", "local_backup_file"}:
                continue
            url = _normalize_space(item.get("url"))
            path = _normalize_space(item.get("path"))
            asset_key = _normalize_space(item.get("asset_key")) or _asset_key_from_url(url, public_base_url=public_base_url)
            candidate_id = f"preferred:{role_hint}:{source_type}:{url or path or index}"
            if candidate_id in seen:
                continue
            if url and url in disallowed_urls:
                continue
            if asset_key and asset_key in disallowed_asset_keys:
                continue
            if source_type == "r2_unused":
                if url and url in used_urls:
                    continue
                if asset_key and asset_key in used_asset_keys:
                    continue
            if source_type in {"existing_media_restore", "r2_unused", "backup_json_url"} and not url:
                continue
            if source_type == "local_backup_file" and not path:
                continue
            seen.add(candidate_id)
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "score": int(item.get("score") or 1000),
                    "role_hint": role_hint,
                    "source_type": source_type,
                    "url": url,
                    "path": path,
                    "asset_key": asset_key,
                    "source_ref": _normalize_space(item.get("source_ref") or url or path),
                    "category_slug": category_slug,
                }
            )
    return candidates


def _select_cover_and_inline_candidates(candidates: Sequence[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (
            0 if item.get("role_hint") == "cover" else 1,
            _source_type_priority(str(item.get("source_type") or "")),
            -int(item.get("score") or 0),
        ),
    )
    cover = sorted_candidates[0] if sorted_candidates else None
    if cover is None:
        return None, None
    inline_candidates = [item for item in candidates if item.get("candidate_id") != cover.get("candidate_id")]
    inline_candidates.sort(
        key=lambda item: (
            0 if item.get("role_hint") == "inline" else 1,
            _source_type_priority(str(item.get("source_type") or "")),
            -int(item.get("score") or 0),
        )
    )
    inline = inline_candidates[0] if inline_candidates else None
    return cover, inline


def _materialize_image_candidate(
    db: Session,
    *,
    candidate: dict[str, Any],
    target_slug: str,
    slot: str,
    public_base_url: str,
) -> dict[str, Any]:
    source_type = _normalize_space(candidate.get("source_type"))
    if source_type in {"existing_media_restore", "r2_unused"}:
        resolved_url = _resolve_reachable_asset_url(candidate.get("url"), public_base_url=public_base_url)
        if not resolved_url:
            raise ValueError(f"{source_type}_image_unreachable")
        asset_key = _normalize_space(candidate.get("asset_key")) or _asset_key_from_url(resolved_url, public_base_url=public_base_url)
        return {
            "url": resolved_url,
            "asset_key": asset_key,
            "hash_or_key": asset_key,
            "source": source_type,
            "source_ref": _normalize_space(candidate.get("source_ref")),
        }

    if source_type == "local_backup_file":
        binary = _load_local_binary(Path(str(candidate.get("path"))))
    elif source_type in {"backup_json_url", "generated_collage"}:
        binary = _download_binary(_normalize_space(candidate.get("url")))
    else:
        raise ValueError(f"Unsupported image candidate source: {source_type}")

    normalized_binary = _normalize_binary_for_filename(content=binary, filename=f"{target_slug}-{slot}.webp", force_webp=True)
    content_hash = _image_content_hash(normalized_binary)
    filename = f"{_sanitize_filename_token(target_slug, 'post')}-{slot}-{content_hash[:12]}.webp"
    category_slug = _normalize_space(candidate.get("category_slug"))
    object_key = _build_cloudflare_media_object_key(
        category_slug=category_slug,
        target_slug=target_slug,
        slot=slot,
        content_hash=content_hash,
    ) if category_slug else None
    public_url, upload_payload, _delivery_meta = upload_binary_to_cloudflare_r2(
        db,
        object_key=object_key,
        filename=filename,
        content=normalized_binary,
    )
    resolved_public_url = _resolve_reachable_asset_url(public_url, public_base_url=public_base_url)
    if not resolved_public_url:
        raise ValueError("uploaded_image_unreachable")
    return {
        "url": resolved_public_url,
        "asset_key": _normalize_space(upload_payload.get("object_key")) or _asset_key_from_url(resolved_public_url, public_base_url=public_base_url),
        "hash_or_key": content_hash,
        "source": source_type,
        "source_ref": _normalize_space(candidate.get("source_ref") or candidate.get("url") or candidate.get("path")),
    }


def _collect_live_image_inventory(
    db: Session,
    *,
    public_base_url: str,
    exclude_remote_post_id: str = "",
    backup_index: Sequence[dict[str, Any]] | None = None,
) -> dict[str, set[str]]:
    used_urls: set[str] = set()
    used_asset_keys: set[str] = set()
    backup_entries_by_slug: dict[str, list[dict[str, Any]]] = {}
    for entry in backup_index or []:
        slug = _normalize_space(entry.get("slug"))
        if slug:
            bucket = backup_entries_by_slug.setdefault(slug, [])
            bucket.append(entry)
    for row in _list_target_posts(db):
        remote_post_id = _normalize_space(row.remote_post_id)
        if exclude_remote_post_id and remote_post_id == exclude_remote_post_id:
            continue
        for raw_url in [
            row.thumbnail_url,
        ]:
            candidate = _canonicalize_cloudflare_asset_url(raw_url, public_base_url=public_base_url)
            if not candidate:
                continue
            used_urls.add(candidate)
            asset_key = _asset_key_from_url(candidate, public_base_url=public_base_url)
            if asset_key:
                used_asset_keys.add(asset_key)
        row_slug = _normalize_space(row.slug)
        for entry in backup_entries_by_slug.get(row_slug, []):
            for raw_url in [
                entry.get("cover_url"),
                *(entry.get("inline_urls") if isinstance(entry.get("inline_urls"), list) else []),
            ]:
                candidate = _canonicalize_cloudflare_asset_url(raw_url, public_base_url=public_base_url)
                if not candidate:
                    continue
                used_urls.add(candidate)
                asset_key = _asset_key_from_url(candidate, public_base_url=public_base_url)
                if asset_key:
                    used_asset_keys.add(asset_key)
    return {"urls": used_urls, "asset_keys": used_asset_keys}


def _reserve_payload_images(payload: dict[str, Any], *, used_urls: set[str], used_asset_keys: set[str]) -> None:
    is_mysteria = _is_mysteria_category_slug(_normalize_space(payload.get("category_slug")))
    for field_name in (("cover_image",) if is_mysteria else ("cover_image", "inline_image")):
        image = payload.get(field_name) if isinstance(payload.get(field_name), dict) else {}
        url = _normalize_space(image.get("url"))
        asset_key = _normalize_space(image.get("asset_key"))
        if url:
            used_urls.add(url)
        if asset_key:
            used_asset_keys.add(asset_key)


def _resolve_payload_images(
    db: Session,
    *,
    payload: dict[str, Any],
    public_base_url: str,
    used_urls: set[str],
    used_asset_keys: set[str],
    backup_index: Sequence[dict[str, Any]],
    local_index: Sequence[dict[str, Any]],
    r2_listing_context: dict[str, str] | None = None,
    r2_unused_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    title = _normalize_space(payload.get("title"))
    category_slug = _normalize_space(payload.get("category_slug"))
    is_mysteria = _is_mysteria_category_slug(category_slug)
    cover_image = _normalize_image_field(payload.get("cover_image"), fallback_alt=title, public_base_url=public_base_url)
    inline_image = _normalize_image_field(payload.get("inline_image"), fallback_alt=title, public_base_url=public_base_url)
    payload["cover_image"] = cover_image
    payload["inline_image"] = inline_image
    source_post = _normalize_source_post_snapshot(payload, cover_image_url=cover_image.get("url", ""), inline_image_url=inline_image.get("url", ""))
    image_uniqueness = _normalize_image_uniqueness(payload)
    backup_resolution = _normalize_backup_image_resolution(payload)
    target_slug = _normalize_space(payload.get("target_slug") or payload.get("slug"))
    current_source_urls: set[str] = set()
    current_source_asset_keys: set[str] = set()
    for raw_url in [
        source_post.get("current_cover_image_url"),
        *(source_post.get("current_inline_image_urls") if isinstance(source_post.get("current_inline_image_urls"), list) else []),
        cover_image.get("url"),
        inline_image.get("url"),
    ]:
        candidate = _normalize_space(raw_url)
        if not candidate:
            continue
        current_source_urls.add(candidate)
        asset_key = _asset_key_from_url(candidate, public_base_url=public_base_url)
        if asset_key:
            current_source_asset_keys.add(asset_key)

    selected_cover: dict[str, Any] | None = None
    selected_inline: dict[str, Any] | None = None
    working_urls = set(used_urls)
    working_asset_keys = set(used_asset_keys)
    resolved_cover_url = _resolve_reachable_asset_url(cover_image.get("url"), public_base_url=public_base_url)
    resolved_inline_url = _resolve_reachable_asset_url(inline_image.get("url"), public_base_url=public_base_url)
    resolved_cover_key = _normalize_space(cover_image.get("asset_key")) or _asset_key_from_url(resolved_cover_url, public_base_url=public_base_url)
    resolved_inline_key = _normalize_space(inline_image.get("asset_key")) or _asset_key_from_url(resolved_inline_url, public_base_url=public_base_url)
    if is_mysteria and resolved_cover_url and _is_cloudflare_media_asset(resolved_cover_url, asset_key=resolved_cover_key, public_base_url=public_base_url) and _image_is_available_for_post(
        resolved_cover_url,
        resolved_cover_key,
        used_urls=working_urls,
        used_asset_keys=working_asset_keys,
    ):
        payload["cover_image"] = {
            "url": resolved_cover_url,
            "alt": _normalize_space(cover_image.get("alt") or payload.get("meta_description") or title),
            "source": _normalize_space(cover_image.get("source") or "current_live"),
            "asset_key": resolved_cover_key,
        }
        payload["inline_image"] = {"url": "", "alt": "", "source": "", "asset_key": ""}
        image_uniqueness["cover_hash_or_key"] = resolved_cover_key or resolved_cover_url
        image_uniqueness["inline_hash_or_key"] = ""
        image_uniqueness["is_distinct_within_post"] = True
        image_uniqueness["is_distinct_across_blog"] = True
        backup_resolution["status"] = "resolved"
        backup_resolution["candidate_count"] = 0
        backup_resolution["cover"] = {
            "source": payload["cover_image"]["source"],
            "source_ref": "current_live",
            "asset_key": payload["cover_image"]["asset_key"],
            "url": payload["cover_image"]["url"],
        }
        backup_resolution["inline"] = None
        return

    if (
        resolved_cover_url
        and resolved_inline_url
        and _is_cloudflare_media_asset(resolved_cover_url, asset_key=resolved_cover_key, public_base_url=public_base_url)
        and _is_cloudflare_media_asset(resolved_inline_url, asset_key=resolved_inline_key, public_base_url=public_base_url)
        and _images_are_distinct(resolved_cover_url, resolved_cover_key, resolved_inline_url, resolved_inline_key)
        and _image_is_available_for_post(
            resolved_cover_url,
            resolved_cover_key,
            used_urls=working_urls,
            used_asset_keys=working_asset_keys,
        )
        and _image_is_available_for_post(
            resolved_inline_url,
            resolved_inline_key,
            used_urls=working_urls,
            used_asset_keys=working_asset_keys,
        )
    ):
        payload["cover_image"] = {
            "url": resolved_cover_url,
            "alt": _normalize_space(cover_image.get("alt") or payload.get("meta_description") or title),
            "source": _normalize_space(cover_image.get("source") or "current_live"),
            "asset_key": resolved_cover_key,
        }
        payload["inline_image"] = {
            "url": resolved_inline_url,
            "alt": _normalize_space(inline_image.get("alt") or title),
            "source": _normalize_space(inline_image.get("source") or "current_live"),
            "asset_key": resolved_inline_key,
        }
        image_uniqueness["cover_hash_or_key"] = resolved_cover_key or resolved_cover_url
        image_uniqueness["inline_hash_or_key"] = resolved_inline_key or resolved_inline_url
        image_uniqueness["is_distinct_within_post"] = True
        image_uniqueness["is_distinct_across_blog"] = True
        backup_resolution["status"] = "resolved"
        backup_resolution["candidate_count"] = 0
        backup_resolution["cover"] = {
            "source": payload["cover_image"]["source"],
            "source_ref": "current_live",
            "asset_key": payload["cover_image"]["asset_key"],
            "url": payload["cover_image"]["url"],
        }
        backup_resolution["inline"] = {
            "source": payload["inline_image"]["source"],
            "source_ref": "current_live",
            "asset_key": payload["inline_image"]["asset_key"],
            "url": payload["inline_image"]["url"],
        }
        backup_resolution["notes"] = ["kept_current_media"]
        return

    source_restore_candidates = _collect_source_snapshot_media_candidates(
        payload,
        used_urls=working_urls,
        used_asset_keys=working_asset_keys,
        public_base_url=public_base_url,
    )
    r2_unused_candidates = _collect_r2_unused_candidates_for_payload(
        payload,
        used_urls=working_urls,
        used_asset_keys=working_asset_keys,
        disallowed_urls=current_source_urls,
        disallowed_asset_keys=current_source_asset_keys,
        public_base_url=public_base_url,
        r2_listing_context=r2_listing_context,
        r2_unused_cache=r2_unused_cache,
    )
    preferred_candidates = _collect_preferred_image_candidates(
        payload,
        used_urls=working_urls,
        used_asset_keys=working_asset_keys,
        disallowed_urls=current_source_urls,
        disallowed_asset_keys=current_source_asset_keys,
        public_base_url=public_base_url,
    )

    backup_candidates = _collect_backup_json_candidates(
        payload,
        backup_index=backup_index,
        used_urls=working_urls,
        used_asset_keys=working_asset_keys,
        disallowed_urls=current_source_urls,
        disallowed_asset_keys=current_source_asset_keys,
        public_base_url=public_base_url,
    )
    local_candidates = _collect_local_backup_file_candidates(payload, local_index=local_index)
    remaining_candidates = [
        *source_restore_candidates,
        *r2_unused_candidates,
        *preferred_candidates,
        *backup_candidates,
        *local_candidates,
    ]
    backup_resolution["candidate_count"] = len(remaining_candidates)

    if selected_cover is None:
        cover_candidates = sorted(
            remaining_candidates,
            key=lambda item: (
                0 if item.get("role_hint") == "cover" else 1,
                _source_type_priority(str(item.get("source_type") or "")),
                -int(item.get("score") or 0),
            ),
        )
        for cover_candidate in cover_candidates:
            cover_url = _normalize_space(cover_candidate.get("url"))
            cover_key = _normalize_space(cover_candidate.get("asset_key"))
            if cover_candidate.get("source_type") in {"r2_unused", "existing_media_restore"} and not _image_is_available_for_post(
                cover_url,
                cover_key,
                used_urls=working_urls,
                used_asset_keys=working_asset_keys,
            ):
                continue
            try:
                selected_cover = _materialize_image_candidate(
                    db,
                    candidate=cover_candidate,
                    target_slug=target_slug,
                    slot="cover",
                    public_base_url=public_base_url,
                )
            except Exception:
                continue
            if selected_cover["url"]:
                working_urls.add(selected_cover["url"])
            if selected_cover["asset_key"]:
                working_asset_keys.add(selected_cover["asset_key"])
            remaining_candidates = [item for item in remaining_candidates if item.get("candidate_id") != cover_candidate.get("candidate_id")]
            break

    if is_mysteria and selected_cover is not None:
        payload["cover_image"] = {
            "url": _normalize_space(selected_cover.get("url")),
            "alt": _normalize_space(cover_image.get("alt") or payload.get("meta_description") or title),
            "source": _normalize_space(selected_cover.get("source")),
            "asset_key": _normalize_space(selected_cover.get("asset_key")),
        }
        payload["inline_image"] = {"url": "", "alt": "", "source": "", "asset_key": ""}
        image_uniqueness["cover_hash_or_key"] = _normalize_space(selected_cover.get("hash_or_key"))
        image_uniqueness["inline_hash_or_key"] = ""
        image_uniqueness["is_distinct_within_post"] = True
        image_uniqueness["is_distinct_across_blog"] = True
        backup_resolution["status"] = "resolved"
        backup_resolution["cover"] = {
            "source": payload["cover_image"]["source"],
            "source_ref": _normalize_space(selected_cover.get("source_ref")),
            "asset_key": payload["cover_image"]["asset_key"],
            "url": payload["cover_image"]["url"],
        }
        backup_resolution["inline"] = None
        backup_resolution["notes"] = []
        source_post["current_cover_image_url"] = _normalize_space(source_post.get("current_cover_image_url") or cover_image.get("url"))
        source_post["current_inline_image_urls"] = []
        return

    if selected_inline is None:
        inline_candidates = sorted(
            remaining_candidates,
            key=lambda item: (
                0 if item.get("role_hint") == "inline" else 1,
                _source_type_priority(str(item.get("source_type") or "")),
                -int(item.get("score") or 0),
            ),
        )
        for inline_candidate in inline_candidates:
            if inline_candidate.get("source_type") in {"r2_unused", "existing_media_restore"}:
                inline_url = _normalize_space(inline_candidate.get("url"))
                inline_key = _normalize_space(inline_candidate.get("asset_key"))
                if not _image_is_available_for_post(inline_url, inline_key, used_urls=working_urls, used_asset_keys=working_asset_keys):
                    continue
                if selected_cover and not _images_are_distinct(
                    inline_url,
                    inline_key,
                    selected_cover.get("url", ""),
                    selected_cover.get("asset_key", ""),
                ):
                    continue
            try:
                materialized = _materialize_image_candidate(
                    db,
                    candidate=inline_candidate,
                    target_slug=target_slug,
                    slot="inline",
                    public_base_url=public_base_url,
                )
            except Exception:
                continue
            if selected_cover and not _images_are_distinct(
                materialized.get("url", ""),
                materialized.get("asset_key", ""),
                selected_cover.get("url", ""),
                selected_cover.get("asset_key", ""),
            ):
                continue
            selected_inline = materialized
            break

    if selected_cover is None:
        try:
            selected_cover = _generate_collage_image_candidate(
                db,
                payload=payload,
                target_slug=target_slug,
                slot="cover",
                public_base_url=public_base_url,
            )
            if selected_cover.get("url"):
                working_urls.add(_normalize_space(selected_cover.get("url")))
            if selected_cover.get("asset_key"):
                working_asset_keys.add(_normalize_space(selected_cover.get("asset_key")))
        except Exception:
            selected_cover = None

    if selected_inline is None and selected_cover is not None:
        try:
            generated_inline = _generate_collage_image_candidate(
                db,
                payload=payload,
                target_slug=target_slug,
                slot="inline",
                public_base_url=public_base_url,
            )
            if _images_are_distinct(
                generated_inline.get("url", ""),
                generated_inline.get("asset_key", ""),
                selected_cover.get("url", ""),
                selected_cover.get("asset_key", ""),
            ):
                selected_inline = generated_inline
        except Exception:
            selected_inline = None

    if selected_cover is None or selected_inline is None:
        backup_resolution["status"] = "manual_review_required"
        backup_resolution["notes"] = ["distinct_image_candidates_not_found"]
        image_uniqueness["is_distinct_within_post"] = False
        image_uniqueness["is_distinct_across_blog"] = False
        return

    payload["cover_image"] = {
        "url": _normalize_space(selected_cover.get("url")),
        "alt": _normalize_space(cover_image.get("alt") or payload.get("meta_description") or title),
        "source": _normalize_space(selected_cover.get("source")),
        "asset_key": _normalize_space(selected_cover.get("asset_key")),
    }
    payload["inline_image"] = {
        "url": _normalize_space(selected_inline.get("url")),
        "alt": _normalize_space(inline_image.get("alt") or title),
        "source": _normalize_space(selected_inline.get("source")),
        "asset_key": _normalize_space(selected_inline.get("asset_key")),
    }
    image_uniqueness["cover_hash_or_key"] = _normalize_space(selected_cover.get("hash_or_key"))
    image_uniqueness["inline_hash_or_key"] = _normalize_space(selected_inline.get("hash_or_key"))
    image_uniqueness["is_distinct_within_post"] = _images_are_distinct(
        payload["cover_image"]["url"],
        payload["cover_image"]["asset_key"],
        payload["inline_image"]["url"],
        payload["inline_image"]["asset_key"],
    )
    image_uniqueness["is_distinct_across_blog"] = True
    backup_resolution["status"] = "resolved"
    backup_resolution["cover"] = {
        "source": payload["cover_image"]["source"],
        "source_ref": _normalize_space(selected_cover.get("source_ref")),
        "asset_key": payload["cover_image"]["asset_key"],
        "url": payload["cover_image"]["url"],
    }
    backup_resolution["inline"] = {
        "source": payload["inline_image"]["source"],
        "source_ref": _normalize_space(selected_inline.get("source_ref")),
        "asset_key": payload["inline_image"]["asset_key"],
        "url": payload["inline_image"]["url"],
    }
    backup_resolution["notes"] = []
    source_post["current_cover_image_url"] = _normalize_space(source_post.get("current_cover_image_url") or cover_image.get("url"))
    source_post["current_inline_image_urls"] = [_normalize_space(item) for item in source_post.get("current_inline_image_urls", []) if _normalize_space(item)]


def _seed_package_from_post(row: SyncedCloudflarePost, detail: dict[str, Any]) -> dict[str, Any]:
    category_slug = _normalize_space(row.canonical_category_slug or row.category_slug)
    category_name = _normalize_space(row.canonical_category_name or row.category_name or category_slug)
    root_category_name, category_folder = _category_root_parts(category_slug)
    title = _normalize_space(detail.get("title") or row.title)
    excerpt = _normalize_space(detail.get("excerpt") or row.excerpt_text)
    meta_description = _normalize_space(detail.get("seoDescription") or excerpt or title)
    seo_title = _normalize_space(detail.get("seoTitle") or title)
    current_content = str(detail.get("contentMarkdown") or detail.get("content") or detail.get("markdown") or "")
    current_slug = _normalize_space(row.slug) or _extract_slug_from_url(detail.get("publicUrl") or row.url)
    cover_image_url = _canonicalize_cloudflare_asset_url(detail.get("coverImage") or row.thumbnail_url)
    cover_alt = _normalize_space(detail.get("coverAlt") or meta_description or title)
    inline_image_url, inline_alt = _inline_image_from_detail(detail, cover_image_url=cover_image_url)
    inline_image_urls = [] if _is_mysteria_category_slug(category_slug) else _extract_existing_image_urls(current_content)
    faq_section = detail.get("faqSection") if isinstance(detail.get("faqSection"), list) else []
    return {
        "remote_post_id": _normalize_space(row.remote_post_id),
        "slug": current_slug,
        "original_slug": current_slug,
        "target_slug": current_slug,
        "published_url": _normalize_space(detail.get("publicUrl") or row.url),
        "root_category_name": root_category_name,
        "category_slug": category_slug,
        "category_name": category_name,
        "category_folder": category_folder,
        "prompt_version": CODEX_WRITE_PROMPT_VERSION,
        "source_prompt_paths": _prompt_paths_for_category(category_slug),
        "source_post": {
            "title": title,
            "excerpt": excerpt,
            "seo_title": seo_title,
            "meta_description": meta_description,
            "content_markdown": current_content,
            "current_cover_image_url": cover_image_url,
            "current_inline_image_urls": inline_image_urls,
            "render_metadata": row.render_metadata or {},
        },
        "title": title,
        "excerpt": excerpt,
        "meta_description": meta_description,
        "seo_title": seo_title,
        "content_body": current_content,
        "html_article": "",
        "faq_section": faq_section,
        "tag_names": _extract_tag_names(detail, row),
        "cover_image": {
            "url": cover_image_url,
            "alt": cover_alt,
            "source": "current_live",
            "asset_key": _asset_key_from_url(cover_image_url),
        },
        "inline_image": ({
            "url": "",
            "alt": "",
            "source": "",
            "asset_key": "",
        } if _is_mysteria_category_slug(category_slug) else {
            "url": _canonicalize_cloudflare_asset_url(inline_image_url),
            "alt": inline_alt or title,
            "source": "current_live",
            "asset_key": _asset_key_from_url(inline_image_url),
        }),
        "image_uniqueness": {
            "cover_hash_or_key": _asset_key_from_url(cover_image_url),
            "inline_hash_or_key": "" if _is_mysteria_category_slug(category_slug) else _asset_key_from_url(inline_image_url),
            "is_distinct_within_post": True if _is_mysteria_category_slug(category_slug) else bool(cover_image_url and inline_image_url and cover_image_url != inline_image_url),
            "is_distinct_across_blog": False,
        },
        "backup_image_resolution": {
            "status": "pending",
            "searched_roots": list(BACKUP_IMAGE_SEARCH_ROOTS),
            "candidate_count": 0,
            "cover": {},
            "inline": {},
            "notes": [],
        },
        "render_metadata": row.render_metadata or {},
        "entity_validation": _seed_entity_validation(category_slug=category_slug, title=title),
        "layout_template": "single-layout-0415",
        "publish_state": {"status": CODEX_WRITE_STATUS_SEEDED, "publish_mode": None, "last_published_at": None, "last_error": None},
    }


def export_codex_write_packages(db: Session, *, category_slugs: Sequence[str] | None = None, slug: str | None = None, limit: int | None = None, overwrite: bool = False, sync_before: bool = True, base_dir: Path | None = None) -> dict[str, Any]:
    root = get_codex_write_root(base_dir=base_dir)
    sync_result: dict[str, Any] | None = sync_cloudflare_posts(db, include_non_published=True) if sync_before else None
    rows = _list_target_posts(db, category_slugs=category_slugs, slug=slug, limit=limit)
    items: list[dict[str, Any]] = []
    created_count = 0
    skipped_count = 0
    for row in rows:
        remote_post_id = _normalize_space(row.remote_post_id)
        category_slug_value = _normalize_space(row.canonical_category_slug or row.category_slug)
        slug_value = _normalize_space(row.slug)
        package_path = _package_path(base_dir=root, category_slug=category_slug_value, slug=slug_value, remote_post_id=remote_post_id)
        if package_path.exists() and not overwrite:
            skipped_count += 1
            items.append({"status": CODEX_WRITE_STATUS_SKIPPED, "reason": "exists", "remote_post_id": remote_post_id, "original_slug": slug_value, "target_slug": slug_value, "category_slug": category_slug_value, "path": str(package_path)})
            continue
        detail = _fetch_integration_post_detail(db, remote_post_id=remote_post_id)
        package = _seed_package_from_post(row, detail)
        _write_json(package_path, package)
        created_count += 1
        items.append({"status": CODEX_WRITE_STATUS_SEEDED, "reason": "exported", "remote_post_id": remote_post_id, "original_slug": package["original_slug"], "target_slug": package["target_slug"], "category_slug": category_slug_value, "path": str(package_path)})
    report_path = _report_path(root, "export")
    _write_json(report_path, {"generated_at": _utc_now_iso(), "sync_before": bool(sync_before), "sync_result": sync_result, "category_slugs": list(category_slugs or []), "slug": _normalize_space(slug), "created_count": created_count, "skipped_count": skipped_count, "items": items})
    return {"status": "ok", "root": str(root), "created_count": created_count, "skipped_count": skipped_count, "report_path": str(report_path), "items": items}


def _package_files_for_publish(*, base_dir: Path, category_slugs: Sequence[str] | None = None, slug: str | None = None, path: Path | None = None, limit: int | None = None) -> list[Path]:
    if path is not None:
        target = Path(path).resolve()
        if not target.exists():
            raise FileNotFoundError(f"codex_write path not found: {target}")
        if target.is_file():
            return [target]
        files = sorted(item for item in target.rglob("*.json") if item.name != "channel.json")
        return files[:limit] if limit is not None and limit > 0 else files
    normalized_categories = [_normalize_space(item) for item in (category_slugs or []) if _normalize_space(item)]
    files: list[Path] = []
    if normalized_categories:
        for category_slug in normalized_categories:
            category_dir = base_dir / get_cloudflare_prompt_category_relative_path(category_slug)
            if category_dir.exists():
                files.extend(sorted(item for item in category_dir.glob("*.json") if item.name != "channel.json"))
    else:
        files.extend(sorted(item for item in base_dir.rglob("*.json") if item.name != "channel.json"))
    normalized_slug = _normalize_space(slug)
    if normalized_slug:
        files = [item for item in files if item.stem == normalized_slug]
    return files[:limit] if limit is not None and limit > 0 else files

def _normalize_tag_names(tag_names: Sequence[Any], *, category_name: str, title: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in [category_name, *tag_names]:
        candidate = _normalize_space(raw).replace("#", " ")
        if candidate and candidate.casefold() not in seen:
            seen.add(candidate.casefold())
            values.append(candidate)
            if len(values) >= 12:
                break
    if values:
        return values
    for token in re.findall(r"[A-Za-z0-9가-힣]{2,}", title or ""):
        candidate = _normalize_space(token)
        if candidate and candidate.casefold() not in seen:
            seen.add(candidate.casefold())
            values.append(candidate)
            if len(values) >= 4:
                break
    return values


def _contains_banned_token(*parts: Any) -> list[str]:
    combined = " ".join(_normalize_space(part) for part in parts if _normalize_space(part))
    combined = re.sub(r"https?://\S+", " ", combined, flags=re.IGNORECASE)
    combined = combined.casefold()
    return [token for token in PUBLIC_BANNED_TOKENS if token.casefold() in combined]


def _matches_live_html_contract(content_body: str) -> bool:
    body = str(content_body or "").strip()
    if not body.startswith("# "):
        return False
    if body.count("<section") != 1 or body.count("</section>") != 1:
        return False
    faq_match = re.search(r"(?is)<h2[^>]*>\s*자주 묻는 질문\s*</h2>", body)
    if not faq_match:
        return False
    record_match = re.search(r"(?is)<h2[^>]*>\s*마무리 기록\s*</h2>", body)
    if not record_match:
        return False
    section_close = body.find("</section>")
    if section_close < faq_match.start():
        return False
    if section_close > record_match.start():
        return False
    if not HTML_IMAGE_RE.search(body):
        return False
    if MARKDOWN_IMAGE_RE.search(body):
        return False
    if re.search(r"(?m)^\s*##+\s+", body):
        return False
    return True


def _normalize_entity_validation(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("entity_validation") if isinstance(payload.get("entity_validation"), dict) else {}
    category_slug = _normalize_space(payload.get("category_slug"))
    normalized = {
        "status": _normalize_space(raw.get("status")) or ("manual_review_required" if category_slug in FACTUAL_ENTITY_CATEGORIES else "not_applicable"),
        "entity_type": _normalize_space(raw.get("entity_type")) or ENTITY_TYPE_BY_CATEGORY.get(category_slug, "reflection"),
        "display_name": _normalize_space(raw.get("display_name")) or _display_name_from_title(_normalize_space(payload.get("title")), category_slug=category_slug),
        "evidence_urls": [_normalize_space(item) for item in (raw.get("evidence_urls") if isinstance(raw.get("evidence_urls"), list) else []) if _normalize_space(item)],
        "evidence_note": _normalize_space(raw.get("evidence_note")),
    }
    payload["entity_validation"] = normalized
    return normalized


def _validate_entity_validation(payload: dict[str, Any]) -> list[str]:
    category_slug = _normalize_space(payload.get("category_slug"))
    entity_validation = _normalize_entity_validation(payload)
    errors: list[str] = []
    if category_slug in FACTUAL_ENTITY_CATEGORIES:
        if entity_validation["status"] != "verified":
            errors.append("entity_validation_not_verified")
        if not entity_validation["display_name"]:
            errors.append("entity_display_name_missing")
        if not entity_validation["evidence_urls"]:
            errors.append("entity_evidence_missing")
    elif entity_validation["status"] not in {"verified", "manual_review_required", "not_applicable"}:
        errors.append("entity_validation_status_invalid")
    return errors


def _validate_codex_write_package(
    payload: dict[str, Any],
    *,
    public_base_url: str = "",
    used_urls: set[str] | None = None,
    used_asset_keys: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    for key in ("remote_post_id", "slug", "original_slug", "target_slug", "category_slug", "title", "excerpt", "meta_description"):
        if not _normalize_space(payload.get(key)):
            errors.append(f"missing:{key}")
    category_slug = _normalize_space(payload.get("category_slug"))
    is_mysteria = _is_mysteria_category_slug(category_slug)
    title = _normalize_space(payload.get("title"))
    content_body = _canonical_content_body(payload)
    if not _normalize_space(content_body):
        errors.append("missing:content_body")
    cover_image = _normalize_image_field(payload.get("cover_image"), fallback_alt=title, public_base_url=public_base_url)
    inline_image = _normalize_image_field(payload.get("inline_image"), fallback_alt=title, public_base_url=public_base_url)
    payload["cover_image"] = cover_image
    payload["inline_image"] = inline_image
    image_uniqueness = _normalize_image_uniqueness(payload)
    backup_resolution = _normalize_backup_image_resolution(payload)
    plain_length = _body_char_length(content_body)
    max_length = 4500 if category_slug == "나스닥의-흐름" else 4000
    if plain_length < 3000 or plain_length > max_length:
        errors.append(f"body_length:{plain_length}")
    if not _matches_live_html_contract(content_body):
        errors.append("content_body_not_live_html_contract")
    if not validate_no_adsense_tokens_in_body(content_body):
        errors.append("adsense_body_token_present")
    headings = _extract_headings(content_body)
    if not headings or headings[-1] != "마무리 기록":
        errors.append("closing_record_missing")
    closing_record_block = _extract_closing_record_block(content_body)
    closing_record_paragraph = _extract_closing_record_paragraph(content_body)
    if not closing_record_block:
        errors.append("closing_record_block_missing")
    else:
        if len(re.findall(r"(?is)<p>.*?</p>", closing_record_block)) != 1:
            errors.append("closing_record_block_invalid")
        normalized_block = closing_record_block.casefold()
        if "text-align:center" in normalized_block or "margin:0 auto" in normalized_block or "box-shadow:" in normalized_block.replace("box-shadow:none", ""):
            errors.append("closing_record_block_style_invalid")
    if _count_sentences(closing_record_paragraph) != 2:
        errors.append("closing_record_style_invalid")
    faq_heading_count = _inline_faq_heading_count(content_body)
    if faq_heading_count != 1:
        errors.append("faq_inline_missing")
    if is_mysteria:
        if _inline_image_count(content_body) != 0:
            errors.append("inline_image_count_invalid")
        if _body_h1_count(content_body) != 0:
            errors.append("body_h1_invalid")
        if _h2_count(content_body) not in {4, 5}:
            errors.append("body_h2_count_invalid")
        if not _normalize_space(payload.get("article_pattern_id")):
            errors.append("article_pattern_id_missing")
        if not payload.get("article_pattern_version"):
            errors.append("article_pattern_version_missing")
    elif _inline_image_count(content_body) != 1:
        errors.append("inline_image_count_invalid")
    if not _normalize_space(cover_image.get("url")):
        errors.append("cover_image_missing")
    if not is_mysteria and not _normalize_space(inline_image.get("url")):
        errors.append("inline_image_missing")
    resolved_cover_url = _resolve_reachable_asset_url(cover_image.get("url"), public_base_url=public_base_url)
    resolved_inline_url = _resolve_reachable_asset_url(inline_image.get("url"), public_base_url=public_base_url)
    if _normalize_space(cover_image.get("url")) and not resolved_cover_url:
        errors.append("cover_image_unreachable")
    if not is_mysteria and _normalize_space(inline_image.get("url")) and not resolved_inline_url:
        errors.append("inline_image_unreachable")
    if resolved_cover_url:
        cover_image["url"] = resolved_cover_url
        cover_image["asset_key"] = _normalize_space(cover_image.get("asset_key")) or _asset_key_from_url(resolved_cover_url, public_base_url=public_base_url)
    if resolved_inline_url:
        inline_image["url"] = resolved_inline_url
        inline_image["asset_key"] = _normalize_space(inline_image.get("asset_key")) or _asset_key_from_url(resolved_inline_url, public_base_url=public_base_url)
    if _normalize_space(cover_image.get("url")) and not _is_cloudflare_media_asset(
        cover_image.get("url"),
        asset_key=cover_image.get("asset_key", ""),
        public_base_url=public_base_url,
    ):
        errors.append("invalid_image_prefix")
    if not is_mysteria and _normalize_space(inline_image.get("url")) and not _is_cloudflare_media_asset(
        inline_image.get("url"),
        asset_key=inline_image.get("asset_key", ""),
        public_base_url=public_base_url,
    ):
        errors.append("invalid_image_prefix")
    if not is_mysteria and _normalize_space(cover_image.get("url")) and _normalize_space(inline_image.get("url")):
        if not _images_are_distinct(
            cover_image.get("url", ""),
            cover_image.get("asset_key", ""),
            inline_image.get("url", ""),
            inline_image.get("asset_key", ""),
        ):
            errors.append("duplicate_image_within_post")
    image_uniqueness["cover_hash_or_key"] = _normalize_space(image_uniqueness.get("cover_hash_or_key") or cover_image.get("asset_key") or cover_image.get("url"))
    image_uniqueness["inline_hash_or_key"] = _normalize_space(image_uniqueness.get("inline_hash_or_key") or inline_image.get("asset_key") or inline_image.get("url"))
    image_uniqueness["is_distinct_within_post"] = True if is_mysteria else _images_are_distinct(
        cover_image.get("url", ""),
        cover_image.get("asset_key", ""),
        inline_image.get("url", ""),
        inline_image.get("asset_key", ""),
    )
    if not image_uniqueness["is_distinct_within_post"]:
        errors.append("duplicate_image_within_post")
    if used_urls is not None or used_asset_keys is not None:
        normalized_used_urls = used_urls or set()
        normalized_used_asset_keys = used_asset_keys or set()
        if _normalize_space(cover_image.get("url")) in normalized_used_urls or (
            _normalize_space(cover_image.get("asset_key")) and _normalize_space(cover_image.get("asset_key")) in normalized_used_asset_keys
        ):
            errors.append("duplicate_image_across_blog")
        if _normalize_space(inline_image.get("url")) in normalized_used_urls or (
            _normalize_space(inline_image.get("asset_key")) and _normalize_space(inline_image.get("asset_key")) in normalized_used_asset_keys
        ):
            errors.append("duplicate_image_across_blog")
        image_uniqueness["is_distinct_across_blog"] = "duplicate_image_across_blog" not in errors
    if backup_resolution["status"] == "manual_review_required":
        errors.append("backup_image_unresolved")
    for field_name in ("cover_image", "inline_image"):
        image_field = payload.get(field_name) if isinstance(payload.get(field_name), dict) else {}
        source_value = _normalize_space(image_field.get("source"))
        if source_value in {"local_backup_file", "backup_json_url", "generated_collage"}:
            if not _normalize_space(image_field.get("url")) or not _normalize_space(image_field.get("asset_key")):
                errors.append("r2_upload_missing")
    for token in _contains_banned_token(
        payload.get("title"),
        payload.get("excerpt"),
        payload.get("meta_description"),
        content_body,
        payload.get("target_slug"),
    ):
        errors.append(f"banned_token:{token}")
    errors.extend(
        _validate_daily_memo_topic_fit(
            payload,
            content_body=content_body,
            headings=headings,
        ),
    )
    errors.extend(_validate_entity_validation(payload))
    return errors


def _build_publish_payload(payload: dict[str, Any], *, category_meta: dict[str, str]) -> dict[str, Any]:
    title = _normalize_space(payload.get("title"))
    excerpt = _normalize_space(payload.get("excerpt"))
    meta_description = _normalize_space(payload.get("meta_description"))
    seo_title = _normalize_space(payload.get("seo_title") or title)
    category_slug_value = _normalize_space(payload.get("category_slug"))
    body = _canonical_content_body(payload)
    cover_image = payload.get("cover_image") if isinstance(payload.get("cover_image"), dict) else {}
    update_payload: dict[str, Any] = {
        "title": title,
        "content": body,
        "excerpt": excerpt,
        "seoTitle": seo_title,
        "seoDescription": meta_description,
        "tagNames": _normalize_tag_names(payload.get("tag_names") if isinstance(payload.get("tag_names"), list) else [], category_name=_normalize_space(category_meta.get("name")), title=title),
        "categoryId": _normalize_space(category_meta.get("id")),
        "status": "published",
    }
    cover_url = _normalize_space(cover_image.get("url"))
    cover_alt = _normalize_space(cover_image.get("alt") or meta_description or title)
    if cover_url:
        update_payload["coverImage"] = cover_url
        update_payload["coverAlt"] = cover_alt
    render_metadata = payload.get("render_metadata")
    if isinstance(render_metadata, dict) and render_metadata:
        update_payload["metadata"] = render_metadata
    target_slug = _normalize_space(payload.get("target_slug"))
    if target_slug:
        update_payload["slug"] = target_slug
    return update_payload


def _slug_matches_response(updated_post: dict[str, Any], target_slug: str) -> bool:
    normalized_target = _normalize_space(target_slug)
    if not normalized_target:
        return True
    response_slug = _normalize_space(updated_post.get("slug"))
    if response_slug and response_slug == normalized_target:
        return True
    response_url_slug = _extract_slug_from_url(updated_post.get("publicUrl") or updated_post.get("url"))
    return bool(response_url_slug and response_url_slug == normalized_target)


def _update_existing_post(db: Session, *, remote_post_id: str, update_payload: dict[str, Any]) -> dict[str, Any]:
    response = _integration_request(db, method="PUT", path=f"/api/integrations/posts/{remote_post_id}", json_payload=update_payload, timeout=120.0)
    updated_post = _integration_data_or_raise(response)
    if not isinstance(updated_post, dict):
        raise ValueError(f"Cloudflare update payload invalid for {remote_post_id}")
    return updated_post


def _delete_post_best_effort(db: Session, *, remote_post_id: str) -> dict[str, Any]:
    try:
        response = _integration_request(db, method="DELETE", path=f"/api/integrations/posts/{remote_post_id}", timeout=60.0)
        try:
            data = _integration_data_or_raise(response)
        except Exception:
            data = {}
        return {"deleted": True, "response": data if isinstance(data, dict) else {}}
    except Exception as exc:
        return {"deleted": False, "error": str(exc)}

def _publish_with_slug_strategy(db: Session, *, payload: dict[str, Any], update_payload: dict[str, Any]) -> dict[str, Any]:
    remote_post_id = _normalize_space(payload.get("remote_post_id"))
    original_slug = _normalize_space(payload.get("original_slug") or payload.get("slug"))
    target_slug = _normalize_space(payload.get("target_slug") or original_slug)
    old_url = _normalize_space(payload.get("published_url"))
    category_slug = _normalize_space(payload.get("category_slug"))
    if not target_slug or target_slug == original_slug:
        updated_post = _update_existing_post(db, remote_post_id=remote_post_id, update_payload=update_payload)
        return {"publish_mode": "put_existing", "remote_post_id": remote_post_id, "original_slug": original_slug, "target_slug": target_slug or original_slug, "old_url": old_url, "new_url": _normalize_space(updated_post.get("publicUrl") or old_url), "response": updated_post}
    updated_post = _update_existing_post(db, remote_post_id=remote_post_id, update_payload=update_payload)
    if _slug_matches_response(updated_post, target_slug):
        return {"publish_mode": "put_with_slug", "remote_post_id": remote_post_id, "original_slug": original_slug, "target_slug": target_slug, "old_url": old_url, "new_url": _normalize_space(updated_post.get("publicUrl") or old_url), "response": updated_post}
    create_payload = dict(update_payload)
    create_payload.pop("categoryId", None)
    if category_slug:
        create_payload["categorySlug"] = category_slug
    create_response = _integration_request(db, method="POST", path="/api/integrations/posts", json_payload=create_payload, timeout=120.0)
    created_post = _integration_data_or_raise(create_response)
    if not isinstance(created_post, dict):
        raise ValueError("Cloudflare create payload invalid during slug fallback")
    delete_result = _delete_post_best_effort(db, remote_post_id=remote_post_id)
    return {"publish_mode": "create_delete_fallback", "remote_post_id": _normalize_space(created_post.get("id") or remote_post_id), "original_slug": original_slug, "target_slug": target_slug, "old_url": old_url, "new_url": _normalize_space(created_post.get("publicUrl") or created_post.get("url")), "response": created_post, "delete_result": delete_result}


def publish_codex_write_packages(db: Session, *, category_slugs: Sequence[str] | None = None, slug: str | None = None, path: Path | None = None, limit: int | None = None, dry_run: bool = False, sync_after: bool = True, base_dir: Path | None = None) -> dict[str, Any]:
    root = get_codex_write_root(base_dir=base_dir)
    package_files = _package_files_for_publish(base_dir=root, category_slugs=category_slugs, slug=slug, path=path, limit=limit)
    settings_map = get_settings_map(db)
    account_id, bucket, access_key_id, secret_access_key, public_base_url, _ = _resolve_cloudflare_r2_configuration(settings_map)
    r2_listing_context = None
    if account_id and bucket and access_key_id and secret_access_key:
        r2_listing_context = {
            "account_id": account_id,
            "bucket": bucket,
            "access_key_id": access_key_id,
            "secret_access_key": secret_access_key,
        }
    r2_unused_cache: dict[str, list[dict[str, Any]]] = {}
    repo_root = _repo_root()
    backup_index = _build_backup_json_index(repo_root)
    local_index = _build_local_backup_image_index(repo_root)
    live_inventory = _collect_live_image_inventory(db, public_base_url=public_base_url, backup_index=backup_index)
    batch_used_urls = set(live_inventory["urls"])
    batch_used_asset_keys = set(live_inventory["asset_keys"])
    categories = [item for item in list_cloudflare_categories(db) if bool(item.get("isLeaf"))]
    categories_by_slug = {
        _normalize_space(item.get("slug")): {"id": _normalize_space(item.get("id")), "name": _normalize_space(item.get("name"))}
        for item in categories if _normalize_space(item.get("slug")) and _normalize_space(item.get("id"))
    }
    items: list[dict[str, Any]] = []
    updated_count = 0
    failed_count = 0
    skipped_count = 0
    touched = False
    daily_signatures: list[dict[str, Any]] = []
    for package_path in package_files:
        payload = _load_json(package_path)
        remote_post_id = _normalize_space(payload.get("remote_post_id"))
        original_slug = _normalize_space(payload.get("original_slug") or payload.get("slug"))
        target_slug = _normalize_space(payload.get("target_slug") or original_slug)
        category_slug_value = _normalize_space(payload.get("category_slug"))
        category_meta = categories_by_slug.get(category_slug_value)
        payload["slug"] = _normalize_space(payload.get("slug") or original_slug)
        current_urls, current_asset_keys = _disallowed_source_images(payload, public_base_url=public_base_url)
        working_used_urls = {item for item in batch_used_urls if item not in current_urls}
        working_used_asset_keys = {item for item in batch_used_asset_keys if item not in current_asset_keys}
        _resolve_payload_images(
            db,
            payload=payload,
            public_base_url=public_base_url,
            used_urls=working_used_urls,
            used_asset_keys=working_used_asset_keys,
            backup_index=backup_index,
            local_index=local_index,
            r2_listing_context=r2_listing_context,
            r2_unused_cache=r2_unused_cache,
        )
        errors = _validate_codex_write_package(
            payload,
            public_base_url=public_base_url,
            used_urls=working_used_urls,
            used_asset_keys=working_used_asset_keys,
        )
        if category_meta is None:
            errors.append(f"unknown_category:{category_slug_value}")
        if not errors and category_slug_value == "일상과-메모":
            similarity_signature = _build_daily_similarity_signature(payload, content_body=str(payload.get("content_body") or ""))
            similarity_error = _daily_similarity_error(similarity_signature, daily_signatures)
            if similarity_error:
                errors.append(similarity_error)
            else:
                daily_signatures.append(similarity_signature)
        publish_state = payload.get("publish_state") if isinstance(payload.get("publish_state"), dict) else {}
        payload["publish_state"] = publish_state
        if errors:
            failed_count += 1
            publish_state["status"] = CODEX_WRITE_STATUS_FAILED
            publish_state["last_error"] = ";".join(errors)
            publish_state["publish_mode"] = None
            _write_json(package_path, payload)
            items.append({"status": CODEX_WRITE_STATUS_FAILED, "path": str(package_path), "remote_post_id": remote_post_id, "original_slug": original_slug, "target_slug": target_slug, "old_url": _normalize_space(payload.get("published_url")), "new_url": "", "publish_mode": None, "validation_errors": errors, "category_slug": category_slug_value})
            continue
        update_payload = _build_publish_payload(payload, category_meta=category_meta or {"id": "", "name": category_slug_value})
        if dry_run:
            skipped_count += 1
            publish_state["status"] = CODEX_WRITE_STATUS_READY
            publish_state["last_error"] = None
            publish_state["publish_mode"] = "dry_run"
            _write_json(package_path, payload)
            _reserve_payload_images(payload, used_urls=batch_used_urls, used_asset_keys=batch_used_asset_keys)
            items.append({"status": CODEX_WRITE_STATUS_READY, "path": str(package_path), "remote_post_id": remote_post_id, "original_slug": original_slug, "target_slug": target_slug, "old_url": _normalize_space(payload.get("published_url")), "new_url": _normalize_space(payload.get("published_url")), "publish_mode": "dry_run", "validation_errors": [], "category_slug": category_slug_value})
            continue
        publish_result = _publish_with_slug_strategy(db, payload=payload, update_payload=update_payload)
        touched = True
        updated_count += 1
        publish_state["status"] = CODEX_WRITE_STATUS_PUBLISHED
        publish_state["publish_mode"] = publish_result["publish_mode"]
        publish_state["last_published_at"] = _utc_now_iso()
        publish_state["last_error"] = None
        payload["published_url"] = _normalize_space(publish_result["new_url"])
        payload["remote_post_id"] = _normalize_space(publish_result["remote_post_id"])
        payload["target_slug"] = target_slug
        _write_json(package_path, payload)
        _reserve_payload_images(payload, used_urls=batch_used_urls, used_asset_keys=batch_used_asset_keys)
        items.append({"status": CODEX_WRITE_STATUS_PUBLISHED, "path": str(package_path), "remote_post_id": payload["remote_post_id"], "original_slug": original_slug, "target_slug": target_slug, "old_url": _normalize_space(publish_result["old_url"]), "new_url": payload["published_url"], "publish_mode": publish_result["publish_mode"], "validation_errors": [], "category_slug": category_slug_value})
    sync_result: dict[str, Any] | None = None
    if touched and sync_after and not dry_run:
        try:
            sync_result = sync_cloudflare_posts(db, include_non_published=True)
        except Exception as exc:
            sync_result = {"status": "failed", "error": str(exc)}
    report_path = _report_path(root, "publish")
    _write_json(report_path, {"generated_at": _utc_now_iso(), "dry_run": bool(dry_run), "category_slugs": list(category_slugs or []), "slug": _normalize_space(slug), "updated_count": updated_count, "failed_count": failed_count, "skipped_count": skipped_count, "sync_result": sync_result, "items": items})
    return {"status": "ok" if failed_count == 0 else ("partial" if updated_count > 0 else "failed"), "root": str(root), "updated_count": updated_count, "failed_count": failed_count, "skipped_count": skipped_count, "report_path": str(report_path), "sync_result": sync_result, "items": items}

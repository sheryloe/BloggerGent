from __future__ import annotations

from collections.abc import Mapping, Sequence
import base64
import hashlib
import hmac
import io
import mimetypes
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import httpx
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.content.travel_blog_policy import (
    build_travel_local_backup_relative_dir,
    build_travel_local_publish_relative_dir,
    is_valid_travel_canonical_object_key,
    parse_travel_canonical_object_key,
)
from app.services.providers.base import ProviderRuntimeError
from app.services.integrations.settings_service import get_settings_map

RESPONSIVE_HERO_WIDTHS = (640, 960, 1280, 1600)
RESPONSIVE_HERO_SIZES = "(max-width: 860px) 100vw, 860px"

CLOUDINARY_HERO_TRANSFORMATION = "f_auto,q_auto,w_1600,c_limit"
CLOUDINARY_CARD_TRANSFORMATION = "f_auto,q_auto,w_640,c_fill,g_auto"

CLOUDFLARE_HERO_OPTIONS: tuple[tuple[str, str], ...] = (
    ("format", "auto"),
    ("fit", "scale-down"),
    ("width", "1600"),
    ("quality", "85"),
)
CLOUDFLARE_CARD_OPTIONS: tuple[tuple[str, str], ...] = (
    ("format", "auto"),
    ("fit", "cover"),
    ("width", "640"),
    ("height", "360"),
    ("quality", "75"),
)
CLOUDFLARE_THUMB_OPTIONS: tuple[tuple[str, str], ...] = (
    ("format", "auto"),
    ("fit", "cover"),
    ("width", "160"),
    ("height", "160"),
    ("quality", "70"),
)
TRUTHY_VALUES = {"1", "true", "yes", "on", "enabled"}
MYSTERY_R2_KEY_PREFIX = "assets/the-midnight-archives/"
MYSTERY_MAIN_SLUG_WEBP_RE = re.compile(
    r"^assets/the-midnight-archives/[a-z0-9-]+/\d{4}/\d{2}/([a-z0-9-]+)/([a-z0-9-]+)\.webp$",
    re.IGNORECASE,
)
FORBIDDEN_R2_TOKENS = (
    "assets/assets/",
    "media/posts",
    "media/blogger",
    "assets/media/google-blogger/",
)


def ensure_storage_dirs() -> None:
    settings.storage_images_dir.mkdir(parents=True, exist_ok=True)
    settings.storage_html_dir.mkdir(parents=True, exist_ok=True)


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _join_public_url(base_url: str, path: str) -> str:
    return f"{_normalize_base_url(base_url)}/{path.lstrip('/')}"


def build_storage_public_url(relative: Path, base_url: str | None = None) -> str:
    resolved_base_url = _normalize_base_url(base_url or settings.public_api_base_url)
    return f"{resolved_base_url}/storage/{relative.as_posix()}"


def _looks_private_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return True
    if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return True
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    if host.startswith("172."):
        return True
    return False


def is_private_asset_url(url: str) -> bool:
    return _looks_private_url(url)


def _resolve_local_public_base_url(values: dict[str, str]) -> str:
    configured = (values.get("public_asset_base_url") or "").strip()
    if configured:
        return _normalize_base_url(configured)
    return _normalize_base_url(settings.public_api_base_url)


def _is_enabled_setting(raw_value: object, *, default: bool = False) -> bool:
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    normalized = str(raw_value).strip().lower()
    if not normalized:
        return default
    return normalized in TRUTHY_VALUES


def _is_mystery_object_key(object_key: str | None) -> bool:
    normalized = str(object_key or "").strip().lstrip("/")
    return normalized.lower().startswith(MYSTERY_R2_KEY_PREFIX)


def _is_valid_mystery_slug_webp_key(object_key: str) -> bool:
    normalized = str(object_key or "").strip().lstrip("/")
    match = MYSTERY_MAIN_SLUG_WEBP_RE.fullmatch(normalized)
    if match is None:
        return False
    return match.group(1).strip().lower() == match.group(2).strip().lower()


def _enforce_strict_storage_root(*, destination_path: str, values: dict[str, str], mystery_only: bool) -> None:
    if not _is_enabled_setting(values.get("strict_storage_root"), default=True):
        return
    if not mystery_only:
        return
    expected_root = str(values.get("mystery_storage_root_windows") or r"D:\Donggri_Runtime\BloggerGent\storage").strip()
    normalized_expected = expected_root.replace("\\", "/").rstrip("/").lower()
    normalized_destination = str(destination_path or "").replace("\\", "/").rstrip("/").lower()
    if not normalized_destination.startswith(normalized_expected):
        raise ProviderRuntimeError(
            provider="storage",
            status_code=422,
            message="Strict storage root violation for mystery image.",
            detail=f"expected_root={expected_root}, actual_path={destination_path}",
        )


def _enforce_strict_r2_schema(*, object_key: str, values: dict[str, str], mystery_only: bool) -> None:
    if not _is_enabled_setting(values.get("strict_r2_key_schema"), default=True):
        return
    normalized = str(object_key or "").strip().lstrip("/")
    lowered = normalized.lower()
    travel_key = parse_travel_canonical_object_key(normalized)
    if not lowered:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=422,
            message="Strict R2 key schema violation.",
            detail="Object key is empty.",
        )
    if mystery_only and not lowered.startswith(MYSTERY_R2_KEY_PREFIX):
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=422,
            message="Strict R2 key schema violation for mystery image.",
            detail=f"object_key={object_key}",
        )
    if mystery_only and not _is_valid_mystery_slug_webp_key(normalized):
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=422,
            message="Mystery R2 key must follow slug.webp contract.",
            detail=f"object_key={object_key}; expected=assets/the-midnight-archives/<category>/YYYY/MM/<slug>/<slug>.webp",
        )
    if travel_key is not None and not is_valid_travel_canonical_object_key(normalized):
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=422,
            message="Strict R2 key schema violation for travel image.",
            detail=f"object_key={object_key}",
        )
    if any(token in lowered for token in FORBIDDEN_R2_TOKENS):
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=422,
            message="Forbidden token detected in R2 object key.",
            detail=f"object_key={object_key}",
        )
    if not lowered.endswith(".webp"):
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=422,
            message="Strict R2 key schema requires .webp extension.",
            detail=f"object_key={object_key}",
        )


def _is_cloudflare_transform_enabled(values: Mapping[str, str]) -> bool:
    return _is_enabled_setting(values.get("cloudflare_cdn_transform_enabled"), default=False)


def _github_pages_base_url(values: dict[str, str]) -> str:
    configured = (values.get("github_pages_base_url") or "").strip()
    if configured:
        return _normalize_base_url(configured)

    owner = (values.get("github_pages_owner") or "").strip()
    repo = (values.get("github_pages_repo") or "").strip()
    if not owner or not repo:
        return ""
    if repo.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner}.github.io"
    return f"https://{owner}.github.io/{repo}"


def _build_github_pages_asset_path(values: dict[str, str], filename: str) -> str:
    root_dir = (values.get("github_pages_assets_dir") or "assets/images").strip().strip("/")
    now = datetime.now(timezone.utc)
    return f"{root_dir}/{now:%Y/%m/%d}/{filename}"


def _github_api_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _fetch_github_pages_source_path(owner: str, repo: str, token: str) -> str:
    response = httpx.get(
        f"https://api.github.com/repos/{owner}/{repo}/pages",
        headers=_github_api_headers(token),
        timeout=60.0,
    )
    if response.status_code == 404:
        return ""
    if not response.is_success:
        raise ProviderRuntimeError(
            provider="github_pages",
            status_code=response.status_code,
            message="Failed to read the GitHub Pages source configuration.",
            detail=response.text,
        )
    payload = response.json()
    return str((payload.get("source") or {}).get("path") or "").strip()


def _normalize_github_pages_repo_asset_path(asset_path: str, source_path: str) -> str:
    normalized_asset_path = asset_path.strip("/")
    normalized_source = source_path.strip().strip("/")
    if not normalized_source:
        return normalized_asset_path
    if normalized_asset_path.startswith(f"{normalized_source}/") or normalized_asset_path == normalized_source:
        return normalized_asset_path
    return f"{normalized_source}/{normalized_asset_path}"


def _normalize_github_pages_public_asset_path(repo_asset_path: str, source_path: str) -> str:
    normalized_repo_path = repo_asset_path.strip("/")
    normalized_source = source_path.strip().strip("/")
    if normalized_source and normalized_repo_path.startswith(f"{normalized_source}/"):
        return normalized_repo_path[len(normalized_source) + 1 :]
    if normalized_source and normalized_repo_path == normalized_source:
        return ""
    return normalized_repo_path


def _upload_to_github_pages(
    *,
    values: dict[str, str],
    filename: str,
    content: bytes,
) -> tuple[str, dict]:
    owner = (values.get("github_pages_owner") or "").strip()
    repo = (values.get("github_pages_repo") or "").strip()
    branch = (values.get("github_pages_branch") or "main").strip()
    token = (values.get("github_pages_token") or "").strip()
    base_url = _github_pages_base_url(values)

    if not owner or not repo or not token:
        raise ProviderRuntimeError(
            provider="github_pages",
            status_code=422,
            message="GitHub Pages delivery is missing required settings.",
            detail="Set github_pages_owner, github_pages_repo, and github_pages_token.",
        )
    if not base_url:
        raise ProviderRuntimeError(
            provider="github_pages",
            status_code=422,
            message="GitHub Pages base URL is missing.",
            detail="Set github_pages_base_url or configure owner/repo so the URL can be derived.",
        )

    source_path = _fetch_github_pages_source_path(owner, repo, token)
    public_asset_path = _build_github_pages_asset_path(values, filename)
    repo_asset_path = _normalize_github_pages_repo_asset_path(public_asset_path, source_path)
    normalized_public_path = _normalize_github_pages_public_asset_path(repo_asset_path, source_path)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{repo_asset_path}"
    headers = _github_api_headers(token)

    existing_sha = None
    get_response = httpx.get(api_url, headers=headers, params={"ref": branch}, timeout=60.0)
    if get_response.status_code == 200:
        existing_sha = get_response.json().get("sha")
    elif get_response.status_code != 404:
        raise ProviderRuntimeError(
            provider="github_pages",
            status_code=get_response.status_code,
            message="Failed to check the existing GitHub Pages asset.",
            detail=get_response.text,
        )

    payload = {
        "message": f"bloggent: upload asset {repo_asset_path}",
        "content": base64.b64encode(content).decode("ascii"),
        "branch": branch,
    }
    if existing_sha:
        payload["sha"] = existing_sha

    response = httpx.put(api_url, headers=headers, json=payload, timeout=120.0)
    if not response.is_success:
        detail = response.text
        try:
            detail = response.json().get("message", detail)
        except ValueError:
            pass
        raise ProviderRuntimeError(
            provider="github_pages",
            status_code=response.status_code,
            message="GitHub Pages upload failed.",
            detail=detail,
        )

    response_payload = response.json()
    public_url = f"{base_url}/{normalized_public_path}"
    return public_url, {
        "asset_path": normalized_public_path,
        "repo_asset_path": repo_asset_path,
        "pages_source_path": source_path or "/",
        "branch": branch,
        "response": response_payload,
    }


def _cloudinary_signature(params: dict[str, str], api_secret: str) -> str:
    serialized = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.sha1(f"{serialized}{api_secret}".encode("utf-8")).hexdigest()


def _resolve_cloudinary_configuration(values: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        (values.get("cloudinary_cloud_name") or "").strip(),
        (values.get("cloudinary_api_key") or "").strip(),
        (values.get("cloudinary_api_secret") or "").strip(),
        (values.get("cloudinary_folder") or "bloggent").strip(),
    )


def _cloudinary_public_id_for_file(*, filename: str, folder: str) -> str:
    public_id = Path(filename).stem
    normalized_folder = folder.strip().strip("/")
    if not normalized_folder:
        return public_id
    return f"{normalized_folder}/{public_id}"


def _cloudinary_extract_cloud_name(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host.endswith("res.cloudinary.com"):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return ""
    return parts[0]


def _cloudinary_version_from_secure_url(url: str) -> str:
    if "/upload/" not in url:
        return ""
    _, suffix = url.split("/upload/", 1)
    suffix_parts = [part for part in suffix.split("/") if part]
    if not suffix_parts:
        return ""
    candidate = suffix_parts[0]
    if candidate.startswith("v") and len(candidate) > 1:
        return candidate
    return ""


def _insert_cloudinary_transformation(url: str, transformation: str) -> str:
    if not url or not transformation or "/upload/" not in url:
        return url
    prefix, suffix = url.split("/upload/", 1)
    return f"{prefix}/upload/{transformation}/{suffix}"


def _cloudinary_secure_url_from_payload(payload: Mapping[str, object] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    return str(payload.get("secure_url") or payload.get("url") or "").strip()


def normalize_cloudinary_upload_result(
    payload: Mapping[str, object] | None,
    *,
    cloud_name: str = "",
) -> dict:
    secure_url_original = _cloudinary_secure_url_from_payload(payload)
    resolved_cloud_name = cloud_name.strip() or _cloudinary_extract_cloud_name(secure_url_original)
    return {
        "provider": "cloudinary",
        "cloudinary": {
            "cloud_name": resolved_cloud_name,
            "public_id": str(payload.get("public_id") or "").strip() if isinstance(payload, Mapping) else "",
            "resource_type": str(payload.get("resource_type") or "image").strip() if isinstance(payload, Mapping) else "image",
            "secure_url_original": secure_url_original,
        },
    }


def build_cloudinary_variant_url(
    secure_url: str,
    *,
    transformation: str,
    cloud_name: str = "",
    public_id: str = "",
    resource_type: str = "image",
    version: str = "",
) -> str:
    if secure_url:
        return _insert_cloudinary_transformation(secure_url, transformation)
    if not cloud_name or not public_id or not transformation:
        return secure_url
    version_segment = f"{version.strip().strip('/')}/" if version else ""
    return f"https://res.cloudinary.com/{cloud_name}/{resource_type}/upload/{transformation}/{version_segment}{public_id}"


def build_cloudinary_srcset_urls(
    *,
    secure_url: str,
    cloud_name: str,
    public_id: str,
    resource_type: str,
    version: str = "",
    widths: tuple[int, ...] = RESPONSIVE_HERO_WIDTHS,
) -> dict[str, str]:
    return {
        str(item_width): build_cloudinary_variant_url(
            secure_url,
            transformation=f"f_auto,q_auto,w_{item_width},c_limit",
            cloud_name=cloud_name,
            public_id=public_id,
            resource_type=resource_type,
            version=version,
        )
        for item_width in widths
    }


def build_cloudinary_delivery_metadata(
    payload: Mapping[str, object] | None,
    *,
    cloud_name: str = "",
) -> dict:
    delivery = normalize_cloudinary_upload_result(payload, cloud_name=cloud_name)
    cloudinary_meta = delivery["cloudinary"]
    secure_url_original = str(cloudinary_meta.get("secure_url_original") or "").strip()
    public_id = str(cloudinary_meta.get("public_id") or "").strip()
    resolved_cloud_name = str(cloudinary_meta.get("cloud_name") or "").strip()
    resource_type = str(cloudinary_meta.get("resource_type") or "image").strip() or "image"
    version = _cloudinary_version_from_secure_url(secure_url_original)

    delivery["presets"] = {
        "hero": build_cloudinary_variant_url(
            secure_url_original,
            transformation=CLOUDINARY_HERO_TRANSFORMATION,
            cloud_name=resolved_cloud_name,
            public_id=public_id,
            resource_type=resource_type,
            version=version,
        ),
        "card": build_cloudinary_variant_url(
            secure_url_original,
            transformation=CLOUDINARY_CARD_TRANSFORMATION,
            cloud_name=resolved_cloud_name,
            public_id=public_id,
            resource_type=resource_type,
            version=version,
        ),
        "thumb": build_cloudinary_variant_url(
            secure_url_original,
            transformation="f_auto,q_auto,w_160,h_160,c_fill,g_auto",
            cloud_name=resolved_cloud_name,
            public_id=public_id,
            resource_type=resource_type,
            version=version,
        ),
    }
    delivery["srcset"] = {
        "hero": build_cloudinary_srcset_urls(
            secure_url=secure_url_original,
            cloud_name=resolved_cloud_name,
            public_id=public_id,
            resource_type=resource_type,
            version=version,
        )
    }
    return delivery


def build_cloudinary_preview_url(*, cloud_name: str, folder: str, file_path: str) -> str:
    public_id = _cloudinary_public_id_for_file(filename=Path(file_path).name, folder=folder)
    return build_cloudinary_variant_url(
        "",
        transformation=CLOUDINARY_HERO_TRANSFORMATION,
        cloud_name=cloud_name,
        public_id=public_id,
        resource_type="image",
        version="<version>",
    )


def delete_cloudinary_asset(
    db: Session,
    *,
    public_id: str,
    resource_type: str = "image",
) -> None:
    if not public_id.strip():
        return

    values = get_settings_map(db)
    cloud_name, api_key, api_secret, _ = _resolve_cloudinary_configuration(values)
    if not cloud_name or not api_key or not api_secret:
        return

    timestamp = str(int(time.time()))
    sign_params = {
        "invalidate": "true",
        "public_id": public_id,
        "timestamp": timestamp,
    }
    signature = _cloudinary_signature(sign_params, api_secret)
    response = httpx.post(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/{resource_type}/destroy",
        data={
            "api_key": api_key,
            "public_id": public_id,
            "invalidate": "true",
            "signature": signature,
            "timestamp": timestamp,
        },
        timeout=60.0,
    )
    if not response.is_success:
        detail = response.text
        try:
            payload = response.json()
            detail = payload.get("error", {}).get("message", detail)
        except ValueError:
            pass
        raise ProviderRuntimeError(
            provider="cloudinary",
            status_code=response.status_code,
            message="Cloudinary asset delete failed.",
            detail=detail,
        )


def _resolve_cloudflare_r2_configuration(
    values: dict[str, str],
    *,
    object_key: str | None = None,
) -> tuple[str, str, str, str, str, str]:
    normalized_object_key = str(object_key or "").strip().lstrip("/")
    mystery_object = _is_mystery_object_key(normalized_object_key)

    integration_base_url, _ = _resolve_cloudflare_integration_upload_configuration(values)
    if mystery_object:
        configured_public_base_url = _normalize_base_url((values.get("mystery_cloudflare_r2_public_base_url") or "").strip())
        resolved_public_base_url = configured_public_base_url
        if not resolved_public_base_url and integration_base_url:
            resolved_public_base_url = _join_public_url(integration_base_url, "/assets")
        return (
            (values.get("mystery_cloudflare_account_id") or "").strip(),
            (values.get("mystery_cloudflare_r2_bucket") or "").strip(),
            (values.get("mystery_cloudflare_r2_access_key_id") or "").strip(),
            (values.get("mystery_cloudflare_r2_secret_access_key") or "").strip(),
            resolved_public_base_url,
            (values.get("mystery_cloudflare_r2_prefix") or MYSTERY_R2_KEY_PREFIX.rstrip("/")).strip().strip("/"),
        )

    configured_public_base_url = _normalize_base_url((values.get("cloudflare_r2_public_base_url") or "").strip())
    resolved_public_base_url = configured_public_base_url
    if not resolved_public_base_url and integration_base_url:
        resolved_public_base_url = _join_public_url(integration_base_url, "/assets")
    return (
        (values.get("cloudflare_account_id") or "").strip(),
        (values.get("cloudflare_r2_bucket") or "").strip(),
        (values.get("cloudflare_r2_access_key_id") or "").strip(),
        (values.get("cloudflare_r2_secret_access_key") or "").strip(),
        resolved_public_base_url,
        (values.get("cloudflare_r2_prefix") or "assets").strip().strip("/"),
    )


def _resolve_cloudflare_integration_upload_configuration(values: dict[str, str]) -> tuple[str, str]:
    return (
        _normalize_base_url((values.get("cloudflare_blog_api_base_url") or "").strip()),
        (values.get("cloudflare_blog_m2m_token") or "").strip(),
    )


def _cloudflare_r2_object_key(*, filename: str, prefix: str) -> str:
    normalized_name = Path(filename).name
    normalized_prefix = prefix.strip().strip("/")
    if not normalized_prefix:
        return normalized_name
    return f"{normalized_prefix}/{normalized_name}"


def _normalize_cloudflare_object_key(*, public_key: str, key: str) -> str:
    normalized_key = unquote((key or "").strip()).lstrip("/")
    if not normalized_key:
        return ""

    normalized_prefix = (public_key or "").strip().strip("/")
    if not normalized_prefix:
        return normalized_key
    if normalized_key == normalized_prefix:
        return normalized_key
    if normalized_key.startswith(f"{normalized_prefix}/"):
        return normalized_key
    prefix_root = normalized_prefix.split("/", 1)[0].lower()
    key_root = normalized_key.split("/", 1)[0].lower()
    if prefix_root and key_root == prefix_root:
        return normalized_key
    return f"{normalized_prefix}/{normalized_key}"


def _strip_cdn_transform_prefix(path: str) -> str:
    candidate = (path or "").lstrip("/")
    lowered = candidate.lower()
    if lowered.startswith("cdn-cgi/image/"):
        parts = candidate.split("/", 3)
        if len(parts) >= 4:
            return "/".join(parts[3:])
        return ""

    if lowered.startswith("cdn-cgi/imagedelivery/"):
        parts = candidate.split("/", 3)
        if len(parts) >= 4:
            return "/".join(parts[3:])
        if len(parts) >= 3:
            return parts[-1]
        return ""

    return candidate


def normalize_r2_url_to_key(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    raw_path = (parsed.path or "").strip()
    if not raw_path:
        return ""
    normalized = unquote(raw_path)
    normalized = _strip_cdn_transform_prefix(normalized)
    normalized = normalized.strip("/")
    return normalized


def cloudflare_r2_object_exists(
    db: Session,
    *,
    public_key: str,
    key: str,
) -> bool:
    values = get_settings_map(db)
    object_key = _normalize_cloudflare_object_key(public_key=public_key, key=key)
    if not object_key:
        return False
    account_id, bucket, access_key_id, secret_access_key, _, _ = _resolve_cloudflare_r2_configuration(
        values,
        object_key=object_key,
    )
    if not account_id or not bucket or not access_key_id or not secret_access_key:
        return False

    headers = _build_r2_authorization_headers(
        method="HEAD",
        account_id=account_id,
        bucket=bucket,
        object_key=object_key,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        payload=b"",
    )
    response = httpx.head(
        _r2_endpoint_url(account_id=account_id, bucket=bucket, object_key=object_key),
        headers=headers,
        timeout=60.0,
    )
    if response.status_code == 404:
        return False
    if not response.is_success:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=response.status_code,
            message="Cloudflare R2 object existence check failed.",
            detail=response.text,
        )
    return True


def cloudflare_r2_object_size(
    db: Session,
    *,
    public_key: str,
    key: str,
) -> int | None:
    values = get_settings_map(db)
    object_key = _normalize_cloudflare_object_key(public_key=public_key, key=key)
    if not object_key:
        return None
    account_id, bucket, access_key_id, secret_access_key, _, _ = _resolve_cloudflare_r2_configuration(
        values,
        object_key=object_key,
    )
    if not account_id or not bucket or not access_key_id or not secret_access_key:
        return None

    headers = _build_r2_authorization_headers(
        method="HEAD",
        account_id=account_id,
        bucket=bucket,
        object_key=object_key,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        payload=b"",
    )
    response = httpx.head(
        _r2_endpoint_url(account_id=account_id, bucket=bucket, object_key=object_key),
        headers=headers,
        timeout=60.0,
    )
    if response.status_code == 404:
        return None
    if not response.is_success:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=response.status_code,
            message="Cloudflare R2 object size check failed.",
            detail=response.text,
        )
    length = response.headers.get("Content-Length") or response.headers.get("content-length") or ""
    try:
        return int(length)
    except (TypeError, ValueError):
        return None


def cloudflare_r2_download_binary(
    db: Session,
    *,
    public_key: str,
    key: str,
) -> bytes:
    values = get_settings_map(db)
    object_key = _normalize_cloudflare_object_key(public_key=public_key, key=key)
    if not object_key:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=422,
            message="Cloudflare R2 object key is missing.",
            detail="Pass a valid R2 object key.",
        )
    account_id, bucket, access_key_id, secret_access_key, _, _ = _resolve_cloudflare_r2_configuration(
        values,
        object_key=object_key,
    )
    if not account_id or not bucket or not access_key_id or not secret_access_key:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=422,
            message="Cloudflare R2 download requested without credentials.",
            detail="Set mystery or default R2 credentials for the requested object key.",
        )

    headers = _build_r2_authorization_headers(
        method="GET",
        account_id=account_id,
        bucket=bucket,
        object_key=object_key,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        payload=b"",
    )
    response = httpx.get(
        _r2_endpoint_url(account_id=account_id, bucket=bucket, object_key=object_key),
        headers=headers,
        timeout=120.0,
    )
    if not response.is_success:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=response.status_code,
            message="Cloudflare R2 object download failed.",
            detail=response.text,
        )
    return response.content


def _cloudflare_r2_original_url(*, public_base_url: str, object_key: str) -> str:
    return _join_public_url(public_base_url, object_key)


def _cloudflare_option_string(options: Sequence[tuple[str, str]]) -> str:
    return ",".join(f"{key}={value}" for key, value in options if key and value)


def build_cloudflare_variant_url(
    *,
    public_base_url: str,
    object_key: str,
    options: Sequence[tuple[str, str]],
) -> str:
    normalized_base_url = _normalize_base_url(public_base_url)
    parsed = urlparse(normalized_base_url)
    if not parsed.scheme or not parsed.netloc:
        return ""

    base_path = parsed.path.rstrip("/")
    object_path = f"{base_path}/{object_key.lstrip('/')}" if base_path else f"/{object_key.lstrip('/')}"
    return f"{parsed.scheme}://{parsed.netloc}/cdn-cgi/image/{_cloudflare_option_string(options)}{object_path}"


def _cloudflare_hero_options_for_width(width: int) -> tuple[tuple[str, str], ...]:
    return (
        ("format", "auto"),
        ("fit", "scale-down"),
        ("width", str(width)),
        ("quality", "85"),
    )


def build_cloudflare_srcset_urls(
    *,
    public_base_url: str,
    object_key: str,
    widths: tuple[int, ...] = RESPONSIVE_HERO_WIDTHS,
) -> dict[str, str]:
    return {
        str(item_width): build_cloudflare_variant_url(
            public_base_url=public_base_url,
            object_key=object_key,
            options=_cloudflare_hero_options_for_width(item_width),
        )
        for item_width in widths
    }


def build_cloudflare_r2_delivery_metadata(
    *,
    bucket: str,
    object_key: str,
    public_base_url: str,
    etag: str = "",
    transform_enabled: bool = True,
) -> dict:
    original_url = _cloudflare_r2_original_url(public_base_url=public_base_url, object_key=object_key)
    if transform_enabled:
        presets = {
            "hero": build_cloudflare_variant_url(
                public_base_url=public_base_url,
                object_key=object_key,
                options=CLOUDFLARE_HERO_OPTIONS,
            ),
            "card": build_cloudflare_variant_url(
                public_base_url=public_base_url,
                object_key=object_key,
                options=CLOUDFLARE_CARD_OPTIONS,
            ),
            "thumb": build_cloudflare_variant_url(
                public_base_url=public_base_url,
                object_key=object_key,
                options=CLOUDFLARE_THUMB_OPTIONS,
            ),
        }
        srcset = {
            "hero": build_cloudflare_srcset_urls(
                public_base_url=public_base_url,
                object_key=object_key,
            )
        }
    else:
        presets = {
            "hero": original_url,
            "card": original_url,
            "thumb": original_url,
        }
        srcset = {"hero": {}}

    return {
        "provider": "cloudflare_r2",
        "cloudflare": {
            "bucket": bucket,
            "object_key": object_key,
            "public_base_url": public_base_url,
            "original_url": original_url,
            "etag": etag,
            "transform_enabled": transform_enabled,
        },
        "presets": presets,
        "srcset": srcset,
    }


def build_cloudflare_r2_preview_url(*, public_base_url: str, prefix: str, file_path: str) -> str:
    object_key = _cloudflare_r2_object_key(filename=Path(file_path).name, prefix=prefix)
    return build_cloudflare_variant_url(
        public_base_url=public_base_url,
        object_key=object_key,
        options=CLOUDFLARE_HERO_OPTIONS,
    )


def _r2_sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _r2_signing_key(secret_access_key: str, *, date_stamp: str, region: str = "auto", service: str = "s3") -> bytes:
    k_date = _r2_sign(f"AWS4{secret_access_key}".encode("utf-8"), date_stamp)
    k_region = _r2_sign(k_date, region)
    k_service = _r2_sign(k_region, service)
    return _r2_sign(k_service, "aws4_request")


def _quote_r2_path(path: str) -> str:
    quoted = quote(path.lstrip("/"), safe="/-_.~")
    return f"/{quoted}" if quoted else "/"


def _r2_endpoint_url(*, account_id: str, bucket: str, object_key: str) -> str:
    host = f"{account_id}.r2.cloudflarestorage.com"
    path = f"{bucket}/{object_key.lstrip('/')}" if object_key else bucket
    return f"https://{host}{_quote_r2_path(path)}"


def _build_r2_authorization_headers(
    *,
    method: str,
    account_id: str,
    bucket: str,
    object_key: str,
    access_key_id: str,
    secret_access_key: str,
    payload: bytes,
    extra_headers: Mapping[str, str] | None = None,
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    host = f"{account_id}.r2.cloudflarestorage.com"
    canonical_uri = _quote_r2_path(f"{bucket}/{object_key.lstrip('/')}" if object_key else bucket)
    payload_hash = hashlib.sha256(payload).hexdigest()

    normalized_headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    for key, value in (extra_headers or {}).items():
        normalized_headers[key.lower()] = " ".join(str(value).strip().split())

    signed_header_names = sorted(normalized_headers)
    canonical_headers = "".join(f"{name}:{normalized_headers[name]}\n" for name in signed_header_names)
    signed_headers = ";".join(signed_header_names)
    canonical_request = "\n".join(
        [
            method.upper(),
            canonical_uri,
            "",
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
    signing_key = _r2_signing_key(secret_access_key, date_stamp=date_stamp)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {key: value for key, value in (extra_headers or {}).items()}
    headers["Host"] = host
    headers["x-amz-content-sha256"] = payload_hash
    headers["x-amz-date"] = amz_date
    headers["Authorization"] = authorization
    return headers


def _extract_cloudflare_integration_asset(payload: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if not isinstance(payload, Mapping):
        return None

    candidates = [payload.get("asset"), payload.get("item")]
    data_payload = payload.get("data")
    if isinstance(data_payload, Mapping):
        candidates.extend([data_payload.get("asset"), data_payload])

    for candidate in candidates:
        if isinstance(candidate, Mapping):
            return candidate
    return None


def _cloudflare_public_base_from_url(public_url: str, object_key: str) -> str:
    normalized_url = str(public_url or "").strip()
    normalized_key = object_key.strip().lstrip("/")
    if not normalized_url or not normalized_key:
        return ""

    parsed = urlparse(normalized_url)
    if not parsed.scheme or not parsed.netloc:
        return ""

    object_suffix = f"/{normalized_key}"
    if parsed.path.endswith(object_suffix):
        base_path = parsed.path[: -len(object_suffix)]
        return f"{parsed.scheme}://{parsed.netloc}{base_path}".rstrip("/")
    return ""


def _upload_to_cloudflare_r2(
    *,
    values: dict[str, str],
    object_key: str | None = None,
    filename: str,
    content: bytes,
) -> tuple[str, dict]:
    normalized_requested_key = str(object_key or "").strip().lstrip("/")
    account_id, bucket, access_key_id, secret_access_key, public_base_url, prefix = _resolve_cloudflare_r2_configuration(
        values,
        object_key=normalized_requested_key,
    )
    integration_base_url, integration_token = _resolve_cloudflare_integration_upload_configuration(values)
    object_key = (
        _normalize_cloudflare_object_key(public_key=prefix, key=normalized_requested_key)
        if normalized_requested_key
        else _cloudflare_r2_object_key(filename=filename, prefix=prefix)
    )
    mystery_object = _is_mystery_object_key(object_key)
    mystery_bucket = (values.get("mystery_cloudflare_r2_bucket") or "").strip()
    if mystery_object:
        if mystery_bucket and bucket and bucket != mystery_bucket:
            raise ProviderRuntimeError(
                provider="cloudflare_r2",
                status_code=422,
                message="Mystery object key must use mystery-only R2 bucket.",
                detail=f"object_key={object_key}; resolved_bucket={bucket}; expected_bucket={mystery_bucket}",
            )
        if not account_id or not bucket or not access_key_id or not secret_access_key:
            raise ProviderRuntimeError(
                provider="cloudflare_r2",
                status_code=422,
                message="Mystery R2 upload requested without mystery credentials.",
                detail="Set mystery_cloudflare_account_id, mystery_cloudflare_r2_bucket, mystery_cloudflare_r2_access_key_id, and mystery_cloudflare_r2_secret_access_key.",
            )
        if not public_base_url:
            raise ProviderRuntimeError(
                provider="cloudflare_r2",
                status_code=422,
                message="Mystery R2 public base URL is missing.",
                detail="Set mystery_cloudflare_r2_public_base_url to the MysteryArchive public domain.",
            )
    elif mystery_bucket and bucket and bucket == mystery_bucket:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=422,
            message="Non-mystery object key cannot access mystery-only R2 bucket.",
            detail=f"object_key={object_key}; mystery_bucket={mystery_bucket}",
        )

    ext = Path(filename).suffix.lower()
    content_type = mimetypes.guess_type(filename)[0] or {
        ".webp": "image/webp",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".avif": "image/avif",
    }.get(ext, "application/octet-stream")
    direct_upload_error: ProviderRuntimeError | None = None

    if account_id and bucket and access_key_id and secret_access_key:
        if not public_base_url:
            direct_upload_error = ProviderRuntimeError(
                provider="cloudflare_r2",
                status_code=422,
                message="Cloudflare R2 public base URL is missing.",
                detail="Set cloudflare_r2_public_base_url to the img.<domain> custom domain.",
            )
        else:
            headers = _build_r2_authorization_headers(
                method="PUT",
                account_id=account_id,
                bucket=bucket,
                object_key=object_key,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                payload=content,
                extra_headers={
                    "Content-Type": content_type,
                    "Cache-Control": "public, max-age=31536000, immutable",
                },
            )
            response = httpx.put(
                _r2_endpoint_url(account_id=account_id, bucket=bucket, object_key=object_key),
                content=content,
                headers=headers,
                timeout=120.0,
            )
            if response.is_success:
                original_url = _cloudflare_r2_original_url(public_base_url=public_base_url, object_key=object_key)
                return original_url, {
                    "bucket": bucket,
                    "object_key": object_key,
                    "etag": str(response.headers.get("etag") or "").strip('"'),
                    "content_type": content_type,
                    "public_base_url": public_base_url,
                    "public_url": original_url,
                }
            direct_upload_error = ProviderRuntimeError(
                provider="cloudflare_r2",
                status_code=response.status_code,
                message="Cloudflare R2 upload failed.",
                detail=response.text,
            )
            if mystery_object or not integration_base_url or not integration_token or response.status_code not in {401, 403}:
                raise direct_upload_error

    if not integration_base_url or not integration_token:
        fallback_detail = (
            f" Direct upload error: {direct_upload_error.detail}" if direct_upload_error is not None else ""
        )
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=422,
            message="Cloudflare R2 delivery is missing required settings.",
            detail=(
                "Set cloudflare_account_id, cloudflare_r2_bucket, cloudflare_r2_access_key_id, "
                "and cloudflare_r2_secret_access_key, or configure cloudflare_blog_api_base_url "
                "and cloudflare_blog_m2m_token for integration proxy uploads."
                + fallback_detail
            ),
        )

    response = httpx.post(
        f"{integration_base_url}/api/integrations/assets",
        headers={"Authorization": f"Bearer {integration_token}"},
        data={
            "postSlug": Path(filename).stem,
            "altText": Path(filename).stem.replace("-", " "),
        },
        files={"file": (filename, content, content_type)},
        timeout=120.0,
    )
    if not response.is_success:
        detail = response.text
        try:
            payload = response.json()
            detail = str(payload.get("message") or payload.get("detail") or payload.get("error") or detail)
        except ValueError:
            pass
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=response.status_code,
            message="Cloudflare integration asset upload failed.",
            detail=detail,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=502,
            message="Cloudflare integration asset upload returned invalid JSON.",
            detail=response.text,
        ) from exc

    if isinstance(payload, Mapping) and payload.get("success") is False:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=502,
            message="Cloudflare integration asset upload failed.",
            detail=str(payload.get("message") or payload.get("detail") or payload.get("error") or "Unknown error"),
        )

    asset_payload = _extract_cloudflare_integration_asset(payload)
    if not isinstance(asset_payload, Mapping):
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=502,
            message="Cloudflare integration asset upload returned no asset payload.",
            detail=str(payload),
        )

    resolved_object_key = str(asset_payload.get("objectKey") or asset_payload.get("object_key") or object_key).strip()
    resolved_public_url = str(asset_payload.get("publicUrl") or asset_payload.get("public_url") or "").strip()
    resolved_public_base_url = (
        str(asset_payload.get("publicBaseUrl") or asset_payload.get("public_base_url") or "").strip()
        or _cloudflare_public_base_from_url(resolved_public_url, resolved_object_key)
        or public_base_url
    )
    if not resolved_public_url and resolved_public_base_url and resolved_object_key:
        resolved_public_url = _cloudflare_r2_original_url(
            public_base_url=resolved_public_base_url,
            object_key=resolved_object_key,
        )
    if not resolved_public_url:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=502,
            message="Cloudflare integration asset upload returned no public URL.",
            detail=str(payload),
        )

    return resolved_public_url, {
        "bucket": str(asset_payload.get("bucket") or bucket).strip(),
        "object_key": resolved_object_key,
        "etag": str(asset_payload.get("etag") or "").strip('"'),
        "content_type": content_type,
        "public_base_url": resolved_public_base_url,
        "public_url": resolved_public_url,
        "upload_path": "integration_fallback" if direct_upload_error is not None else "integration",
        "direct_upload_error": (
            {
                "status_code": direct_upload_error.status_code,
                "message": direct_upload_error.message,
                "detail": direct_upload_error.detail,
            }
            if direct_upload_error is not None
            else None
        ),
        "integration_response": payload,
    }


def upload_binary_to_cloudflare_r2(
    db: Session,
    *,
    object_key: str | None = None,
    filename: str,
    content: bytes,
) -> tuple[str, dict, dict]:
    values = get_settings_map(db)
    transform_enabled = _is_cloudflare_transform_enabled(values)
    _, bucket, _, _, public_base_url, _ = _resolve_cloudflare_r2_configuration(values, object_key=object_key)
    _, upload_payload = _upload_to_cloudflare_r2(
        values=values,
        object_key=object_key,
        filename=filename,
        content=content,
    )
    resolved_bucket = str(upload_payload.get("bucket") or bucket).strip()
    resolved_public_base_url = str(upload_payload.get("public_base_url") or public_base_url).strip()
    delivery_meta = build_cloudflare_r2_delivery_metadata(
        bucket=resolved_bucket,
        object_key=upload_payload["object_key"],
        public_base_url=resolved_public_base_url,
        etag=str(upload_payload.get("etag") or "").strip(),
        transform_enabled=transform_enabled,
    )
    original_url = str(((delivery_meta.get("cloudflare") or {}).get("original_url") or "")).strip()
    if transform_enabled:
        public_url = str((delivery_meta.get("presets") or {}).get("hero") or upload_payload.get("public_url") or "").strip()
    else:
        public_url = original_url or str(upload_payload.get("public_url") or "").strip()
    return public_url, upload_payload, delivery_meta


def delete_cloudflare_r2_asset(
    db: Session,
    *,
    object_key: str,
) -> None:
    if not object_key.strip():
        return

    values = get_settings_map(db)
    account_id, bucket, access_key_id, secret_access_key, _, _ = _resolve_cloudflare_r2_configuration(
        values,
        object_key=object_key,
    )
    if not account_id or not bucket or not access_key_id or not secret_access_key:
        return

    headers = _build_r2_authorization_headers(
        method="DELETE",
        account_id=account_id,
        bucket=bucket,
        object_key=object_key,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        payload=b"",
    )
    response = httpx.delete(
        _r2_endpoint_url(account_id=account_id, bucket=bucket, object_key=object_key),
        headers=headers,
        timeout=60.0,
    )
    if not response.is_success:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=response.status_code,
            message="Cloudflare R2 asset delete failed.",
            detail=response.text,
        )


def _resolve_cloudinary_preset_url(
    value: object,
    *,
    fallback_transformation: str,
    secure_url_original: str,
    cloud_name: str,
    public_id: str,
    resource_type: str,
) -> str:
    preset_value = str(value or "").strip()
    if preset_value.startswith("http://") or preset_value.startswith("https://"):
        return preset_value
    transformation = preset_value or fallback_transformation
    return build_cloudinary_variant_url(
        secure_url_original,
        transformation=transformation,
        cloud_name=cloud_name,
        public_id=public_id,
        resource_type=resource_type,
        version=_cloudinary_version_from_secure_url(secure_url_original),
    )


def _resolve_cloudflare_preset_url(
    value: object,
    *,
    fallback_options: Sequence[tuple[str, str]],
    public_base_url: str,
    object_key: str,
) -> str:
    preset_value = str(value or "").strip()
    if preset_value.startswith("http://") or preset_value.startswith("https://"):
        return preset_value
    if not public_base_url or not object_key:
        return ""
    return build_cloudflare_variant_url(
        public_base_url=public_base_url,
        object_key=object_key,
        options=fallback_options,
    )


def _build_srcset_attribute(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, Mapping):
        return ""

    ordered_candidates: list[tuple[int, str]] = []
    for width, url in value.items():
        try:
            normalized_width = int(str(width).strip())
        except (TypeError, ValueError):
            continue
        normalized_url = str(url or "").strip()
        if not normalized_url:
            continue
        ordered_candidates.append((normalized_width, normalized_url))
    ordered_candidates.sort(key=lambda item: item[0])
    return ", ".join(f"{url} {width}w" for width, url in ordered_candidates)


def build_public_image_variants(
    *,
    public_url: str,
    image_metadata: dict | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict:
    metadata = image_metadata or {}
    delivery = metadata.get("delivery") if isinstance(metadata, dict) else {}
    delivery = delivery if isinstance(delivery, dict) else {}
    provider = str(delivery.get("provider") or metadata.get("storage_provider") or "").strip().lower()

    variants = {
        "provider": provider or "plain",
        "plain": public_url,
        "hero_src": public_url,
        "hero_srcset": "",
        "hero_sizes": RESPONSIVE_HERO_SIZES,
        "card_src": public_url,
        "thumb_src": public_url,
        "width": width,
        "height": height,
    }

    if provider == "cloudinary":
        cloudinary_meta = delivery.get("cloudinary") if isinstance(delivery, dict) else {}
        cloudinary_meta = cloudinary_meta if isinstance(cloudinary_meta, dict) else {}
        secure_url_original = str(cloudinary_meta.get("secure_url_original") or "").strip()
        cloud_name = str(cloudinary_meta.get("cloud_name") or "").strip()
        public_id = str(cloudinary_meta.get("public_id") or "").strip()
        resource_type = str(cloudinary_meta.get("resource_type") or "image").strip() or "image"

        presets = delivery.get("presets") if isinstance(delivery, dict) else {}
        presets = presets if isinstance(presets, dict) else {}
        variants["hero_src"] = _resolve_cloudinary_preset_url(
            presets.get("hero"),
            fallback_transformation=CLOUDINARY_HERO_TRANSFORMATION,
            secure_url_original=secure_url_original,
            cloud_name=cloud_name,
            public_id=public_id,
            resource_type=resource_type,
        ) or public_url
        variants["card_src"] = _resolve_cloudinary_preset_url(
            presets.get("card"),
            fallback_transformation=CLOUDINARY_CARD_TRANSFORMATION,
            secure_url_original=secure_url_original,
            cloud_name=cloud_name,
            public_id=public_id,
            resource_type=resource_type,
        ) or public_url
        variants["thumb_src"] = _resolve_cloudinary_preset_url(
            presets.get("thumb"),
            fallback_transformation="f_auto,q_auto,w_160,h_160,c_fill,g_auto",
            secure_url_original=secure_url_original,
            cloud_name=cloud_name,
            public_id=public_id,
            resource_type=resource_type,
        ) or variants["card_src"]

        srcset = delivery.get("srcset") if isinstance(delivery, dict) else {}
        srcset = srcset if isinstance(srcset, dict) else {}
        variants["hero_srcset"] = _build_srcset_attribute(srcset.get("hero"))
        if not variants["hero_srcset"] and (secure_url_original or (cloud_name and public_id)):
            fallback_srcset = build_cloudinary_srcset_urls(
                secure_url=secure_url_original,
                cloud_name=cloud_name,
                public_id=public_id,
                resource_type=resource_type,
                version=_cloudinary_version_from_secure_url(secure_url_original),
            )
            variants["hero_srcset"] = ", ".join(
                f"{fallback_srcset[str(item_width)]} {item_width}w"
                for item_width in RESPONSIVE_HERO_WIDTHS
                if fallback_srcset.get(str(item_width))
            )
        return variants

    if provider == "cloudflare_r2":
        cloudflare_meta = delivery.get("cloudflare") if isinstance(delivery, dict) else {}
        cloudflare_meta = cloudflare_meta if isinstance(cloudflare_meta, dict) else {}
        public_base_url = str(cloudflare_meta.get("public_base_url") or "").strip()
        object_key = str(cloudflare_meta.get("object_key") or "").strip()
        original_url = str(cloudflare_meta.get("original_url") or "").strip()
        transform_enabled = _is_enabled_setting(cloudflare_meta.get("transform_enabled"), default=True)
        if not transform_enabled:
            resolved_url = original_url or public_url
            variants["hero_src"] = resolved_url
            variants["card_src"] = resolved_url
            variants["thumb_src"] = resolved_url
            variants["hero_srcset"] = ""
            return variants

        presets = delivery.get("presets") if isinstance(delivery, dict) else {}
        presets = presets if isinstance(presets, dict) else {}
        variants["hero_src"] = _resolve_cloudflare_preset_url(
            presets.get("hero"),
            fallback_options=CLOUDFLARE_HERO_OPTIONS,
            public_base_url=public_base_url,
            object_key=object_key,
        ) or public_url
        variants["card_src"] = _resolve_cloudflare_preset_url(
            presets.get("card"),
            fallback_options=CLOUDFLARE_CARD_OPTIONS,
            public_base_url=public_base_url,
            object_key=object_key,
        ) or public_url
        variants["thumb_src"] = _resolve_cloudflare_preset_url(
            presets.get("thumb"),
            fallback_options=CLOUDFLARE_THUMB_OPTIONS,
            public_base_url=public_base_url,
            object_key=object_key,
        ) or variants["card_src"]

        srcset = delivery.get("srcset") if isinstance(delivery, dict) else {}
        srcset = srcset if isinstance(srcset, dict) else {}
        variants["hero_srcset"] = _build_srcset_attribute(srcset.get("hero"))
        if not variants["hero_srcset"] and public_base_url and object_key:
            fallback_srcset = build_cloudflare_srcset_urls(
                public_base_url=public_base_url,
                object_key=object_key,
            )
            variants["hero_srcset"] = ", ".join(
                f"{fallback_srcset[str(item_width)]} {item_width}w"
                for item_width in RESPONSIVE_HERO_WIDTHS
                if fallback_srcset.get(str(item_width))
            )
        return variants

    return variants


def _upload_to_cloudinary(
    *,
    values: dict[str, str],
    filename: str,
    content: bytes,
) -> tuple[str, dict]:
    cloud_name, api_key, api_secret, folder = _resolve_cloudinary_configuration(values)

    if not cloud_name or not api_key or not api_secret:
        raise ProviderRuntimeError(
            provider="cloudinary",
            status_code=422,
            message="Cloudinary delivery is missing required settings.",
            detail="Set cloudinary_cloud_name, cloudinary_api_key, and cloudinary_api_secret.",
        )

    timestamp = str(int(time.time()))
    public_id = Path(filename).stem
    sign_params = {
        "folder": folder,
        "overwrite": "true",
        "public_id": public_id,
        "timestamp": timestamp,
    }
    signature = _cloudinary_signature(sign_params, api_secret)
    response = httpx.post(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
        data={
            "api_key": api_key,
            "folder": folder,
            "overwrite": "true",
            "public_id": public_id,
            "signature": signature,
            "timestamp": timestamp,
        },
        files={"file": (filename, content, "application/octet-stream")},
        timeout=120.0,
    )
    if not response.is_success:
        detail = response.text
        try:
            payload = response.json()
            detail = payload.get("error", {}).get("message", detail)
        except ValueError:
            pass
        raise ProviderRuntimeError(
            provider="cloudinary",
            status_code=response.status_code,
            message="Cloudinary upload failed.",
            detail=detail,
        )

    payload = response.json()
    return payload.get("secure_url") or payload.get("url") or "", payload


def upload_binary_to_cloudinary(
    db: Session,
    *,
    filename: str,
    content: bytes,
) -> tuple[str, dict, dict]:
    values = get_settings_map(db)
    cloud_name, _, _, _ = _resolve_cloudinary_configuration(values)
    _, upload_payload = _upload_to_cloudinary(values=values, filename=filename, content=content)
    delivery_meta = build_cloudinary_delivery_metadata(upload_payload, cloud_name=cloud_name)
    public_url = str((delivery_meta.get("presets") or {}).get("hero") or "").strip()
    return public_url, upload_payload, delivery_meta


def save_binary(
    *,
    subdir: str,
    filename: str,
    content: bytes,
    public_base_url: str | None = None,
) -> tuple[str, str]:
    ensure_storage_dirs()
    relative = Path(subdir) / filename
    destination = Path(settings.storage_root) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    public_url = build_storage_public_url(relative, public_base_url)
    return str(destination), public_url


def _save_binary_with_root(
    *,
    storage_root: str,
    subdir: str,
    filename: str,
    content: bytes,
    public_base_url: str | None = None,
) -> tuple[str, str]:
    base_root = Path(str(storage_root or settings.storage_root))
    relative = Path(subdir) / filename
    destination = base_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    public_url = build_storage_public_url(relative, public_base_url)
    return str(destination), public_url


def _base_delivery_metadata(*, provider: str, local_public_url: str) -> dict:
    return {
        "provider": provider,
        "local_public_url": local_public_url,
        "local_public_url_is_private": _looks_private_url(local_public_url),
    }


def _ensure_webp_filename(filename: str) -> str:
    return str(Path(filename).with_suffix(".webp"))


def _normalize_binary_for_filename(*, content: bytes, filename: str, force_webp: bool = False) -> bytes:
    should_convert = force_webp or Path(filename).suffix.lower() == ".webp"
    if not should_convert:
        return content
    try:
        with Image.open(io.BytesIO(content)) as loaded:
            output = io.BytesIO()
            converted = loaded if loaded.mode in {"RGB", "RGBA"} else loaded.convert("RGB")
            converted.save(output, format="WEBP", quality=88, method=6)
            return output.getvalue()
    except Exception as exc:  # noqa: BLE001
        if force_webp:
            raise ValueError("Failed to convert image to WebP.") from exc
        return content


def _convert_binary_to_png(content: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(content)) as loaded:
            output = io.BytesIO()
            converted = loaded.convert("RGBA") if loaded.mode not in {"RGB", "RGBA"} else loaded
            converted.save(output, format="PNG")
            return output.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Failed to convert image to PNG.") from exc


def save_public_binary(
    db: Session,
    *,
    subdir: str,
    filename: str,
    content: bytes,
    object_key: str | None = None,
    provider_override: str | None = None,
) -> tuple[str, str, dict]:
    values = get_settings_map(db)
    provider = (provider_override or values.get("public_image_provider") or "local").strip().lower()
    mystery_object = _is_mystery_object_key(object_key)
    travel_object = parse_travel_canonical_object_key(object_key) is not None
    travel_parts = parse_travel_canonical_object_key(object_key)
    local_base_url = _resolve_local_public_base_url(values)
    storage_root_override = str(values.get("storage_root") or settings.storage_root).strip()
    normalized_filename = filename
    resolved_subdir = subdir
    force_webp = False
    if provider == "cloudflare_r2":
        normalized_filename = _ensure_webp_filename(filename)
        force_webp = True
        if mystery_object or travel_object:
            _enforce_strict_r2_schema(object_key=str(object_key or ""), values=values, mystery_only=mystery_object)
            resolved_subdir = str(values.get("mystery_storage_subdir") or "images/mystery").strip().replace("\\", "/")
            if travel_object:
                normalized_filename = "cover.webp"
                resolved_subdir = build_travel_local_publish_relative_dir(
                    category_key=str(travel_parts.get("category_key") or "uncategorized"),
                    post_slug=str(travel_parts.get("post_slug") or "post"),
                )
    normalized_content = _normalize_binary_for_filename(
        content=content,
        filename=normalized_filename,
        force_webp=force_webp,
    )
    local_png_path = ""
    if provider == "cloudflare_r2" and (mystery_object or travel_object):
        png_filename = "cover.png" if travel_object else f"{Path(normalized_filename).stem}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}.png"
        png_subdir = resolved_subdir
        if travel_object:
            png_subdir = build_travel_local_backup_relative_dir(
                category_key=str(travel_parts.get("category_key") or "uncategorized"),
                post_slug=str(travel_parts.get("post_slug") or "post"),
            )
        png_bytes = _convert_binary_to_png(content)
        local_png_path, _ = _save_binary_with_root(
            storage_root=storage_root_override,
            subdir=png_subdir,
            filename=png_filename,
            content=png_bytes,
            public_base_url=local_base_url,
        )
        _enforce_strict_storage_root(destination_path=local_png_path, values=values, mystery_only=mystery_object)

    file_path, local_public_url = _save_binary_with_root(
        storage_root=storage_root_override,
        subdir=resolved_subdir,
        filename=normalized_filename,
        content=normalized_content,
        public_base_url=local_base_url,
    )
    _enforce_strict_storage_root(destination_path=file_path, values=values, mystery_only=mystery_object)
    delivery_meta = _base_delivery_metadata(provider=provider, local_public_url=local_public_url)
    if local_png_path:
        delivery_meta["local_png_path"] = local_png_path

    if provider == "cloudflare_r2":
        public_url, _, provider_delivery = upload_binary_to_cloudflare_r2(
            db,
            object_key=object_key,
            filename=normalized_filename,
            content=normalized_content,
        )
        if _is_enabled_setting(values.get("strict_r2_key_schema"), default=True):
            lowered_public = str(public_url or "").lower()
            if any(token in lowered_public for token in FORBIDDEN_R2_TOKENS):
                raise ProviderRuntimeError(
                    provider="cloudflare_r2",
                    status_code=422,
                    message="Forbidden token detected in public URL.",
                    detail=f"public_url={public_url}",
                )
        provider_delivery.update(delivery_meta)
        provider_delivery["public_url"] = public_url
        return file_path, public_url, provider_delivery

    if provider == "cloudinary":
        public_url, _, provider_delivery = upload_binary_to_cloudinary(
            db,
            filename=filename,
            content=normalized_content,
        )
        provider_delivery.update(delivery_meta)
        provider_delivery["public_url"] = public_url
        return file_path, public_url, provider_delivery

    if provider == "github_pages":
        public_url, upload_payload = _upload_to_github_pages(values=values, filename=filename, content=normalized_content)
        delivery_meta["github_pages"] = upload_payload
        delivery_meta["public_url"] = public_url
        return file_path, public_url, delivery_meta

    delivery_meta["public_url"] = local_public_url
    return file_path, local_public_url, delivery_meta


def ensure_existing_public_image_url(
    db: Session,
    *,
    file_path: str,
    object_key: str | None = None,
) -> tuple[str, dict]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {file_path}")

    try:
        relative = path.resolve().relative_to(Path(settings.storage_root).resolve())
    except ValueError:
        relative = Path("images") / path.name

    values = get_settings_map(db)
    local_base_url = _resolve_local_public_base_url(values)
    local_public_url = build_storage_public_url(relative, local_base_url)
    provider = (values.get("public_image_provider") or "local").strip().lower()
    delivery_meta = _base_delivery_metadata(provider=provider, local_public_url=local_public_url)

    if provider == "cloudflare_r2":
        upload_filename = _ensure_webp_filename(path.name)
        upload_content = _normalize_binary_for_filename(
            content=path.read_bytes(),
            filename=upload_filename,
            force_webp=True,
        )
        public_url, _, provider_delivery = upload_binary_to_cloudflare_r2(
            db,
            object_key=object_key,
            filename=upload_filename,
            content=upload_content,
        )
        provider_delivery.update(delivery_meta)
        provider_delivery["public_url"] = public_url
        return public_url, provider_delivery

    if provider == "cloudinary":
        public_url, _, provider_delivery = upload_binary_to_cloudinary(
            db,
            filename=path.name,
            content=path.read_bytes(),
        )
        provider_delivery.update(delivery_meta)
        provider_delivery["public_url"] = public_url
        return public_url, provider_delivery

    if provider == "github_pages":
        public_url, upload_payload = _upload_to_github_pages(values=values, filename=path.name, content=path.read_bytes())
        delivery_meta["github_pages"] = upload_payload
        delivery_meta["public_url"] = public_url
        return public_url, delivery_meta

    delivery_meta["public_url"] = local_public_url
    return local_public_url, delivery_meta


def save_html(*, slug: str, html: str) -> tuple[str, str]:
    ensure_storage_dirs()
    filename = f"{slug}.html"
    relative = Path("html") / filename
    destination = Path(settings.storage_root) / relative
    destination.write_text(html, encoding="utf-8")
    public_url = build_storage_public_url(relative)
    return str(destination), public_url


def clear_generated_storage(*, subdirs: tuple[str, ...] = ("images", "html")) -> int:
    ensure_storage_dirs()
    deleted_files = 0

    for subdir in subdirs:
        root = Path(settings.storage_root) / subdir
        if not root.exists():
            continue

        for path in sorted(root.rglob("*"), reverse=True):
            if path.name == ".gitkeep":
                continue
            if path.is_file():
                path.unlink(missing_ok=True)
                deleted_files += 1
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass

    return deleted_files

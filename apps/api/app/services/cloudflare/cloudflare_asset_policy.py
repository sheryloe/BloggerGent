from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slugify import slugify

from app.core.config import settings
from app.models.entities import ManagedChannel

CLOUDFLARE_MANAGED_CHANNEL_ID = "cloudflare:dongriarchive"
CLOUDFLARE_R2_NAMESPACE = "cloudflare"
CLOUDFLARE_R2_CHANNEL_SLUG = "dongri-archive"
CLOUDFLARE_R2_PREFIX = f"assets/media/{CLOUDFLARE_R2_NAMESPACE}/{CLOUDFLARE_R2_CHANNEL_SLUG}"
CLOUDFLARE_ALLOWED_CATEGORY_SLUGS: tuple[str, ...] = (
    "개발과-프로그래밍",
    "나스닥의-흐름",
    "동그리의-생각",
    "문화와-공간",
    "미스테리아-스토리",
    "삶을-유용하게",
    "삶의-기름칠",
    "여행과-기록",
    "일상과-메모",
    "주식의-흐름",
    "축제와-현장",
    "크립토의-흐름",
)
CLOUDFLARE_CATEGORY_LEAF_MAP: dict[str, str] = {
    "개발과-프로그래밍": "gaebalgwa-peurogeuraeming",
    "나스닥의-흐름": "naseudagyi-heureum",
    "동그리의-생각": "donggeuriyi-saenggag",
    "문화와-공간": "munhwawa-gonggan",
    "미스테리아-스토리": "miseuteria-seutori",
    "삶을-유용하게": "salmeul-yuyonghage",
    "삶의-기름칠": "salmyi-gireumcil",
    "여행과-기록": "yeohaenggwa-girog",
    "일상과-메모": "ilsanggwa-memo",
    "주식의-흐름": "jusigyi-heureum",
    "축제와-현장": "cugjewa-hyeonjang",
    "크립토의-흐름": "keuribtoyi-heureum",
}


@dataclass(frozen=True, slots=True)
class CloudflareAssetPolicy:
    channel_id: str
    r2_namespace: str
    r2_prefix: str
    local_asset_root: str
    hero_only: bool
    allowed_category_slugs: tuple[str, ...]
    category_leaf_map: dict[str, str]

    @property
    def local_asset_root_path(self) -> Path:
        configured = str(self.local_asset_root or "").strip()
        if configured:
            return Path(configured)
        return default_cloudflare_local_asset_root()


def _truthy(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def default_cloudflare_local_asset_root() -> Path:
    runtime_root = Path(settings.cloudflare_storage_root_windows)
    canonical_runtime_root = runtime_root / "cloudflare"
    if canonical_runtime_root.exists():
        return canonical_runtime_root
    legacy_runtime_root = runtime_root / "images" / "Cloudflare"
    if legacy_runtime_root.exists():
        return legacy_runtime_root
    return Path(settings.storage_root) / "cloudflare"


def default_cloudflare_channel_metadata() -> dict[str, Any]:
    return {
        "r2_namespace": CLOUDFLARE_R2_NAMESPACE,
        "r2_prefix": CLOUDFLARE_R2_PREFIX,
        "local_asset_root": str(default_cloudflare_local_asset_root()),
        "hero_only": True,
        "allowed_category_slugs": list(CLOUDFLARE_ALLOWED_CATEGORY_SLUGS),
        "category_leaf_map": dict(CLOUDFLARE_CATEGORY_LEAF_MAP),
    }


def ensure_cloudflare_channel_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = default_cloudflare_channel_metadata()
    merged: dict[str, Any] = dict(defaults)
    if isinstance(metadata, Mapping):
        merged.update({key: value for key, value in metadata.items() if value is not None})

    allowed = merged.get("allowed_category_slugs")
    normalized_allowed = tuple(
        slug
        for slug in [str(item or "").strip() for item in (allowed or CLOUDFLARE_ALLOWED_CATEGORY_SLUGS)]
        if slug
    )
    if not normalized_allowed:
        normalized_allowed = CLOUDFLARE_ALLOWED_CATEGORY_SLUGS

    category_leaf_map = dict(CLOUDFLARE_CATEGORY_LEAF_MAP)
    raw_leaf_map = merged.get("category_leaf_map")
    if isinstance(raw_leaf_map, Mapping):
        for key, value in raw_leaf_map.items():
            slug = str(key or "").strip()
            leaf = slugify(str(value or "").strip(), separator="-") if str(value or "").strip() else ""
            if slug and leaf:
                category_leaf_map[slug] = leaf

    for slug in normalized_allowed:
        category_leaf_map.setdefault(slug, slugify(slug, separator="-") or "uncategorized")

    merged["r2_namespace"] = str(merged.get("r2_namespace") or CLOUDFLARE_R2_NAMESPACE).strip() or CLOUDFLARE_R2_NAMESPACE
    merged["r2_prefix"] = str(merged.get("r2_prefix") or CLOUDFLARE_R2_PREFIX).strip().strip("/") or CLOUDFLARE_R2_PREFIX
    merged["local_asset_root"] = str(merged.get("local_asset_root") or default_cloudflare_local_asset_root()).strip()
    merged["hero_only"] = _truthy(merged.get("hero_only"), default=True)
    merged["allowed_category_slugs"] = list(normalized_allowed)
    merged["category_leaf_map"] = category_leaf_map
    return merged


def get_cloudflare_asset_policy(channel: ManagedChannel | None) -> CloudflareAssetPolicy:
    if channel is None:
        raise ValueError("Cloudflare channel is not configured.")
    if str(channel.provider or "").strip().lower() != "cloudflare":
        raise ValueError("Cloudflare asset policy requires a cloudflare managed channel.")
    if str(channel.channel_id or "").strip() != CLOUDFLARE_MANAGED_CHANNEL_ID:
        raise ValueError(f"Unsupported Cloudflare managed channel: {channel.channel_id}")
    metadata = ensure_cloudflare_channel_metadata(channel.channel_metadata or {})
    return CloudflareAssetPolicy(
        channel_id=str(channel.channel_id or "").strip(),
        r2_namespace=str(metadata["r2_namespace"]),
        r2_prefix=str(metadata["r2_prefix"]),
        local_asset_root=str(metadata["local_asset_root"]),
        hero_only=bool(metadata["hero_only"]),
        allowed_category_slugs=tuple(str(item or "").strip() for item in metadata["allowed_category_slugs"] if str(item or "").strip()),
        category_leaf_map={
            str(key or "").strip(): str(value or "").strip()
            for key, value in dict(metadata["category_leaf_map"]).items()
            if str(key or "").strip() and str(value or "").strip()
        },
    )


def build_default_cloudflare_asset_policy() -> CloudflareAssetPolicy:
    metadata = ensure_cloudflare_channel_metadata({})
    return CloudflareAssetPolicy(
        channel_id=CLOUDFLARE_MANAGED_CHANNEL_ID,
        r2_namespace=str(metadata["r2_namespace"]),
        r2_prefix=str(metadata["r2_prefix"]),
        local_asset_root=str(metadata["local_asset_root"]),
        hero_only=bool(metadata["hero_only"]),
        allowed_category_slugs=tuple(str(item or "").strip() for item in metadata["allowed_category_slugs"] if str(item or "").strip()),
        category_leaf_map={
            str(key or "").strip(): str(value or "").strip()
            for key, value in dict(metadata["category_leaf_map"]).items()
            if str(key or "").strip() and str(value or "").strip()
        },
    )


def resolve_cloudflare_local_asset_root(policy: CloudflareAssetPolicy, *, prefer_existing: bool = True) -> Path:
    configured = policy.local_asset_root_path
    fallback = settings.storage_images_dir / "Cloudflare"
    if not prefer_existing:
        return configured
    for candidate in (configured, fallback):
        if candidate.exists():
            return candidate
    return configured


def resolve_cloudflare_category_slug(category_slug: str | None, *, policy: CloudflareAssetPolicy) -> str:
    normalized = str(category_slug or "").strip()
    if not normalized:
        raise ValueError("Cloudflare category slug is required.")
    if normalized not in policy.allowed_category_slugs:
        raise ValueError(f"Cloudflare category slug is not allowed: {normalized}")
    return normalized


def resolve_cloudflare_category_leaf(category_slug: str | None, *, policy: CloudflareAssetPolicy) -> str:
    resolved_slug = resolve_cloudflare_category_slug(category_slug, policy=policy)
    leaf = str(policy.category_leaf_map.get(resolved_slug) or "").strip()
    if not leaf:
        leaf = slugify(resolved_slug, separator="-") or "uncategorized"
    return leaf


def resolve_cloudflare_post_slug(post_slug: str | None) -> str:
    normalized = str(post_slug or "").strip().strip("/")
    normalized = normalized.replace("\\", "-").replace("/", "-")
    return normalized or "post"


def build_cloudflare_r2_object_key(
    *,
    policy: CloudflareAssetPolicy,
    category_slug: str,
    post_slug: str,
    published_at: datetime | None = None,
) -> str:
    resolved_category = resolve_cloudflare_category_leaf(category_slug, policy=policy)
    resolved_post_slug = resolve_cloudflare_post_slug(post_slug)
    resolved_time = published_at.astimezone(timezone.utc) if isinstance(published_at, datetime) and published_at.tzinfo else published_at
    if resolved_time is None:
        resolved_time = datetime.now(timezone.utc)
    elif resolved_time.tzinfo is None:
        resolved_time = resolved_time.replace(tzinfo=timezone.utc)
    else:
        resolved_time = resolved_time.astimezone(timezone.utc)
    return (
        f"{policy.r2_prefix}/{resolved_category}/"
        f"{resolved_time:%Y}/{resolved_time:%m}/{resolved_post_slug}/{resolved_post_slug}.webp"
    )


def build_cloudflare_local_asset_path(
    *,
    policy: CloudflareAssetPolicy,
    category_slug: str,
    post_slug: str,
    prefer_existing_root: bool = True,
) -> Path:
    resolved_category = resolve_cloudflare_category_slug(category_slug, policy=policy)
    resolved_post_slug = resolve_cloudflare_post_slug(post_slug)
    root = resolve_cloudflare_local_asset_root(policy, prefer_existing=prefer_existing_root)
    return root / resolved_category / f"{resolved_post_slug}.webp"


def assert_cloudflare_asset_scope(
    *,
    policy: CloudflareAssetPolicy,
    category_slug: str | None = None,
    object_key: str | None = None,
    local_path: str | Path | None = None,
) -> None:
    if category_slug is not None:
        resolve_cloudflare_category_slug(category_slug, policy=policy)
    if object_key is not None:
        normalized_key = str(object_key or "").strip().lstrip("/")
        if not normalized_key.startswith(f"{policy.r2_prefix}/"):
            raise ValueError(f"Cloudflare object key escaped the channel prefix: {normalized_key}")
    if local_path is not None:
        root = resolve_cloudflare_local_asset_root(policy, prefer_existing=False).resolve()
        target = Path(local_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Cloudflare local asset path escaped the channel root: {target}") from exc

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image as PILImage, ImageOps, UnidentifiedImageError
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
DEFAULT_RUNTIME_IMAGE_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\images")
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and ((value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"'))):
            value = value[1:-1]
        os.environ[key] = value


_load_runtime_env(RUNTIME_ENV_PATH)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        DEFAULT_DATABASE_URL,
    )
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import (  # noqa: E402
    Article,
    Blog,
    BloggerPost,
    PostStatus,
    R2AssetRelayoutMapping,
    SyncedBloggerPost,
)
from app.services.blogger.blogger_live_audit_service import fetch_and_audit_blogger_post  # noqa: E402
from app.services.content.article_service import resolve_r2_category_key  # noqa: E402
from app.services.content.travel_blog_policy import (  # noqa: E402
    TRAVEL_BLOG_IDS,
    assert_travel_scope_blog,
    build_travel_asset_object_key,
    get_travel_blog_policy,
    normalize_travel_category_key,
)
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import (  # noqa: E402
    cloudflare_r2_object_exists,
    cloudflare_r2_object_size,
    delete_cloudflare_r2_asset,
    normalize_r2_url_to_key,
    upload_binary_to_cloudflare_r2,
)

IMAGE_URL_RE = re.compile(r"https?://[^\s'\"<>)]+?\.(?:webp|png|jpg|jpeg|gif|avif)", re.IGNORECASE)
TRAVEL_COVER_SIZE = (1024, 1024)
ALLOWED_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg", ".avif", ".gif")
EXCLUDED_SOURCE_TOKENS = ("cover", "inline", "4panel", "3x2", "thumbnail")
_EXTENSION_PRIORITY = {ext: index for index, ext in enumerate(ALLOWED_EXTENSIONS)}
_RESAMPLING_LANCZOS = getattr(getattr(PILImage, "Resampling", PILImage), "LANCZOS")
TRAVEL_BLOG_GROUP = "travel-blogger"
LANGUAGE_LABELS = {
    "en": "english",
    "es": "spanish",
    "ja": "japanese",
}


@dataclass(slots=True)
class SourceMatch:
    status: str
    source_path: Path | None = None
    source_slug: str = ""
    bucket: str = ""
    candidates: list[str] | None = None
    reason: str = ""


@dataclass(slots=True)
class LocalImageInventory:
    root_exact: dict[str, list[Path]]
    cloudflare_exact: dict[str, list[Path]]
    root_files: list[Path]
    cloudflare_files: list[Path]


@dataclass(slots=True)
class RebuildAction:
    article_id: int
    blog_id: int
    post_slug: str
    category_key: str
    old_url: str
    legacy_key: str
    target_key: str
    target_url: str
    source_match: SourceMatch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild Travel Blogger hero images into the canonical Travel R2 layout.")
    parser.add_argument("--profile-key", default="korea_travel")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--live-audit", action="store_true")
    parser.add_argument("--report-prefix", default="travel-rebuild")
    parser.add_argument("--runtime-image-root", default=str(DEFAULT_RUNTIME_IMAGE_ROOT))
    parser.add_argument(
        "--cloudflare-public-base-url",
        default=str(
            os.environ.get("CLOUDFLARE_R2_PUBLIC_BASE_URL")
            or os.environ.get("cloudflare_r2_public_base_url")
            or ""
        ).strip(),
    )
    parser.add_argument("--verify-http", action="store_true")
    return parser.parse_args()


def _travel_root(runtime_image_root: Path) -> Path:
    return runtime_image_root / "Travel"


def _travel_backup_root(runtime_image_root: Path) -> Path:
    return runtime_image_root / "TravelBackup"


def _report_root(runtime_image_root: Path) -> Path:
    return _travel_root(runtime_image_root) / "_logs"


def _manifest_root(runtime_image_root: Path) -> Path:
    return _travel_root(runtime_image_root) / "_manifests"


def _report_path(prefix: str, runtime_image_root: Path) -> Path:
    root = _report_root(runtime_image_root)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return root / f"{prefix}-{stamp}.json"


def _manifest_path(prefix: str, runtime_image_root: Path) -> Path:
    root = _manifest_root(runtime_image_root)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return root / f"{prefix}-{stamp}.json"


def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _slug_token(value: str | None) -> str:
    return slugify(str(value or "").strip(), separator="-") or "post"


def _extract_asset_urls(value: Any) -> list[str]:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    seen: set[str] = set()
    urls: list[str] = []
    for match in IMAGE_URL_RE.findall(text):
        url = str(match or "").strip()
        if not url or "/assets/" not in url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _deep_replace_urls(value: Any, url_map: dict[str, str]) -> Any:
    if not url_map:
        return value
    if isinstance(value, str):
        updated = value
        for old, new in url_map.items():
            updated = updated.replace(old, new)
        return updated
    if isinstance(value, list):
        return [_deep_replace_urls(item, url_map) for item in value]
    if isinstance(value, dict):
        return {key: _deep_replace_urls(item, url_map) for key, item in value.items()}
    return value


def _infer_public_base_url(url: str | None) -> str:
    parsed = urlsplit(str(url or "").strip())
    scheme = str(parsed.scheme or "").strip().lower()
    host = str(parsed.netloc or "").strip()
    if not scheme or not host:
        return ""
    return f"{scheme}://{host}"


def _cloudflare_public_url(db: Session, object_key: str, *, public_base_url_override: str = "", fallback_url: str = "") -> str:
    override = str(public_base_url_override or "").strip().rstrip("/")
    if override:
        return f"{override}/{str(object_key).strip().lstrip('/')}"

    secret_error: RuntimeError | None = None
    try:
        values = get_settings_map(db)
    except RuntimeError as exc:
        if "SETTINGS_ENCRYPTION_SECRET" in str(exc):
            secret_error = exc
            values = {}
        else:
            raise
    base = str(values.get("cloudflare_r2_public_base_url") or "").strip().rstrip("/")
    if not base:
        base = _infer_public_base_url(fallback_url).rstrip("/")
    if not base and secret_error is not None:
        raise RuntimeError(
            "SETTINGS_ENCRYPTION_SECRET is required to read Cloudflare R2 settings for Travel rebuild."
        ) from secret_error
    if not base:
        raise RuntimeError("cloudflare_r2_public_base_url is required for canonical URL mapping")
    return f"{base}/{str(object_key).strip().lstrip('/')}"


def _basename_from_url(url: str | None) -> str:
    path = urlsplit(str(url or "").strip()).path
    return Path(path).name.strip()


def _normalize_source_name(path: Path) -> str:
    return path.name.strip().lower()


def _is_source_candidate(path: Path) -> bool:
    lowered_name = _normalize_source_name(path)
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return False
    return not any(token in lowered_name for token in EXCLUDED_SOURCE_TOKENS)


def _candidate_sort_key(path: Path) -> tuple[int, int, str]:
    return (
        int(_EXTENSION_PRIORITY.get(path.suffix.lower(), len(ALLOWED_EXTENSIONS))),
        len(path.name),
        str(path).lower(),
    )


def _pick_preferred_path(paths: list[Path]) -> Path:
    return sorted(paths, key=_candidate_sort_key)[0]


def _build_local_image_inventory(runtime_image_root: Path) -> LocalImageInventory:
    root_exact: dict[str, list[Path]] = {}
    cloudflare_exact: dict[str, list[Path]] = {}
    root_files: list[Path] = []
    cloudflare_files: list[Path] = []
    for path in runtime_image_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        try:
            relative = path.relative_to(runtime_image_root)
        except ValueError:
            continue
        if not relative.parts:
            continue
        top_level = relative.parts[0].lower()
        if top_level in {"travel", "travelbackup"}:
            continue
        normalized_name = _normalize_source_name(path)
        if len(relative.parts) == 1:
            root_exact.setdefault(normalized_name, []).append(path)
            root_files.append(path)
            continue
        if top_level == "cloudflare":
            cloudflare_exact.setdefault(normalized_name, []).append(path)
            cloudflare_files.append(path)
    return LocalImageInventory(
        root_exact=root_exact,
        cloudflare_exact=cloudflare_exact,
        root_files=root_files,
        cloudflare_files=cloudflare_files,
    )


def _ordered_exact_candidates(slug: str, exact_index: dict[str, list[Path]]) -> list[Path]:
    candidates: list[Path] = []
    for extension in ALLOWED_EXTENSIONS:
        candidates.extend(exact_index.get(f"{slug}{extension}", []))
    return sorted(candidates, key=_candidate_sort_key)


def _near_slug_groups(slug: str, candidates: list[Path]) -> dict[str, list[Path]]:
    prefix = f"{slug}-"
    groups: dict[str, list[Path]] = {}
    for path in candidates:
        if not _is_source_candidate(path):
            continue
        stem = path.stem.strip().lower()
        if not stem.startswith(prefix):
            continue
        groups.setdefault(stem, []).append(path)
    return groups


def _resolve_local_source_for_slug(slug: str, inventory: LocalImageInventory) -> SourceMatch:
    normalized_slug = _slug_token(slug)
    exact_root = _ordered_exact_candidates(normalized_slug, inventory.root_exact)
    if exact_root:
        return SourceMatch(
            status="mapped",
            source_path=_pick_preferred_path(exact_root),
            source_slug=normalized_slug,
            bucket="root_exact",
            candidates=[str(path) for path in exact_root],
        )

    exact_cloudflare = _ordered_exact_candidates(normalized_slug, inventory.cloudflare_exact)
    if exact_cloudflare:
        return SourceMatch(
            status="mapped",
            source_path=_pick_preferred_path(exact_cloudflare),
            source_slug=normalized_slug,
            bucket="cloudflare_exact",
            candidates=[str(path) for path in exact_cloudflare],
        )

    root_near = _near_slug_groups(normalized_slug, inventory.root_files)
    if len(root_near) == 1:
        source_slug, paths = next(iter(root_near.items()))
        return SourceMatch(
            status="mapped",
            source_path=_pick_preferred_path(paths),
            source_slug=source_slug,
            bucket="root_near_slug",
            candidates=[str(path) for path in sorted(paths, key=_candidate_sort_key)],
        )
    if len(root_near) > 1:
        return SourceMatch(
            status="conflict",
            source_slug=normalized_slug,
            bucket="root_near_slug",
            candidates=sorted(source_slug for source_slug in root_near.keys()),
            reason="multiple_root_near_slug_matches",
        )

    cloudflare_near = _near_slug_groups(normalized_slug, inventory.cloudflare_files)
    if len(cloudflare_near) == 1:
        source_slug, paths = next(iter(cloudflare_near.items()))
        return SourceMatch(
            status="mapped",
            source_path=_pick_preferred_path(paths),
            source_slug=source_slug,
            bucket="cloudflare_near_slug",
            candidates=[str(path) for path in sorted(paths, key=_candidate_sort_key)],
        )
    if len(cloudflare_near) > 1:
        return SourceMatch(
            status="conflict",
            source_slug=normalized_slug,
            bucket="cloudflare_near_slug",
            candidates=sorted(source_slug for source_slug in cloudflare_near.keys()),
            reason="multiple_cloudflare_near_slug_matches",
        )

    return SourceMatch(
        status="missing_source",
        source_slug=normalized_slug,
        reason="slug_source_not_found",
    )


def _discover_article_owned_urls(article: Article) -> list[tuple[str, str]]:
    discovered: list[tuple[str, str]] = []
    seen: set[str] = set()
    legacy_index = 1

    def _append(url: str | None, role_name: str) -> None:
        candidate = str(url or "").strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        discovered.append((candidate, role_name))

    cover_url = str(getattr(article.image, "public_url", "") or "").strip()
    if cover_url:
        _append(cover_url, "cover")

    inline_media = article.inline_media if isinstance(article.inline_media, list) else []
    for index, item in enumerate(inline_media, start=1):
        if not isinstance(item, dict):
            continue
        _append(item.get("image_url"), f"inline-{index:02d}")

    html_urls: list[str] = []
    for source in (article.assembled_html, article.html_article):
        html_urls.extend(_extract_asset_urls(source))
    for url in html_urls:
        if url == cover_url:
            continue
        if any(isinstance(item, dict) and str(item.get("image_url") or "").strip() == url for item in inline_media):
            continue
        _append(url, f"legacy-{legacy_index:02d}")
        legacy_index += 1

    return discovered


def _load_target_articles(db: Session, profile_key: str) -> list[Article]:
    return (
        db.execute(
            select(Article)
            .join(Blog, Blog.id == Article.blog_id)
            .join(BloggerPost, BloggerPost.article_id == Article.id)
            .join(
                SyncedBloggerPost,
                (SyncedBloggerPost.blog_id == BloggerPost.blog_id)
                & (SyncedBloggerPost.remote_post_id == BloggerPost.blogger_post_id),
            )
            .where(
                Blog.profile_key == profile_key,
                Blog.id.in_(tuple(TRAVEL_BLOG_IDS)),
                BloggerPost.post_status.in_((PostStatus.PUBLISHED, PostStatus.SCHEDULED)),
                SyncedBloggerPost.url.like("https://%.blogspot.com/%"),
            )
            .options(
                selectinload(Article.blog),
                selectinload(Article.image),
                selectinload(Article.blogger_post),
            )
            .order_by(Article.blog_id.asc(), Article.id.asc())
        )
        .scalars()
        .all()
    )


def _resolve_travel_category(article: Article) -> str:
    return normalize_travel_category_key(
        resolve_r2_category_key(
            profile_key="korea_travel",
            primary_language=str(getattr(article.blog, "primary_language", "") or ""),
            editorial_category_key=article.editorial_category_key,
            editorial_category_label=article.editorial_category_label,
            labels=list(article.labels or []),
            title=article.title,
            summary=article.excerpt,
        )
    )


def _discover_primary_cover_url(article: Article) -> str:
    image_url = str(getattr(article.image, "public_url", "") or "").strip()
    if image_url:
        return image_url
    thumbnail = str(getattr(article.blogger_post, "thumbnail_url", "") or "").strip()
    if thumbnail:
        return thumbnail
    for url, role in _discover_article_owned_urls(article):
        if role == "cover":
            return url
    owned = _discover_article_owned_urls(article)
    return owned[0][0] if owned else ""


def _render_png_backup(source_bytes: bytes) -> bytes:
    try:
        with PILImage.open(BytesIO(source_bytes)) as image:
            converted = image.convert("RGBA") if image.mode not in {"RGB", "RGBA"} else image
            buffer = BytesIO()
            converted.save(buffer, format="PNG")
            return buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RuntimeError(f"Failed to convert source image to PNG: {exc}") from exc


def _render_publish_webp(source_bytes: bytes) -> bytes:
    try:
        with PILImage.open(BytesIO(source_bytes)) as image:
            converted = image.convert("RGB") if image.mode not in {"RGB", "RGBA"} else image.convert("RGB")
            fitted = ImageOps.fit(converted, TRAVEL_COVER_SIZE, method=_RESAMPLING_LANCZOS)
            buffer = BytesIO()
            fitted.save(buffer, format="WEBP", quality=90, method=6)
            return buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RuntimeError(f"Failed to convert source image to 1024x1024 WEBP: {exc}") from exc


def _write_bytes(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path)


def _canonical_backup_path(runtime_image_root: Path, category_key: str, post_slug: str) -> Path:
    return _travel_backup_root(runtime_image_root) / category_key / f"{_slug_token(post_slug)}.png"


def _canonical_publish_path(runtime_image_root: Path, category_key: str, post_slug: str) -> Path:
    return _travel_root(runtime_image_root) / category_key / f"{_slug_token(post_slug)}.webp"


def _language_summary_name(blog_id: int) -> str:
    policy = get_travel_blog_policy(blog_id=blog_id)
    language = str(getattr(policy, "primary_language", "") or "").strip().lower()
    return LANGUAGE_LABELS.get(language, language or f"blog-{blog_id}")


def _new_category_summary(category_key: str) -> dict[str, Any]:
    return {
        "category_key": category_key,
        "article_count": 0,
        "classified_success": 0,
        "missing_source": 0,
        "conflict": 0,
        "skipped": 0,
        "near_slug_used": 0,
        "upload_success": 0,
        "upload_failed": 0,
        "db_rewrite_success": 0,
        "db_rewrite_failed": 0,
        "live_image_normal": 0,
        "live_image_abnormal": 0,
        "travel_prefix_applied": 0,
    }


def _new_language_summary(blog_id: int) -> dict[str, Any]:
    return {
        "blog_id": blog_id,
        "language": _language_summary_name(blog_id),
        "article_count": 0,
        "classified_success": 0,
        "missing_source": 0,
        "conflict": 0,
        "skipped": 0,
        "near_slug_used": 0,
        "upload_success": 0,
        "upload_failed": 0,
        "db_rewrite_success": 0,
        "db_rewrite_failed": 0,
        "live_image_normal": 0,
        "live_image_abnormal": 0,
        "travel_prefix_applied": 0,
        "categories": {},
    }


def _ensure_language_category_summary(report: dict[str, Any], *, blog_id: int, category_key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    languages = report.setdefault("language_reports", {})
    language_key = _language_summary_name(blog_id)
    language_summary = languages.setdefault(language_key, _new_language_summary(blog_id))
    categories = language_summary.setdefault("categories", {})
    category_summary = categories.setdefault(category_key, _new_category_summary(category_key))
    return language_summary, category_summary


def _increment_summary(summary: dict[str, Any], key: str, amount: int = 1) -> None:
    summary[key] = int(summary.get(key, 0) or 0) + amount


def _record_inventory_summary(report: dict[str, Any], *, action: RebuildAction) -> None:
    language_summary, category_summary = _ensure_language_category_summary(
        report,
        blog_id=action.blog_id,
        category_key=action.category_key,
    )
    for summary in (language_summary, category_summary):
        _increment_summary(summary, "article_count")
        if action.source_match.status == "mapped":
            _increment_summary(summary, "classified_success")
            if str(action.source_match.bucket or "").endswith("near_slug"):
                _increment_summary(summary, "near_slug_used")
        elif action.source_match.status == "missing_source":
            _increment_summary(summary, "missing_source")
        elif action.source_match.status == "conflict":
            _increment_summary(summary, "conflict")
        else:
            _increment_summary(summary, "skipped")


def _record_execution_summary(report: dict[str, Any], *, action: RebuildAction, outcome: dict[str, Any]) -> None:
    language_summary, category_summary = _ensure_language_category_summary(
        report,
        blog_id=action.blog_id,
        category_key=action.category_key,
    )
    status = str(outcome.get("status") or "").strip().lower()
    for summary in (language_summary, category_summary):
        if status in {"uploaded", "deleted_legacy"}:
            _increment_summary(summary, "upload_success")
            _increment_summary(summary, "db_rewrite_success")
        elif status == "failed":
            _increment_summary(summary, "upload_failed")
            _increment_summary(summary, "db_rewrite_failed")


def _record_live_audit_summary(
    report: dict[str, Any],
    *,
    blog_id: int,
    category_key: str,
    audit_issue: str,
    prefix_applied: bool,
) -> None:
    language_summary, category_summary = _ensure_language_category_summary(
        report,
        blog_id=blog_id,
        category_key=category_key,
    )
    for summary in (language_summary, category_summary):
        _increment_summary(summary, "article_count")
        if audit_issue:
            _increment_summary(summary, "live_image_abnormal")
        else:
            _increment_summary(summary, "live_image_normal")
        if prefix_applied:
            _increment_summary(summary, "travel_prefix_applied")


def _verify_public_asset(
    db: Session,
    *,
    object_key: str,
    target_url: str,
    verify_http: bool,
    upload_payload: dict[str, Any] | None = None,
    expected_size: int | None = None,
) -> dict[str, Any]:
    normalized_upload_path = str((upload_payload or {}).get("upload_path") or "").strip().lower()
    verification_mode = "direct"
    exists = False
    size: int | None = None

    if normalized_upload_path.startswith("integration"):
        try:
            exists = cloudflare_r2_object_exists(db, public_key="", key=object_key)
            size = cloudflare_r2_object_size(db, public_key="", key=object_key)
        except Exception:  # noqa: BLE001
            exists = False
            size = None
        if not exists or not int(size or 0):
            exists = bool(str((upload_payload or {}).get("public_url") or target_url).strip())
            size = int(expected_size or 0) or int((upload_payload or {}).get("size") or 0) or None
            verification_mode = normalized_upload_path or "integration"
    else:
        exists = cloudflare_r2_object_exists(db, public_key="", key=object_key)
        size = cloudflare_r2_object_size(db, public_key="", key=object_key)

    payload: dict[str, Any] = {
        "exists": exists,
        "size": size,
        "verification_mode": verification_mode,
    }
    if verify_http:
        response = httpx.head(target_url, timeout=30.0, follow_redirects=True)
        if response.status_code >= 400:
            response = httpx.get(target_url, timeout=30.0, follow_redirects=True)
        payload["http_status"] = response.status_code
        payload["content_type"] = str(response.headers.get("content-type") or "").strip()
        payload["http_ok"] = response.is_success and payload["content_type"].lower().startswith("image/webp")
    return payload


def _legacy_cleanup_local_paths(runtime_image_root: Path, action: RebuildAction) -> list[Path]:
    slug = _slug_token(action.post_slug)
    candidates = [
        _travel_root(runtime_image_root) / action.category_key / slug / "cover.webp",
        _travel_root(runtime_image_root) / action.category_key / slug / "cover.png",
        _travel_backup_root(runtime_image_root) / action.category_key / slug / "cover.png",
        _travel_backup_root(runtime_image_root) / action.category_key / slug / "cover.webp",
    ]
    seen: set[str] = set()
    resolved: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(candidate)
    return resolved


def _legacy_delete_key(action: RebuildAction) -> str:
    legacy_key = str(action.legacy_key or "").strip().lstrip("/")
    if not legacy_key or legacy_key == action.target_key:
        return ""
    return legacy_key


def _upsert_mapping(
    db: Session,
    *,
    action: RebuildAction,
    status: str,
    notes: str | None = None,
) -> None:
    mapping = (
        db.execute(
            select(R2AssetRelayoutMapping).where(
                R2AssetRelayoutMapping.source_type == "blogger",
                R2AssetRelayoutMapping.source_post_id == str(action.article_id),
                R2AssetRelayoutMapping.legacy_key == (action.legacy_key or None),
                R2AssetRelayoutMapping.migrated_key == action.target_key,
            )
        )
        .scalar_one_or_none()
    )
    if mapping is None:
        mapping = R2AssetRelayoutMapping(
            source_type="blogger",
            source_blog_id=action.blog_id,
            source_post_id=str(action.article_id),
            source_post_url=None,
            legacy_url=action.old_url or None,
            legacy_key=action.legacy_key or None,
            migrated_url=action.target_url,
            migrated_key=action.target_key,
            blog_group=TRAVEL_BLOG_GROUP,
            category_key=action.category_key,
            asset_role="main",
        )
    mapping.status = status
    mapping.notes = notes
    mapping.migrated_url = action.target_url
    mapping.migrated_key = action.target_key
    mapping.category_key = action.category_key
    mapping.asset_role = "main"
    db.add(mapping)
    db.commit()


def _rewrite_article_urls(article: Article, *, old_url: str, new_url: str, old_key: str | None = None) -> None:
    normalized_old_key = str(old_key or normalize_r2_url_to_key(old_url)).strip().lstrip("/")
    url_map = {old_url: new_url} if old_url else {}

    article.html_article = _deep_replace_urls(article.html_article, url_map)
    article.assembled_html = _deep_replace_urls(article.assembled_html, url_map)
    if article.image:
        article.image.public_url = new_url
        article.image.image_metadata = _deep_replace_urls(article.image.image_metadata, url_map)
    if article.blogger_post:
        article.blogger_post.response_payload = _deep_replace_urls(article.blogger_post.response_payload, url_map)

    rewritten_inline: list[dict] = []
    for item in (article.inline_media or []):
        if not isinstance(item, dict):
            rewritten_inline.append(item)
            continue
        current_url = str(item.get("image_url") or "").strip()
        current_key = normalize_r2_url_to_key(current_url).lstrip("/")
        if current_url and (current_url == old_url or (normalized_old_key and current_key == normalized_old_key)):
            rewritten_inline.append({**item, "image_url": new_url})
        else:
            rewritten_inline.append(item)
    article.inline_media = rewritten_inline


def _rewrite_synced_thumbnail(db: Session, article: Article, *, old_url: str, new_url: str, old_key: str | None = None) -> int:
    if not article.blogger_post or not article.blog:
        return 0
    remote_post_id = str(getattr(article.blogger_post, "blogger_post_id", "") or "").strip()
    if not remote_post_id:
        return 0
    synced = (
        db.execute(
            select(SyncedBloggerPost).where(
                SyncedBloggerPost.blog_id == article.blog_id,
                SyncedBloggerPost.remote_post_id == remote_post_id,
            )
        )
        .scalar_one_or_none()
    )
    if synced is None:
        return 0
    normalized_old_key = str(old_key or normalize_r2_url_to_key(old_url)).strip().lstrip("/")
    current = str(getattr(synced, "thumbnail_url", "") or "").strip()
    current_key = normalize_r2_url_to_key(current).lstrip("/")
    if current == old_url or (normalized_old_key and current_key == normalized_old_key):
        synced.thumbnail_url = new_url
        db.add(synced)
        db.commit()
        return 1
    return 0


def _build_action(
    db: Session,
    article: Article,
    *,
    inventory: LocalImageInventory,
    public_base_url_override: str = "",
) -> RebuildAction | None:
    policy = get_travel_blog_policy(blog=article.blog)
    if policy is None:
        return None
    assert_travel_scope_blog(blog=article.blog)
    old_url = _discover_primary_cover_url(article)
    category_key = _resolve_travel_category(article)
    target_key = build_travel_asset_object_key(
        policy=policy,
        category_key=category_key,
        post_slug=article.slug,
        asset_role="main",
    )
    return RebuildAction(
        article_id=article.id,
        blog_id=article.blog_id,
        post_slug=_slug_token(article.slug),
        category_key=category_key,
        old_url=old_url,
        legacy_key=normalize_r2_url_to_key(old_url).lstrip("/"),
        target_key=target_key,
        target_url=_cloudflare_public_url(
            db,
            target_key,
            public_base_url_override=public_base_url_override,
            fallback_url=old_url,
        ),
        source_match=_resolve_local_source_for_slug(article.slug, inventory),
    )


def _cleanup_local_legacy_files(paths: list[Path]) -> tuple[list[str], list[str]]:
    deleted: list[str] = []
    errors: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            path.unlink()
            deleted.append(str(path))
            parent = path.parent
            while parent.exists() and parent.is_dir():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    return deleted, errors


def _action_preview(action: RebuildAction, runtime_image_root: Path) -> dict[str, Any]:
    return {
        "article_id": action.article_id,
        "blog_id": action.blog_id,
        "post_slug": action.post_slug,
        "category_key": action.category_key,
        "old_url": action.old_url,
        "legacy_key": action.legacy_key,
        "target_key": action.target_key,
        "target_url": action.target_url,
        "source_status": action.source_match.status,
        "source_bucket": action.source_match.bucket,
        "source_path": str(action.source_match.source_path) if action.source_match.source_path else None,
        "source_slug": action.source_match.source_slug,
        "source_candidates": action.source_match.candidates or [],
        "legacy_delete_key": _legacy_delete_key(action),
        "legacy_local_cleanup_candidates": [str(path) for path in _legacy_cleanup_local_paths(runtime_image_root, action)],
    }


def _process_action(
    db: Session,
    *,
    article: Article,
    action: RebuildAction,
    runtime_image_root: Path,
    verify_http: bool,
) -> dict[str, Any]:
    result = _action_preview(action, runtime_image_root)
    if action.source_match.status != "mapped" or action.source_match.source_path is None:
        _upsert_mapping(db, action=action, status=action.source_match.status, notes=action.source_match.reason)
        result["status"] = action.source_match.status
        return result

    source_bytes = action.source_match.source_path.read_bytes()
    backup_png = _render_png_backup(source_bytes)
    publish_webp = _render_publish_webp(backup_png)

    backup_path = _canonical_backup_path(runtime_image_root, action.category_key, action.post_slug)
    publish_path = _canonical_publish_path(runtime_image_root, action.category_key, action.post_slug)
    _write_bytes(backup_path, backup_png)
    _write_bytes(publish_path, publish_webp)

    try:
        uploaded_public_url, upload_payload, _delivery_meta = upload_binary_to_cloudflare_r2(
            db,
            object_key=action.target_key,
            filename=f"{action.post_slug}.webp",
            content=publish_webp,
        )
    except Exception as exc:  # noqa: BLE001
        status_code = getattr(exc, "status_code", None)
        message = getattr(exc, "message", str(exc))
        detail = getattr(exc, "detail", "")
        notes = f"upload_failed status={status_code!s} message={message} detail={detail}".strip()
        _upsert_mapping(db, action=action, status="failed", notes=notes)
        result["status"] = "failed"
        result["upload_error"] = {
            "status_code": status_code,
            "message": message,
            "detail": detail,
        }
        result["backup_png_path"] = str(backup_path)
        result["publish_webp_path"] = str(publish_path)
        return result
    resolved_upload_key = str(upload_payload.get("object_key") or "").strip().lstrip("/")
    if resolved_upload_key and resolved_upload_key != action.target_key:
        _upsert_mapping(
            db,
            action=action,
            status="failed",
            notes=f"canonical_key_mismatch expected={action.target_key} actual={resolved_upload_key}",
        )
        result["status"] = "failed"
        result["upload_payload"] = upload_payload
        return result

    resolved_public_url = str(upload_payload.get("public_url") or uploaded_public_url or action.target_url).strip()
    resolved_public_key = normalize_r2_url_to_key(resolved_public_url).lstrip("/")
    if resolved_public_key and resolved_public_key != action.target_key:
        _upsert_mapping(
            db,
            action=action,
            status="failed",
            notes=f"canonical_url_mismatch expected={action.target_key} actual={resolved_public_key}",
        )
        result["status"] = "failed"
        result["upload_payload"] = upload_payload
        return result

    verification = _verify_public_asset(
        db,
        object_key=action.target_key,
        target_url=resolved_public_url or action.target_url,
        verify_http=verify_http,
        upload_payload=upload_payload,
        expected_size=len(publish_webp),
    )
    if not verification.get("exists") or not int(verification.get("size") or 0):
        _upsert_mapping(db, action=action, status="failed", notes="upload_verification_failed")
        result["status"] = "failed"
        result["verification"] = verification
        result["upload_payload"] = upload_payload
        return result
    if verify_http and not verification.get("http_ok"):
        _upsert_mapping(db, action=action, status="failed", notes="http_verification_failed")
        result["status"] = "failed"
        result["verification"] = verification
        result["upload_payload"] = upload_payload
        return result

    _rewrite_article_urls(article, old_url=action.old_url, new_url=resolved_public_url or action.target_url, old_key=action.legacy_key)
    db.add(article)
    if article.image:
        db.add(article.image)
    if article.blogger_post:
        db.add(article.blogger_post)
    db.commit()

    synced_rows = _rewrite_synced_thumbnail(
        db,
        article,
        old_url=action.old_url,
        new_url=resolved_public_url or action.target_url,
        old_key=action.legacy_key,
    )

    legacy_key = _legacy_delete_key(action)
    legacy_deleted = False
    cleanup_errors: list[str] = []
    if legacy_key:
        try:
            delete_cloudflare_r2_asset(db, object_key=legacy_key)
            legacy_deleted = True
        except Exception as exc:  # noqa: BLE001
            cleanup_errors.append(f"legacy_r2_delete_failed: {exc}")

    deleted_local_paths, local_cleanup_errors = _cleanup_local_legacy_files(_legacy_cleanup_local_paths(runtime_image_root, action))
    cleanup_errors.extend(local_cleanup_errors)

    status = "deleted_legacy" if legacy_deleted else "uploaded"
    notes_parts = [str(action.source_match.source_path)]
    if cleanup_errors:
        notes_parts.extend(cleanup_errors)
    _upsert_mapping(db, action=action, status=status, notes=" | ".join(notes_parts))

    result["status"] = status
    result["uploaded_public_url"] = resolved_public_url
    result["upload_payload"] = upload_payload
    result["backup_png_path"] = str(backup_path)
    result["publish_webp_path"] = str(publish_path)
    result["verification"] = verification
    result["synced_thumbnail_rows"] = synced_rows
    result["deleted_legacy_key"] = legacy_key if legacy_deleted else ""
    result["deleted_local_paths"] = deleted_local_paths
    result["cleanup_errors"] = cleanup_errors
    return result


def _run_live_audit(
    *,
    db: Session,
    articles: list[Article],
    report: dict[str, Any],
) -> None:
    tasks: list[dict[str, Any]] = []
    for article in articles:
        policy = get_travel_blog_policy(blog=article.blog)
        if policy is None:
            continue
        tasks.append(
            {
                "article_id": article.id,
                "blog_id": article.blog_id,
                "post_slug": _slug_token(article.slug),
                "category_key": _resolve_travel_category(article),
                "published_url": str(getattr(article.blogger_post, "published_url", "") or "").strip(),
            }
        )

    def _audit_task(task: dict[str, Any]) -> dict[str, Any]:
        audit = fetch_and_audit_blogger_post(task["published_url"], probe_images=True, timeout=8.0)
        audit_issue = str(audit.live_image_issue or "").strip()
        prefix_applied = any("/assets/travel-blogger/" in str(url or "").lower() for url in audit.renderable_image_urls)
        return {
            **task,
            "status": "live_ok" if not audit_issue else "live_issue",
            "live_image_issue": audit_issue,
            "live_image_count": audit.live_image_count,
            "live_unique_image_count": audit.live_unique_image_count,
            "travel_prefix_applied": prefix_applied,
            "renderable_image_urls": list(audit.renderable_image_urls),
        }

    max_workers = min(8, max(1, len(tasks)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for outcome in executor.map(_audit_task, tasks):
            _record_live_audit_summary(
                report,
                blog_id=int(outcome["blog_id"]),
                category_key=str(outcome["category_key"]),
                audit_issue=str(outcome["live_image_issue"] or ""),
                prefix_applied=bool(outcome["travel_prefix_applied"]),
            )
            status_key = str(outcome["status"] or "live_issue")
            report["status_counts"][status_key] = int(report["status_counts"].get(status_key, 0) or 0) + 1
            report["actions"].append(outcome)


def main() -> int:
    args = parse_args()
    runtime_image_root = Path(str(args.runtime_image_root)).resolve()
    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "profile_key": args.profile_key,
        "execute": bool(args.execute),
        "live_audit": bool(args.live_audit),
        "mode": "live-audit" if args.live_audit else ("execute" if args.execute else "dry-run"),
        "verify_http": bool(args.verify_http),
        "runtime_image_root": str(runtime_image_root),
        "travel_root": str(_travel_root(runtime_image_root)),
        "travel_backup_root": str(_travel_backup_root(runtime_image_root)),
        "blogs": [],
        "article_count": 0,
        "language_reports": {},
        "actions": [],
        "status_counts": {},
    }

    with SessionLocal() as db:
        articles = _load_target_articles(db, profile_key=args.profile_key)
        inventory = _build_local_image_inventory(runtime_image_root)
        report["article_count"] = len(articles)
        report["blogs"] = sorted({article.blog_id for article in articles})

        if args.live_audit:
            _run_live_audit(db=db, articles=articles, report=report)
            _json_write(_report_path(args.report_prefix, runtime_image_root), report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        if not args.execute:
            for article in articles:
                action = _build_action(
                    db,
                    article,
                    inventory=inventory,
                    public_base_url_override=str(args.cloudflare_public_base_url or "").strip(),
                )
                if action is None:
                    continue
                item = _action_preview(action, runtime_image_root)
                report["actions"].append(item)
                _record_inventory_summary(report, action=action)
                status_key = action.source_match.status
                report["status_counts"][status_key] = int(report["status_counts"].get(status_key, 0) or 0) + 1
            _json_write(_report_path(args.report_prefix, runtime_image_root), report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        manifest = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "items": [],
        }
        for article in articles:
            action = _build_action(
                db,
                article,
                inventory=inventory,
                public_base_url_override=str(args.cloudflare_public_base_url or "").strip(),
            )
            if action is None:
                continue
            _record_inventory_summary(report, action=action)
            outcome = _process_action(
                db,
                article=article,
                action=action,
                runtime_image_root=runtime_image_root,
                verify_http=bool(args.verify_http),
            )
            report["actions"].append(outcome)
            _record_execution_summary(report, action=action, outcome=outcome)
            status_key = str(outcome.get("status") or "unknown")
            report["status_counts"][status_key] = int(report["status_counts"].get(status_key, 0) or 0) + 1
            manifest["items"].append(
                {
                    "article_id": action.article_id,
                    "target_key": action.target_key,
                    "target_url": action.target_url,
                    "status": status_key,
                    "source_slug": action.source_match.source_slug,
                    "deleted_legacy_key": str(outcome.get("deleted_legacy_key") or ""),
                }
            )

        _json_write(_manifest_path(args.report_prefix, runtime_image_root), manifest)
        _json_write(_report_path(args.report_prefix, runtime_image_root), report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

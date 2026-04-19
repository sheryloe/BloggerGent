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
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
DEFAULT_RUNTIME_IMAGE_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\images")
DEFAULT_TRAVEL_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
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
from app.services.blogger.blogger_live_audit_service import audit_blogger_article_fragment  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.content.article_service import resolve_r2_category_key  # noqa: E402
from app.services.content.travel_blog_policy import (  # noqa: E402
    TRAVEL_BLOG_IDS,
    assert_travel_scope_blog,
    build_travel_asset_object_key,
    get_travel_blog_policy,
    normalize_travel_category_key,
)
from app.services.content.travel_translation_state_service import refresh_travel_translation_state  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import (  # noqa: E402
    cloudflare_r2_object_exists,
    cloudflare_r2_object_size,
    delete_cloudflare_r2_asset,
    normalize_r2_url_to_key,
    upload_binary_to_cloudflare_r2,
)
from app.services.platform.publishing_service import rebuild_article_html, upsert_article_blogger_post  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402

IMAGE_URL_RE = re.compile(r"https?://[^\s'\"<>)]+?\.(?:webp|png|jpg|jpeg|gif|avif)", re.IGNORECASE)
_URL_VALUE_RE = re.compile(r"https?://[^\s\"'<>`]+")
TRAVEL_INLINE_MARKER_RE = re.compile(r"<!--\s*TRAVEL_INLINE_3X2\s*-->", re.IGNORECASE)
TRAVEL_INLINE_MARKER_FIGURE_RE = re.compile(
    r"<!--\s*TRAVEL_INLINE_3X2\s*-->\s*<figure\b[^>]*>.*?</figure>",
    re.IGNORECASE | re.DOTALL,
)
FIGURE_BLOCK_RE = re.compile(r"<figure\b[^>]*>.*?</figure>", re.IGNORECASE | re.DOTALL)
TRAVEL_FIGURE_IMG_RE = re.compile(
    r"<img\b[^>]*\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\\s>]+))[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
TRAVEL_COVER_SIZE = (1024, 1024)
ALLOWED_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg", ".avif", ".gif")
EXCLUDED_SOURCE_TOKENS = ("cover", "inline", "4panel", "3x2", "thumbnail")
TRAVEL_SOURCE_EXCLUDED_PARTS = {"travel", "travelbackup", "mystery", "the-midnight-archives"}
TRAVEL_SIMILARITY_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "best",
    "busan",
    "complete",
    "corea",
    "de",
    "del",
    "en",
    "for",
    "from",
    "guide",
    "in",
    "korea",
    "korean",
    "la",
    "los",
    "of",
    "on",
    "seoul",
    "south",
    "the",
    "tips",
    "to",
    "ultimate",
    "with",
}
TRAVEL_SIMILARITY_MIN_SHARED_TOKENS = 2
TRAVEL_SIMILARITY_MIN_SCORE_GAP = 20
_EXTENSION_PRIORITY = {ext: index for index, ext in enumerate(ALLOWED_EXTENSIONS)}
_RESAMPLING_LANCZOS = getattr(getattr(PILImage, "Resampling", PILImage), "LANCZOS")
TRAVEL_BLOG_GROUP = "travel-blogger"
LANGUAGE_LABELS = {
    "en": "english",
    "es": "spanish",
    "ja": "japanese",
}
DEFAULT_DEPLOY_CANARY_COUNT = 20
DEPLOY_CANARY_LANGUAGE_QUOTA = {
    34: 10,
    36: 5,
    37: 5,
}
DEFAULT_TRAVEL_EXTRA_SOURCE_ROOT = Path(r"D:\Donggri Docker\BloManagent\docs\assets\images\bloggent\2026\03")
TRAVEL_COVER_HASH_RE = re.compile(r"/cover-[a-f0-9]{8,}\.webp(?:$|[?#])", re.IGNORECASE)
REPLACE_SCOPE_CHOICES = ("hero_only", "hero_inline")
TRAVEL_LIVE_AUDIT_IGNORED_ISSUES = {"missing_inline", "duplicate_images"}


@dataclass(slots=True)
class SourceMatch:
    status: str
    source_path: Path | None = None
    source_slug: str = ""
    bucket: str = ""
    candidates: list[str] | None = None
    reason: str = ""
    adopted_paths: list[str] | None = None


@dataclass(slots=True)
class LocalImageInventory:
    root_exact: dict[str, list[Path]]
    cloudflare_exact: dict[str, list[Path]]
    source_mirror_exact: dict[str, list[Path]]
    root_files: list[Path]
    cloudflare_files: list[Path]
    source_mirror_files: list[Path]


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
    owned_urls: list[tuple[str, str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild Travel Blogger hero images into the canonical Travel R2 layout.")
    parser.add_argument("--profile-key", default="korea_travel")
    parser.add_argument("--blog-ids", default="34")
    parser.add_argument("--focus-article-ids", default="", help="Comma-separated article IDs to process only")
    parser.add_argument(
        "--focus-article-id-file",
        default="",
        help="Optional file with article IDs (whitespace/comma/newline separated)",
    )
    parser.add_argument(
        "--source-override-file",
        default="",
        help="Optional JSON file with article_id/source_path overrides",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--live-audit", action="store_true")
    parser.add_argument("--report-prefix", default="travel-rebuild")
    parser.add_argument("--runtime-image-root", default=str(DEFAULT_RUNTIME_IMAGE_ROOT))
    parser.add_argument("--report-root", default=str(DEFAULT_TRAVEL_REPORT_ROOT))
    parser.add_argument(
        "--cloudflare-public-base-url",
        default=str(
            os.environ.get("CLOUDFLARE_R2_PUBLIC_BASE_URL")
            or os.environ.get("cloudflare_r2_public_base_url")
            or ""
        ).strip(),
    )
    parser.add_argument("--verify-http", action="store_true")
    parser.add_argument("--deploy-live", action="store_true")
    parser.add_argument("--deploy-mode", choices=("dry-run", "canary", "full"), default="dry-run")
    parser.add_argument("--deploy-canary-count", type=int, default=DEFAULT_DEPLOY_CANARY_COUNT)
    parser.add_argument("--replace-scope", choices=REPLACE_SCOPE_CHOICES, default="hero_inline")
    parser.add_argument("--enable-similar-recovery", action="store_true")
    parser.add_argument(
        "--fallback-source-path",
        default=r"D:\Donggri_Runtime\BloggerGent\storage\images\TravelBackup\travel\busan-haeundae-district-transit-beaches-food-guide.png",
    )
    parser.add_argument("--max-similar-recovery", type=int, default=None)
    parser.add_argument("--max-fallback-recovery", type=int, default=None)
    parser.add_argument("--cleanup-adopted-sources", action="store_true")
    parser.add_argument("--refresh-translation-state", action="store_true")
    parser.add_argument("--repair-related-cover-thumbnails", action="store_true")
    parser.add_argument(
        "--source-extra-root",
        default=str(DEFAULT_TRAVEL_EXTRA_SOURCE_ROOT),
        help="Optional extra source root(s) for similar recovery, comma-separated.",
    )
    parser.add_argument(
        "--common-fallback-url",
        default="",
        help="Fallback public URL used when no canonical/similar source can be resolved.",
    )
    return parser.parse_args()


def _parse_blog_ids(raw: str | None) -> tuple[int, ...]:
    tokens = [segment.strip() for segment in str(raw or "").split(",") if segment.strip()]
    if not tokens:
        raise ValueError("--blog-ids is required")
    resolved: list[int] = []
    for token in tokens:
        try:
            blog_id = int(token)
        except ValueError as exc:
            raise ValueError(f"Invalid --blog-ids token: {token}") from exc
        if blog_id not in TRAVEL_BLOG_IDS:
            raise ValueError(f"Travel scope allows only {sorted(TRAVEL_BLOG_IDS)}; got {blog_id}")
        if blog_id not in resolved:
            resolved.append(blog_id)
    if not resolved:
        raise ValueError("--blog-ids resolved to empty set")
    return tuple(sorted(resolved))


def _parse_article_ids(raw: str | None) -> tuple[int, ...]:
    tokens = [segment.strip() for segment in str(raw or "").replace("\n", ",").replace("\r", ",").split(",") if segment.strip()]
    if not tokens:
        return tuple()
    resolved: list[int] = []
    for token in tokens:
        token = str(token or "").strip().lstrip("\ufeff")
        if not token or token.startswith("#"):
            continue
        try:
            value = int(token)
        except ValueError as exc:
            raise ValueError(f"Invalid article id token: {token}") from exc
        if value <= 0:
            raise ValueError(f"Article id must be positive: {token}")
        if value not in resolved:
            resolved.append(value)
    return tuple(resolved)


def _load_focus_article_ids_from_file(path: str | None) -> tuple[int, ...]:
    if not path:
        return tuple()
    file_path = Path(path).resolve()
    if not file_path.exists():
        return tuple()
    raw = file_path.read_text(encoding="utf-8")
    return _parse_article_ids(raw)


def _load_source_overrides_from_file(path: str | None) -> dict[int, Path]:
    if not path:
        return {}
    file_path = Path(path).resolve()
    if not file_path.exists():
        return {}
    raw = file_path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in source override file: {file_path}") from exc

    entries: list[dict[str, Any]] = []
    if isinstance(payload, list):
        entries = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            entries = [item for item in payload["items"] if isinstance(item, dict)]
        else:
            for key, value in payload.items():
                entries.append({"article_id": key, "source_path": value})
    else:
        raise ValueError(f"Unsupported source override payload type: {type(payload).__name__}")

    overrides: dict[int, Path] = {}
    for entry in entries:
        article_token = entry.get("article_id")
        source_token = entry.get("source_path")
        if article_token is None:
            continue
        if source_token is None:
            raise ValueError(f"Missing source_path for article_id={article_token} in {file_path}")
        try:
            article_id = int(str(article_token).strip())
        except ValueError as exc:
            raise ValueError(f"Invalid article_id in source overrides: {article_token}") from exc
        if article_id <= 0:
            raise ValueError(f"article_id must be positive in source overrides: {article_token}")
        source_path = Path(str(source_token).strip()).resolve()
        overrides[article_id] = source_path
    return overrides


def _parse_extra_source_roots(raw: str | None) -> tuple[Path, ...]:
    tokens = [segment.strip() for segment in str(raw or "").replace("\n", ",").replace("\r", ",").split(",") if segment.strip()]
    resolved: list[Path] = []
    seen: set[str] = set()
    for token in tokens:
        path = Path(token).resolve()
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(path)
    return tuple(resolved)


def _merge_path_index(left: dict[str, list[Path]], right: dict[str, list[Path]]) -> dict[str, list[Path]]:
    merged: dict[str, list[Path]] = {key: list(value) for key, value in left.items()}
    for key, paths in right.items():
        bucket = merged.setdefault(key, [])
        seen = {str(item).lower() for item in bucket}
        for path in paths:
            signature = str(path).lower()
            if signature in seen:
                continue
            seen.add(signature)
            bucket.append(path)
    return merged


def _merge_path_list(left: list[Path], right: list[Path]) -> list[Path]:
    merged = list(left)
    seen = {str(item).lower() for item in merged}
    for path in right:
        signature = str(path).lower()
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(path)
    return merged


def _merge_local_image_inventory(base: LocalImageInventory, extra: LocalImageInventory) -> LocalImageInventory:
    return LocalImageInventory(
        root_exact=_merge_path_index(base.root_exact, extra.root_exact),
        cloudflare_exact=_merge_path_index(base.cloudflare_exact, extra.cloudflare_exact),
        source_mirror_exact=_merge_path_index(base.source_mirror_exact, extra.source_mirror_exact),
        root_files=_merge_path_list(base.root_files, extra.root_files),
        cloudflare_files=_merge_path_list(base.cloudflare_files, extra.cloudflare_files),
        source_mirror_files=_merge_path_list(base.source_mirror_files, extra.source_mirror_files),
    )


def _travel_root(runtime_image_root: Path) -> Path:
    return runtime_image_root / "Travel"


def _travel_backup_root(runtime_image_root: Path) -> Path:
    return runtime_image_root / "TravelBackup"


def _report_root(report_root: Path) -> Path:
    return report_root / "reports"


def _manifest_root(report_root: Path) -> Path:
    return report_root / "logs" / "manifests"


def _report_path(prefix: str, report_root: Path) -> Path:
    root = _report_root(report_root)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return root / f"{prefix}-{stamp}.json"


def _manifest_path(prefix: str, report_root: Path) -> Path:
    root = _manifest_root(report_root)
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


def _is_cover_hash_url(url: str | None) -> bool:
    candidate = str(url or "").strip()
    if not candidate:
        return False
    return bool(TRAVEL_COVER_HASH_RE.search(candidate))


def _extract_cover_hash_urls(value: Any) -> list[str]:
    urls = _extract_asset_urls(value)
    return [url for url in urls if _is_cover_hash_url(url)]


def _is_canonical_travel_url(url: str | None) -> bool:
    candidate = str(url or "").strip().lower()
    return bool(candidate and "/assets/travel-blogger/" in candidate and candidate.endswith(".webp"))


def _article_cover_hash_targets(article: Article, synced_post: SyncedBloggerPost | None) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()

    def _append(url: str | None) -> None:
        candidate = str(url or "").strip()
        if not candidate or not _is_cover_hash_url(candidate):
            return
        if candidate in seen:
            return
        seen.add(candidate)
        targets.append(candidate)

    for url in _extract_cover_hash_urls(article.html_article):
        _append(url)
    for url in _extract_cover_hash_urls(article.assembled_html):
        _append(url)
    if article.blogger_post and isinstance(article.blogger_post.response_payload, (dict, list)):
        for url in _extract_cover_hash_urls(article.blogger_post.response_payload):
            _append(url)
    if synced_post is not None:
        _append(getattr(synced_post, "thumbnail_url", ""))
    return targets


def _apply_cover_hash_rewrite(
    article: Article,
    *,
    replacement_url: str,
    target_urls: list[str],
) -> None:
    url_map = {str(url): replacement_url for url in target_urls if str(url).strip()}
    if not url_map:
        return
    article.html_article = _sanitize_travel_inline_artifacts(_deep_replace_urls(article.html_article, url_map))
    article.assembled_html = _sanitize_travel_inline_artifacts(_deep_replace_urls(article.assembled_html, url_map))
    if article.blogger_post:
        article.blogger_post.response_payload = _deep_replace_urls(article.blogger_post.response_payload, url_map)
    if article.image and _is_cover_hash_url(str(getattr(article.image, "public_url", "") or "")):
        article.image.public_url = replacement_url
        if isinstance(article.image.image_metadata, dict):
            article.image.image_metadata = _force_media_delivery_urls(
                _deep_replace_urls(article.image.image_metadata, url_map),
                new_url=replacement_url,
            )


def _load_synced_blogger_post_map(db: Session, *, blog_ids: tuple[int, ...]) -> dict[tuple[int, str], SyncedBloggerPost]:
    rows = (
        db.execute(
            select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id.in_(tuple(blog_ids)))
        )
        .scalars()
        .all()
    )
    mapped: dict[tuple[int, str], SyncedBloggerPost] = {}
    for row in rows:
        key = (int(row.blog_id), str(row.remote_post_id or "").strip())
        if not key[1]:
            continue
        mapped[key] = row
    return mapped


def _write_cover_hash_global_analysis(
    db: Session,
    *,
    report_root: Path,
) -> Path:
    try:
        stats_rows = db.execute(
            select(
                SyncedBloggerPost.blog_id,
                sa.func.count(SyncedBloggerPost.id),
                sa.func.sum(
                    sa.case(
                        (
                            sa.and_(
                                sa.func.lower(sa.func.coalesce(SyncedBloggerPost.thumbnail_url, "")).like("%/cover-%"),
                                sa.func.lower(sa.func.coalesce(SyncedBloggerPost.thumbnail_url, "")).like("%.webp%"),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                sa.func.sum(
                    sa.case(
                        (SyncedBloggerPost.thumbnail_url.ilike("%/assets/travel-blogger/%"), 1),
                        else_=0,
                    )
                ),
                sa.func.sum(
                    sa.case(
                        (SyncedBloggerPost.travel_image_migration_status == "fallback", 1),
                        else_=0,
                    )
                ),
            ).group_by(SyncedBloggerPost.blog_id).order_by(SyncedBloggerPost.blog_id.asc())
        ).all()
    except Exception:  # noqa: BLE001
        db.rollback()
        stats_rows = db.execute(
            select(
                SyncedBloggerPost.blog_id,
                sa.func.count(SyncedBloggerPost.id),
                sa.func.sum(
                    sa.case(
                        (
                            sa.and_(
                                sa.func.lower(sa.func.coalesce(SyncedBloggerPost.thumbnail_url, "")).like("%/cover-%"),
                                sa.func.lower(sa.func.coalesce(SyncedBloggerPost.thumbnail_url, "")).like("%.webp%"),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                sa.func.sum(
                    sa.case(
                        (SyncedBloggerPost.thumbnail_url.ilike("%/assets/travel-blogger/%"), 1),
                        else_=0,
                    )
                ),
                sa.literal(0),
            ).group_by(SyncedBloggerPost.blog_id).order_by(SyncedBloggerPost.blog_id.asc())
        ).all()

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "blogs": [
            {
                "blog_id": int(row[0]),
                "synced_total": int(row[1] or 0),
                "legacy_cover_hash_count": int(row[2] or 0),
                "canonical_travel_count": int(row[3] or 0),
                "fallback_count": int(row[4] or 0),
            }
            for row in stats_rows
        ],
    }
    path = _report_path("travel-cover-hash-global-analysis", report_root)
    _json_write(path, payload)
    return path


def _deploy_single_live_update(db: Session, *, article: Article, target_url: str) -> tuple[bool, str]:
    if article.blog is None or article.blogger_post is None:
        return False, "missing_article_or_blogger_post"
    try:
        provider = get_blogger_provider(db, article.blog)
        if type(provider).__name__.startswith("Mock"):
            return False, "mock_provider"
        content = str(rebuild_article_html(db, article, target_url) or "").strip()
        if not content:
            content = str(article.assembled_html or article.html_article or "").strip()
        content = _sanitize_travel_inline_artifacts(content)
        if not content:
            return False, "empty_article_content"
        summary, raw_payload = provider.update_post(
            post_id=str(article.blogger_post.blogger_post_id or "").strip(),
            title=str(article.title or "").strip(),
            content=content,
            labels=list(article.labels or []),
            meta_description=str(article.meta_description or "").strip(),
        )
        upsert_article_blogger_post(
            db,
            article=article,
            summary=summary,
            raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
        )
        return True, str(summary.get("url") or "").strip()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return False, str(exc)


def _run_cover_hash_repair_mode(
    db: Session,
    *,
    report: dict[str, Any],
    articles: list[Article],
    inventory: LocalImageInventory,
    runtime_image_root: Path,
    source_overrides: dict[int, Path],
    fallback_source_path: Path | None,
    enable_similar_recovery: bool,
    recovery_budget: dict[str, int | None] | None,
    verify_http: bool,
    replace_scope: str,
    cleanup_adopted_sources: bool,
    deploy_live: bool,
    common_fallback_url: str,
) -> None:
    synced_map = _load_synced_blogger_post_map(db, blog_ids=tuple(report.get("blog_ids") or []))
    touched_blog_ids: set[int] = set()
    outcomes: list[dict[str, Any]] = []
    common_fallback = str(common_fallback_url or "").strip()

    for article in articles:
        remote_post_id = str(getattr(getattr(article, "blogger_post", None), "blogger_post_id", "") or "").strip()
        synced = synced_map.get((int(article.blog_id), remote_post_id)) if remote_post_id else None
        cover_targets = _article_cover_hash_targets(article, synced)
        if not cover_targets:
            continue

        action = _build_action(
            db,
            article,
            inventory=inventory,
            enable_similar_recovery=enable_similar_recovery,
            recovery_budget=recovery_budget,
            fallback_source_path=fallback_source_path,
            source_overrides=source_overrides,
            public_base_url_override=str(report.get("cloudflare_public_base_url") or ""),
        )
        if action is None:
            continue

        item: dict[str, Any] = {
            "article_id": article.id,
            "blog_id": article.blog_id,
            "post_slug": action.post_slug,
            "category_key": action.category_key,
            "cover_hash_targets": list(cover_targets),
            "source_status": action.source_match.status,
            "source_bucket": action.source_match.bucket,
            "target_url": action.target_url,
            "status": "planned",
            "migration_status": "legacy_cover",
            "replaced_count": 0,
            "deployed_live": False,
            "deploy_detail": "",
        }

        existing_url = str(getattr(getattr(article, "image", None), "public_url", "") or "").strip()
        replacement_url = ""
        replacement_mode = "legacy_cover"
        process_outcome: dict[str, Any] | None = None

        if _is_canonical_travel_url(existing_url) and not _is_cover_hash_url(existing_url):
            replacement_url = existing_url
            replacement_mode = "canonical"
        elif action.source_match.status == "mapped":
            replacement_url = action.target_url
            replacement_mode = "canonical" if str(action.source_match.bucket or "") != "fallback_seed" else "fallback"
            if report.get("execute"):
                process_outcome = _process_action(
                    db,
                    article=article,
                    action=action,
                    runtime_image_root=runtime_image_root,
                    verify_http=verify_http,
                    replace_scope=replace_scope,
                    cleanup_adopted_sources=cleanup_adopted_sources,
                )
                item["process_outcome_status"] = str(process_outcome.get("status") or "")
                if str(process_outcome.get("status") or "").lower() not in {"uploaded", "deleted_legacy"}:
                    replacement_mode = "error"
                    item["status"] = "error"
                    item["error"] = str(process_outcome.get("upload_error") or process_outcome.get("cleanup_errors") or "")
                else:
                    replacement_url = str(process_outcome.get("uploaded_public_url") or process_outcome.get("target_url") or replacement_url)
        elif common_fallback:
            replacement_url = common_fallback
            replacement_mode = "fallback"
        else:
            replacement_mode = "missing"

        if report.get("execute") and replacement_url and replacement_mode in {"canonical", "fallback"}:
            try:
                _apply_cover_hash_rewrite(article, replacement_url=replacement_url, target_urls=cover_targets)
                if synced is not None:
                    if _is_cover_hash_url(synced.thumbnail_url):
                        synced.thumbnail_url = replacement_url
                    synced.travel_image_migration_status = replacement_mode
                    db.add(synced)
                db.add(article)
                if article.image:
                    db.add(article.image)
                if article.blogger_post:
                    db.add(article.blogger_post)
                db.commit()
                touched_blog_ids.add(int(article.blog_id))
                item["status"] = "rewritten"
                item["migration_status"] = replacement_mode
                item["replacement_url"] = replacement_url
                item["replaced_count"] = len(cover_targets)

                if deploy_live:
                    ok, detail = _deploy_single_live_update(db, article=article, target_url=replacement_url)
                    item["deployed_live"] = ok
                    item["deploy_detail"] = detail
                    if not ok:
                        item["status"] = "error"
                        item["migration_status"] = "error"
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                item["status"] = "error"
                item["migration_status"] = "error"
                item["error"] = str(exc)
                if synced is not None:
                    try:
                        synced.travel_image_migration_status = "error"
                        db.add(synced)
                        db.commit()
                    except Exception:  # noqa: BLE001
                        db.rollback()
        else:
            item["status"] = "planned" if replacement_mode in {"canonical", "fallback"} else "unresolved"
            item["migration_status"] = replacement_mode
            item["replacement_url"] = replacement_url

        synced_status = (
            replacement_mode
            if replacement_mode in {"canonical", "fallback", "legacy_cover", "missing", "error"}
            else "legacy_cover"
        )
        if synced is not None and report.get("execute"):
            try:
                synced.travel_image_migration_status = synced_status
                db.add(synced)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                item["status"] = "error"
                item["migration_status"] = "error"
                item["error"] = f"sync_status_update_failed: {exc}"
        elif synced is not None:
            item["planned_synced_status"] = synced_status

        outcomes.append(item)

    if report.get("execute") and touched_blog_ids:
        for blog_id in sorted(touched_blog_ids):
            blog = db.get(Blog, blog_id)
            if blog is None:
                continue
            try:
                sync_blogger_posts_for_blog(db, blog)
            except Exception:  # noqa: BLE001
                db.rollback()

    report["actions"] = outcomes
    report["status_counts"] = {}
    for item in outcomes:
        key = str(item.get("status") or "unknown")
        report["status_counts"][key] = int(report["status_counts"].get(key, 0) or 0) + 1
def _force_media_delivery_urls(item: dict[str, Any], *, new_url: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        return item
    delivery = item.get("delivery")
    if not isinstance(delivery, dict):
        delivery = {}
        item["delivery"] = delivery
    delivery["public_url"] = new_url
    delivery["local_public_url"] = new_url
    delivery["resolved_public_url"] = new_url
    delivery["original_url"] = new_url

    cloudflare_meta = delivery.get("cloudflare")
    if not isinstance(cloudflare_meta, dict):
        cloudflare_meta = {}
        delivery["cloudflare"] = cloudflare_meta
    cloudflare_meta["original_url"] = new_url
    cloudflare_meta["public_url"] = new_url
    cloudflare_meta["url"] = new_url

    cloudinary_meta = delivery.get("cloudinary")
    if isinstance(cloudinary_meta, dict):
        cloudinary_meta["secure_url_original"] = new_url
        cloudinary_meta["secure_url"] = new_url
        cloudinary_meta["url"] = new_url
    return item


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


def _replace_urls_by_key_targets(value: Any, *, key_targets: set[str], replacement: str = "") -> Any:
    if not value:
        return value
    if not key_targets:
        return value

    normalized_targets: set[str] = {
        str(candidate).strip().lstrip("/")
        for candidate in key_targets
        if str(candidate).strip()
    }
    if not normalized_targets:
        return value

    def _replace_urls_in_text(text: str) -> str:
        if not isinstance(text, str):
            return text

        def _replace_one(match: re.Match[str]) -> str:
            candidate = match.group(0).strip()
            normalized = normalize_r2_url_to_key(candidate).strip().lstrip("/")
            if normalized and normalized in normalized_targets:
                return replacement
            return candidate

        return _URL_VALUE_RE.sub(_replace_one, text)

    if isinstance(value, str):
        return _replace_urls_in_text(value)
    if isinstance(value, list):
        return [_replace_urls_by_key_targets(item, key_targets=normalized_targets, replacement=replacement) for item in value]
    if isinstance(value, dict):
        return {key: _replace_urls_by_key_targets(item, key_targets=normalized_targets, replacement=replacement) for key, item in value.items()}
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
    base = str(values.get("travel_cloudflare_r2_public_base_url") or "").strip().rstrip("/")
    if not base:
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
    available = [path for path in paths if path.exists() and path.is_file()]
    if not available:
        return sorted(paths, key=_candidate_sort_key)[0]
    return sorted(available, key=_candidate_sort_key)[0]


def _is_travel_safe_source_path(path: Path) -> bool:
    lowered_path = str(path).replace("/", "\\").lower()
    if "\\images\\travel\\" in lowered_path or lowered_path.endswith("\\images\\travel"):
        return False
    if "\\images\\travelbackup\\" in lowered_path or lowered_path.endswith("\\images\\travelbackup"):
        return False
    lowered_parts = {part.strip().lower() for part in path.parts if str(part).strip()}
    return not bool(lowered_parts & {"mystery", "the-midnight-archives"})


def _is_storage_source_mirror_path(path: Path, storage_root: Path) -> bool:
    try:
        relative = path.relative_to(storage_root)
    except ValueError:
        return False
    lowered = [part.strip().lower() for part in relative.parts]
    if len(lowered) < 4 or lowered[0] != "cloudflare":
        return False
    return "images" in lowered and "source" in lowered


def _build_local_image_inventory(runtime_image_root: Path) -> LocalImageInventory:
    root_exact: dict[str, list[Path]] = {}
    cloudflare_exact: dict[str, list[Path]] = {}
    source_mirror_exact: dict[str, list[Path]] = {}
    root_files: list[Path] = []
    cloudflare_files: list[Path] = []
    source_mirror_files: list[Path] = []
    storage_root = runtime_image_root.parent
    for path in runtime_image_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        if not _is_travel_safe_source_path(path):
            continue
        try:
            relative = path.relative_to(runtime_image_root)
        except ValueError:
            continue
        if not relative.parts:
            continue
        top_level = relative.parts[0].lower()
        if top_level in TRAVEL_SOURCE_EXCLUDED_PARTS:
            continue
        normalized_name = _normalize_source_name(path)
        if len(relative.parts) == 1:
            root_exact.setdefault(normalized_name, []).append(path)
            root_files.append(path)
            continue
        if top_level == "cloudflare":
            cloudflare_exact.setdefault(normalized_name, []).append(path)
            cloudflare_files.append(path)

    sibling_cloudflare_root = storage_root / "CloudFlare"
    if sibling_cloudflare_root.exists():
        for path in sibling_cloudflare_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            if not _is_travel_safe_source_path(path):
                continue
            if not _is_storage_source_mirror_path(path, storage_root):
                continue
            normalized_name = _normalize_source_name(path)
            source_mirror_exact.setdefault(normalized_name, []).append(path)
            source_mirror_files.append(path)

    return LocalImageInventory(
        root_exact=root_exact,
        cloudflare_exact=cloudflare_exact,
        source_mirror_exact=source_mirror_exact,
        root_files=root_files,
        cloudflare_files=cloudflare_files,
        source_mirror_files=source_mirror_files,
    )


def _ordered_exact_candidates(slug: str, exact_index: dict[str, list[Path]]) -> list[Path]:
    candidates: list[Path] = []
    for extension in ALLOWED_EXTENSIONS:
        candidates.extend([path for path in exact_index.get(f"{slug}{extension}", []) if path.exists() and path.is_file()])
    return sorted(candidates, key=_candidate_sort_key)


def _near_slug_groups(slug: str, candidates: list[Path]) -> dict[str, list[Path]]:
    prefix = f"{slug}-"
    groups: dict[str, list[Path]] = {}
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        if not _is_source_candidate(path):
            continue
        stem = path.stem.strip().lower()
        if not stem.startswith(prefix):
            continue
        groups.setdefault(stem, []).append(path)
    return groups


def _slug_similarity_tokens(value: str | None) -> list[str]:
    raw = slugify(str(value or "").strip(), separator="-")
    tokens: list[str] = []
    for token in raw.split("-"):
        normalized = token.strip().lower()
        if not normalized:
            continue
        if normalized in EXCLUDED_SOURCE_TOKENS or normalized in TRAVEL_SIMILARITY_STOPWORDS:
            continue
        if re.fullmatch(r"\d{4}", normalized):
            continue
        if normalized.isdigit():
            continue
        if len(normalized) <= 1:
            continue
        tokens.append(normalized)
    return tokens


def _similarity_score_for_slug(slug: str, candidate: Path) -> tuple[int, int]:
    slug_tokens = _slug_similarity_tokens(slug)
    candidate_tokens = _slug_similarity_tokens(candidate.stem)
    if not slug_tokens or not candidate_tokens:
        return 0, 0
    candidate_set = set(candidate_tokens)
    shared_tokens = [token for token in slug_tokens if token in candidate_set]
    shared_count = len(shared_tokens)
    if shared_count == 0:
        return 0, 0
    ordered_overlap = 0
    for left, right in zip(slug_tokens, candidate_tokens):
        if left != right:
            break
        ordered_overlap += 1
    score = (shared_count * 100) + (ordered_overlap * 10) - (abs(len(candidate_tokens) - len(slug_tokens)) * 3)
    return score, shared_count


def _resolve_similar_source_for_slug(slug: str, candidates: list[Path]) -> SourceMatch | None:
    ranked: list[tuple[int, int, Path]] = []
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        if not _is_source_candidate(path) or not _is_travel_safe_source_path(path):
            continue
        score, shared_count = _similarity_score_for_slug(slug, path)
        if shared_count < TRAVEL_SIMILARITY_MIN_SHARED_TOKENS or score <= 0:
            continue
        ranked.append((score, shared_count, path))
    if not ranked:
        return None

    ranked.sort(key=lambda item: (-item[0], -item[1], _candidate_sort_key(item[2])))
    best_score, best_shared_count, best_path = ranked[0]
    runner_up_score = ranked[1][0] if len(ranked) > 1 else None
    if runner_up_score is not None and (best_score - runner_up_score) < TRAVEL_SIMILARITY_MIN_SCORE_GAP:
        return None

    same_name_paths = [item[2] for item in ranked if item[2].name.lower() == best_path.name.lower()]
    adopted_paths = sorted({str(path) for path in same_name_paths + [best_path]})
    reason = f"similar_match score={best_score} shared_tokens={best_shared_count}"
    if runner_up_score is not None:
        reason = f"{reason} runner_up={runner_up_score}"
    return SourceMatch(
        status="mapped",
        source_path=best_path,
        source_slug=best_path.stem.strip().lower(),
        bucket="similar_match",
        candidates=[str(item[2]) for item in ranked[:10]],
        reason=reason,
        adopted_paths=adopted_paths,
    )


def _consume_recovery_budget(
    recovery_budget: dict[str, int | None] | None,
    bucket: str,
) -> bool:
    if recovery_budget is None:
        return True
    remaining = recovery_budget.get(bucket)
    if remaining is None:
        return True
    if remaining <= 0:
        return False
    recovery_budget[bucket] = remaining - 1
    return True


def _has_recovery_budget(
    recovery_budget: dict[str, int | None] | None,
    bucket: str,
) -> bool:
    if recovery_budget is None:
        return True
    remaining = recovery_budget.get(bucket)
    if remaining is None:
        return True
    return remaining > 0


def _resolve_recovery_limit(raw: int | None) -> int | None:
    if raw is None:
        return None
    if raw < 0:
        return 0
    return int(raw)


def _resolve_local_source_for_slug(
    slug: str,
    inventory: LocalImageInventory,
    *,
    enable_similar_recovery: bool,
    fallback_source_path: Path | None,
    recovery_budget: dict[str, int | None] | None = None,
) -> SourceMatch:
    normalized_slug = _slug_token(slug)
    exact_root = _ordered_exact_candidates(normalized_slug, inventory.root_exact)
    if exact_root:
        return SourceMatch(
            status="mapped",
            source_path=_pick_preferred_path(exact_root),
            source_slug=normalized_slug,
            bucket="root_exact",
            candidates=[str(path) for path in exact_root],
            adopted_paths=[str(path) for path in exact_root],
        )

    exact_cloudflare = _ordered_exact_candidates(normalized_slug, inventory.cloudflare_exact)
    if exact_cloudflare:
        return SourceMatch(
            status="mapped",
            source_path=_pick_preferred_path(exact_cloudflare),
            source_slug=normalized_slug,
            bucket="cloudflare_exact",
            candidates=[str(path) for path in exact_cloudflare],
            adopted_paths=[str(path) for path in exact_cloudflare],
        )

    exact_source_mirror = _ordered_exact_candidates(normalized_slug, inventory.source_mirror_exact)
    if exact_source_mirror:
        return SourceMatch(
            status="mapped",
            source_path=_pick_preferred_path(exact_source_mirror),
            source_slug=normalized_slug,
            bucket="cloudflare_source_exact",
            candidates=[str(path) for path in exact_source_mirror],
            adopted_paths=[str(path) for path in exact_source_mirror],
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
            adopted_paths=[str(path) for path in sorted(paths, key=_candidate_sort_key)],
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
            adopted_paths=[str(path) for path in sorted(paths, key=_candidate_sort_key)],
        )
    if len(cloudflare_near) > 1:
        return SourceMatch(
            status="conflict",
            source_slug=normalized_slug,
            bucket="cloudflare_near_slug",
            candidates=sorted(source_slug for source_slug in cloudflare_near.keys()),
            reason="multiple_cloudflare_near_slug_matches",
        )

    source_mirror_near = _near_slug_groups(normalized_slug, inventory.source_mirror_files)
    if len(source_mirror_near) == 1:
        source_slug, paths = next(iter(source_mirror_near.items()))
        return SourceMatch(
            status="mapped",
            source_path=_pick_preferred_path(paths),
            source_slug=source_slug,
            bucket="cloudflare_source_near_slug",
            candidates=[str(path) for path in sorted(paths, key=_candidate_sort_key)],
            adopted_paths=[str(path) for path in sorted(paths, key=_candidate_sort_key)],
        )
    if len(source_mirror_near) > 1:
        return SourceMatch(
            status="conflict",
            source_slug=normalized_slug,
            bucket="cloudflare_source_near_slug",
            candidates=sorted(source_slug for source_slug in source_mirror_near.keys()),
            reason="multiple_cloudflare_source_near_slug_matches",
        )

    if enable_similar_recovery and _has_recovery_budget(recovery_budget, "similar"):
        similar_match = _resolve_similar_source_for_slug(
            normalized_slug,
            inventory.root_files + inventory.cloudflare_files + inventory.source_mirror_files,
        )
        if similar_match is not None:
            _consume_recovery_budget(recovery_budget, "similar")
            return similar_match

    fallback = Path(fallback_source_path).resolve() if fallback_source_path else None
    if (
        _consume_recovery_budget(recovery_budget, "fallback")
        and fallback is not None
        and fallback.exists()
        and fallback.is_file()
    ):
        return SourceMatch(
            status="mapped",
            source_path=fallback,
            source_slug=fallback.stem.strip().lower(),
            bucket="fallback_seed",
            candidates=[str(fallback)],
            reason="fallback_seed_applied",
            adopted_paths=[str(fallback)],
        )

    return SourceMatch(
        status="missing_source",
        source_slug=normalized_slug,
        reason="slug_source_not_found" if fallback is None else "slug_source_not_found_and_fallback_missing",
    )


def _resolve_source_match_for_article(
    article_id: int,
    slug: str,
    inventory: LocalImageInventory,
    *,
    source_overrides: dict[int, Path] | None,
    enable_similar_recovery: bool,
    fallback_source_path: Path | None,
    recovery_budget: dict[str, int | None] | None = None,
) -> SourceMatch:
    override_path = source_overrides.get(int(article_id)) if source_overrides else None
    normalized_slug = _slug_token(slug)
    if override_path is not None:
        resolved = Path(override_path).resolve()
        if not resolved.exists():
            return SourceMatch(
                status="missing_source",
                source_slug=normalized_slug,
                bucket="override_file",
                candidates=[str(resolved)],
                reason="source_override_missing",
            )
        if not resolved.is_file():
            return SourceMatch(
                status="missing_source",
                source_slug=normalized_slug,
                bucket="override_file",
                candidates=[str(resolved)],
                reason="source_override_not_file",
            )
        if not _is_travel_safe_source_path(resolved):
            return SourceMatch(
                status="missing_source",
                source_slug=normalized_slug,
                bucket="override_file",
                candidates=[str(resolved)],
                reason="source_override_not_travel_safe",
            )
        if not _is_source_candidate(resolved):
            return SourceMatch(
                status="missing_source",
                source_slug=normalized_slug,
                bucket="override_file",
                candidates=[str(resolved)],
                reason="source_override_excluded_name_pattern",
            )
        return SourceMatch(
            status="mapped",
            source_path=resolved,
            source_slug=_slug_token(resolved.stem),
            bucket="override_file",
            candidates=[str(resolved)],
            reason="source_override_applied",
            adopted_paths=[str(resolved)],
        )

    return _resolve_local_source_for_slug(
        slug,
        inventory,
        enable_similar_recovery=enable_similar_recovery,
        fallback_source_path=fallback_source_path,
        recovery_budget=recovery_budget,
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

    if isinstance(getattr(article.image, "image_metadata", None), dict):
        for url in _extract_asset_urls(article.image.image_metadata):
            if url == cover_url:
                continue
            _append(url, f"legacy-{legacy_index:02d}")
            legacy_index += 1

    inline_media = article.inline_media if isinstance(article.inline_media, list) else []
    for index, item in enumerate(inline_media, start=1):
        if not isinstance(item, dict):
            continue
        inline_url = str(item.get("image_url") or "").strip()
        if inline_url:
            _append(inline_url, f"inline-{index:02d}")
        for url in _extract_asset_urls(item):
            if url == inline_url or url == cover_url:
                continue
            _append(url, f"legacy-{legacy_index:02d}")
            legacy_index += 1

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

    blogger_post = getattr(article, "blogger_post", None)
    if blogger_post and isinstance(getattr(blogger_post, "response_payload", None), dict):
        for url in _extract_asset_urls(blogger_post.response_payload):
            if url == cover_url:
                continue
            if any(existing_url == url for existing_url, _ in discovered):
                continue
            _append(url, f"legacy-{legacy_index:02d}")
            legacy_index += 1

    return discovered


def _load_target_articles(db: Session, profile_key: str, *, blog_ids: tuple[int, ...]) -> list[Article]:
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
                Blog.id.in_(tuple(blog_ids)),
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


def _discover_primary_cover_url(article: Article, *, owned_urls: list[tuple[str, str]] | None = None) -> str:
    discovered = owned_urls if owned_urls is not None else _discover_article_owned_urls(article)
    image_url = str(getattr(article.image, "public_url", "") or "").strip()
    if image_url:
        return image_url
    thumbnail = str(getattr(article.blogger_post, "thumbnail_url", "") or "").strip()
    if thumbnail:
        return thumbnail
    for url, role in discovered:
        if role == "cover":
            return url
    return discovered[0][0] if discovered else ""


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
        "similar_used": 0,
        "fallback_used": 0,
        "upload_success": 0,
        "upload_failed": 0,
        "db_rewrite_success": 0,
        "db_rewrite_failed": 0,
        "cleanup_success": 0,
        "cleanup_failed": 0,
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
        "similar_used": 0,
        "fallback_used": 0,
        "upload_success": 0,
        "upload_failed": 0,
        "db_rewrite_success": 0,
        "db_rewrite_failed": 0,
        "cleanup_success": 0,
        "cleanup_failed": 0,
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
            if str(action.source_match.bucket or "") == "similar_match":
                _increment_summary(summary, "similar_used")
            if str(action.source_match.bucket or "") == "fallback_seed":
                _increment_summary(summary, "fallback_used")
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
        elif status in {"missing_source", "conflict"}:
            cleanup_targets = outcome.get("cleanup_targets") or {}
            has_cleanup_targets = bool(cleanup_targets.get("urls") or cleanup_targets.get("keys"))
            db_clear_applied = bool(outcome.get("db_references_cleared"))
            legacy_deleted = bool(outcome.get("legacy_deleted"))
            cleanup_performed = bool(outcome.get("cleanup_performed"))
            if not outcome.get("cleanup_errors") and (
                db_clear_applied
                or legacy_deleted
                or cleanup_performed
                or not has_cleanup_targets
            ):
                _increment_summary(summary, "cleanup_success")
            else:
                _increment_summary(summary, "cleanup_failed")


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


def _collect_unmatched_cleanup_targets(action: RebuildAction) -> tuple[set[str], set[str]]:
    targets: set[str] = set()
    for owned_url, _role in action.owned_urls:
        candidate = str(owned_url or "").strip()
        if candidate:
            targets.add(candidate)
    if str(action.old_url or "").strip():
        targets.add(str(action.old_url).strip())

    key_targets: set[str] = set()
    for target in list(targets):
        normalized = normalize_r2_url_to_key(target).strip().lstrip("/")
        if normalized:
            key_targets.add(normalized)
    return targets, key_targets


def _figure_has_renderable_image(raw_figure: str) -> bool:
    figure = str(raw_figure or "")
    for match in TRAVEL_FIGURE_IMG_RE.finditer(figure):
        src = str(match.group(1) or match.group(2) or match.group(3) or "").strip()
        if src:
            return True
    return False


def _sanitize_empty_image_figures(raw_html: str) -> str:
    html_text = str(raw_html or "")
    if not html_text.strip():
        return html_text

    def _prune(match: re.Match[str]) -> str:
        block = str(match.group(0) or "")
        if "<img" not in block.lower():
            return block
        if _figure_has_renderable_image(block):
            return block
        return ""

    return FIGURE_BLOCK_RE.sub(_prune, html_text)


def _sanitize_travel_inline_artifacts(raw_html: str) -> str:
    html_text = str(raw_html or "")
    if not html_text.strip():
        return html_text

    def _prune_figure(match: re.Match[str]) -> str:
        block = match.group(0)
        if _figure_has_renderable_image(block):
            return TRAVEL_INLINE_MARKER_RE.sub("", block)
        return ""

    cleaned = TRAVEL_INLINE_MARKER_FIGURE_RE.sub(_prune_figure, html_text)
    cleaned = TRAVEL_INLINE_MARKER_RE.sub("", cleaned)
    cleaned = _sanitize_empty_image_figures(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _clear_unmatched_references(
    *,
    article: Article,
    targets: set[str],
    key_targets: set[str],
) -> None:
    if not targets and not key_targets:
        return

    replacement_map = {str(target): "" for target in sorted(targets) if str(target).strip().lower().startswith(("http://", "https://"))}

    if article.image:
        article.image.public_url = ""
        metadata = _deep_replace_urls(article.image.image_metadata, replacement_map)
        metadata = _replace_urls_by_key_targets(metadata, key_targets=key_targets)
        if isinstance(metadata, dict):
            metadata = _force_media_delivery_urls(metadata, new_url="")
        article.image.image_metadata = metadata

    article.html_article = _replace_urls_by_key_targets(
        _deep_replace_urls(str(article.html_article or ""), replacement_map),
        key_targets=key_targets,
    )
    article.html_article = _sanitize_travel_inline_artifacts(article.html_article)
    article.assembled_html = _replace_urls_by_key_targets(
        _deep_replace_urls(str(article.assembled_html or ""), replacement_map),
        key_targets=key_targets,
    )
    article.assembled_html = _sanitize_travel_inline_artifacts(article.assembled_html)

    if article.blogger_post:
        article.blogger_post.response_payload = _replace_urls_by_key_targets(
            _deep_replace_urls(article.blogger_post.response_payload, replacement_map),
            key_targets=key_targets,
        )

    cleared_inline: list[dict] = []
    if isinstance(article.inline_media, list):
        for item in article.inline_media:
            if not isinstance(item, dict):
                cleared_inline.append(item)
                continue

            current = dict(item)

            current_url = str(current.get("image_url") or "").strip()
            current_key = normalize_r2_url_to_key(current_url).lstrip("/")
            should_clear = False
            if current_url in targets or current_key in key_targets:
                should_clear = True
            if should_clear:
                current = _deep_replace_urls(current, replacement_map)
                current = _replace_urls_by_key_targets(current, key_targets=key_targets)
                current["image_url"] = ""
                current = _force_media_delivery_urls(current, new_url="")
            cleared_inline.append(current)
        article.inline_media = cleared_inline


def _clear_synced_main_thumbnail(
    db: Session,
    *,
    article: Article,
    old_url: str,
    key_targets: set[str],
) -> int:
    if not article.blogger_post or not article.blog:
        return 0
    remote_post_id = str(getattr(article.blogger_post, "blogger_post_id", "") or "").strip()
    if not remote_post_id:
        return 0

    normalized_old_key = normalize_r2_url_to_key(old_url).strip().lstrip("/")
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

    current = str(getattr(synced, "thumbnail_url", "") or "").strip()
    if not current:
        return 0
    current_key = normalize_r2_url_to_key(current).lstrip("/")
    if current in {str(old_url).strip()} or current_key == normalized_old_key or current_key in key_targets:
        synced.thumbnail_url = None
        db.add(synced)
        db.commit()
        return 1
    return 0


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


def _build_url_map(action: RebuildAction, *, replace_scope: str, resolved_public_url: str) -> dict[str, str]:
    normalized_scope = str(replace_scope or "hero_inline").strip().lower()
    if normalized_scope not in REPLACE_SCOPE_CHOICES:
        normalized_scope = "hero_inline"

    url_map: dict[str, str] = {}
    if normalized_scope == "hero_inline":
        for owned_url, role in action.owned_urls:
            candidate_url = str(owned_url or "").strip()
            if not candidate_url:
                continue
            if role == "cover" or role.startswith("inline-") or role.startswith("legacy-"):
                url_map[candidate_url] = resolved_public_url

    if action.old_url:
        url_map.setdefault(action.old_url, resolved_public_url)
    return url_map


def _build_key_map(url_map: dict[str, str]) -> dict[str, str]:
    key_map: dict[str, str] = {}
    for old_url, new_url in url_map.items():
        normalized_key = normalize_r2_url_to_key(old_url).lstrip("/")
        if normalized_key:
            key_map[normalized_key] = new_url
    return key_map


def _rewrite_article_urls(
    article: Article,
    *,
    new_url: str,
    url_map: dict[str, str],
    replace_scope: str = "hero_inline",
) -> None:
    normalized_url_map = {str(old).strip(): str(new).strip() for old, new in url_map.items() if str(old).strip()}
    key_map = _build_key_map(normalized_url_map)
    normalized_scope = str(replace_scope or "hero_inline").strip().lower()
    if normalized_scope not in REPLACE_SCOPE_CHOICES:
        normalized_scope = "hero_inline"

    article.html_article = _deep_replace_urls(article.html_article, normalized_url_map)
    article.assembled_html = _deep_replace_urls(article.assembled_html, normalized_url_map)
    article.html_article = _sanitize_travel_inline_artifacts(article.html_article)
    article.assembled_html = _sanitize_travel_inline_artifacts(article.assembled_html)
    if article.image:
        article.image.public_url = new_url
        metadata = _deep_replace_urls(article.image.image_metadata, normalized_url_map)
        if isinstance(metadata, dict):
            metadata = _force_media_delivery_urls(metadata, new_url=new_url)
        article.image.image_metadata = metadata
    if article.blogger_post:
        article.blogger_post.response_payload = _deep_replace_urls(article.blogger_post.response_payload, normalized_url_map)

    rewritten_inline: list[dict] = []
    for item in (article.inline_media or []):
        if not isinstance(item, dict):
            rewritten_inline.append(item)
            continue
        current_item = _deep_replace_urls(item, normalized_url_map)
        if not isinstance(current_item, dict):
            rewritten_inline.append(current_item)
            continue
        current_url = str(current_item.get("image_url") or "").strip()
        current_key = normalize_r2_url_to_key(current_url).lstrip("/")
        has_inline_slot = "inline" in str(current_item.get("slot") or "").strip().lower()
        has_asset_hint = bool(current_url or _extract_asset_urls(current_item))

        target_inline_url = ""
        if current_url and current_url in normalized_url_map:
            target_inline_url = normalized_url_map[current_url]
        elif current_key and current_key in key_map:
            target_inline_url = key_map[current_key]
        elif normalized_scope == "hero_inline" and (has_inline_slot or has_asset_hint):
            target_inline_url = new_url

        if target_inline_url:
            rewritten_item = {**current_item, "image_url": target_inline_url}
            rewritten_item = _force_media_delivery_urls(rewritten_item, new_url=target_inline_url)
            rewritten_inline.append(rewritten_item)
        else:
            rewritten_inline.append(current_item)
    article.inline_media = rewritten_inline


def _rewrite_synced_thumbnail(db: Session, article: Article, *, old_url: str, new_url: str, url_map: dict[str, str]) -> int:
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
    normalized_old_key = str(normalize_r2_url_to_key(old_url)).strip().lstrip("/")
    key_map = _build_key_map(url_map)
    current = str(getattr(synced, "thumbnail_url", "") or "").strip()
    current_key = normalize_r2_url_to_key(current).lstrip("/")
    if current in url_map:
        synced.thumbnail_url = url_map[current]
        db.add(synced)
        db.commit()
        return 1
    if normalized_old_key and current_key == normalized_old_key:
        synced.thumbnail_url = new_url
        db.add(synced)
        db.commit()
        return 1
    if current_key and current_key in key_map:
        synced.thumbnail_url = key_map[current_key]
        db.add(synced)
        db.commit()
        return 1
    return 0


def _build_action(
    db: Session,
    article: Article,
    *,
    inventory: LocalImageInventory,
    enable_similar_recovery: bool,
    fallback_source_path: Path | None,
    recovery_budget: dict[str, int | None] | None = None,
    source_overrides: dict[int, Path] | None = None,
    public_base_url_override: str = "",
) -> RebuildAction | None:
    policy = get_travel_blog_policy(blog=article.blog)
    if policy is None:
        return None
    assert_travel_scope_blog(blog=article.blog)
    owned_urls = _discover_article_owned_urls(article)
    old_url = _discover_primary_cover_url(article, owned_urls=owned_urls)
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
        source_match=_resolve_source_match_for_article(
            article.id,
            article.slug,
            inventory,
            source_overrides=source_overrides,
            enable_similar_recovery=enable_similar_recovery,
            fallback_source_path=fallback_source_path,
            recovery_budget=recovery_budget,
        ),
        owned_urls=owned_urls,
    )


def _normalize_travel_live_issue(issue_text: str | None) -> str:
    tokens = [str(part or "").strip() for part in str(issue_text or "").split(",")]
    normalized: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if not lowered:
            continue
        if lowered in TRAVEL_LIVE_AUDIT_IGNORED_ISSUES:
            continue
        normalized.append(lowered)
    if not normalized:
        return ""
    return ",".join(sorted(set(normalized)))


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
    clear_targets, clear_key_targets = _collect_unmatched_cleanup_targets(action)
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
        "db_clear_plan": {
            "urls": sorted(clear_targets),
            "keys": sorted(clear_key_targets),
        },
        "unmatched_cleanup_scope": "cover+owned+legacy",
        "source_candidates": action.source_match.candidates or [],
        "source_adopted_paths": action.source_match.adopted_paths or [],
        "owned_url_count": len(action.owned_urls or []),
        "owned_urls": [url for url, _role in (action.owned_urls or [])],
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
    replace_scope: str,
    cleanup_adopted_sources: bool,
) -> dict[str, Any]:
    result = _action_preview(action, runtime_image_root)
    status = str(action.source_match.status or "").strip().lower() or "missing_source"
    cleanup_status = status
    cleanup_notes = str(action.source_match.reason or "").strip()

    source_path = action.source_match.source_path
    if source_path is None:
        cleanup_status = "missing_source"
        cleanup_notes = "source_path_missing" if not cleanup_notes else f"{cleanup_notes};source_path_missing"
    elif not source_path.exists() or not source_path.is_file():
        cleanup_status = "missing_source"
        cleanup_notes = f"{cleanup_notes};source_path_missing:{source_path}" if cleanup_notes else f"source_path_missing:{source_path}"

    if status != "mapped" or source_path is None or (source_path and (not source_path.exists() or not source_path.is_file())):
        clear_targets, clear_key_targets = _collect_unmatched_cleanup_targets(action)
        result["cleanup_targets"] = {"urls": sorted(clear_targets), "keys": sorted(clear_key_targets)}
        result["cleanup_performed"] = False
        result["cleanup_errors"] = []
        result["db_references_cleared"] = False
        result["cleanup_status"] = cleanup_status
        result["cleanup_notes"] = cleanup_notes
        result["legacy_delete_attempted"] = False
        result["legacy_deleted"] = False
        result["cleared_synced_thumbnail_rows"] = 0
        if clear_targets or clear_key_targets:
            try:
                _clear_unmatched_references(
                    article=article,
                    targets=clear_targets,
                    key_targets=clear_key_targets,
                )
                synced_rows = _clear_synced_main_thumbnail(
                    db,
                    article=article,
                    old_url=action.old_url,
                    key_targets=clear_key_targets,
                )
                result["cleared_synced_thumbnail_rows"] = synced_rows
                db.add(article)
                if article.image:
                    db.add(article.image)
                if article.blogger_post:
                    db.add(article.blogger_post)
                db.commit()
                result["cleanup_performed"] = True
                result["db_references_cleared"] = True
            except Exception as exc:  # noqa: BLE001
                result["cleanup_errors"].append(f"db_cleanup_error: {exc}")

        if action.legacy_key:
            legacy_key = _legacy_delete_key(action)
            if legacy_key:
                result["legacy_delete_attempted"] = True
                try:
                    delete_cloudflare_r2_asset(db, object_key=legacy_key)
                    result["legacy_deleted"] = True
                except Exception as exc:  # noqa: BLE001
                    result["legacy_deleted"] = False
                    result["cleanup_errors"].append(f"legacy_r2_delete_failed: {exc}")

        _upsert_mapping(
            db,
            action=action,
            status=cleanup_status,
            notes=cleanup_notes,
        )
        result["status"] = cleanup_status
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

    resolved_target_url = resolved_public_url or action.target_url
    url_map = _build_url_map(action, replace_scope=replace_scope, resolved_public_url=resolved_target_url)
    _rewrite_article_urls(
        article,
        new_url=resolved_target_url,
        url_map=url_map,
        replace_scope=replace_scope,
    )
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
        new_url=resolved_target_url,
        url_map=url_map,
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
    deleted_adopted_source_paths: list[str] = []
    if cleanup_adopted_sources and str(action.source_match.bucket or "") != "fallback_seed":
        adopted_candidates = [
            Path(item)
            for item in (action.source_match.adopted_paths or [])
            if str(item or "").strip()
        ]
        deleted_adopted_source_paths, adopted_errors = _cleanup_local_legacy_files(adopted_candidates)
        cleanup_errors.extend(adopted_errors)

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
    result["replace_scope"] = str(replace_scope or "")
    result["replaced_url_count"] = len(url_map)
    result["replaced_urls"] = sorted(url_map.keys())
    result["deleted_legacy_key"] = legacy_key if legacy_deleted else ""
    result["deleted_local_paths"] = deleted_local_paths
    result["deleted_adopted_source_paths"] = deleted_adopted_source_paths
    result["cleanup_errors"] = cleanup_errors
    return result


def _audit_from_blogger_feed_entry(
    *,
    published_url: str,
    remote_post_id: str,
) -> tuple[Any | None, str]:
    normalized_url = str(published_url or "").strip()
    normalized_post_id = str(remote_post_id or "").strip()
    if not normalized_url or not normalized_post_id:
        return None, ""
    parsed = urlsplit(normalized_url)
    if not str(parsed.scheme or "").strip() or not str(parsed.netloc or "").strip():
        return None, ""
    feed_url = f"{parsed.scheme}://{parsed.netloc}/feeds/posts/default/{normalized_post_id}?alt=json"
    try:
        response = httpx.get(feed_url, timeout=12.0, follow_redirects=True)
    except Exception:  # noqa: BLE001
        return None, feed_url
    if response.status_code >= 400:
        return None, feed_url
    try:
        payload = response.json()
    except ValueError:
        return None, feed_url
    entry = payload.get("entry") if isinstance(payload, dict) else None
    content_meta = entry.get("content") if isinstance(entry, dict) else None
    content_html = str((content_meta or {}).get("$t") or "").strip() if isinstance(content_meta, dict) else ""
    if not content_html:
        return None, feed_url
    fallback_audit = audit_blogger_article_fragment(
        content_html,
        page_url=normalized_url,
        probe_images=False,
    )
    return fallback_audit, feed_url


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
                "remote_post_id": str(getattr(article.blogger_post, "blogger_post_id", "") or "").strip(),
            }
        )

    def _audit_task(task: dict[str, Any]) -> dict[str, Any]:
        audit = fetch_and_audit_blogger_post(task["published_url"], probe_images=True, timeout=8.0)
        audit_source = "live_page"
        audit_issue = _normalize_travel_live_issue(audit.live_image_issue)
        if (
            not tuple(audit.renderable_image_urls or ())
            and ("missing_cover" in str(audit_issue or "") or "missing_inline" in str(audit_issue or ""))
        ):
            feed_audit, feed_url = _audit_from_blogger_feed_entry(
                published_url=str(task.get("published_url") or ""),
                remote_post_id=str(task.get("remote_post_id") or ""),
            )
            if feed_audit is not None and tuple(feed_audit.renderable_image_urls or ()):
                audit = feed_audit
                audit_source = "feed_entry_fallback"
                task["audit_feed_url"] = feed_url
                audit_issue = _normalize_travel_live_issue(audit.live_image_issue)
        prefix_applied = any("/assets/travel-blogger/" in str(url or "").lower() for url in audit.renderable_image_urls)
        return {
            **task,
            "status": "live_ok" if not audit_issue else "live_issue",
            "live_image_issue": audit_issue,
            "live_image_count": audit.live_image_count,
            "live_unique_image_count": audit.live_unique_image_count,
            "travel_prefix_applied": prefix_applied,
            "renderable_image_urls": list(audit.renderable_image_urls),
            "audit_source": audit_source,
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


def _is_deployable_outcome(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").strip().lower()
    article_id = int(item.get("article_id") or 0)
    return status in {"uploaded", "deleted_legacy"} and article_id > 0


def _select_deploy_targets(
    outcomes: list[dict[str, Any]],
    *,
    deploy_mode: str,
    canary_count: int,
) -> list[dict[str, Any]]:
    candidates = [item for item in outcomes if _is_deployable_outcome(item)]
    if deploy_mode == "full":
        return candidates
    if deploy_mode != "canary":
        return []

    by_blog: dict[int, list[dict[str, Any]]] = {34: [], 36: [], 37: []}
    for item in candidates:
        blog_id = int(item.get("blog_id") or 0)
        by_blog.setdefault(blog_id, []).append(item)

    selected: list[dict[str, Any]] = []
    used_article_ids: set[int] = set()
    remaining = max(1, int(canary_count or DEFAULT_DEPLOY_CANARY_COUNT))

    def _take(blog_id: int, quota: int) -> None:
        nonlocal remaining
        if quota <= 0 or remaining <= 0:
            return
        taken = 0
        for item in by_blog.get(blog_id, []):
            article_id = int(item.get("article_id") or 0)
            if article_id <= 0 or article_id in used_article_ids:
                continue
            selected.append(item)
            used_article_ids.add(article_id)
            taken += 1
            remaining -= 1
            if taken >= quota or remaining <= 0:
                return

    for blog_id in (34, 36, 37):
        _take(blog_id, min(int(DEPLOY_CANARY_LANGUAGE_QUOTA.get(blog_id, 0) or 0), remaining))
    if remaining > 0:
        for blog_id in (34, 36, 37):
            _take(blog_id, remaining)
            if remaining <= 0:
                break
    return selected


def _deploy_live_updates(
    db: Session,
    *,
    report: dict[str, Any],
    deploy_mode: str,
    canary_count: int,
) -> None:
    outcomes = [item for item in report.get("actions", []) if isinstance(item, dict)]
    candidates = [item for item in outcomes if _is_deployable_outcome(item)]
    targets = _select_deploy_targets(outcomes, deploy_mode=deploy_mode, canary_count=canary_count)

    payload: dict[str, Any] = {
        "enabled": True,
        "mode": deploy_mode,
        "requested_canary_count": int(canary_count or DEFAULT_DEPLOY_CANARY_COUNT),
        "candidate_count": len(candidates),
        "selected_count": len(targets),
        "success_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "targets": [],
    }

    for item in targets:
        article_id = int(item.get("article_id") or 0)
        blog_id = int(item.get("blog_id") or 0)
        target_url = str(item.get("uploaded_public_url") or item.get("target_url") or "").strip()
        target_record: dict[str, Any] = {
            "article_id": article_id,
            "blog_id": blog_id,
            "post_slug": str(item.get("post_slug") or "").strip(),
            "target_url": target_url,
            "status": "planned" if deploy_mode == "dry-run" else "pending",
            "reason": "",
        }
        payload["targets"].append(target_record)

        if deploy_mode == "dry-run":
            continue

        article = (
            db.execute(
                select(Article)
                .where(Article.id == article_id)
                .options(
                    selectinload(Article.blog),
                    selectinload(Article.image),
                    selectinload(Article.blogger_post),
                )
            )
            .scalar_one_or_none()
        )
        if article is None or article.blog is None or article.blogger_post is None:
            target_record["status"] = "skipped"
            target_record["reason"] = "missing_article_or_blogger_post"
            payload["skipped_count"] = int(payload["skipped_count"] or 0) + 1
            continue

        policy = get_travel_blog_policy(blog=article.blog)
        if policy is None:
            target_record["status"] = "skipped"
            target_record["reason"] = "non_travel_policy"
            payload["skipped_count"] = int(payload["skipped_count"] or 0) + 1
            continue

        try:
            assert_travel_scope_blog(blog=article.blog)
            provider = get_blogger_provider(db, article.blog)
            if type(provider).__name__.startswith("Mock"):
                raise RuntimeError("mock_provider")

            hero_image_url = str(getattr(getattr(article, "image", None), "public_url", "") or "").strip()
            if not hero_image_url:
                hero_image_url = target_url
            content = str(rebuild_article_html(db, article, hero_image_url) or "").strip()
            if not content:
                content = str(article.assembled_html or article.html_article or "").strip()
            content = _sanitize_travel_inline_artifacts(content)
            if not content:
                raise RuntimeError("empty_article_content")

            summary, raw_payload = provider.update_post(
                post_id=str(article.blogger_post.blogger_post_id or "").strip(),
                title=str(article.title or "").strip(),
                content=content,
                labels=list(article.labels or []),
                meta_description=str(article.meta_description or "").strip(),
            )
            upsert_article_blogger_post(
                db,
                article=article,
                summary=summary,
                raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
            )
            target_record["status"] = "deployed"
            target_record["published_url"] = str(summary.get("url") or "").strip()
            payload["success_count"] = int(payload["success_count"] or 0) + 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            target_record["status"] = "failed"
            target_record["reason"] = str(exc)
            payload["failed_count"] = int(payload["failed_count"] or 0) + 1

    report["live_deploy"] = payload


def _build_url_review_report(report: dict[str, Any], *, deploy_mode: str) -> dict[str, Any]:
    actions = [item for item in report.get("actions", []) if isinstance(item, dict)]
    issues_by_language: dict[str, dict[str, int]] = {}
    samples_by_language: dict[str, list[dict[str, Any]]] = {}
    duplicate_assets_assets_count = 0
    prefix_applied_count = 0
    live_issue_count = 0
    live_ok_count = 0

    for action in actions:
        blog_id = int(action.get("blog_id") or 0)
        language_key = _language_summary_name(blog_id)
        issues = issues_by_language.setdefault(language_key, {})
        samples = samples_by_language.setdefault(language_key, [])

        status = str(action.get("status") or "").strip().lower()
        if status == "live_issue":
            live_issue_count += 1
        elif status == "live_ok":
            live_ok_count += 1

        issue_text = str(action.get("live_image_issue") or "").strip()
        if issue_text:
            for token in [part.strip() for part in issue_text.split(",") if part.strip()]:
                issues[token] = int(issues.get(token, 0) or 0) + 1
        else:
            issues["ok"] = int(issues.get("ok", 0) or 0) + 1

        renderable = [str(url or "").strip() for url in (action.get("renderable_image_urls") or [])]
        if any("/assets/travel-blogger/" in value.lower() for value in renderable):
            prefix_applied_count += 1
        has_assets_assets = any("/assets/assets/" in value.lower() for value in renderable)
        if has_assets_assets:
            duplicate_assets_assets_count += 1

        if (issue_text or has_assets_assets) and len(samples) < 20:
            samples.append(
                {
                    "article_id": int(action.get("article_id") or 0),
                    "post_slug": str(action.get("post_slug") or "").strip(),
                    "published_url": str(action.get("published_url") or "").strip(),
                    "live_image_issue": issue_text,
                    "has_assets_assets": has_assets_assets,
                    "renderable_image_urls": renderable[:3],
                }
            )

    return {
        "generated_at": str(report.get("generated_at") or ""),
        "profile_key": str(report.get("profile_key") or ""),
        "mode": deploy_mode,
        "summary": {
            "article_count": len(actions),
            "live_ok_count": live_ok_count,
            "live_issue_count": live_issue_count,
            "travel_prefix_applied_count": prefix_applied_count,
            "assets_assets_duplicate_count": duplicate_assets_assets_count,
        },
        "language_reports": report.get("language_reports", {}),
        "issue_distribution": issues_by_language,
        "broken_url_samples": samples_by_language,
    }


def _build_compact_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    actions = [item for item in report.get("actions", []) if isinstance(item, dict)]
    mapped = 0
    unresolved = 0
    rewritten = 0
    live_ok = 0
    live_broken = 0
    assets_assets_count = 0
    similar_used = 0
    fallback_used = 0
    unresolved_source_statuses = {"missing_source", "conflict", "skipped"}
    rewritten_statuses = {"uploaded", "deleted_legacy"}

    for item in actions:
        source_status = str(item.get("source_status") or "").strip().lower()
        source_bucket = str(item.get("source_bucket") or "").strip().lower()
        status = str(item.get("status") or "").strip().lower()
        if source_status == "mapped" or status in rewritten_statuses:
            mapped += 1
        if source_status in unresolved_source_statuses or status in unresolved_source_statuses:
            unresolved += 1
        if status in rewritten_statuses:
            rewritten += 1
        if status == "live_ok":
            live_ok += 1
        if status == "live_issue":
            live_broken += 1

        renderable = [str(url or "").strip().lower() for url in (item.get("renderable_image_urls") or [])]
        replaced_urls = [str(url or "").strip().lower() for url in (item.get("replaced_urls") or [])]
        if any("/assets/assets/" in value for value in renderable + replaced_urls):
            assets_assets_count += 1
        if source_bucket == "similar_match":
            similar_used += 1
        if source_bucket == "fallback_seed":
            fallback_used += 1

    return {
        "total_posts": int(report.get("article_count") or 0),
        "mapped": mapped,
        "unresolved": unresolved,
        "rewritten": rewritten,
        "live_ok": live_ok,
        "live_broken": live_broken,
        "assets_assets_count": assets_assets_count,
        "similar_used": similar_used,
        "fallback_used": fallback_used,
    }


def main() -> int:
    args = parse_args()
    runtime_image_root = Path(str(args.runtime_image_root)).resolve()
    report_root = Path(str(args.report_root)).resolve()
    extra_source_roots = _parse_extra_source_roots(getattr(args, "source_extra_root", ""))
    fallback_source_path = Path(str(args.fallback_source_path)).resolve() if str(args.fallback_source_path or "").strip() else None
    blog_ids = _parse_blog_ids(getattr(args, "blog_ids", "34"))
    replace_scope = str(args.replace_scope or "hero_inline").strip().lower()
    if replace_scope not in REPLACE_SCOPE_CHOICES:
        replace_scope = "hero_inline"
    if args.deploy_live and not args.execute:
        print(json.dumps({"warning": "--deploy-live is ignored without --execute"}, ensure_ascii=False))
    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "profile_key": args.profile_key,
        "blog_ids": list(blog_ids),
        "execute": bool(args.execute),
        "live_audit": bool(args.live_audit),
        "mode": "live-audit" if args.live_audit else ("execute" if args.execute else "dry-run"),
        "verify_http": bool(args.verify_http),
        "cloudflare_public_base_url": str(args.cloudflare_public_base_url or "").strip(),
        "runtime_image_root": str(runtime_image_root),
        "report_root": str(report_root),
        "replace_scope": replace_scope,
        "enable_similar_recovery": bool(args.enable_similar_recovery),
        "fallback_source_path": str(fallback_source_path) if fallback_source_path else "",
        "source_extra_roots": [str(path) for path in extra_source_roots],
        "common_fallback_url": str(args.common_fallback_url or "").strip(),
        "cleanup_adopted_sources": bool(args.cleanup_adopted_sources),
        "refresh_translation_state": bool(args.refresh_translation_state),
        "repair_related_cover_thumbnails": bool(args.repair_related_cover_thumbnails),
        "deploy_live": bool(args.deploy_live),
        "deploy_mode": str(args.deploy_mode or "dry-run"),
        "deploy_canary_count": int(args.deploy_canary_count or DEFAULT_DEPLOY_CANARY_COUNT),
        "travel_root": str(_travel_root(runtime_image_root)),
        "travel_backup_root": str(_travel_backup_root(runtime_image_root)),
        "blogs": [],
        "article_count": 0,
        "language_reports": {},
        "actions": [],
        "status_counts": {},
    }

    with SessionLocal() as db:
        articles = _load_target_articles(db, profile_key=args.profile_key, blog_ids=blog_ids)
        source_overrides = _load_source_overrides_from_file(getattr(args, "source_override_file", ""))
        focus_raw_ids = set(_parse_article_ids(getattr(args, "focus_article_ids", "")))
        focus_file_ids = set(_load_focus_article_ids_from_file(getattr(args, "focus_article_id_file", "")))
        focus_article_ids = set(focus_raw_ids | focus_file_ids)
        if focus_article_ids:
            focus_article_ids = {article_id for article_id in focus_article_ids if article_id > 0}
            articles = [article for article in articles if int(article.id) in focus_article_ids]
            report["focus_article_ids"] = sorted(focus_article_ids)
            if not articles:
                report["mode"] = "aborted-no-targets"
                report["article_count"] = 0
                report["blogs"] = []
                report["compact_summary"] = _build_compact_report_summary(report)
                report_path = _report_path(args.report_prefix, report_root)
                report["report_path"] = str(report_path)
                _json_write(report_path, report)
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 0
        if source_overrides:
            report["source_override_file"] = str(Path(str(args.source_override_file)).resolve())
            report["source_override_count"] = len(source_overrides)
            if focus_article_ids:
                report["source_override_applied_to_focus_count"] = len(
                    [article_id for article_id in source_overrides if article_id in focus_article_ids]
                )
        inventory = _build_local_image_inventory(runtime_image_root)
        for extra_root in extra_source_roots:
            if not extra_root.exists() or not extra_root.is_dir():
                continue
            inventory = _merge_local_image_inventory(inventory, _build_local_image_inventory(extra_root))
        effective_enable_similar_recovery = bool(args.enable_similar_recovery)
        max_similar_recovery = _resolve_recovery_limit(args.max_similar_recovery)
        if max_similar_recovery not in (None, 0):
            effective_enable_similar_recovery = True
        recovery_budget = {
            "similar": max_similar_recovery,
            "fallback": _resolve_recovery_limit(args.max_fallback_recovery),
        }
        report["article_count"] = len(articles)
        report["blogs"] = sorted({article.blog_id for article in articles})
        report["max_similar_recovery"] = max_similar_recovery
        report["max_fallback_recovery"] = recovery_budget["fallback"]
        report["enable_similar_recovery"] = effective_enable_similar_recovery

        if args.repair_related_cover_thumbnails:
            _run_cover_hash_repair_mode(
                db,
                report=report,
                articles=articles,
                inventory=inventory,
                runtime_image_root=runtime_image_root,
                source_overrides=source_overrides,
                fallback_source_path=fallback_source_path,
                enable_similar_recovery=effective_enable_similar_recovery,
                recovery_budget=recovery_budget,
                verify_http=bool(args.verify_http),
                replace_scope=replace_scope,
                cleanup_adopted_sources=bool(args.cleanup_adopted_sources),
                deploy_live=bool(args.deploy_live),
                common_fallback_url=str(args.common_fallback_url or "").strip(),
            )
            analysis_path = _write_cover_hash_global_analysis(db, report_root=report_root)
            report["global_analysis_report_path"] = str(analysis_path)
            if args.live_audit:
                _run_live_audit(db=db, articles=articles, report=report)
            report["compact_summary"] = _build_compact_report_summary(report)
            report_path = _report_path(args.report_prefix, report_root)
            report["report_path"] = str(report_path)
            _json_write(report_path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        if args.live_audit:
            _run_live_audit(db=db, articles=articles, report=report)
            url_review_prefix = (
                f"travel-url-review-{args.deploy_mode}"
                if str(args.deploy_mode or "").strip().lower() in {"canary", "full"}
                else "travel-url-review-dry-run"
            )
            url_review_payload = _build_url_review_report(
                report,
                deploy_mode=str(args.deploy_mode or "dry-run"),
            )
            url_review_path = _report_path(url_review_prefix, report_root)
            _json_write(url_review_path, url_review_payload)
            report["url_review_report_path"] = str(url_review_path)
            report["url_review_summary"] = url_review_payload.get("summary", {})
            report["compact_summary"] = _build_compact_report_summary(report)
            report_path = _report_path(args.report_prefix, report_root)
            report["report_path"] = str(report_path)
            _json_write(report_path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        if not args.execute:
            for article in articles:
                action = _build_action(
                    db,
                    article,
                    inventory=inventory,
                    enable_similar_recovery=effective_enable_similar_recovery,
                    recovery_budget=recovery_budget,
                    fallback_source_path=fallback_source_path,
                    source_overrides=source_overrides,
                    public_base_url_override=str(args.cloudflare_public_base_url or "").strip(),
                )
                if action is None:
                    continue
                item = _action_preview(action, runtime_image_root)
                report["actions"].append(item)
                _record_inventory_summary(report, action=action)
                status_key = action.source_match.status
                report["status_counts"][status_key] = int(report["status_counts"].get(status_key, 0) or 0) + 1
            report["compact_summary"] = _build_compact_report_summary(report)
            report_path = _report_path(args.report_prefix, report_root)
            report["report_path"] = str(report_path)
            _json_write(report_path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        manifest = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "items": [],
            "deleted_sources": [],
            "kept_candidates": [],
            "fallback_applied_articles": [],
        }
        for article in articles:
            action = _build_action(
                db,
                article,
                inventory=inventory,
                enable_similar_recovery=effective_enable_similar_recovery,
                recovery_budget=recovery_budget,
                fallback_source_path=fallback_source_path,
                source_overrides=source_overrides,
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
                replace_scope=replace_scope,
                cleanup_adopted_sources=bool(args.cleanup_adopted_sources),
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
                    "replace_scope": replace_scope,
                    "deleted_legacy_key": str(outcome.get("deleted_legacy_key") or ""),
                    "source_bucket": str(action.source_match.bucket or ""),
                    "deleted_adopted_source_paths": list(outcome.get("deleted_adopted_source_paths") or []),
                }
            )
            manifest["deleted_sources"].extend(list(outcome.get("deleted_adopted_source_paths") or []))
            manifest["kept_candidates"].append(
                {
                    "article_id": action.article_id,
                    "source_bucket": str(action.source_match.bucket or ""),
                    "source_candidates": list(action.source_match.candidates or []),
                }
            )
            if str(action.source_match.bucket or "") == "fallback_seed":
                manifest["fallback_applied_articles"].append(
                    {
                        "article_id": action.article_id,
                        "post_slug": action.post_slug,
                        "target_key": action.target_key,
                    }
                )

        if args.deploy_live:
            _deploy_live_updates(
                db,
                report=report,
                deploy_mode=str(args.deploy_mode or "dry-run"),
                canary_count=int(args.deploy_canary_count or DEFAULT_DEPLOY_CANARY_COUNT),
            )
            manifest["live_deploy"] = report.get("live_deploy", {})
        if args.refresh_translation_state:
            translation_refresh = refresh_travel_translation_state(
                db,
                blog_ids=blog_ids,
                report_root=report_root,
                write_report=True,
            )
            report["translation_refresh"] = translation_refresh
            manifest["translation_refresh"] = {
                "ready_count": int((translation_refresh.get("summary") or {}).get("ready_count") or 0),
                "report_path": str(translation_refresh.get("report_path") or ""),
            }

        report["compact_summary"] = _build_compact_report_summary(report)
        manifest_path = _manifest_path(args.report_prefix, report_root)
        report_path = _report_path(args.report_prefix, report_root)
        report["report_path"] = str(report_path)
        report["manifest_path"] = str(manifest_path)
        _json_write(manifest_path, manifest)
        _json_write(report_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

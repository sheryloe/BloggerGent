from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image as PILImage, ImageOps, UnidentifiedImageError
from slugify import slugify
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_REPORT_DIR = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
DEFAULT_SCAN_ROOTS = (Path(r"D:\\"),)
DEFAULT_BAD_HASH = "1ABA64599E3740963FC47334842BC42F44546D7D6B6A328439916DCB659273A3"
DEFAULT_BAD_SOURCE_HASHES = (
    DEFAULT_BAD_HASH,
    "6C0FE456DF868DC2209D2212F691DA32C6660C97ABD593E473876FC34DBEB774",
)
TRAVEL_COVER_SIZE = (1024, 1024)
ALLOWED_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg", ".avif"}
STRIP_SUFFIX_PATTERNS = (
    re.compile(r"-(?:inline-)?3x2$", re.IGNORECASE),
    re.compile(r"-inline$", re.IGNORECASE),
    re.compile(r"-cover$", re.IGNORECASE),
    re.compile(r"-thumbnail$", re.IGNORECASE),
    re.compile(r"^rank\d+-", re.IGNORECASE),
)
SKIP_DIR_NAMES = {
    ".cache",
    ".git",
    ".next",
    ".playwright-cli",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "node_modules",
    "site-packages",
    "venv",
}
GENERIC_TOKENS = {
    "a",
    "accommodation",
    "access",
    "activities",
    "an",
    "and",
    "at",
    "best",
    "book",
    "booking",
    "bus",
    "buses",
    "cafe",
    "cafes",
    "complete",
    "crowd",
    "date",
    "dates",
    "detour",
    "detours",
    "district",
    "efficient",
    "efficiently",
    "etiquette",
    "event",
    "events",
    "evening",
    "exhibit",
    "exhibition",
    "exhibitions",
    "exhibits",
    "explore",
    "exploring",
    "family",
    "festival",
    "finish",
    "food",
    "foreigners",
    "from",
    "guide",
    "highlights",
    "how",
    "in",
    "info",
    "insider",
    "local",
    "lodging",
    "market",
    "markets",
    "navigate",
    "navigating",
    "night",
    "nighttime",
    "on",
    "onboard",
    "park",
    "photo",
    "plan",
    "planning",
    "practical",
    "public",
    "reach",
    "recommendations",
    "route",
    "routes",
    "safety",
    "schedule",
    "shopping",
    "shuttle",
    "spring",
    "station",
    "stay",
    "stops",
    "strategies",
    "strategy",
    "street",
    "the",
    "through",
    "ticket",
    "tickets",
    "timing",
    "tips",
    "to",
    "tour",
    "traditional",
    "transfer",
    "transfers",
    "transport",
    "transit",
    "travel",
    "trip",
    "understanding",
    "use",
    "venue",
    "viewing",
    "walk",
    "walking",
    "walks",
    "with",
}
RESAMPLING_LANCZOS = getattr(getattr(PILImage, "Resampling", PILImage), "LANCZOS")


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
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
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, PostStatus  # noqa: E402
from app.services.content.article_service import resolve_r2_category_key  # noqa: E402
from app.services.content.travel_blog_policy import (  # noqa: E402
    assert_travel_scope_blog,
    build_travel_asset_object_key,
    get_travel_blog_policy,
    normalize_travel_category_key,
)
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import upload_binary_to_cloudflare_r2  # noqa: E402


@dataclass(frozen=True, slots=True)
class Target:
    article_id: int
    blog_id: int
    slug: str
    title: str
    published_at: str
    category_key: str
    object_key: str
    public_url: str


@dataclass(frozen=True, slots=True)
class SourceRecord:
    path: Path
    raw_slug: str
    clean_slug: str
    tokens: frozenset[str]
    distinct_tokens: frozenset[str]
    size: int


@dataclass(frozen=True, slots=True)
class Candidate:
    source: SourceRecord
    score: int
    source_hash: str
    publish_hash: str
    match_mode: str
    missing_distinct_tokens: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair English Travel Blogger duplicate R2 images by overwriting only safe source matches.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run mode. This is the default.")
    parser.add_argument("--execute", action="store_true", help="Overwrite R2 objects for safe matches.")
    parser.add_argument("--blog-id", type=int, default=34)
    parser.add_argument("--profile-key", default="korea_travel")
    parser.add_argument("--bad-hash", action="append", default=[], help="Remote bad SHA256 hash to repair.")
    parser.add_argument("--bad-source-hash", action="append", default=[], help="Local source SHA256 hash to reject.")
    parser.add_argument("--scan-root", action="append", default=[], help="Image source root to scan. Defaults to D:\\.")
    parser.add_argument("--published-from", default="", help="Inclusive BloggerPost.published_at lower bound, e.g. 2026-03-17.")
    parser.add_argument("--published-to", default="", help="Inclusive BloggerPost.published_at upper date, e.g. 2026-03-28.")
    parser.add_argument(
        "--repair-duplicate-remote-hashes",
        action="store_true",
        help="Also repair targets whose current remote hash is duplicated inside the selected date range.",
    )
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--public-base-url", default="")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--http-timeout", type=float, default=30.0)
    parser.add_argument("--verify-delay-sec", type=float, default=1.0)
    parser.add_argument("--report-prefix", default="english-travel-r2-duplicate-repair")
    return parser.parse_args()


def slug_token(value: str | None) -> str:
    return slugify(str(value or "").strip(), separator="-").lower()


def clean_slug(value: str | None) -> str:
    candidate = slug_token(value)
    changed = True
    while changed:
        changed = False
        for pattern in STRIP_SUFFIX_PATTERNS:
            updated = pattern.sub("", candidate)
            if updated != candidate:
                candidate = updated
                changed = True
    return candidate


def slug_tokens(value: str | None, *, distinct: bool = False) -> tuple[str, ...]:
    tokens: list[str] = []
    for token in slug_token(value).split("-"):
        normalized = token.strip().lower()
        if not normalized or len(normalized) <= 1:
            continue
        if normalized.isdigit() or re.fullmatch(r"\d{4}", normalized):
            continue
        if distinct and normalized in GENERIC_TOKENS:
            continue
        tokens.append(normalized)
    return tuple(tokens)


def parse_utc_datetime_bound(value: str | None, *, inclusive_date_end: bool = False) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    is_date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw))
    normalized = raw.replace("Z", "+00:00")
    if is_date_only:
        parsed = datetime.fromisoformat(f"{normalized}T00:00:00+00:00")
        if inclusive_date_end:
            parsed += timedelta(days=1)
        return parsed
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


def sha256_file(path: Path, cache: dict[str, str]) -> str:
    key = str(path)
    cached = cache.get(key)
    if cached:
        return cached
    digest = sha256_bytes(path.read_bytes())
    cache[key] = digest
    return digest


def render_publish_webp(source_path: Path) -> bytes:
    try:
        with PILImage.open(source_path) as image:
            image = ImageOps.exif_transpose(image)
            converted = image.convert("RGB")
            fitted = ImageOps.fit(converted, TRAVEL_COVER_SIZE, method=RESAMPLING_LANCZOS)
            buffer = BytesIO()
            fitted.save(buffer, format="WEBP", quality=90, method=6)
            return buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RuntimeError(f"Failed to convert source image to 1024x1024 WEBP: {source_path}: {exc}") from exc


def rendered_publish_hash(path: Path, cache: dict[str, str]) -> str:
    key = str(path)
    cached = cache.get(key)
    if cached:
        return cached
    digest = sha256_bytes(render_publish_webp(path))
    cache[key] = digest
    return digest


def source_sort_key(source: SourceRecord) -> tuple[int, int, int, int, str]:
    path_text = str(source.path).lower().replace("/", "\\")
    if "\\donggri_runtime\\bloggergent\\storage\\images\\" in path_text:
        bucket_rank = 0
    elif "\\assets\\images\\" in path_text:
        bucket_rank = 1
    else:
        bucket_rank = 2
    ext_rank = {".png": 0, ".webp": 1, ".jpg": 2, ".jpeg": 2, ".avif": 3}.get(source.path.suffix.lower(), 9)
    return (bucket_rank, ext_rank, -source.size, len(source.path.name), path_text)


def report_path(report_dir: Path, prefix: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return report_dir / f"{prefix}-{stamp}.json"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def load_target_articles(
    db,
    *,
    profile_key: str,
    blog_id: int,
    public_base_url: str,
    published_from: datetime | None = None,
    published_to_exclusive: datetime | None = None,
) -> list[Target]:
    if blog_id != 34:
        raise ValueError("This repair script is intentionally limited to English Travel blog_id=34.")
    filters = [
        Blog.profile_key == profile_key,
        Blog.id == blog_id,
        BloggerPost.post_status.in_((PostStatus.PUBLISHED, PostStatus.SCHEDULED)),
    ]
    if published_from is not None:
        filters.append(BloggerPost.published_at >= published_from)
    if published_to_exclusive is not None:
        filters.append(BloggerPost.published_at < published_to_exclusive)
    rows = (
        db.execute(
            select(Article)
            .join(Blog, Blog.id == Article.blog_id)
            .join(BloggerPost, BloggerPost.article_id == Article.id)
            .where(*filters)
            .options(
                selectinload(Article.blog),
                selectinload(Article.image),
                selectinload(Article.blogger_post),
            )
            .order_by(BloggerPost.published_at.asc(), Article.id.asc())
        )
        .scalars()
        .all()
    )
    targets: list[Target] = []
    seen_article_ids: set[int] = set()
    for article in rows:
        article_id = int(article.id)
        if article_id in seen_article_ids:
            continue
        seen_article_ids.add(article_id)
        policy = get_travel_blog_policy(blog=article.blog)
        if policy is None:
            continue
        assert_travel_scope_blog(blog=article.blog)
        category_key = normalize_travel_category_key(
            resolve_r2_category_key(
                profile_key=profile_key,
                primary_language=str(getattr(article.blog, "primary_language", "") or ""),
                editorial_category_key=article.editorial_category_key,
                editorial_category_label=article.editorial_category_label,
                labels=list(article.labels or []),
                title=article.title,
                summary=article.excerpt,
            )
        )
        object_key = build_travel_asset_object_key(
            policy=policy,
            category_key=category_key,
            post_slug=article.slug,
            asset_role="main",
        )
        targets.append(
            Target(
                article_id=article_id,
                blog_id=int(article.blog_id),
                slug=slug_token(article.slug),
                title=str(article.title or ""),
                published_at=article.blogger_post.published_at.isoformat() if article.blogger_post and article.blogger_post.published_at else "",
                category_key=category_key,
                object_key=object_key,
                public_url=f"{public_base_url.rstrip('/')}/{object_key.lstrip('/')}",
            )
        )
    return targets


def resolve_public_base_url(db, override: str) -> str:
    normalized = str(override or "").strip().rstrip("/")
    if normalized:
        return normalized
    values = get_settings_map(db)
    base = str(values.get("travel_cloudflare_r2_public_base_url") or "").strip().rstrip("/")
    if not base:
        base = str(values.get("cloudflare_r2_public_base_url") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("travel_cloudflare_r2_public_base_url is required.")
    return base


def fetch_url_hash(url: str, *, timeout: float) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        content = response.content
        return {
            "url": url,
            "status_code": response.status_code,
            "ok": response.is_success,
            "bytes": len(content),
            "hash": sha256_bytes(content) if response.is_success else "",
            "content_type": str(response.headers.get("content-type") or "").strip(),
            "error": "" if response.is_success else response.text[:500],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "url": url,
            "status_code": None,
            "ok": False,
            "bytes": 0,
            "hash": "",
            "content_type": "",
            "error": str(exc),
        }


def fetch_current_remote_hashes(targets: list[Target], *, timeout: float, max_workers: int) -> dict[int, dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    workers = max(1, int(max_workers or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(fetch_url_hash, target.public_url, timeout=timeout): target for target in targets}
        for future in as_completed(future_map):
            target = future_map[future]
            by_id[target.article_id] = future.result()
    return by_id


def build_remote_duplicate_hash_clusters(targets: list[Target], remote_hashes: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    by_hash: dict[str, list[Target]] = defaultdict(list)
    for target in targets:
        remote = remote_hashes.get(target.article_id, {})
        if not remote.get("ok"):
            continue
        remote_hash = str(remote.get("hash") or "").strip().upper()
        if not remote_hash:
            continue
        by_hash[remote_hash].append(target)
    clusters: list[dict[str, Any]] = []
    for remote_hash, grouped_targets in by_hash.items():
        if len(grouped_targets) <= 1:
            continue
        clusters.append(
            {
                "hash": remote_hash,
                "count": len(grouped_targets),
                "slugs": [target.slug for target in grouped_targets],
                "article_ids": [target.article_id for target in grouped_targets],
            }
        )
    clusters.sort(key=lambda item: (-int(item["count"]), str(item["hash"])))
    return clusters


def iter_image_files(scan_roots: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(str(root), topdown=True, onerror=lambda _exc: None):
            dirnames[:] = [name for name in dirnames if name.lower() not in SKIP_DIR_NAMES]
            for name in filenames:
                path = Path(dirpath) / name
                if path.suffix.lower() in ALLOWED_EXTENSIONS:
                    files.append(path)
    return files


def build_source_records(scan_roots: tuple[Path, ...]) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    seen: set[str] = set()
    for path in iter_image_files(scan_roots):
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        raw_slug = slug_token(path.stem)
        records.append(
            SourceRecord(
                path=path,
                raw_slug=raw_slug,
                clean_slug=clean_slug(path.stem),
                tokens=frozenset(slug_tokens(raw_slug)),
                distinct_tokens=frozenset(slug_tokens(raw_slug, distinct=True)),
                size=size,
            )
        )
    return records


def candidate_score(target: Target, source: SourceRecord) -> tuple[str, int]:
    if source.raw_slug == target.slug or source.clean_slug == target.slug:
        return "exact", 10000
    target_tokens = set(slug_tokens(target.slug))
    if not target_tokens or not source.tokens:
        return "", 0
    shared_tokens = target_tokens & set(source.tokens)
    if len(shared_tokens) < 2:
        return "", 0
    score = (len(shared_tokens) * 100) - (abs(len(target_tokens) - len(source.tokens)) * 4)
    if source.raw_slug.startswith(f"{target.slug}-") or source.clean_slug.startswith(f"{target.slug}-"):
        score += 300
    target_order = slug_tokens(target.slug)
    source_order = slug_tokens(source.raw_slug)
    ordered_overlap = 0
    for left, right in zip(target_order, source_order):
        if left != right:
            break
        ordered_overlap += 1
    score += ordered_overlap * 12
    return "fuzzy", score


def find_best_candidate(
    target: Target,
    sources: list[SourceRecord],
    *,
    bad_source_hashes: set[str],
    hash_cache: dict[str, str],
    publish_hash_cache: dict[str, str],
) -> tuple[Candidate | None, list[dict[str, Any]], str, str]:
    plausible: list[tuple[str, int, SourceRecord, tuple[str, ...]]] = []
    target_distinct = set(slug_tokens(target.slug, distinct=True))
    for source in sources:
        mode, score = candidate_score(target, source)
        if not mode or score <= 0:
            continue
        missing_distinct = tuple(sorted(target_distinct - set(source.distinct_tokens)))
        plausible.append((mode, score, source, missing_distinct))

    plausible.sort(key=lambda item: (-item[1], source_sort_key(item[2])))
    candidates: list[Candidate] = []
    rejected_preview: list[dict[str, Any]] = []
    for mode, score, source, missing_distinct in plausible[:40]:
        try:
            source_hash = sha256_file(source.path, hash_cache)
        except Exception as exc:  # noqa: BLE001
            rejected_preview.append(
                {
                    "path": str(source.path),
                    "reason": f"hash_failed:{exc}",
                    "score": score,
                    "match_mode": mode,
                }
            )
            continue
        if source_hash in bad_source_hashes:
            rejected_preview.append(
                {
                    "path": str(source.path),
                    "reason": "bad_source_hash",
                    "score": score,
                    "hash": source_hash,
                    "match_mode": mode,
                }
            )
            continue
        candidates.append(
            Candidate(
                source=source,
                score=score,
                source_hash=source_hash,
                publish_hash="",
                match_mode=mode,
                missing_distinct_tokens=missing_distinct,
            )
        )

    if not candidates:
        return None, rejected_preview[:12], "skipped_no_safe_source", "no non-bad source candidate"

    def publish_safe_candidate(candidate: Candidate) -> Candidate | None:
        try:
            publish_hash = rendered_publish_hash(candidate.source.path, publish_hash_cache)
        except Exception as exc:  # noqa: BLE001
            rejected_preview.append(
                {
                    "path": str(candidate.source.path),
                    "reason": f"render_failed:{exc}",
                    "score": candidate.score,
                    "hash": candidate.source_hash,
                    "match_mode": candidate.match_mode,
                }
            )
            return None
        if publish_hash in bad_source_hashes:
            rejected_preview.append(
                {
                    "path": str(candidate.source.path),
                    "reason": "bad_render_hash",
                    "score": candidate.score,
                    "hash": candidate.source_hash,
                    "publish_hash": publish_hash,
                    "match_mode": candidate.match_mode,
                }
            )
            return None
        return Candidate(
            source=candidate.source,
            score=candidate.score,
            source_hash=candidate.source_hash,
            publish_hash=publish_hash,
            match_mode=candidate.match_mode,
            missing_distinct_tokens=candidate.missing_distinct_tokens,
        )

    exact_candidates = [candidate for candidate in candidates if candidate.match_mode == "exact"]
    for candidate in exact_candidates:
        safe_candidate = publish_safe_candidate(candidate)
        if safe_candidate is not None:
            return safe_candidate, rejected_preview[:12], "selected", "exact slug match"

    safe_fuzzy = [
        candidate
        for candidate in candidates
        if candidate.score >= 250 and not candidate.missing_distinct_tokens
    ]
    for candidate in safe_fuzzy:
        safe_candidate = publish_safe_candidate(candidate)
        if safe_candidate is not None:
            return safe_candidate, rejected_preview[:12], "selected", "high-confidence token match"

    if exact_candidates or safe_fuzzy:
        return None, rejected_preview[:12], "skipped_no_safe_source", "no source remains after rendered bad-hash rejection"

    top = candidates[0]
    return (
        None,
        [
            {
                "path": str(item.source.path),
                "hash": item.source_hash,
                "score": item.score,
                "match_mode": item.match_mode,
                "missing_distinct_tokens": list(item.missing_distinct_tokens),
                "raw_slug": item.source.raw_slug,
                "clean_slug": item.source.clean_slug,
            }
            for item in candidates[:12]
        ],
        "skipped_needs_review",
        f"top candidate missing distinct tokens: {list(top.missing_distinct_tokens)}",
    )
def verify_uploaded_public_url(
    url: str,
    *,
    expected_hash: str,
    bad_hashes: set[str],
    timeout: float,
) -> dict[str, Any]:
    first = fetch_url_hash(url, timeout=timeout)
    if first.get("hash") == expected_hash:
        return {"status": "ok", "first": first, "cache_bust": None, "purge_recommended": False}

    bust_url = f"{url}{'&' if '?' in url else '?'}v={int(time.time())}"
    second = fetch_url_hash(bust_url, timeout=timeout)
    if second.get("hash") == expected_hash:
        return {"status": "cache_stale", "first": first, "cache_bust": second, "purge_recommended": True}
    if first.get("hash") in bad_hashes or second.get("hash") in bad_hashes:
        return {"status": "still_bad_hash", "first": first, "cache_bust": second, "purge_recommended": True}
    return {"status": "mismatch", "first": first, "cache_bust": second, "purge_recommended": True}


def execute_upload(
    db,
    target: Target,
    candidate: Candidate,
    *,
    bad_hashes: set[str],
    timeout: float,
    verify_delay_sec: float,
) -> dict[str, Any]:
    publish_webp = render_publish_webp(candidate.source.path)
    publish_hash = sha256_bytes(publish_webp)
    if publish_hash in bad_hashes:
        return {
            "status": "skipped_no_safe_source",
            "reason": "rendered source image matches known bad hash",
            "publish_hash": publish_hash,
        }
    if candidate.publish_hash and candidate.publish_hash != publish_hash:
        return {
            "status": "failed",
            "error": f"render hash changed before upload: selected={candidate.publish_hash} actual={publish_hash}",
            "publish_hash": publish_hash,
        }
    public_url, upload_payload, _delivery_meta = upload_binary_to_cloudflare_r2(
        db,
        object_key=target.object_key,
        filename=f"{target.slug}.webp",
        content=publish_webp,
    )
    uploaded_key = str(upload_payload.get("object_key") or "").strip().lstrip("/")
    if uploaded_key != target.object_key:
        return {
            "status": "failed",
            "error": f"canonical key mismatch: expected={target.object_key} actual={uploaded_key}",
            "upload_payload": upload_payload,
            "publish_hash": publish_hash,
        }
    if verify_delay_sec > 0:
        time.sleep(verify_delay_sec)
    verification = verify_uploaded_public_url(
        target.public_url,
        expected_hash=publish_hash,
        bad_hashes=bad_hashes,
        timeout=timeout,
    )
    if verification["status"] not in {"ok", "cache_stale"}:
        return {
            "status": "failed",
            "error": f"verification failed: {verification['status']}",
            "uploaded_public_url": public_url,
            "upload_payload": upload_payload,
            "publish_hash": publish_hash,
            "verification": verification,
        }
    return {
        "status": "uploaded",
        "uploaded_public_url": public_url,
        "upload_payload": upload_payload,
        "publish_hash": publish_hash,
        "verification": verification,
    }


def parse_scan_roots(values: list[str]) -> tuple[Path, ...]:
    if not values:
        return DEFAULT_SCAN_ROOTS
    roots: list[Path] = []
    for value in values:
        for token in str(value or "").split(","):
            token = token.strip()
            if token:
                roots.append(Path(token))
    return tuple(roots or DEFAULT_SCAN_ROOTS)


def build_action_payload(
    target: Target,
    *,
    remote: dict[str, Any],
    candidate: Candidate | None,
    status: str,
    reason: str,
    preview: list[dict[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "article_id": target.article_id,
        "blog_id": target.blog_id,
        "slug": target.slug,
        "title": target.title,
        "published_at": target.published_at,
        "category_key": target.category_key,
        "object_key": target.object_key,
        "public_url": target.public_url,
        "remote_status_code": remote.get("status_code"),
        "remote_hash": remote.get("hash", ""),
        "remote_bytes": remote.get("bytes", 0),
        "status": status,
        "reason": reason,
        "source_preview": preview,
    }
    if candidate is not None:
        payload["source"] = {
            "path": str(candidate.source.path),
            "hash": candidate.source_hash,
            "publish_hash": candidate.publish_hash,
            "size": candidate.source.size,
            "raw_slug": candidate.source.raw_slug,
            "clean_slug": candidate.source.clean_slug,
            "score": candidate.score,
            "match_mode": candidate.match_mode,
            "missing_distinct_tokens": list(candidate.missing_distinct_tokens),
        }
    return payload


def evaluate_duplicate_source_hash_policy(
    article_ids: list[int],
    *,
    selected: dict[int, Candidate],
    targets_by_id: dict[int, Target],
) -> dict[str, Any]:
    slugs = [targets_by_id[article_id].slug for article_id in article_ids if article_id in targets_by_id]
    if len(article_ids) > 2:
        return {
            "allowed": False,
            "reason": "same source hash selected for more than two target slugs",
            "duplicate_source_hash_slugs": sorted(slugs),
        }
    target_token_sets = [set(slug_tokens(targets_by_id[article_id].slug, distinct=True)) for article_id in article_ids if article_id in targets_by_id]
    if not target_token_sets:
        return {
            "allowed": False,
            "reason": "duplicate source hash target tokens are empty",
            "duplicate_source_hash_slugs": sorted(slugs),
        }
    shared_topic_tokens = set.intersection(*target_token_sets)
    first_candidate = selected[article_ids[0]]
    source_tokens = set(first_candidate.source.distinct_tokens)
    if len(shared_topic_tokens) >= 2 and shared_topic_tokens <= source_tokens:
        return {
            "allowed": True,
            "reason": "same source hash allowed for near-duplicate same-topic slugs",
            "duplicate_source_hash_slugs": sorted(slugs),
            "shared_topic_tokens": sorted(shared_topic_tokens),
            "source_distinct_tokens": sorted(source_tokens),
        }
    return {
        "allowed": False,
        "reason": "same source hash selected for multiple target slugs without enough shared source-backed topic tokens",
        "duplicate_source_hash_slugs": sorted(slugs),
        "shared_topic_tokens": sorted(shared_topic_tokens),
        "source_distinct_tokens": sorted(source_tokens),
    }


def main() -> int:
    args = parse_args()
    execute = bool(args.execute)
    published_from = parse_utc_datetime_bound(args.published_from)
    published_to_exclusive = parse_utc_datetime_bound(args.published_to, inclusive_date_end=True)
    bad_hashes = {str(item).strip().upper() for item in args.bad_hash if str(item).strip()}
    if not bad_hashes:
        bad_hashes = {DEFAULT_BAD_HASH}
    bad_source_hashes = set(DEFAULT_BAD_SOURCE_HASHES)
    bad_source_hashes.update(str(item).strip().upper() for item in args.bad_source_hash if str(item).strip())
    bad_source_hashes.update(bad_hashes)

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "execute" if execute else "dry-run",
        "blog_id": int(args.blog_id),
        "profile_key": str(args.profile_key),
        "bad_hashes": sorted(bad_hashes),
        "bad_source_hashes": sorted(bad_source_hashes),
        "scan_roots": [str(path) for path in parse_scan_roots(args.scan_root)],
        "published_from": published_from.isoformat() if published_from else "",
        "published_to": str(args.published_to or ""),
        "published_to_exclusive": published_to_exclusive.isoformat() if published_to_exclusive else "",
        "repair_duplicate_remote_hashes": bool(args.repair_duplicate_remote_hashes),
        "report_dir": str(Path(args.report_dir)),
        "actions": [],
        "status_counts": {},
        "summary": {},
    }

    scan_roots = parse_scan_roots(args.scan_root)
    report_dir = Path(str(args.report_dir)).resolve()
    with SessionLocal() as db:
        public_base_url = resolve_public_base_url(db, str(args.public_base_url or ""))
        report["public_base_url"] = public_base_url
        targets = load_target_articles(
            db,
            profile_key=str(args.profile_key),
            blog_id=int(args.blog_id),
            public_base_url=public_base_url,
            published_from=published_from,
            published_to_exclusive=published_to_exclusive,
        )
        report["target_count"] = len(targets)

        remote_hashes = fetch_current_remote_hashes(
            targets,
            timeout=float(args.http_timeout),
            max_workers=int(args.max_workers),
        )
        remote_duplicate_hash_clusters = build_remote_duplicate_hash_clusters(targets, remote_hashes)
        duplicate_remote_hashes = {
            str(cluster["hash"]).upper()
            for cluster in remote_duplicate_hash_clusters
            if bool(args.repair_duplicate_remote_hashes)
        }
        known_bad_targets = [
            target
            for target in targets
            if str(remote_hashes.get(target.article_id, {}).get("hash", "")).upper() in bad_hashes
        ]
        bad_targets = [
            target
            for target in targets
            if str(remote_hashes.get(target.article_id, {}).get("hash", "")).upper() in bad_hashes
            or str(remote_hashes.get(target.article_id, {}).get("hash", "")).upper() in duplicate_remote_hashes
        ]
        report["remote_duplicate_hash_clusters"] = remote_duplicate_hash_clusters
        report["remote_duplicate_hash_cluster_count"] = len(remote_duplicate_hash_clusters)
        report["remote_duplicate_target_count"] = len(
            {
                article_id
                for cluster in remote_duplicate_hash_clusters
                for article_id in cluster.get("article_ids", [])
            }
        )
        report["remote_bad_count"] = len(known_bad_targets)
        report["repair_target_count"] = len(bad_targets)
        report["remote_error_count"] = len([target for target in targets if not remote_hashes.get(target.article_id, {}).get("ok")])

        sources = build_source_records(scan_roots)
        report["scanned_source_count"] = len(sources)
        hash_cache: dict[str, str] = {}
        publish_hash_cache: dict[str, str] = {}
        selected: dict[int, Candidate] = {}
        pending_payloads: dict[int, dict[str, Any]] = {}

        for target in bad_targets:
            candidate, preview, status, reason = find_best_candidate(
                target,
                sources,
                bad_source_hashes=bad_source_hashes,
                hash_cache=hash_cache,
                publish_hash_cache=publish_hash_cache,
            )
            if candidate is not None and status == "selected":
                remote_hash = str(remote_hashes[target.article_id].get("hash", "") or "").upper()
                if remote_hash and remote_hash == candidate.publish_hash:
                    report["actions"].append(
                        build_action_payload(
                            target,
                            remote=remote_hashes[target.article_id],
                            candidate=candidate,
                            status="skipped_already_matches_source",
                            reason="current remote hash already matches selected source render",
                            preview=preview,
                        )
                    )
                    continue
                selected[target.article_id] = candidate
                pending_payloads[target.article_id] = build_action_payload(
                    target,
                    remote=remote_hashes[target.article_id],
                    candidate=candidate,
                    status="planned_upload" if not execute else "pending_upload",
                    reason=reason,
                    preview=preview,
                )
                continue
            report["actions"].append(
                build_action_payload(
                    target,
                    remote=remote_hashes[target.article_id],
                    candidate=None,
                    status=status,
                    reason=reason,
                    preview=preview,
                )
            )

        by_source_hash: dict[str, list[int]] = defaultdict(list)
        for article_id, candidate in selected.items():
            by_source_hash[candidate.source_hash].append(article_id)
        bad_target_by_id = {target.article_id: target for target in bad_targets}
        duplicate_source_hash_policy_by_id: dict[int, dict[str, Any]] = {}
        for article_ids in by_source_hash.values():
            if len(article_ids) <= 1:
                continue
            policy = evaluate_duplicate_source_hash_policy(article_ids, selected=selected, targets_by_id=bad_target_by_id)
            for article_id in article_ids:
                duplicate_source_hash_policy_by_id[article_id] = policy

        for article_id, payload in pending_payloads.items():
            target = bad_target_by_id[article_id]
            candidate = selected[article_id]
            duplicate_policy = duplicate_source_hash_policy_by_id.get(article_id)
            if duplicate_policy:
                payload.update({key: value for key, value in duplicate_policy.items() if key != "allowed"})
                payload["source_hash_policy"] = "allowed_same_topic_source_hash" if duplicate_policy.get("allowed") else "skipped_duplicate_source_hash"
            if duplicate_policy and not duplicate_policy.get("allowed"):
                payload["status"] = "skipped_duplicate_source_hash"
                report["actions"].append(payload)
                continue

            if not execute:
                if duplicate_policy and duplicate_policy.get("allowed"):
                    payload["status"] = "allowed_same_topic_source_hash"
                report["actions"].append(payload)
                continue

            try:
                upload_result = execute_upload(
                    db,
                    target,
                    candidate,
                    bad_hashes=bad_hashes,
                    timeout=float(args.http_timeout),
                    verify_delay_sec=float(args.verify_delay_sec),
                )
                payload.update(upload_result)
            except Exception as exc:  # noqa: BLE001
                payload["status"] = "failed"
                payload["error"] = str(exc)
            report["actions"].append(payload)

    report["actions"].sort(key=lambda item: int(item.get("article_id") or 0))
    report["status_counts"] = dict(Counter(str(item.get("status") or "unknown") for item in report["actions"]))
    report["summary"] = {
        "target_count": report.get("target_count", 0),
        "remote_bad_count": report.get("remote_bad_count", 0),
        "repair_target_count": report.get("repair_target_count", 0),
        "remote_duplicate_hash_clusters": report.get("remote_duplicate_hash_cluster_count", 0),
        "remote_duplicate_target_count": report.get("remote_duplicate_target_count", 0),
        "uploaded": report["status_counts"].get("uploaded", 0),
        "planned_upload": report["status_counts"].get("planned_upload", 0),
        "allowed_same_topic_source_hash": len(
            [
                item
                for item in report["actions"]
                if item.get("status") == "allowed_same_topic_source_hash"
                or item.get("source_hash_policy") == "allowed_same_topic_source_hash"
            ]
        ),
        "skipped_no_safe_source": report["status_counts"].get("skipped_no_safe_source", 0),
        "skipped_needs_review": report["status_counts"].get("skipped_needs_review", 0),
        "skipped_duplicate_source_hash": report["status_counts"].get("skipped_duplicate_source_hash", 0),
        "skipped_already_matches_source": report["status_counts"].get("skipped_already_matches_source", 0),
        "failed": report["status_counts"].get("failed", 0),
    }
    path = report_path(report_dir, str(args.report_prefix))
    report["report_path"] = str(path)
    write_json(path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 1 if execute and report["status_counts"].get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

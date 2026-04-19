from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.orm import selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, SyncedBloggerPost  # noqa: E402
from app.services.content.article_service import build_article_r2_asset_object_key  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import (  # noqa: E402
    normalize_r2_url_to_key,
    upload_binary_to_cloudflare_r2,
)

MYSTERY_BLOG_ID = 35
LIVE_STATUSES = {"LIVE", "PUBLISHED", "live", "published"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
URL_RE = re.compile(r"https?://[^\s'\"<>()]+", re.IGNORECASE)
DEFAULT_EXTRA_SOURCE_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\app\storage\images")
MYSTERY_KEY_RE = re.compile(
    r"^assets/the-midnight-archives/[a-z0-9-]+/\d{4}/\d{2}/[a-z0-9-]+/[a-z0-9-]+\.webp$",
    re.IGNORECASE,
)
TIMESTAMP_SUFFIX_RE = re.compile(r"^(?P<slug>.+)-\d{14}$", re.IGNORECASE)
HASH_SUFFIX_RE = re.compile(r"^(?P<slug>.+)[.-][a-f0-9]{8,}$", re.IGNORECASE)
INLINE_SUFFIX_RE = re.compile(r"^(?P<slug>.+)-inline-[a-z0-9-]+$", re.IGNORECASE)
STOPWORDS = {
    "the",
    "of",
    "and",
    "a",
    "an",
    "what",
    "how",
    "why",
    "new",
    "latest",
    "inside",
    "can",
    "case",
    "mystery",
    "history",
    "true",
    "story",
    "fact",
    "facts",
    "review",
    "revisited",
    "documentary",
    "explained",
    "reality",
    "recent",
    "news",
    "with",
    "from",
    "for",
    "its",
    "into",
    "investigative",
    "investigating",
    "reexamined",
    "reexamining",
    "reconstruction",
    "forensic",
}
UNMAPPED_EXTRA_SOURCE_RE = re.compile(r"^(cover|hero-refresh|inline-3x2)-", re.IGNORECASE)
EXTRA_SOURCE_SLUG_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|/)beast-gevaudan-18th-century-france-mystery(?:-inline-3x2)?\.(webp|png|jpe?g)$", re.IGNORECASE), "the-beast-of-gevaudan-unraveling"),
    (re.compile(r"(^|/)frederick-valentich-disappearance-1978-australia-ufo-case-file(?:-inline-3x2)?\.(webp|png|jpe?g)$", re.IGNORECASE), "case-file-disappearance-of-frederick"),
    (re.compile(r"(^|/)curse-of-the-pharaohs-fact-vs-fiction-ancient-egyptian-tomb-legends\.(webp|png|jpe?g)$", re.IGNORECASE), "the-curse-of-pharaohs-fact-vs-fiction"),
    (re.compile(r"(^|/)great-molasses-flood-1919-industrial-negligence-legacy\.(webp|png|jpe?g)$", re.IGNORECASE), "the-great-molasses-flood-of-1919-how"),
    (re.compile(r"(^|/)hinterkaifeck-murders-reinvestigation-modern-forensics(?:\.[a-f0-9]{8,})?\.(webp|png|jpe?g)$", re.IGNORECASE), "the-hinterkaifeck-murders"),
    (re.compile(r"(^|/)somerton-man-mystery-forensic-advances-theories\.(webp|png|jpe?g)$", re.IGNORECASE), "the-somerton-man-mystery-new-forensic"),
    (re.compile(r"(^|/)the-roanoke-colony-disappearance-reinvestigation(?:\.[a-f0-9]{8,})?\.(webp|png|jpe?g)$", re.IGNORECASE), "the-roanoke-colony-disappearance"),
    (re.compile(r"(^|/)the-sodder-children-disappearance-revisiting-[^.]+(?:\.[a-f0-9]{8,})?\.(webp|png|jpe?g)$", re.IGNORECASE), "the-sodder-children-disappearance-new-0350460426"),
    (re.compile(r"(^|/)taman-shud-case-south-korea-2000s-unidentified-man(?:-inline-3x2)?\.(webp|png|jpe?g)$", re.IGNORECASE), "the-taman-shud-case-of-south-korea"),
    (re.compile(r"(^|/)vanishing-village-hoer-verde-brazil-1923-mass-disappearance(?:-inline-3x2)?\.(webp|png|jpe?g)$", re.IGNORECASE), "the-vanishing-village-of-hoer-verde"),
)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: Any, *, fallback: str = "") -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", _safe_str(value).lower()).strip("-")
    if normalized:
        return normalized
    return re.sub(r"[^a-z0-9]+", "-", _safe_str(fallback).lower()).strip("-")


def _normalize_token(token: str) -> str:
    lowered = _safe_str(token).lower()
    if lowered.endswith("ies") and len(lowered) > 4:
        return lowered[:-3] + "y"
    if lowered.endswith("s") and len(lowered) > 4 and not lowered.endswith("ss"):
        return lowered[:-1]
    return lowered


def _tokenize(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw in re.split(r"[^a-z0-9]+", _safe_str(value).lower()):
        token = _normalize_token(raw)
        if token:
            tokens.append(token)
    return tuple(tokens)


def _meaningful_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in _tokenize(value) if token and token not in STOPWORDS)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _extract_post_slug(row: SyncedBloggerPost) -> str:
    candidate = _safe_str(row.url).rstrip("/")
    if candidate:
        tail = candidate.split("/")[-1]
        if tail.endswith(".html"):
            tail = tail[:-5]
        normalized = _slugify(tail)
        if normalized:
            return normalized
    return _slugify(row.title or row.remote_post_id)


def _resolve_storage_root() -> Path:
    candidate = _safe_str(os.environ.get("STORAGE_ROOT"))
    if candidate:
        return Path(candidate)
    return Path("/app/storage")


def _archive_root(storage_root: Path) -> Path:
    return storage_root / "the-midnight-archives"


def _review_manifest_path(storage_root: Path) -> Path:
    return _archive_root(storage_root) / "reports" / "mystery-unique-image-review.json"


def _override_manifest_path(storage_root: Path) -> Path:
    return _archive_root(storage_root) / "commands" / "mystery-manual-review-overrides.json"


def _final_manifest_path(storage_root: Path) -> Path:
    return _archive_root(storage_root) / "reports" / "mystery-unique-image-final-selection.json"


def _review_image_root(storage_root: Path) -> Path:
    return _archive_root(storage_root) / "images" / "review"


def _unmapped_extra_review_root(storage_root: Path) -> Path:
    return _review_image_root(storage_root) / "unmapped-app-storage"


def _app_storage_imported_root(storage_root: Path) -> Path:
    return _archive_root(storage_root) / "images" / "app-storage-imported"


def _canonical_image_root(storage_root: Path) -> Path:
    return _archive_root(storage_root) / "images" / "slug-canonical"


def _variants_root(storage_root: Path) -> Path:
    return _archive_root(storage_root) / "images" / "slug-variants"


def _mystery_local_root(storage_root: Path) -> Path:
    return storage_root / "images" / "mystery"


def _current_mystery_urls(*parts: str) -> list[str]:
    candidates: list[str] = []
    for raw in parts:
        for match in URL_RE.findall(raw or ""):
            parsed = urlparse(_safe_str(match))
            if parsed.scheme not in {"http", "https"}:
                continue
            key = _safe_str(normalize_r2_url_to_key(match)).lstrip("/")
            if not MYSTERY_KEY_RE.fullmatch(key):
                continue
            candidates.append(match)
    return candidates


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _resolve_manifest_path(storage_root: Path, value: str) -> Path:
    raw = _safe_str(value)
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    return (storage_root / raw).resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _extra_source_roots_from_args(args: argparse.Namespace | None) -> list[Path]:
    raw_values = list(getattr(args, "extra_source_root", None) or [])
    roots = [Path(_safe_str(value)).resolve() for value in raw_values if _safe_str(value)]
    if not roots and DEFAULT_EXTRA_SOURCE_ROOT.exists():
        roots.append(DEFAULT_EXTRA_SOURCE_ROOT.resolve())
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _extra_source_slug_for_path(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.name
    for pattern, slug in EXTRA_SOURCE_SLUG_RULES:
        if pattern.search(rel):
            return slug
    return ""


def _is_unmapped_extra_source_file(path: Path) -> bool:
    return bool(UNMAPPED_EXTRA_SOURCE_RE.match(path.name))


def _canonical_key_from_row(*, article: Article | None, row: SyncedBloggerPost | None) -> tuple[str, str]:
    if article is not None:
        image = article.image
        key = build_article_r2_asset_object_key(
            article,
            asset_role="hero",
            timestamp=(getattr(image, "created_at", None) or article.created_at),
        )
        current_public_url = _safe_str(getattr(image, "public_url", ""))
        return key, current_public_url
    if row is not None:
        url_candidates = _current_mystery_urls(row.content_html or "", row.thumbnail_url or "")
        for candidate in url_candidates:
            key = _safe_str(normalize_r2_url_to_key(candidate)).lstrip("/")
            if MYSTERY_KEY_RE.fullmatch(key):
                return key, candidate
    raise RuntimeError("canonical_object_key_missing")


def _match_kind_rank(kind: str) -> int:
    return {"exact": 0, "prefix": 1, "token": 2}.get(kind, 9)


def _source_rank(path: Path) -> int:
    normalized = path.as_posix().lower()
    if "/images/mystery/" in normalized:
        return 0
    if "/the-midnight-archives/images/slug-variants/" in normalized:
        return 1
    if "/the-midnight-archives/images/slug-canonical/" in normalized:
        return 2
    if "/images/" in normalized:
        return 3
    return 9


def _ext_rank(path: Path) -> int:
    return {".webp": 0, ".png": 1, ".jpg": 2, ".jpeg": 2}.get(path.suffix.lower(), 9)


def _normalized_aliases_for_name(stem: str) -> list[str]:
    normalized = _slugify(stem)
    aliases = [normalized] if normalized else []
    for pattern in (TIMESTAMP_SUFFIX_RE, HASH_SUFFIX_RE, INLINE_SUFFIX_RE):
        match = pattern.fullmatch(normalized)
        if match is not None:
            stripped = _slugify(match.group("slug"))
            if stripped and stripped not in aliases:
                aliases.append(stripped)
    return aliases


def _match_alias_to_slug(alias: str, slug: str) -> tuple[str, int] | None:
    alias_slug = _slugify(alias)
    target_slug = _slugify(slug)
    if not alias_slug or not target_slug:
        return None
    if alias_slug == target_slug:
        return ("exact", 100)
    if alias_slug.startswith(f"{target_slug}-") or alias_slug.startswith(f"{target_slug}."):
        return ("prefix", 95)

    target_tokens = set(_meaningful_tokens(target_slug))
    alias_tokens = set(_meaningful_tokens(alias_slug))
    overlap = sorted(target_tokens & alias_tokens)
    if len(overlap) < 2:
        return None
    overlap_ratio = len(overlap) / max(1, len(target_tokens))
    score = int(round(30 + len(overlap) * 10 + overlap_ratio * 20))
    return ("token", min(score, 89))


@dataclass(frozen=True)
class FileRecord:
    path: Path
    relative_path: str
    stem: str
    aliases: tuple[str, ...]
    suffix: str
    sha256: str
    source_rank: int
    ext_rank: int
    size_bytes: int


@dataclass(frozen=True)
class CandidateEdge:
    slug: str
    sha256: str
    match_kind: str
    score: int
    path: Path
    relative_path: str
    source_rank: int
    ext_rank: int
    size_bytes: int
    alias: str


def _candidate_sort_key(edge: CandidateEdge) -> tuple[int, int, int, int, int, str]:
    return (
        _match_kind_rank(edge.match_kind),
        -int(edge.score),
        int(edge.source_rank),
        int(edge.ext_rank),
        len(edge.relative_path),
        edge.relative_path,
    )


def _discover_file_records(storage_root: Path, extra_source_roots: list[Path] | None = None) -> tuple[list[FileRecord], list[dict[str, Any]]]:
    scan_roots = [
        storage_root / "images",
        _archive_root(storage_root) / "images" / "slug-canonical",
        _archive_root(storage_root) / "images" / "slug-variants",
    ]
    discovered: list[FileRecord] = []
    unmapped_extra_files: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append_record(path: Path, *, relative_path: str, aliases: tuple[str, ...], source_rank: int) -> None:
        normalized_path = str(path.resolve())
        if normalized_path in seen:
            return
        seen.add(normalized_path)
        if not aliases:
            return
        try:
            stat = path.stat()
        except OSError:
            return
        discovered.append(
            FileRecord(
                path=path.resolve(),
                relative_path=relative_path,
                stem=_safe_str(path.stem).lower(),
                aliases=aliases,
                suffix=path.suffix.lower(),
                sha256=_sha256_path(path),
                source_rank=source_rank,
                ext_rank=_ext_rank(path),
                size_bytes=int(stat.st_size),
            )
        )

    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            stem = _safe_str(path.stem).lower()
            aliases = tuple(_normalized_aliases_for_name(stem))
            relative_path = path.resolve().relative_to(storage_root.resolve()).as_posix()
            _append_record(path, relative_path=relative_path, aliases=aliases, source_rank=_source_rank(path))

    for root in extra_source_roots or []:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            try:
                rel_to_extra = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                rel_to_extra = path.name
            mapped_slug = _extra_source_slug_for_path(path, root)
            if not mapped_slug:
                if _is_unmapped_extra_source_file(path):
                    unmapped_extra_files.append(
                        {
                            "path": str(path.resolve()),
                            "relative_to_extra_root": rel_to_extra,
                            "sha256": _sha256_path(path),
                            "suffix": path.suffix.lower(),
                            "size_bytes": int(path.stat().st_size),
                        }
                    )
                continue
            stem = _safe_str(path.stem).lower()
            aliases = tuple(dict.fromkeys([mapped_slug, *_normalized_aliases_for_name(stem)]))
            is_inline = "-inline-3x2" in path.name.lower()
            _append_record(
                path,
                relative_path=str(path.resolve()),
                aliases=aliases,
                source_rank=-1 if is_inline else -2,
            )
    return discovered, sorted(unmapped_extra_files, key=lambda item: item["path"])


def _build_candidate_edges(*, slugs: list[str], file_records: list[FileRecord]) -> tuple[dict[str, list[CandidateEdge]], list[dict[str, Any]]]:
    slug_to_edges: dict[str, dict[str, CandidateEdge]] = {slug: {} for slug in slugs}
    candidate_file_paths: dict[str, dict[str, Any]] = {}
    for record in file_records:
        matched_any = False
        for slug in slugs:
            best_for_record: CandidateEdge | None = None
            for alias in record.aliases:
                matched = _match_alias_to_slug(alias, slug)
                if matched is None:
                    continue
                edge = CandidateEdge(
                    slug=slug,
                    sha256=record.sha256,
                    match_kind=matched[0],
                    score=int(matched[1]),
                    path=record.path,
                    relative_path=record.relative_path,
                    source_rank=record.source_rank,
                    ext_rank=record.ext_rank,
                    size_bytes=record.size_bytes,
                    alias=alias,
                )
                if best_for_record is None or _candidate_sort_key(edge) < _candidate_sort_key(best_for_record):
                    best_for_record = edge
            if best_for_record is None:
                continue
            matched_any = True
            current = slug_to_edges[slug].get(record.sha256)
            if current is None or _candidate_sort_key(best_for_record) < _candidate_sort_key(current):
                slug_to_edges[slug][record.sha256] = best_for_record
        if matched_any and record.relative_path not in candidate_file_paths:
            candidate_file_paths[record.relative_path] = {
                "path": record.relative_path,
                "sha256": record.sha256,
                "suffix": record.suffix,
                "source_rank": record.source_rank,
            }
    sorted_edges = {
        slug: sorted(edges.values(), key=_candidate_sort_key)
        for slug, edges in slug_to_edges.items()
        if edges
    }
    return sorted_edges, sorted(candidate_file_paths.values(), key=lambda item: item["path"])


def _assign_unique_hashes(slugs: list[str], slug_to_edges: dict[str, list[CandidateEdge]]) -> dict[str, CandidateEdge]:
    ordered_slugs = sorted(
        slugs,
        key=lambda slug: (
            len(slug_to_edges.get(slug, [])),
            min((_match_kind_rank(edge.match_kind) for edge in slug_to_edges.get(slug, [])), default=9),
            slug,
        ),
    )
    assigned_by_hash: dict[str, str] = {}
    assigned_edge_by_slug: dict[str, CandidateEdge] = {}

    def _dfs(slug: str, seen_hashes: set[str]) -> bool:
        for edge in slug_to_edges.get(slug, []):
            if edge.sha256 in seen_hashes:
                continue
            seen_hashes.add(edge.sha256)
            current_slug = assigned_by_hash.get(edge.sha256)
            if current_slug is None:
                assigned_by_hash[edge.sha256] = slug
                assigned_edge_by_slug[slug] = edge
                return True
            if _dfs(current_slug, seen_hashes):
                assigned_by_hash[edge.sha256] = slug
                assigned_edge_by_slug[slug] = edge
                return True
        return False

    for slug in ordered_slugs:
        _dfs(slug, set())
    return assigned_edge_by_slug


def _convert_to_webp(content: bytes) -> bytes:
    with PILImage.open(BytesIO(content)) as loaded:
        output = BytesIO()
        converted = loaded if loaded.mode in {"RGB", "RGBA"} else loaded.convert("RGB")
        converted.save(output, format="WEBP", quality=88, method=6)
        return output.getvalue()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_local_public_base_url(values: dict[str, Any]) -> str:
    configured = _safe_str(values.get("public_asset_base_url"))
    if configured:
        return configured.rstrip("/")
    return _safe_str(os.environ.get("PUBLIC_API_BASE_URL") or "http://localhost:7002").rstrip("/")


def _copy_review_candidates(storage_root: Path, manual_items: list[dict[str, Any]], unmapped_extra_files: list[dict[str, Any]] | None = None) -> None:
    review_root = _review_image_root(storage_root)
    if review_root.exists():
        shutil.rmtree(review_root)
    _ensure_dir(review_root)
    for item in manual_items:
        slug = _safe_str(item.get("slug"))
        if not slug:
            continue
        slug_dir = review_root / slug
        _ensure_dir(slug_dir)
        for index, option in enumerate(item.get("options") or [], start=1):
            source_path = _resolve_manifest_path(storage_root, _safe_str(option.get("relative_path")))
            if not source_path.exists():
                continue
            destination = slug_dir / f"{index:02d}-{source_path.name}"
            shutil.copy2(source_path, destination)
    unmapped_root = _unmapped_extra_review_root(storage_root)
    for item in unmapped_extra_files or []:
        source_path = _resolve_manifest_path(storage_root, _safe_str(item.get("path")))
        if not source_path.exists():
            continue
        relative = _safe_str(item.get("relative_to_extra_root")) or source_path.name
        destination = unmapped_root / relative
        _ensure_dir(destination.parent)
        shutil.copy2(source_path, destination)


def _write_override_template(storage_root: Path, manual_items: list[dict[str, Any]]) -> Path:
    override_path = _override_manifest_path(storage_root)
    payload = {
        "generated_at": _utc_now_iso(),
        "choices": {
            _safe_str(item.get("slug")): {
                "selected_sha256": _safe_str(item.get("selected_sha256")),
                "selected_path": _safe_str(item.get("selected_path")),
                "recommended_sha256": _safe_str(item.get("selected_sha256")),
                "recommended_path": _safe_str(item.get("selected_path")),
                "options": item.get("options") or [],
            }
            for item in manual_items
            if _safe_str(item.get("slug"))
        },
    }
    _write_json(override_path, payload)
    return override_path


def _load_review_context(db, *, blog_id: int) -> tuple[Blog, dict[str, SyncedBloggerPost], dict[str, Article], dict[str, tuple[str, str]]]:
    blog = db.get(Blog, int(blog_id))
    if blog is None:
        raise RuntimeError(f"blog_not_found:{blog_id}")
    if _safe_str(blog.profile_key).lower() != "world_mystery":
        raise RuntimeError(f"blog_profile_not_mystery:{blog.profile_key}")

    rows = (
        db.execute(
            select(SyncedBloggerPost)
            .where(
                SyncedBloggerPost.blog_id == blog.id,
                SyncedBloggerPost.status.in_(sorted(LIVE_STATUSES)),
            )
            .order_by(SyncedBloggerPost.published_at.desc().nullslast(), SyncedBloggerPost.id.desc())
        )
        .scalars()
        .all()
    )
    row_by_slug: dict[str, SyncedBloggerPost] = {}
    for row in rows:
        slug = _extract_post_slug(row)
        if slug and slug not in row_by_slug:
            row_by_slug[slug] = row

    slugs = sorted(row_by_slug)
    articles = (
        db.execute(
            select(Article)
            .where(
                Article.blog_id == blog.id,
                Article.slug.in_(slugs),
            )
            .options(selectinload(Article.image), selectinload(Article.blog))
        )
        .scalars()
        .all()
    )
    article_by_slug = {_safe_str(article.slug).lower(): article for article in articles}
    canonical_by_slug: dict[str, tuple[str, str]] = {}
    for slug in slugs:
        canonical_by_slug[slug] = _canonical_key_from_row(
            article=article_by_slug.get(slug),
            row=row_by_slug.get(slug),
        )
    return blog, row_by_slug, article_by_slug, canonical_by_slug


def _build_review_payload(*, storage_root: Path, blog_id: int, extra_source_roots: list[Path] | None = None) -> dict[str, Any]:
    with SessionLocal() as db:
        blog, row_by_slug, article_by_slug, canonical_by_slug = _load_review_context(db, blog_id=blog_id)
        slugs = sorted(row_by_slug)
        file_records, unmapped_extra_files = _discover_file_records(storage_root, extra_source_roots)
        slug_to_edges, candidate_file_paths = _build_candidate_edges(slugs=slugs, file_records=file_records)
        assignments = _assign_unique_hashes(slugs, slug_to_edges)
        missing_slugs = [slug for slug in slugs if slug not in assignments]
        if missing_slugs:
            raise RuntimeError(f"unassigned_live_slugs:{','.join(missing_slugs[:10])}")

        selections: list[dict[str, Any]] = []
        manual_items: list[dict[str, Any]] = []
        selected_hashes: list[str] = []
        for slug in slugs:
            edge = assignments[slug]
            row = row_by_slug.get(slug)
            article = article_by_slug.get(slug)
            canonical_key, current_public_url = canonical_by_slug[slug]
            top_candidates: list[dict[str, Any]] = []
            seen_options: set[tuple[str, str]] = set()
            preferred_options = [edge, *slug_to_edges.get(slug, [])]
            for candidate in preferred_options:
                option_key = (candidate.sha256, candidate.relative_path)
                if option_key in seen_options:
                    continue
                seen_options.add(option_key)
                top_candidates.append(
                    {
                        "sha256": candidate.sha256,
                        "relative_path": candidate.relative_path,
                        "match_kind": candidate.match_kind,
                        "score": int(candidate.score),
                        "alias": candidate.alias,
                    }
                )
                if len(top_candidates) >= 3:
                    break
            requires_manual = bool(edge.match_kind == "token")
            payload = {
                "slug": slug,
                "row_id": int(getattr(row, "id", 0) or 0) or None,
                "article_id": int(getattr(article, "id", 0) or 0) or None,
                "image_id": int(getattr(getattr(article, "image", None), "id", 0) or 0) or None,
                "canonical_object_key": canonical_key,
                "current_public_url": current_public_url or None,
                "selected_sha256": edge.sha256,
                "selected_path": edge.relative_path,
                "match_kind": edge.match_kind,
                "score": int(edge.score),
                "candidate_count": len(slug_to_edges.get(slug, [])),
                "status": "manual_review_required" if requires_manual else "auto_confirmed",
                "review_options": top_candidates if requires_manual else [],
            }
            selections.append(payload)
            selected_hashes.append(edge.sha256)
            if requires_manual:
                manual_items.append(
                    {
                        "slug": slug,
                        "selected_sha256": edge.sha256,
                        "selected_path": edge.relative_path,
                        "options": top_candidates,
                    }
                )

        summary = {
            "blog_id": int(blog.id),
            "live_posts": len(slugs),
            "candidate_files": len(file_records),
            "candidate_pool_files": len(candidate_file_paths),
            "candidate_hashes": len({record.sha256 for record in file_records}),
            "selected_posts": len(selections),
            "auto_confirmed": sum(1 for item in selections if item["status"] == "auto_confirmed"),
            "manual_review_required": sum(1 for item in selections if item["status"] == "manual_review_required"),
            "duplicate_hash_groups_after_selection": len(selected_hashes) - len(set(selected_hashes)),
        }
        return {
            "generated_at": _utc_now_iso(),
            "blog_id": int(blog.id),
            "profile_key": _safe_str(blog.profile_key),
            "storage_root": str(storage_root),
            "extra_source_roots": [str(root) for root in extra_source_roots or []],
            "summary": summary,
            "candidate_file_paths": candidate_file_paths,
            "unmapped_extra_files": unmapped_extra_files,
            "selections": selections,
            "manual_review": manual_items,
        }


def _resolve_manual_choice(*, selection: dict[str, Any], override_choices: dict[str, Any]) -> tuple[str, str]:
    slug = _safe_str(selection.get("slug"))
    if selection.get("status") != "manual_review_required":
        return _safe_str(selection.get("selected_sha256")), _safe_str(selection.get("selected_path"))

    override = override_choices.get(slug) if isinstance(override_choices, dict) else None
    selected_sha = _safe_str((override or {}).get("selected_sha256"))
    selected_path = _safe_str((override or {}).get("selected_path"))
    options = selection.get("review_options") or []
    if selected_sha:
        for option in options:
            if _safe_str(option.get("sha256")) == selected_sha:
                return selected_sha, _safe_str(option.get("relative_path"))
    if selected_path:
        for option in options:
            if _safe_str(option.get("relative_path")) == selected_path:
                return _safe_str(option.get("sha256")), selected_path
    raise RuntimeError(f"manual_review_unresolved:{slug}")


def _save_local_webp(path: Path, payload: bytes) -> None:
    _ensure_dir(path.parent)
    path.write_bytes(payload)


def _prune_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue


def _run_review(args: argparse.Namespace) -> dict[str, Any]:
    storage_root = Path(_safe_str(args.storage_root) or _resolve_storage_root()).resolve()
    extra_source_roots = _extra_source_roots_from_args(args)
    review_payload = _build_review_payload(storage_root=storage_root, blog_id=int(args.blog_id), extra_source_roots=extra_source_roots)
    _copy_review_candidates(
        storage_root,
        review_payload.get("manual_review") or [],
        review_payload.get("unmapped_extra_files") or [],
    )
    override_path = _write_override_template(storage_root, review_payload.get("manual_review") or [])
    review_payload["manual_override_path"] = str(override_path)
    _write_json(_review_manifest_path(storage_root), review_payload)
    return review_payload


def _run_apply(args: argparse.Namespace) -> dict[str, Any]:
    storage_root = Path(_safe_str(args.storage_root) or _resolve_storage_root()).resolve()
    review_path = _review_manifest_path(storage_root)
    if not review_path.exists():
        raise RuntimeError(f"review_manifest_missing:{review_path}")
    review_payload = _load_json(review_path)
    override_path = _override_manifest_path(storage_root)
    if not override_path.exists():
        raise RuntimeError(f"manual_override_missing:{override_path}")
    override_payload = _load_json(override_path)
    override_choices = override_payload.get("choices") if isinstance(override_payload, dict) else {}

    local_mystery_root = _mystery_local_root(storage_root)
    canonical_root = _canonical_image_root(storage_root)
    _ensure_dir(local_mystery_root)
    _ensure_dir(canonical_root)

    resolved_choices: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for selection in review_payload.get("selections") or []:
        slug = _safe_str(selection.get("slug"))
        if not slug:
            continue
        selected_sha, selected_relative_path = _resolve_manual_choice(
            selection=selection,
            override_choices=override_choices,
        )
        if selected_sha in {item[0] for item in resolved_choices.values()}:
            raise RuntimeError(f"manual_review_duplicate_sha256:{slug}:{selected_sha}")
        resolved_choices[slug] = (selected_sha, selected_relative_path, selection)

    summary = {
        "blog_id": int(args.blog_id),
        "selected_posts": 0,
        "applied_posts": 0,
        "failed_posts": 0,
        "manual_resolved": 0,
        "unique_hashes": 0,
    }
    items: list[dict[str, Any]] = []
    applied_hashes: set[str] = set()

    with SessionLocal() as db:
        settings_map = get_settings_map(db)
        _, _, article_by_slug, _ = _load_review_context(db, blog_id=int(args.blog_id))

        for slug, (selected_sha, selected_relative_path, selection) in resolved_choices.items():
            summary["selected_posts"] += 1
            try:
                if selection.get("status") == "manual_review_required":
                    summary["manual_resolved"] += 1
                source_path = _resolve_manifest_path(storage_root, selected_relative_path)
                if not source_path.exists():
                    fallback_local_webp = (local_mystery_root / f"{slug}.webp").resolve()
                    if fallback_local_webp.exists():
                        source_path = fallback_local_webp
                    else:
                        raise RuntimeError(f"selected_source_missing:{selected_relative_path}")

                webp_bytes = _convert_to_webp(source_path.read_bytes())
                selected_sha = _sha256_bytes(webp_bytes)
                local_webp_path = local_mystery_root / f"{slug}.webp"
                archive_webp_path = canonical_root / slug / f"{slug}.webp"
                _save_local_webp(local_webp_path, webp_bytes)
                _save_local_webp(archive_webp_path, webp_bytes)

                canonical_key = _safe_str(selection.get("canonical_object_key"))
                public_url, upload_payload, delivery_meta = upload_binary_to_cloudflare_r2(
                    db,
                    object_key=canonical_key,
                    filename=f"{slug}.webp",
                    content=webp_bytes,
                )

                article = article_by_slug.get(slug)
                image = getattr(article, "image", None) if article is not None else None
                if article is not None and image is not None:
                    image.file_path = str(local_webp_path)
                    image.public_url = public_url
                    image_meta = dict(image.image_metadata or {}) if isinstance(image.image_metadata, dict) else {}
                    image_meta.pop("local_png_path", None)
                    image_meta["delivery"] = delivery_meta
                    image_meta["canonical_object_key"] = canonical_key
                    image_meta["curated_unique_image"] = {
                        "selected_sha256": selected_sha,
                        "source_relative_path": selected_relative_path,
                        "applied_at": _utc_now_iso(),
                    }
                    image.image_metadata = image_meta
                    article_meta = dict(article.render_metadata or {}) if isinstance(article.render_metadata, dict) else {}
                    article_meta["mystery_canonical_object_key"] = canonical_key
                    article_meta["curated_unique_image_sha256"] = selected_sha
                    article.render_metadata = article_meta
                    db.add(image)
                    db.add(article)
                    db.commit()

                applied_hashes.add(selected_sha)
                summary["applied_posts"] += 1
                items.append(
                    {
                        "slug": slug,
                        "status": "applied",
                        "selected_sha256": selected_sha,
                        "selected_source_path": selected_relative_path,
                        "local_webp_path": str(local_webp_path.resolve()),
                        "archive_webp_path": str(archive_webp_path.resolve()),
                        "canonical_object_key": canonical_key,
                        "public_url": public_url,
                        "upload_bucket": _safe_str(upload_payload.get("bucket")),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                summary["failed_posts"] += 1
                items.append(
                    {
                        "slug": slug,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

    summary["unique_hashes"] = len(applied_hashes)
    final_payload = {
        "generated_at": _utc_now_iso(),
        "blog_id": int(args.blog_id),
        "storage_root": str(storage_root),
        "summary": summary,
        "items": items,
        "candidate_file_paths": review_payload.get("candidate_file_paths") or [],
    }
    _write_json(_final_manifest_path(storage_root), final_payload)
    return final_payload


def _run_cleanup(args: argparse.Namespace) -> dict[str, Any]:
    storage_root = Path(_safe_str(args.storage_root) or _resolve_storage_root()).resolve()
    final_path = _final_manifest_path(storage_root)
    if not final_path.exists():
        raise RuntimeError(f"final_manifest_missing:{final_path}")
    final_payload = _load_json(final_path)
    archive_root = _archive_root(storage_root).resolve()
    keep_paths = {
        str((_mystery_local_root(storage_root) / f"{_safe_str(item.get('slug'))}.webp").resolve())
        for item in final_payload.get("items") or []
        if _safe_str(item.get("status")) == "applied" and _safe_str(item.get("slug"))
    }

    summary = {
        "deleted_candidate_files": 0,
        "deleted_mystery_local_files": 0,
        "deleted_slug_variant_files": 0,
        "archived_extra_source_files": 0,
        "deleted_extra_source_files": 0,
        "remaining_mystery_webp": 0,
        "remaining_mystery_other": 0,
        "remaining_slug_variant_files": 0,
        "remaining_extra_source_files": 0,
    }

    extra_source_roots = _extra_source_roots_from_args(args)
    if bool(getattr(args, "cleanup_extra_source", False)):
        imported_root = _app_storage_imported_root(storage_root)
        for extra_root in extra_source_roots:
            if not extra_root.exists():
                continue
            for path in sorted(extra_root.rglob("*")):
                if not path.is_file():
                    continue
                try:
                    relative = path.resolve().relative_to(extra_root.resolve())
                except ValueError:
                    relative = Path(path.name)
                destination = imported_root / relative
                _ensure_dir(destination.parent)
                shutil.copy2(path, destination)
                summary["archived_extra_source_files"] += 1

    for item in final_payload.get("candidate_file_paths") or []:
        relative_path = _safe_str(item.get("path"))
        if not relative_path:
            continue
        candidate_path = _resolve_manifest_path(storage_root, relative_path)
        if not candidate_path.exists():
            continue
        if str(candidate_path) in keep_paths:
            continue
        if any(_is_relative_to(candidate_path, extra_root) for extra_root in extra_source_roots):
            continue
        try:
            candidate_path.relative_to(archive_root)
            continue
        except ValueError:
            pass
        try:
            candidate_path.unlink()
            summary["deleted_candidate_files"] += 1
        except OSError:
            continue

    mystery_root = _mystery_local_root(storage_root)
    if mystery_root.exists():
        for path in mystery_root.rglob("*"):
            if not path.is_file():
                continue
            if str(path.resolve()) in keep_paths:
                continue
            try:
                path.unlink()
                summary["deleted_mystery_local_files"] += 1
            except OSError:
                continue
        _prune_empty_dirs(mystery_root)
        for path in mystery_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".webp":
                summary["remaining_mystery_webp"] += 1
            else:
                summary["remaining_mystery_other"] += 1

    variants_root = _variants_root(storage_root)
    if variants_root.exists():
        for path in variants_root.rglob("*"):
            if not path.is_file():
                continue
            try:
                path.unlink()
                summary["deleted_slug_variant_files"] += 1
            except OSError:
                continue
        _prune_empty_dirs(variants_root)
        summary["remaining_slug_variant_files"] = sum(1 for path in variants_root.rglob("*") if path.is_file())

    if bool(getattr(args, "cleanup_extra_source", False)):
        for extra_root in extra_source_roots:
            if not extra_root.exists():
                continue
            for path in sorted((item for item in extra_root.rglob("*") if item.is_file()), key=lambda item: len(item.parts), reverse=True):
                try:
                    path.unlink()
                    summary["deleted_extra_source_files"] += 1
                except OSError:
                    continue
            _prune_empty_dirs(extra_root)
    for extra_root in extra_source_roots:
        if extra_root.exists():
            summary["remaining_extra_source_files"] += sum(1 for path in extra_root.rglob("*") if path.is_file())

    cleanup_payload = {
        "generated_at": _utc_now_iso(),
        "blog_id": int(args.blog_id),
        "storage_root": str(storage_root),
        "extra_source_roots": [str(root) for root in extra_source_roots],
        "summary": summary,
    }
    _write_json(_final_manifest_path(storage_root), {**final_payload, "cleanup": cleanup_payload})
    return cleanup_payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Curate 1:1 unique mystery images for live posts.")
    parser.add_argument("--blog-id", type=int, default=MYSTERY_BLOG_ID)
    parser.add_argument("--mode", choices=("review", "apply", "cleanup"), required=True)
    parser.add_argument("--storage-root", default="", help="Optional storage root override.")
    parser.add_argument("--extra-source-root", action="append", default=[], help="Additional mystery image source root.")
    parser.add_argument("--cleanup-extra-source", action="store_true", help="Archive and remove files from extra source roots during cleanup.")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if int(args.blog_id) != MYSTERY_BLOG_ID:
        raise RuntimeError(f"mystery_blog_only:{args.blog_id}")
    if args.mode == "review":
        payload = _run_review(args)
    elif args.mode == "apply":
        payload = _run_apply(args)
    else:
        payload = _run_cleanup(args)
    print(json.dumps(payload.get("summary") or {}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

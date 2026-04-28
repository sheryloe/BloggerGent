from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ManagedChannel, SyncedCloudflarePost
from app.services.cloudflare.cloudflare_asset_policy import (
    CLOUDFLARE_MANAGED_CHANNEL_ID,
    CloudflareAssetPolicy,
    assert_cloudflare_asset_scope,
    build_cloudflare_local_asset_path,
    build_cloudflare_r2_object_key,
    get_cloudflare_asset_policy,
    resolve_cloudflare_post_slug,
    resolve_cloudflare_local_asset_root,
)
from app.services.cloudflare.cloudflare_channel_service import (
    _fetch_integration_post_detail,
    _integration_data_or_raise,
    _integration_request,
    _prepare_markdown_body,
    _strip_generated_body_images,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts
from app.services.integrations.settings_service import get_settings_map
from app.services.integrations.storage_service import ensure_cloudflare_r2_bucket, upload_binary_to_cloudflare_r2
from app.services.platform.platform_service import ensure_managed_channels

try:
    from rapidfuzz import fuzz as rapidfuzz_fuzz
except ImportError:  # pragma: no cover - fallback for environments without rapidfuzz
    from difflib import SequenceMatcher

    class _RapidFuzzFallback:
        @staticmethod
        def ratio(left: str, right: str) -> float:
            return SequenceMatcher(a=left, b=right).ratio() * 100.0

    rapidfuzz_fuzz = _RapidFuzzFallback()

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}
INLINE_ROLE_RE = re.compile(r"(?:^|[-_])inline(?:[-_][0-9]+x[0-9]+)?(?:$|[-_])", re.IGNORECASE)
LEGACY_COVER_RE = re.compile(r"^cover-[a-z0-9]{6,}$", re.IGNORECASE)
SIMILARITY_SEPARATOR_RE = re.compile(r"[-_]+")
SIMILARITY_SPACE_RE = re.compile(r"\s+")
KNOWN_SUFFIX_TOKENS = {"inline", "3x2", "hero", "main"}
SIMILARITY_AUTO_THRESHOLD = 92.0
SIMILARITY_CONDITIONAL_THRESHOLD = 85.0
SIMILARITY_GAP_THRESHOLD = 5.0
DEFAULT_IGNORE_FILENAME_PATTERNS = ("cover",)
DEFAULT_SOURCE_SCOPE = "cloudflare_backup_tree"
BACKUP_TREE_EXCLUDED_DIRS = {"mystery", "travel", "probe", "_manifests"}
REMOTE_THUMBNAIL_PREFLIGHT_SAMPLE_SIZE = 20
REMOTE_THUMBNAIL_PREFLIGHT_MIN_SUCCESS_RATIO = 0.5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_slug(value: Any) -> str:
    return slugify(str(value or "").strip(), separator="-") or ""


def _legacy_url_scheme(url: str | None) -> str:
    lowered = str(url or "").strip().lower()
    if not lowered:
        return "missing"
    if "/assets/media/cloudflare/" in lowered and "/assets/assets/" not in lowered:
        return "canonical_cloudflare"
    if "/assets/assets/media/cloudflare/" in lowered:
        return "legacy_assets_assets_media_cloudflare"
    if "/assets/media/posts/" in lowered:
        return "legacy_media_posts"
    if "/assets/" in lowered:
        return "other_assets"
    return "other"


def _asset_slug_from_url(url: str | None) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.path:
        return ""
    parts = [segment for segment in parsed.path.split("/") if segment]
    if not parts:
        return ""
    filename = Path(parts[-1]).stem
    if parts[-1].lower().endswith(".webp") and len(parts) >= 2 and parts[-2] == filename:
        return _normalize_slug(parts[-2])
    if parts[-1].lower().endswith(".webp") and len(parts) >= 2 and LEGACY_COVER_RE.fullmatch(filename):
        return _normalize_slug(parts[-2])
    cleaned = INLINE_ROLE_RE.sub("", filename)
    if cleaned:
        return _normalize_slug(cleaned)
    if len(parts) >= 2:
        return _normalize_slug(parts[-2])
    return ""


def _legacy_object_slug_from_url(url: str | None) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.path:
        return ""
    parts = [segment for segment in parsed.path.split("/") if segment]
    if len(parts) < 2:
        return ""
    return _normalize_slug(parts[-2])


def _strip_similarity_suffixes(value: str) -> str:
    tokens = [token for token in SIMILARITY_SPACE_RE.split(value.strip()) if token]
    while tokens and tokens[-1] in KNOWN_SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _normalize_similarity_text(value: Any) -> str:
    decoded = unquote(str(value or "").strip()).casefold()
    if not decoded:
        return ""
    normalized = SIMILARITY_SEPARATOR_RE.sub(" ", decoded)
    normalized = SIMILARITY_SPACE_RE.sub(" ", normalized).strip()
    if not normalized:
        return ""
    return _strip_similarity_suffixes(normalized)


def _contains_ignored_pattern(path: Path, *, ignore_patterns: list[str]) -> bool:
    lowered_name = unquote(path.name).casefold()
    lowered_stem = unquote(path.stem).casefold()
    for raw_pattern in ignore_patterns:
        normalized = str(raw_pattern or "").strip().casefold()
        if not normalized:
            continue
        if normalized in lowered_name or normalized in lowered_stem:
            return True
    return False


def _clean_candidate_stem(path: Path) -> str:
    stem = str(path.stem or "").strip()
    if not stem:
        return ""
    if LEGACY_COVER_RE.fullmatch(stem):
        parent_name = _normalize_slug(path.parent.name)
        if parent_name and parent_name not in {"cloudflare", "images"}:
            return parent_name
    return _normalize_slug(_normalize_similarity_text(stem))


def _candidate_role(path: Path) -> str:
    raw_stem = unquote(str(path.stem or "").strip()).casefold()
    if "inline" in raw_stem:
        return "inline"
    return "hero"


def _slug_similarity_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return float(rapidfuzz_fuzz.ratio(left, right))


def _extension_priority(path: Path) -> int:
    lowered = path.suffix.lower()
    if lowered == ".webp":
        return 2
    if lowered == ".png":
        return 1
    return 0


def _cloudflare_manifest_dir(policy: CloudflareAssetPolicy) -> Path:
    return resolve_cloudflare_local_asset_root(policy, prefer_existing=False) / "_manifests"


def _storage_images_root(policy: CloudflareAssetPolicy) -> Path:
    local_root = resolve_cloudflare_local_asset_root(policy, prefer_existing=False)
    if local_root.name.lower() == "cloudflare":
        return local_root.parent
    return local_root.parent if local_root.parent.exists() else local_root


def _iter_image_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return (
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def _candidate_category_slug(path: Path, *, policy: CloudflareAssetPolicy) -> str:
    local_root = resolve_cloudflare_local_asset_root(policy, prefer_existing=False)
    try:
        relative = path.resolve().relative_to(local_root.resolve())
    except ValueError:
        return ""
    parts = list(relative.parts)
    if len(parts) < 2:
        return ""
    category_slug = str(parts[0] or "").strip()
    if category_slug in policy.allowed_category_slugs:
        return category_slug
    return ""


def _raw_candidate_slug(path: Path) -> str:
    return _normalize_slug(unquote(str(path.stem or "").strip()))


def _candidate_source_kind(path: Path, *, policy: CloudflareAssetPolicy) -> str:
    if _candidate_category_slug(path, policy=policy):
        return "cloudflare_classified_pool"
    return "cloudflare_backup_pool"


def _should_skip_backup_tree_path(path: Path, *, storage_root: Path, policy: CloudflareAssetPolicy) -> bool:
    try:
        relative = path.resolve().relative_to(storage_root.resolve())
    except ValueError:
        return True
    lower_parts = {str(part).strip().casefold() for part in relative.parts[:-1]}
    if lower_parts & BACKUP_TREE_EXCLUDED_DIRS:
        return True
    local_root = resolve_cloudflare_local_asset_root(policy, prefer_existing=False)
    try:
        local_relative = path.resolve().relative_to(local_root.resolve())
    except ValueError:
        return False
    if local_relative.parts and str(local_relative.parts[0]).strip().casefold() == "_manifests":
        return True
    return False


def _iter_manifest_category_rows(payload: dict[str, Any]) -> Iterable[tuple[str, str]]:
    rows = payload.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            source = str(row.get("source") or "").strip()
            category = str(row.get("target_category") or row.get("category_slug") or "").strip()
            if source and category:
                yield source, category

    for key in ("items", "unresolved"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            source = str(row.get("resolved_local_source") or row.get("source") or "").strip()
            category = str(row.get("category_slug") or row.get("target_category") or "").strip()
            if source and category:
                yield source, category


def _load_manifest_history(manifest_dir: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    source_category_history: dict[str, set[str]] = defaultdict(set)
    stem_category_history: dict[str, set[str]] = defaultdict(set)
    if not manifest_dir.exists():
        return source_category_history, stem_category_history

    manifest_files = sorted(manifest_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for manifest_file in manifest_files[:20]:
        try:
            payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for source, category in _iter_manifest_category_rows(payload):
            normalized_source = str(Path(source))
            source_category_history[normalized_source].add(category)
            stem = _clean_candidate_stem(Path(source))
            if stem:
                stem_category_history[stem].add(category)
    return source_category_history, stem_category_history


def _inventory_candidates(
    policy: CloudflareAssetPolicy,
    *,
    ignore_filename_patterns: list[str] | None = None,
    source_scope: str = DEFAULT_SOURCE_SCOPE,
) -> list[dict[str, Any]]:
    storage_root = _storage_images_root(policy)
    normalized_ignore_patterns = [
        str(pattern or "").strip()
        for pattern in (ignore_filename_patterns or list(DEFAULT_IGNORE_FILENAME_PATTERNS))
        if str(pattern or "").strip()
    ]
    normalized_source_scope = str(source_scope or DEFAULT_SOURCE_SCOPE).strip().lower()
    if normalized_source_scope not in {DEFAULT_SOURCE_SCOPE, "cloudflare_only_root_pool"}:
        raise ValueError(f"Unsupported source_scope: {source_scope}")
    candidates: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    if not storage_root.exists():
        return candidates

    if normalized_source_scope == "cloudflare_only_root_pool":
        iter_paths = sorted(path for path in storage_root.iterdir() if path.is_file())
    else:
        iter_paths = sorted(_iter_image_files(storage_root))

    for path in iter_paths:
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if normalized_source_scope == DEFAULT_SOURCE_SCOPE and _should_skip_backup_tree_path(path, storage_root=storage_root, policy=policy):
            continue
        normalized_path = str(path.resolve())
        if normalized_path in seen_paths:
            continue
        if _contains_ignored_pattern(path, ignore_patterns=normalized_ignore_patterns):
            continue
        seen_paths.add(normalized_path)
        similarity_stem = _normalize_similarity_text(path.stem)
        if not similarity_stem:
            continue
        candidates.append(
            {
                "path": str(path),
                "source_kind": _candidate_source_kind(path, policy=policy),
                "category_slug": _candidate_category_slug(path, policy=policy),
                "raw_slug": _raw_candidate_slug(path),
                "normalized_stem": _clean_candidate_stem(path),
                "similarity_stem": similarity_stem,
                "role": _candidate_role(path),
                "extension": path.suffix.lower(),
            }
        )
    return candidates


def _rank_candidate(post: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    candidate_stem = str(candidate.get("similarity_stem") or "").strip()
    post_similarity_slug = str(post.get("similarity_slug") or "").strip()
    post_slug = str(post.get("slug") or "").strip()
    normalized_candidate_stem = str(candidate.get("normalized_stem") or "").strip()
    raw_candidate_slug = str(candidate.get("raw_slug") or "").strip()
    if not candidate_stem or not post_similarity_slug or not post_slug:
        return {"score": 0.0, "match_source": "", "reason": ""}

    if normalized_candidate_stem and normalized_candidate_stem == post_slug:
        if raw_candidate_slug == post_slug:
            return {"score": 100.0, "match_source": "exact_slug", "reason": "exact_slug"}
        return {"score": 100.0, "match_source": "slug_family", "reason": "slug_family"}

    score = _slug_similarity_ratio(candidate_stem, post_similarity_slug)
    return {"score": score, "match_source": "slug_similarity", "reason": "slug_similarity"}


def _build_legacy_evidence(
    post: dict[str, Any],
    candidate: dict[str, Any],
    *,
    source_category_history: dict[str, set[str]],
    stem_category_history: dict[str, set[str]],
    use_legacy_evidence: bool,
) -> dict[str, Any]:
    url_asset_slug = str(post.get("url_asset_slug") or "").strip()
    legacy_object_slug = str(post.get("legacy_object_slug") or "").strip()
    candidate_path = str(candidate.get("path") or "").strip()
    normalized_stem = str(candidate.get("normalized_stem") or "").strip()
    manifest_categories = set(source_category_history.get(candidate_path, set())) | set(stem_category_history.get(normalized_stem, set()))
    manifest_category_hit = bool(str(post.get("category_slug") or "").strip() and str(post.get("category_slug") or "").strip() in manifest_categories)
    evidence_sources: list[str] = []
    evidence_score = 0.0
    if use_legacy_evidence and normalized_stem:
        if url_asset_slug:
            if normalized_stem == url_asset_slug:
                evidence_sources.append("url_asset_exact")
                evidence_score += 100.0
            elif (
                normalized_stem.startswith(url_asset_slug)
                or url_asset_slug.startswith(normalized_stem)
                or normalized_stem in url_asset_slug
                or url_asset_slug in normalized_stem
            ):
                evidence_sources.append("url_asset_prefix")
                evidence_score += 25.0
        if legacy_object_slug and legacy_object_slug != url_asset_slug:
            if normalized_stem == legacy_object_slug:
                evidence_sources.append("legacy_object_exact")
                evidence_score += 80.0
            elif (
                normalized_stem.startswith(legacy_object_slug)
                or legacy_object_slug.startswith(normalized_stem)
                or normalized_stem in legacy_object_slug
                or legacy_object_slug in normalized_stem
            ):
                evidence_sources.append("legacy_object_prefix")
                evidence_score += 20.0
        if manifest_category_hit:
            evidence_sources.append("manifest_category_hit")
            evidence_score += 10.0
    return {
        "url_asset_slug": url_asset_slug,
        "legacy_object_slug": legacy_object_slug,
        "manifest_category_hit": manifest_category_hit,
        "evidence_score": round(evidence_score, 4),
        "evidence_sources": evidence_sources,
    }


def _is_category_aligned(post: dict[str, Any], candidate: dict[str, Any], evidence: dict[str, Any]) -> bool:
    post_category = str(post.get("category_slug") or "").strip()
    candidate_category = str(candidate.get("category_slug") or "").strip()
    if post_category and candidate_category and post_category == candidate_category:
        return True
    return bool(evidence.get("manifest_category_hit"))


def _rank_candidates_for_post(
    post: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    source_category_history: dict[str, set[str]],
    stem_category_history: dict[str, set[str]],
    use_legacy_evidence: bool,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        score_payload = _rank_candidate(post, candidate)
        score = float(score_payload.get("score") or 0.0)
        evidence = _build_legacy_evidence(
            post,
            candidate,
            source_category_history=source_category_history,
            stem_category_history=stem_category_history,
            use_legacy_evidence=use_legacy_evidence,
        )
        evidence_score = float(evidence.get("evidence_score") or 0.0)
        if score <= 0.0 and evidence_score <= 0.0:
            continue
        source_path = Path(str(candidate["path"]))
        length_gap = abs(len(str(candidate.get("similarity_stem") or "")) - len(str(post.get("similarity_slug") or "")))
        ranked.append(
            {
                "path": str(candidate["path"]),
                "score": round(score, 4),
                "match_source": str(score_payload.get("match_source") or "").strip(),
                "reason": str(score_payload.get("reason") or "").strip(),
                "role": str(candidate.get("role") or "").strip(),
                "source_kind": str(candidate.get("source_kind") or "").strip(),
                "category_slug": str(candidate.get("category_slug") or "").strip(),
                "extension": source_path.suffix.lower(),
                "extension_priority": _extension_priority(source_path),
                "length_gap": length_gap,
                "similarity_stem": str(candidate.get("similarity_stem") or "").strip(),
                "normalized_stem": str(candidate.get("normalized_stem") or "").strip(),
                "raw_slug": str(candidate.get("raw_slug") or "").strip(),
                "evidence_score": evidence_score,
                "evidence_sources": list(evidence.get("evidence_sources") or []),
                "url_asset_slug": str(evidence.get("url_asset_slug") or "").strip(),
                "legacy_object_slug": str(evidence.get("legacy_object_slug") or "").strip(),
                "manifest_category_hit": bool(evidence.get("manifest_category_hit")),
                "category_aligned": _is_category_aligned(post, candidate, evidence),
            }
        )
    ranked.sort(
        key=lambda item: (
            float(item["score"]),
            float(item["evidence_score"]),
            1 if bool(item.get("category_aligned")) else 0,
            1 if str(item["role"]) == "hero" else 0,
            int(item["extension_priority"]),
            -int(item["length_gap"]),
            str(item["path"]),
        ),
        reverse=True,
    )
    return ranked[:8]


def _coerce_post_row(row: SyncedCloudflarePost, *, policy: CloudflareAssetPolicy) -> dict[str, Any]:
    category_slug = str(row.canonical_category_slug or row.category_slug or "").strip()
    resolved_category = category_slug if category_slug in policy.allowed_category_slugs else ""
    slug = resolve_cloudflare_post_slug(row.slug)
    title = _normalize_space(row.title)
    return {
        "remote_post_id": str(row.remote_post_id or "").strip(),
        "slug": slug,
        "similarity_slug": _normalize_similarity_text(row.slug),
        "title": title,
        "category_slug": resolved_category,
        "category_name": _normalize_space(row.canonical_category_name or row.category_name or resolved_category),
        "published_at": row.published_at,
        "thumbnail_url": str(row.thumbnail_url or "").strip(),
        "legacy_url_scheme": _legacy_url_scheme(row.thumbnail_url),
        "url_asset_slug": _asset_slug_from_url(row.thumbnail_url),
        "legacy_object_slug": _legacy_object_slug_from_url(row.thumbnail_url),
        "target_path": str(
            build_cloudflare_local_asset_path(
                policy=policy,
                category_slug=resolved_category,
                post_slug=slug,
                prefer_existing_root=False,
            )
        )
        if resolved_category and slug
        else "",
        "object_key": build_cloudflare_r2_object_key(policy=policy, category_slug=resolved_category, post_slug=slug, published_at=row.published_at) if resolved_category and slug else "",
        "row": row,
    }


def _load_target_posts(db: Session, *, policy: CloudflareAssetPolicy, category_slugs: list[str] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    channel = db.execute(select(ManagedChannel).where(ManagedChannel.channel_id == policy.channel_id)).scalar_one()
    rows = (
        db.execute(
            select(SyncedCloudflarePost)
            .where(SyncedCloudflarePost.managed_channel_id == channel.id)
            .order_by(SyncedCloudflarePost.published_at.desc().nullslast(), SyncedCloudflarePost.id.desc())
        )
        .scalars()
        .all()
    )
    normalized_categories = {str(item or "").strip() for item in (category_slugs or []) if str(item or "").strip()}
    coerced: list[dict[str, Any]] = []
    for row in rows:
        item = _coerce_post_row(row, policy=policy)
        if not item["slug"] or not item["category_slug"]:
            continue
        if normalized_categories and item["category_slug"] not in normalized_categories:
            continue
        coerced.append(item)
        if limit and len(coerced) >= limit:
            break
    return coerced


def _available_second_score(ranked: list[dict[str, Any]], *, chosen_path: str, used_paths: set[str]) -> float:
    for candidate in ranked:
        candidate_path = str(candidate["path"])
        if candidate_path == chosen_path or candidate_path in used_paths:
            continue
        return float(candidate["score"])
    return 0.0


def _empty_post_evidence(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "url_asset_slug": str(post.get("url_asset_slug") or "").strip(),
        "legacy_object_slug": str(post.get("legacy_object_slug") or "").strip(),
        "manifest_category_hit": False,
        "evidence_score": 0.0,
        "evidence_sources": [],
    }


def _select_matches(
    posts: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    use_fallback_heuristic: bool,
    source_category_history: dict[str, set[str]],
    stem_category_history: dict[str, set[str]],
    use_legacy_evidence: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked_posts: list[dict[str, Any]] = []
    for post in posts:
        ranked = _rank_candidates_for_post(
            post,
            candidates,
            source_category_history=source_category_history,
            stem_category_history=stem_category_history,
            use_legacy_evidence=use_legacy_evidence,
        )
        ranked_posts.append({"post": post, "ranked": ranked})
    ranked_posts.sort(key=lambda item: (float(item["ranked"][0]["score"]) if item["ranked"] else -1.0, str(item["post"]["slug"])), reverse=True)

    used_paths: set[str] = set()
    matched: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for entry in ranked_posts:
        post = entry["post"]
        ranked = entry["ranked"]
        chosen: dict[str, Any] | None = None
        for candidate in ranked:
            if str(candidate["path"]) in used_paths:
                continue
            chosen = candidate
            break

        if chosen is None:
            unresolved.append({
                "remote_post_id": post["remote_post_id"],
                "slug": post["slug"],
                "category_slug": post["category_slug"],
                "title": post["title"],
                "legacy_url_scheme": post["legacy_url_scheme"],
                "reason": "no_available_candidate",
                **_empty_post_evidence(post),
                "top_candidates": ranked[:3],
            })
            continue

        score = float(chosen["score"])
        second_score = _available_second_score(ranked, chosen_path=str(chosen["path"]), used_paths=used_paths)
        score_gap = round(score - second_score, 4)
        exact_or_family_match = str(chosen.get("match_source") or "").strip() in {"exact_slug", "slug_family"}
        category_aligned = bool(chosen.get("category_aligned"))
        has_legacy_evidence = bool(list(chosen.get("evidence_sources") or []))
        auto_match = exact_or_family_match or score >= SIMILARITY_AUTO_THRESHOLD
        conditional_match = (
            use_fallback_heuristic
            and score >= SIMILARITY_CONDITIONAL_THRESHOLD
            and score < SIMILARITY_AUTO_THRESHOLD
            and score_gap >= SIMILARITY_GAP_THRESHOLD
            and category_aligned
            and has_legacy_evidence
        )
        if not auto_match and not conditional_match:
            unresolved.append({
                "remote_post_id": post["remote_post_id"],
                "slug": post["slug"],
                "category_slug": post["category_slug"],
                "title": post["title"],
                "legacy_url_scheme": post["legacy_url_scheme"],
                "reason": "low_confidence" if score < SIMILARITY_CONDITIONAL_THRESHOLD else "ambiguous_match",
                "confidence": round(score, 4),
                "score_gap": score_gap,
                "url_asset_slug": str(chosen.get("url_asset_slug") or post.get("url_asset_slug") or "").strip(),
                "legacy_object_slug": str(chosen.get("legacy_object_slug") or post.get("legacy_object_slug") or "").strip(),
                "manifest_category_hit": bool(chosen.get("manifest_category_hit")),
                "evidence_score": round(float(chosen.get("evidence_score") or 0.0), 4),
                "evidence_sources": list(chosen.get("evidence_sources") or []),
                "category_aligned": category_aligned,
                "top_candidates": ranked[:3],
            })
            continue

        used_paths.add(str(chosen["path"]))
        match_source = str(chosen["match_source"] or "").strip()
        if conditional_match:
            match_source = "slug_similarity_gap"
        elif match_source not in {"exact_slug", "slug_family"}:
            match_source = "slug_similarity_auto"
        matched.append({
            **post,
            "match_source": match_source,
            "confidence": round(score, 4),
            "score_gap": score_gap,
            "resolved_local_source": str(chosen["path"]),
            "candidate_role": str(chosen["role"]),
            "candidate_source_kind": str(chosen["source_kind"]),
            "match_reason": str(chosen["reason"]),
            "url_asset_slug": str(chosen.get("url_asset_slug") or post.get("url_asset_slug") or "").strip(),
            "legacy_object_slug": str(chosen.get("legacy_object_slug") or post.get("legacy_object_slug") or "").strip(),
            "manifest_category_hit": bool(chosen.get("manifest_category_hit")),
            "evidence_score": round(float(chosen.get("evidence_score") or 0.0), 4),
            "evidence_sources": list(chosen.get("evidence_sources") or []),
            "category_aligned": category_aligned,
            "top_candidates": ranked[:3],
        })
    return matched, unresolved


def _preflight_remote_thumbnail_fetch(posts: list[dict[str, Any]]) -> dict[str, Any]:
    urls: list[str] = []
    seen: set[str] = set()
    for post in posts:
        url = str(post.get("thumbnail_url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= REMOTE_THUMBNAIL_PREFLIGHT_SAMPLE_SIZE:
            break

    status_breakdown: Counter[str] = Counter()
    successful = 0
    for url in urls:
        status_label = "error"
        try:
            response = httpx.head(url, follow_redirects=True, timeout=20.0)
            if response.status_code == 405 or response.status_code >= 400:
                response = httpx.get(url, headers={"Range": "bytes=0-0"}, follow_redirects=True, timeout=20.0)
            status_label = str(response.status_code)
            if response.status_code < 400:
                successful += 1
        except Exception:  # noqa: BLE001
            status_label = "error"
        status_breakdown[status_label] += 1

    attempted = len(urls)
    enabled = bool(attempted) and successful > 0 and (successful / attempted) >= REMOTE_THUMBNAIL_PREFLIGHT_MIN_SUCCESS_RATIO
    return {
        "enabled": enabled,
        "preflight_count": attempted,
        "successful_preflight_count": successful,
        "status_breakdown": dict(status_breakdown),
    }


def _resolve_public_base_url_for_strategy(db: Session, *, strategy: str) -> str:
    values = get_settings_map(db)
    normalized_strategy = str(strategy or "direct_public").strip().lower()
    if normalized_strategy == "integration_assets":
        integration_base_url = str(values.get("cloudflare_blog_api_base_url") or "").strip().rstrip("/")
        if not integration_base_url:
            raise ValueError("cloudflare_blog_api_base_url must be configured for integration_assets uploads.")
        return f"{integration_base_url}/assets"
    if normalized_strategy == "configured":
        return str(values.get("cloudflare_r2_public_base_url") or "").strip().rstrip("/")
    if normalized_strategy != "direct_public":
        raise ValueError(f"Unsupported public_url_strategy: {strategy}")

    direct_public_base_url = str(
        values.get("cloudflare_r2_direct_public_base_url")
        or values.get("cloudflare_r2_public_base_url")
        or ""
    ).strip().rstrip("/")
    if not direct_public_base_url:
        raise ValueError("cloudflare_r2_direct_public_base_url must be configured for direct_public uploads.")
    if "api.dongriarchive.com" in direct_public_base_url.casefold():
        raise ValueError("direct_public uploads cannot use api.dongriarchive.com as the public base URL.")
    return direct_public_base_url


def _verify_public_image_url(url: str) -> tuple[bool, int | None]:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return False, None
    try:
        response = httpx.head(normalized_url, follow_redirects=True, timeout=20.0)
        if response.status_code == 405 or response.status_code >= 400:
            response = httpx.get(
                normalized_url,
                headers={"Range": "bytes=0-0"},
                follow_redirects=True,
                timeout=20.0,
            )
        return response.status_code < 400, int(response.status_code)
    except Exception:  # noqa: BLE001
        return False, None


def _build_evidence_breakdown(*, matched: list[dict[str, Any]], unresolved: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in list(matched) + list(unresolved):
        for source in list(item.get("evidence_sources") or []):
            normalized = str(source or "").strip()
            if normalized:
                counts[normalized] += 1
    return dict(counts)


def _ensure_webp_bytes(source_path: Path) -> bytes:
    with Image.open(source_path) as loaded:
        output = io.BytesIO()
        converted = loaded.convert("RGB") if loaded.mode not in {"RGB", "RGBA"} else loaded
        converted.save(output, format="WEBP", quality=88, optimize=True, method=6)
        return output.getvalue()


def purge_cloudflare_target_categories(*, policy: CloudflareAssetPolicy, category_slugs: list[str]) -> list[str]:
    root = resolve_cloudflare_local_asset_root(policy, prefer_existing=False)
    purged: list[str] = []
    for category_slug in category_slugs:
        target_dir = root / category_slug
        target_dir.mkdir(parents=True, exist_ok=True)
        assert_cloudflare_asset_scope(policy=policy, category_slug=category_slug, local_path=target_dir)
        for path in sorted(target_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        purged.append(str(target_dir))
    return purged


def _normalize_tag_names(detail: dict[str, Any], row: SyncedCloudflarePost, category_slug: str) -> list[str]:
    tag_names: list[str] = []
    for raw in detail.get("tagNames") or []:
        normalized = _normalize_space(raw)
        if normalized and normalized not in tag_names:
            tag_names.append(normalized)
    if not tag_names:
        for raw in detail.get("tags") or []:
            if isinstance(raw, dict):
                normalized = _normalize_space(raw.get("name") or raw.get("label"))
            else:
                normalized = _normalize_space(raw)
            if normalized and normalized not in tag_names:
                tag_names.append(normalized)
    if not tag_names:
        for raw in [category_slug, *(row.labels or [])]:
            normalized = _normalize_space(raw)
            if normalized and normalized not in tag_names:
                tag_names.append(normalized)
    return tag_names[:20]


def _update_live_post_cover(db: Session, *, row: SyncedCloudflarePost, category_slug: str, cover_image_url: str) -> dict[str, Any]:
    detail = _fetch_integration_post_detail(db, str(row.remote_post_id or "").strip())
    title = _normalize_space(detail.get("title") or row.title or row.slug or "Untitled")
    stripped_body = _strip_generated_body_images(str(detail.get("contentMarkdown") or detail.get("content") or detail.get("markdown") or ""))
    payload: dict[str, Any] = {
        "title": title,
        "content": _prepare_markdown_body(title, stripped_body),
        "excerpt": _normalize_excerpt_length(_normalize_space(detail.get("excerpt") or row.excerpt_text or title)),
        "seoTitle": _normalize_space(detail.get("seoTitle") or title),
        "seoDescription": _normalize_excerpt_length(_normalize_space(detail.get("seoDescription") or row.excerpt_text or title)),
        "tagNames": _normalize_tag_names(detail, row, category_slug),
        "status": _normalize_space(detail.get("status") or row.status or "published") or "published",
        "coverImage": cover_image_url,
        "coverAlt": _normalize_space(detail.get("coverAlt") or row.excerpt_text or title)[:180],
    }
    metadata = detail.get("metadata")
    if isinstance(metadata, dict) and metadata:
        payload["metadata"] = metadata
    elif isinstance(row.render_metadata, dict) and row.render_metadata:
        payload["metadata"] = row.render_metadata

    category_payload = detail.get("category")
    if isinstance(category_payload, dict):
        category_id = _normalize_space(category_payload.get("id"))
        category_slug_live = _normalize_space(category_payload.get("slug"))
        if category_id:
            payload["categoryId"] = category_id
        elif category_slug_live:
            payload["categorySlug"] = category_slug_live
    if "categoryId" not in payload and "categorySlug" not in payload:
        payload["categorySlug"] = category_slug

    # Try PATCH to update only the cover image, avoiding strict body validation
    patch_payload = {
        "coverImage": cover_image_url,
        "status": payload.get("status", "published")
    }
    response = _integration_request(db, method="PATCH", path=f"/api/integrations/posts/{row.remote_post_id}", json_payload=patch_payload, timeout=60.0)
    
    # If PATCH is not supported, fallback to original PUT logic
    status_code = getattr(response, "status_code", None)
    if status_code == 405 or status_code == 404:
        response = _integration_request(db, method="PUT", path=f"/api/integrations/posts/{row.remote_post_id}", json_payload=payload, timeout=120.0)
    
    data = _integration_data_or_raise(response)
    if not isinstance(data, dict):
        raise ValueError("Cloudflare rebuild update returned an invalid post payload.")
    return data


def _normalize_excerpt_length(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        cleaned = "자세한 내용을 확인하려면 클릭하세요. 유용한 정보와 깊이 있는 분석을 제공합니다."
    
    if len(cleaned) < 90:
        # Pad with title or filler
        cleaned = (cleaned + " " + "본 포스팅에서는 해당 주제에 대한 상세한 가이드와 실무 적용 사례를 깊이 있게 다루고 있습니다. 지금 바로 확인해보세요.").strip()
    
    if len(cleaned) > 170:
        cleaned = cleaned[:167] + "..."
    
    # Final check
    if len(cleaned) < 90:
        cleaned = cleaned.ljust(95, '.')
        
    # print(f"DEBUG EXCERPT: len={len(cleaned)} content={cleaned}")
    return cleaned[:170]

def _write_report_artifacts(*, policy: CloudflareAssetPolicy, report: dict[str, Any]) -> tuple[str, str]:
    manifest_dir = _cloudflare_manifest_dir(policy)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = manifest_dir / f"rebuild-{timestamp}.json"
    csv_path = manifest_dir / f"rebuild-{timestamp}.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")

    csv_rows = list(report.get("items") or []) + [{**item, "status": "unresolved"} for item in list(report.get("unresolved") or [])]
    fieldnames = [
        "status",
        "remote_post_id",
        "slug",
        "title",
        "category_slug",
        "match_source",
        "confidence",
        "legacy_url_scheme",
        "url_asset_slug",
        "legacy_object_slug",
        "manifest_category_hit",
        "evidence_score",
        "evidence_sources",
        "resolved_local_source",
        "resolved_target_path",
        "resolved_object_key",
        "resolved_public_url",
        "error",
        "reason",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in csv_rows:
            if isinstance(row, dict):
                writer.writerow(row)
    return str(json_path), str(csv_path)


def _latest_report_file(policy: CloudflareAssetPolicy) -> Path | None:
    manifest_dir = _cloudflare_manifest_dir(policy)
    if not manifest_dir.exists():
        return None
    files = sorted(manifest_dir.glob("rebuild-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0] if files else None


def get_latest_cloudflare_asset_rebuild_report(db: Session, *, channel_id: str = CLOUDFLARE_MANAGED_CHANNEL_ID) -> dict[str, Any]:
    ensure_managed_channels(db)
    channel = db.execute(select(ManagedChannel).where(ManagedChannel.channel_id == channel_id)).scalar_one_or_none()
    policy = get_cloudflare_asset_policy(channel)
    report_file = _latest_report_file(policy)
    if report_file is None:
        return {"status": "missing", "channel_id": channel_id, "report_path": "", "manifest_path": "", "report": None}
    payload = json.loads(report_file.read_text(encoding="utf-8"))
    return {
        "status": "ok",
        "channel_id": channel_id,
        "report_path": str(report_file),
        "manifest_path": str(report_file),
        "report": payload,
    }


def rebuild_cloudflare_assets(
    db: Session,
    *,
    mode: str = "dry_run",
    channel_id: str = CLOUDFLARE_MANAGED_CHANNEL_ID,
    category_slugs: list[str] | None = None,
    limit: int | None = None,
    purge_target: bool = True,
    use_fallback_heuristic: bool = True,
    image_match_strategy: str = "slug_similarity",
    ignore_filename_patterns: list[str] | None = None,
    allow_thumbnail_fallback: bool = False,
    bucket_override: str | None = None,
    source_scope: str = DEFAULT_SOURCE_SCOPE,
    public_url_strategy: str = "direct_public",
    update_live_posts: bool = True,
    allow_remote_thumbnail_fetch: bool = False,
    use_legacy_evidence: bool = True,
    legacy_evidence_can_auto_accept: bool = False,
) -> dict[str, Any]:
    normalized_mode = str(mode or "dry_run").strip().lower()
    if normalized_mode not in {"dry_run", "execute"}:
        raise ValueError(f"Unsupported rebuild mode: {mode}")
    normalized_match_strategy = str(image_match_strategy or "slug_similarity").strip().lower()
    if normalized_match_strategy != "slug_similarity":
        raise ValueError(f"Unsupported image_match_strategy: {image_match_strategy}")
    normalized_source_scope = str(source_scope or DEFAULT_SOURCE_SCOPE).strip().lower()
    if normalized_source_scope not in {DEFAULT_SOURCE_SCOPE, "cloudflare_only_root_pool"}:
        raise ValueError(f"Unsupported source_scope: {source_scope}")
    normalized_public_url_strategy = str(public_url_strategy or "direct_public").strip().lower()
    if normalized_public_url_strategy not in {"configured", "direct_public", "integration_assets"}:
        raise ValueError(f"Unsupported public_url_strategy: {public_url_strategy}")
    if allow_thumbnail_fallback:
        raise ValueError("allow_thumbnail_fallback=true is not supported for Cloudflare rebuild.")
    if legacy_evidence_can_auto_accept:
        raise ValueError("legacy_evidence_can_auto_accept=true is not supported in phase 1.")

    ensure_managed_channels(db)
    channel = db.execute(select(ManagedChannel).where(ManagedChannel.channel_id == channel_id)).scalar_one_or_none()
    policy = get_cloudflare_asset_policy(channel)
    normalized_categories = [str(item or "").strip() for item in (category_slugs or []) if str(item or "").strip()]
    normalized_ignore_patterns = [
        str(pattern or "").strip()
        for pattern in (ignore_filename_patterns or list(DEFAULT_IGNORE_FILENAME_PATTERNS))
        if str(pattern or "").strip()
    ]
    for category_slug in normalized_categories:
        assert_cloudflare_asset_scope(policy=policy, category_slug=category_slug)

    candidates = _inventory_candidates(
        policy,
        ignore_filename_patterns=normalized_ignore_patterns,
        source_scope=normalized_source_scope,
    )
    posts = _load_target_posts(db, policy=policy, category_slugs=normalized_categories or None, limit=limit)
    source_category_history, stem_category_history = _load_manifest_history(_cloudflare_manifest_dir(policy))
    public_base_url_override = ""
    if normalized_mode == "execute":
        resolved_bucket_name = str(bucket_override or "").strip() or "dongriarchive-cloudflare"
        bucket_probe = ensure_cloudflare_r2_bucket(
            db,
            bucket_name=resolved_bucket_name,
            verify=False,
            create_if_missing=False,
        )
        resolved_bucket_name = str(bucket_probe.get("bucket_name") or resolved_bucket_name)
        public_base_url_override = _resolve_public_base_url_for_strategy(db, strategy=normalized_public_url_strategy)
    else:
        resolved_bucket_name = str(bucket_override or "").strip()
    remote_fetch_probe = (
        _preflight_remote_thumbnail_fetch(posts)
        if allow_remote_thumbnail_fetch
        else {"enabled": False, "preflight_count": 0, "successful_preflight_count": 0, "status_breakdown": {}}
    )
    matched, unresolved = _select_matches(
        posts,
        candidates,
        use_fallback_heuristic=use_fallback_heuristic,
        source_category_history=source_category_history,
        stem_category_history=stem_category_history,
        use_legacy_evidence=use_legacy_evidence,
    )

    items: list[dict[str, Any]] = []
    failed_count = 0
    uploaded_count = 0
    updated_count = 0
    public_url_verified_count = 0
    purged_categories: list[str] = []
    sample_uploaded_keys: list[str] = []
    remote_fetch_attempted_count = 0
    remote_fetch_success_count = 0
    force_integration_proxy = normalized_public_url_strategy == "integration_assets"
    touched_categories = sorted({str(item.get("category_slug") or "").strip() for item in matched if str(item.get("category_slug") or "").strip()})
    if normalized_mode == "execute" and purge_target and touched_categories:
        purged_categories = purge_cloudflare_target_categories(policy=policy, category_slugs=touched_categories)

    for item in matched:
        row = item["row"]
        report_row = {
            "status": "matched",
            "remote_post_id": item["remote_post_id"],
            "slug": item["slug"],
            "title": item["title"],
            "category_slug": item["category_slug"],
            "match_source": item["match_source"],
            "confidence": item["confidence"],
            "legacy_url_scheme": item["legacy_url_scheme"],
            "url_asset_slug": item["url_asset_slug"],
            "legacy_object_slug": item["legacy_object_slug"],
            "manifest_category_hit": item["manifest_category_hit"],
            "evidence_score": item["evidence_score"],
            "evidence_sources": list(item["evidence_sources"]),
            "resolved_local_source": item["resolved_local_source"],
            "resolved_target_path": item["target_path"],
            "resolved_object_key": item["object_key"],
            "resolved_public_url": "",
            "error": "",
            "reason": item["match_reason"],
        }
        if normalized_mode == "dry_run":
            items.append(report_row)
            continue

        try:
            source_path = Path(str(item["resolved_local_source"]))
            target_path = Path(str(item["target_path"]))
            target_path.parent.mkdir(parents=True, exist_ok=True)
            assert_cloudflare_asset_scope(policy=policy, category_slug=str(item["category_slug"]), object_key=str(item["object_key"]), local_path=target_path)
            webp_bytes = _ensure_webp_bytes(source_path)
            target_path.write_bytes(webp_bytes)
            cover_image_url, upload_payload, _delivery_meta = upload_binary_to_cloudflare_r2(
                db,
                object_key=str(item["object_key"]),
                filename=target_path.name,
                content=webp_bytes,
                bucket_override=None if force_integration_proxy else bucket_override,
                public_base_url_override=public_base_url_override or None,
                force_integration_proxy=force_integration_proxy,
            )
            resolved_object_key = str(upload_payload.get("object_key") or "").strip()
            if resolved_object_key != str(item["object_key"]):
                raise ValueError(f"canonical_object_key_mismatch expected={item['object_key']} actual={resolved_object_key}")
            if not resolved_bucket_name:
                resolved_bucket_name = str(upload_payload.get("bucket") or "").strip()
            verified_public_url, public_status_code = _verify_public_image_url(cover_image_url)
            if not verified_public_url:
                raise ValueError(f"public_url_unreachable status={public_status_code or 'error'} url={cover_image_url}")
            uploaded_count += 1
            public_url_verified_count += 1
            if len(sample_uploaded_keys) < 10:
                sample_uploaded_keys.append(resolved_object_key)
            if update_live_posts:
                _update_live_post_cover(db, row=row, category_slug=str(item["category_slug"]), cover_image_url=cover_image_url)
                row.thumbnail_url = cover_image_url
                db.add(row)
                db.flush()
                report_row["status"] = "updated"
                updated_count += 1
            else:
                report_row["status"] = "uploaded"
            report_row["resolved_public_url"] = cover_image_url
        except Exception as exc:  # noqa: BLE001
            report_row["status"] = "failed"
            report_row["error"] = str(exc)
            failed_count += 1
        items.append(report_row)

    sync_result: dict[str, Any] | None = None
    if normalized_mode == "execute":
        db.commit()
        if update_live_posts and updated_count > 0:
            sync_result = sync_cloudflare_posts(db, include_non_published=True)

    evidence_breakdown = _build_evidence_breakdown(matched=matched, unresolved=unresolved)
    report = {
        "status": "ok" if failed_count == 0 else ("partial" if uploaded_count > 0 else "failed"),
        "mode": normalized_mode,
        "channel_id": policy.channel_id,
        "generated_at": _utc_now_iso(),
        "db_posts": len(posts),
        "post_count": len(posts),
        "matched": len(matched),
        "candidate_count": len(candidates),
        "matched_count": sum(1 for item in matched if item["match_source"] != "slug_similarity_gap"),
        "heuristic_matched_count": sum(1 for item in matched if item["match_source"] == "slug_similarity_gap"),
        "uploaded": uploaded_count,
        "uploaded_count": uploaded_count,
        "unresolved_total": len(unresolved),
        "unresolved_count": len(unresolved),
        "updated_count": updated_count,
        "failed_count": failed_count,
        "purged_categories": purged_categories,
        "legacy_scheme_breakdown": dict(Counter(item["legacy_url_scheme"] for item in posts)),
        "evidence_breakdown": evidence_breakdown,
        "url_asset_exact_count": int(evidence_breakdown.get("url_asset_exact", 0)),
        "url_asset_prefix_count": int(evidence_breakdown.get("url_asset_prefix", 0)),
        "manifest_category_hit_count": int(evidence_breakdown.get("manifest_category_hit", 0)),
        "image_match_strategy": normalized_match_strategy,
        "ignore_filename_patterns": normalized_ignore_patterns,
        "allow_thumbnail_fallback": False,
        "bucket_name": resolved_bucket_name or None,
        "public_url_strategy": normalized_public_url_strategy,
        "bucket_verified": True if normalized_mode == "execute" else None,
        "sample_uploaded_keys": sample_uploaded_keys,
        "source_scope": normalized_source_scope,
        "update_live_posts": update_live_posts,
        "allow_remote_thumbnail_fetch": allow_remote_thumbnail_fetch,
        "remote_fetch_enabled": bool(remote_fetch_probe.get("enabled")),
        "remote_fetch_attempted_count": remote_fetch_attempted_count,
        "remote_fetch_success_count": remote_fetch_success_count,
        "remote_fetch_preflight_count": int(remote_fetch_probe.get("preflight_count") or 0),
        "remote_fetch_preflight_success_count": int(remote_fetch_probe.get("successful_preflight_count") or 0),
        "remote_fetch_status_breakdown": dict(remote_fetch_probe.get("status_breakdown") or {}),
        "use_legacy_evidence": use_legacy_evidence,
        "legacy_evidence_can_auto_accept": legacy_evidence_can_auto_accept,
        "public_url_verified_count": public_url_verified_count,
        "direct_public_url_verified_count": public_url_verified_count,
        "matched_by_exact_slug": sum(1 for item in matched if item["match_source"] == "exact_slug"),
        "matched_by_slug_family": sum(1 for item in matched if item["match_source"] == "slug_family"),
        "matched_by_similarity_with_evidence": sum(
            1
            for item in matched
            if item["match_source"] in {"slug_similarity_auto", "slug_similarity_gap"} and list(item.get("evidence_sources") or [])
        ),
        "created_categories": [],
        "sync_result": sync_result,
        "items": items,
        "unresolved": unresolved,
    }
    json_path, csv_path = _write_report_artifacts(policy=policy, report=report)
    report["report_path"] = json_path
    report["manifest_path"] = json_path
    report["csv_path"] = csv_path
    return report

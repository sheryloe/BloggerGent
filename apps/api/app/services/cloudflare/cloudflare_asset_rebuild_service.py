from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from difflib import SequenceMatcher
import io
import json
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import urlparse

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
from app.services.integrations.storage_service import upload_binary_to_cloudflare_r2
from app.services.platform.platform_service import ensure_managed_channels

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}
INLINE_ROLE_RE = re.compile(r"-(?:inline(?:-[0-9]+x[0-9]+)?)$", re.IGNORECASE)
LEGACY_COVER_RE = re.compile(r"^cover-[a-z0-9]{6,}$", re.IGNORECASE)
PATH_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
DEFAULT_MATCH_CONFIDENCE = 0.64
AMBIGUITY_GAP = 0.04


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


def _tokenize(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        raw = _normalize_space(value)
        if not raw:
            continue
        tokens.update(token for token in PATH_TOKEN_RE.findall(raw.lower()) if token)
        slug_text = _normalize_slug(raw).replace("-", " ").strip()
        if slug_text:
            tokens.update(token for token in slug_text.split() if token)
    return tokens


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


def _clean_candidate_stem(path: Path) -> str:
    stem = str(path.stem or "").strip()
    if not stem:
        return ""
    if LEGACY_COVER_RE.fullmatch(stem):
        parent_name = _normalize_slug(path.parent.name)
        if parent_name and parent_name not in {"cloudflare", "images"}:
            return parent_name
    return _normalize_slug(INLINE_ROLE_RE.sub("", stem))


def _candidate_role(path: Path) -> str:
    stem = str(path.stem or "").strip().lower()
    if "inline" in stem:
        return "inline"
    if LEGACY_COVER_RE.fullmatch(path.stem or ""):
        return "legacy_cover"
    return "hero"


def _score_token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    if intersection <= 0:
        return 0.0
    return intersection / max(len(left), len(right), 1)


def _sequence_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=left, b=right).ratio()


def _cloudflare_manifest_dir(policy: CloudflareAssetPolicy) -> Path:
    return resolve_cloudflare_local_asset_root(policy) / "_manifests"


def _storage_images_root(policy: CloudflareAssetPolicy) -> Path:
    local_root = resolve_cloudflare_local_asset_root(policy)
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
        rows = payload.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            source = str(row.get("source") or "").strip()
            category = str(row.get("target_category") or "").strip()
            if not source or not category:
                continue
            normalized_source = str(Path(source))
            source_category_history[normalized_source].add(category)
            stem = _clean_candidate_stem(Path(source))
            if stem:
                stem_category_history[stem].add(category)
    return source_category_history, stem_category_history


def _inventory_candidates(policy: CloudflareAssetPolicy) -> list[dict[str, Any]]:
    local_root = resolve_cloudflare_local_asset_root(policy)
    storage_root = _storage_images_root(policy)
    manifest_dir = _cloudflare_manifest_dir(policy)
    source_history, stem_history = _load_manifest_history(manifest_dir)

    candidates: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    roots: list[tuple[Path, str]] = []
    if storage_root.exists():
        roots.append((storage_root, "storage_pool"))
    mystery_root = storage_root / "mystery"
    if mystery_root.exists():
        roots.append((mystery_root, "mystery_pool"))
    if local_root.exists():
        roots.append((local_root, "cloudflare_existing"))

    for root, source_kind in roots:
        for path in _iter_image_files(root):
            normalized_path = str(path.resolve())
            if normalized_path in seen_paths:
                continue
            if "_manifests" in path.parts:
                continue
            if source_kind == "storage_pool":
                try:
                    relative = path.relative_to(storage_root)
                except ValueError:
                    relative = path
                if relative.parts and relative.parts[0] in {"Cloudflare", "mystery"}:
                    continue
            seen_paths.add(normalized_path)
            normalized_stem = _clean_candidate_stem(path)
            if not normalized_stem:
                continue
            category_hint = ""
            if source_kind == "cloudflare_existing":
                try:
                    relative = path.relative_to(local_root)
                except ValueError:
                    relative = path
                if len(relative.parts) >= 2:
                    category_hint = str(relative.parts[0]).strip()
            manifest_categories = sorted({*source_history.get(str(path), set()), *stem_history.get(normalized_stem, set())})
            candidates.append(
                {
                    "path": str(path),
                    "source_kind": source_kind,
                    "normalized_stem": normalized_stem,
                    "role": _candidate_role(path),
                    "extension": path.suffix.lower(),
                    "category_hint": category_hint,
                    "manifest_categories": manifest_categories,
                    "tokens": sorted(_tokenize(path.stem, normalized_stem, path.name)),
                }
            )
    return candidates


def _rank_candidate(post: dict[str, Any], candidate: dict[str, Any], *, use_fallback_heuristic: bool) -> dict[str, Any]:
    candidate_stem = str(candidate.get("normalized_stem") or "").strip()
    post_slug = str(post.get("slug") or "").strip()
    if not candidate_stem or not post_slug:
        return {"score": 0.0, "match_source": "", "reason": ""}

    desired_category = str(post.get("category_slug") or "").strip()
    asset_slug_hint = str(post.get("asset_slug_hint") or "").strip()
    role = str(candidate.get("role") or "").strip().lower()
    candidate_tokens = {str(token) for token in candidate.get("tokens") or [] if str(token).strip()}
    post_tokens = {str(token) for token in post.get("tokens") or [] if str(token).strip()}
    manifest_categories = {str(item) for item in candidate.get("manifest_categories") or [] if str(item).strip()}
    category_hint = str(candidate.get("category_hint") or "").strip()

    if candidate_stem == post_slug and role == "hero":
        return {"score": 1.0, "match_source": "exact_slug", "reason": "candidate_stem=post_slug"}
    if candidate_stem == post_slug and role != "hero":
        return {"score": 0.82, "match_source": "exact_slug", "reason": f"candidate_stem=post_slug role={role}"}
    if asset_slug_hint and candidate_stem == asset_slug_hint and role == "hero":
        return {"score": 0.97, "match_source": "asset_path_slug", "reason": "candidate_stem=thumbnail_slug"}
    if asset_slug_hint and candidate_stem == asset_slug_hint:
        return {"score": 0.79, "match_source": "asset_path_slug", "reason": f"candidate_stem=thumbnail_slug role={role}"}

    slug_similarity = _sequence_ratio(candidate_stem, post_slug)
    title_similarity = _sequence_ratio(candidate_stem, str(post.get("title_slug") or "").strip())
    token_overlap = _score_token_overlap(candidate_tokens, post_tokens)
    category_bonus = 0.0
    manifest_bonus = 0.0

    if category_hint and category_hint == desired_category:
        category_bonus += 0.18
    if desired_category and desired_category in manifest_categories:
        manifest_bonus += 0.22

    score = (slug_similarity * 0.46) + (title_similarity * 0.16) + (token_overlap * 0.28) + category_bonus + manifest_bonus
    if role == "inline":
        score -= 0.18
    elif role == "legacy_cover":
        score -= 0.08

    if manifest_bonus > 0 and score >= DEFAULT_MATCH_CONFIDENCE:
        return {"score": min(score, 0.94), "match_source": "manifest_history", "reason": "manifest_category_history"}
    if category_bonus > 0 and token_overlap > 0:
        return {"score": min(score, 0.9), "match_source": "title_category_tokens", "reason": "category_hint+token_overlap"}
    if token_overlap > 0.18 or slug_similarity > 0.74:
        return {"score": min(score, 0.86), "match_source": "title_category_tokens", "reason": "token_or_slug_similarity"}
    if use_fallback_heuristic:
        score += 0.08
        return {"score": min(score, 0.74), "match_source": "fallback_heuristic", "reason": "fallback_heuristic"}
    return {"score": max(score, 0.0), "match_source": "", "reason": ""}


def _rank_candidates_for_post(post: dict[str, Any], candidates: list[dict[str, Any]], *, use_fallback_heuristic: bool) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        score_payload = _rank_candidate(post, candidate, use_fallback_heuristic=use_fallback_heuristic)
        score = float(score_payload.get("score") or 0.0)
        if score <= 0.0:
            continue
        ranked.append(
            {
                "path": str(candidate["path"]),
                "score": round(score, 4),
                "match_source": str(score_payload.get("match_source") or "").strip(),
                "reason": str(score_payload.get("reason") or "").strip(),
                "role": str(candidate.get("role") or "").strip(),
                "source_kind": str(candidate.get("source_kind") or "").strip(),
            }
        )
    ranked.sort(key=lambda item: (item["score"], item["match_source"] == "exact_slug"), reverse=True)
    return ranked[:8]


def _coerce_post_row(row: SyncedCloudflarePost, *, policy: CloudflareAssetPolicy) -> dict[str, Any]:
    category_slug = str(row.canonical_category_slug or row.category_slug or "").strip()
    resolved_category = category_slug if category_slug in policy.allowed_category_slugs else ""
    slug = _normalize_slug(row.slug)
    title = _normalize_space(row.title)
    title_slug = _normalize_slug(title)
    return {
        "remote_post_id": str(row.remote_post_id or "").strip(),
        "slug": slug,
        "title": title,
        "title_slug": title_slug,
        "category_slug": resolved_category,
        "category_name": _normalize_space(row.canonical_category_name or row.category_name or resolved_category),
        "published_at": row.published_at,
        "thumbnail_url": str(row.thumbnail_url or "").strip(),
        "asset_slug_hint": _asset_slug_from_url(row.thumbnail_url),
        "legacy_url_scheme": _legacy_url_scheme(row.thumbnail_url),
        "tokens": sorted(_tokenize(slug, title_slug, title, resolved_category)),
        "target_path": str(build_cloudflare_local_asset_path(policy=policy, category_slug=resolved_category, post_slug=slug)) if resolved_category and slug else "",
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


def _select_matches(posts: list[dict[str, Any]], candidates: list[dict[str, Any]], *, use_fallback_heuristic: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked_posts: list[dict[str, Any]] = []
    for post in posts:
        ranked = _rank_candidates_for_post(post, candidates, use_fallback_heuristic=use_fallback_heuristic)
        ranked_posts.append({"post": post, "ranked": ranked})
    ranked_posts.sort(key=lambda item: (float(item["ranked"][0]["score"]) if item["ranked"] else -1.0, str(item["post"]["slug"])), reverse=True)

    used_paths: set[str] = set()
    matched: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for entry in ranked_posts:
        post = entry["post"]
        ranked = entry["ranked"]
        chosen: dict[str, Any] | None = None
        second_score = float(ranked[1]["score"]) if len(ranked) > 1 else 0.0
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
                "top_candidates": ranked[:3],
            })
            continue

        score = float(chosen["score"])
        ambiguous = second_score > 0 and abs(score - second_score) < AMBIGUITY_GAP and score < 0.98
        confidence_threshold = DEFAULT_MATCH_CONFIDENCE if str(chosen["match_source"]) != "fallback_heuristic" else 0.58
        if score < confidence_threshold or ambiguous:
            unresolved.append({
                "remote_post_id": post["remote_post_id"],
                "slug": post["slug"],
                "category_slug": post["category_slug"],
                "title": post["title"],
                "legacy_url_scheme": post["legacy_url_scheme"],
                "reason": "low_confidence" if score < confidence_threshold else "ambiguous_match",
                "confidence": round(score, 4),
                "top_candidates": ranked[:3],
            })
            continue

        used_paths.add(str(chosen["path"]))
        matched.append({
            **post,
            "match_source": str(chosen["match_source"]),
            "confidence": round(score, 4),
            "resolved_local_source": str(chosen["path"]),
            "candidate_role": str(chosen["role"]),
            "candidate_source_kind": str(chosen["source_kind"]),
            "match_reason": str(chosen["reason"]),
            "top_candidates": ranked[:3],
        })
    return matched, unresolved


def _ensure_webp_bytes(source_path: Path) -> bytes:
    with Image.open(source_path) as loaded:
        output = io.BytesIO()
        converted = loaded.convert("RGB") if loaded.mode not in {"RGB", "RGBA"} else loaded
        converted.save(output, format="WEBP", quality=88, optimize=True, method=6)
        return output.getvalue()


def purge_cloudflare_target_categories(*, policy: CloudflareAssetPolicy, category_slugs: list[str]) -> list[str]:
    root = resolve_cloudflare_local_asset_root(policy)
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
        "excerpt": _normalize_space(detail.get("excerpt") or row.excerpt_text or ""),
        "seoTitle": _normalize_space(detail.get("seoTitle") or title),
        "seoDescription": _normalize_space(detail.get("seoDescription") or row.excerpt_text or title),
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

    response = _integration_request(db, method="PUT", path=f"/api/integrations/posts/{row.remote_post_id}", json_payload=payload, timeout=120.0)
    data = _integration_data_or_raise(response)
    if not isinstance(data, dict):
        raise ValueError("Cloudflare rebuild update returned an invalid post payload.")
    return data


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
) -> dict[str, Any]:
    normalized_mode = str(mode or "dry_run").strip().lower()
    if normalized_mode not in {"dry_run", "execute"}:
        raise ValueError(f"Unsupported rebuild mode: {mode}")

    ensure_managed_channels(db)
    channel = db.execute(select(ManagedChannel).where(ManagedChannel.channel_id == channel_id)).scalar_one_or_none()
    policy = get_cloudflare_asset_policy(channel)
    normalized_categories = [str(item or "").strip() for item in (category_slugs or []) if str(item or "").strip()]
    for category_slug in normalized_categories:
        assert_cloudflare_asset_scope(policy=policy, category_slug=category_slug)

    candidates = _inventory_candidates(policy)
    posts = _load_target_posts(db, policy=policy, category_slugs=normalized_categories or None, limit=limit)
    matched, unresolved = _select_matches(posts, candidates, use_fallback_heuristic=use_fallback_heuristic)

    items: list[dict[str, Any]] = []
    failed_count = 0
    updated_count = 0
    purged_categories: list[str] = []
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
            cover_image_url, upload_payload, _delivery_meta = upload_binary_to_cloudflare_r2(db, object_key=str(item["object_key"]), filename=target_path.name, content=webp_bytes)
            resolved_object_key = str(upload_payload.get("object_key") or "").strip()
            if resolved_object_key != str(item["object_key"]):
                raise ValueError(f"canonical_object_key_mismatch expected={item['object_key']} actual={resolved_object_key}")
            _update_live_post_cover(db, row=row, category_slug=str(item["category_slug"]), cover_image_url=cover_image_url)
            row.thumbnail_url = cover_image_url
            db.add(row)
            db.flush()
            report_row["status"] = "updated"
            report_row["resolved_public_url"] = cover_image_url
            updated_count += 1
        except Exception as exc:  # noqa: BLE001
            report_row["status"] = "failed"
            report_row["error"] = str(exc)
            failed_count += 1
        items.append(report_row)

    sync_result: dict[str, Any] | None = None
    if normalized_mode == "execute" and updated_count > 0:
        db.commit()
        sync_result = sync_cloudflare_posts(db, include_non_published=True)

    report = {
        "status": "ok" if failed_count == 0 else ("partial" if updated_count > 0 else "failed"),
        "mode": normalized_mode,
        "channel_id": policy.channel_id,
        "generated_at": _utc_now_iso(),
        "post_count": len(posts),
        "candidate_count": len(candidates),
        "matched_count": sum(1 for item in matched if item["match_source"] != "fallback_heuristic"),
        "heuristic_matched_count": sum(1 for item in matched if item["match_source"] == "fallback_heuristic"),
        "unresolved_count": len(unresolved),
        "updated_count": updated_count,
        "failed_count": failed_count,
        "purged_categories": purged_categories,
        "legacy_scheme_breakdown": dict(Counter(item["legacy_url_scheme"] for item in posts)),
        "sync_result": sync_result,
        "items": items,
        "unresolved": unresolved,
    }
    json_path, csv_path = _write_report_artifacts(policy=policy, report=report)
    report["report_path"] = json_path
    report["manifest_path"] = json_path
    report["csv_path"] = csv_path
    return report

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.orm import selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPO_ROOT.parent.parent
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, SyncedBloggerPost  # noqa: E402
from app.services.content.article_service import build_article_r2_asset_object_key  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import (  # noqa: E402
    cloudflare_r2_download_binary,
    normalize_r2_url_to_key,
    save_public_binary,
)

LIVE_STATUSES = {"LIVE", "PUBLISHED", "live", "published"}
URL_RE = re.compile(r"https?://[^\s'\"<>()]+", re.IGNORECASE)
IMAGE_FILE_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _slug_token(value: Any, *, fallback: str = "") -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", _safe_str(value).lower()).strip("-")
    if normalized:
        return normalized
    return re.sub(r"[^a-z0-9]+", "-", _safe_str(fallback).lower()).strip("-")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate mystery assets to slug.webp canonical layout.")
    parser.add_argument("--blog-id", type=int, default=35)
    parser.add_argument("--mode", choices=("dry-run", "apply", "rewrite-only"), default="dry-run")
    parser.add_argument(
        "--backup-root",
        action="append",
        default=[],
        help="Additional backup root path (repeatable).",
    )
    parser.add_argument("--report-path", default="", help="Optional JSON report path.")
    return parser.parse_args(argv)


def _convert_to_webp(content: bytes) -> bytes:
    with PILImage.open(BytesIO(content)) as loaded:
        output = BytesIO()
        converted = loaded if loaded.mode in {"RGB", "RGBA"} else loaded.convert("RGB")
        converted.save(output, format="WEBP", quality=88, method=6)
        return output.getvalue()


def _candidate_backup_roots(args: argparse.Namespace) -> list[Path]:
    configured: list[Path] = [Path(item).resolve() for item in (args.backup_root or []) if _safe_str(item)]
    defaults = [
        Path(r"D:\Donggri_Runtime\BloggerGent\storage"),
        PROJECT_ROOT / "storage",
        PROJECT_ROOT / "backup",
        PROJECT_ROOT / "backups",
    ]
    all_roots = [*configured, *defaults]
    resolved: list[Path] = []
    seen: set[str] = set()
    for root in all_roots:
        key = str(root.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        if root.exists():
            resolved.append(root)
    return resolved


def _build_backup_index(roots: list[Path]) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in IMAGE_FILE_EXTENSIONS:
                continue
            stem = _safe_str(path.stem).lower()
            if not stem:
                continue
            index.setdefault(stem, []).append(path)
    return index


def _select_backup_path(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    priority = {".png": 0, ".webp": 1, ".jpg": 2, ".jpeg": 2}
    ranked: list[tuple[int, float, Path]] = []
    for path in paths:
        try:
            stat = path.stat()
            ranked.append((priority.get(path.suffix.lower(), 9), -float(stat.st_mtime), path))
        except OSError:
            ranked.append((priority.get(path.suffix.lower(), 9), 0.0, path))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0][2] if ranked else None


def _lookup_backup_binary(*, backup_index: dict[str, list[Path]], slug: str) -> tuple[bytes, str] | None:
    normalized_slug = _safe_str(slug).lower()
    candidate_keys = [normalized_slug]
    if normalized_slug.endswith("-html"):
        candidate_keys.append(normalized_slug[: -len("-html")])
    for key in candidate_keys:
        candidate = _select_backup_path(list(backup_index.get(key, [])))
        if candidate is None:
            continue
        try:
            return candidate.read_bytes(), f"backup:{candidate}"
        except OSError:
            continue
    return None


def _load_source_binary(
    db,
    *,
    file_path: str | None,
    public_url: str | None,
    slug: str,
    backup_index: dict[str, list[Path]],
) -> tuple[bytes, str]:
    normalized_path = _safe_str(file_path)
    if normalized_path:
        local_path = Path(normalized_path)
        if local_path.exists():
            return local_path.read_bytes(), f"local:{local_path}"

    normalized_public_url = _safe_str(public_url)
    if normalized_public_url:
        object_key = _safe_str(normalize_r2_url_to_key(normalized_public_url)).lstrip("/")
        if object_key:
            try:
                payload = cloudflare_r2_download_binary(db, public_key="", key=object_key)
                return payload, f"r2:{object_key}"
            except Exception:  # noqa: BLE001
                # The legacy bucket/object may already be removed during migration.
                # Continue to backup fallback instead of failing the whole article.
                pass

    backup_binary = _lookup_backup_binary(backup_index=backup_index, slug=slug)
    if backup_binary is not None:
        return backup_binary

    raise RuntimeError("source_binary_not_found")


def _join_url(base_url: str, object_key: str) -> str:
    return f"{_safe_str(base_url).rstrip('/')}/{_safe_str(object_key).lstrip('/')}"


def _build_key_url_map(url_map: dict[str, str]) -> dict[str, str]:
    key_map: dict[str, str] = {}
    for old_url, new_url in url_map.items():
        key = _safe_str(normalize_r2_url_to_key(old_url)).lstrip("/")
        if key and key not in key_map:
            key_map[key] = new_url
    return key_map


def _slug_key_token_from_url(url: str) -> str:
    canonical_key = _safe_str(normalize_r2_url_to_key(url)).lstrip("/")
    if not canonical_key:
        return ""
    parts = [part for part in canonical_key.split("/") if part]
    if len(parts) < 2:
        return ""
    filename = _safe_str(parts[-1]).lower()
    if not filename.endswith(".webp"):
        return ""
    slug_token = _safe_str(parts[-2]).lower()
    if slug_token.endswith("-html"):
        slug_token = slug_token[: -len("-html")]
    return slug_token


def _extract_mystery_layout_info(url: str) -> tuple[str, str, str, str] | None:
    canonical_key = _safe_str(normalize_r2_url_to_key(url)).lstrip("/")
    if not canonical_key:
        return None
    parts = [part for part in canonical_key.split("/") if part]
    try:
        anchor_index = parts.index("the-midnight-archives")
    except ValueError:
        return None
    if anchor_index + 4 >= len(parts):
        return None
    category = _safe_str(parts[anchor_index + 1]).lower()
    year = _safe_str(parts[anchor_index + 2])
    month = _safe_str(parts[anchor_index + 3])
    slug_token = _safe_str(parts[anchor_index + 4]).lower()
    if slug_token.endswith("-html"):
        slug_token = slug_token[: -len("-html")]
    if not category or not year.isdigit() or len(year) != 4 or not month.isdigit() or len(month) != 2:
        return None
    return category, year, month, slug_token


def _extract_post_slug_from_url(post_url: str | None, *, fallback: str = "") -> str:
    candidate = _safe_str(post_url)
    if not candidate:
        return _slug_token(fallback)
    parsed = urlparse(candidate)
    path = _safe_str(parsed.path).strip("/")
    if not path:
        return _slug_token(fallback)
    tail = _safe_str(path.split("/")[-1])
    if tail.endswith(".html"):
        tail = tail[: -len(".html")]
    if tail:
        return _slug_token(tail, fallback=_slug_token(fallback))
    return _slug_token(fallback)


def _rewrite_url(value: str, *, direct_map: dict[str, str], key_map: dict[str, str], slug_map: dict[str, str]) -> str:
    candidate = _safe_str(value)
    if not candidate:
        return value
    if candidate in direct_map:
        return direct_map[candidate]
    key = _safe_str(normalize_r2_url_to_key(candidate)).lstrip("/")
    if key and key in key_map:
        return key_map[key]
    slug_token = _slug_key_token_from_url(candidate)
    if slug_token and slug_token in slug_map:
        return slug_map[slug_token]
    return value


def _rewrite_text_urls(
    text: str | None,
    *,
    direct_map: dict[str, str],
    key_map: dict[str, str],
    slug_map: dict[str, str],
) -> tuple[str, int]:
    source = str(text or "")
    replacements = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal replacements
        url = match.group(0)
        rewritten = _rewrite_url(url, direct_map=direct_map, key_map=key_map, slug_map=slug_map)
        if rewritten != url:
            replacements += 1
            return rewritten
        return url

    rewritten_text = URL_RE.sub(_replace, source)
    return rewritten_text, replacements


def run(args: argparse.Namespace) -> dict[str, Any]:
    mode = _safe_str(args.mode).lower()
    apply_mode = mode == "apply"
    rewrite_only_mode = mode == "rewrite-only"
    report: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "mode": mode,
        "blog_id": int(args.blog_id),
        "summary": {
            "articles_scanned": 0,
            "articles_migrated": 0,
            "articles_rewritten_only": 0,
            "articles_planned": 0,
            "articles_skipped_no_image": 0,
            "articles_failed": 0,
            "url_mappings": 0,
            "article_assembled_html_rewrites": 0,
            "synced_post_rewrites": 0,
        },
        "items": [],
    }

    with SessionLocal() as db:
        blog = db.get(Blog, int(args.blog_id))
        if blog is None:
            raise RuntimeError(f"blog_not_found:{args.blog_id}")
        if _safe_str(blog.profile_key).lower() != "world_mystery":
            raise RuntimeError(f"blog_profile_not_mystery:{blog.profile_key}")

        settings_map = get_settings_map(db)
        mystery_public_base = _safe_str(
            settings_map.get("mystery_cloudflare_r2_public_base_url") or settings_map.get("cloudflare_r2_public_base_url")
        )

        articles = (
            db.execute(
                select(Article)
                .where(Article.blog_id == blog.id)
                .options(selectinload(Article.image))
                .order_by(Article.created_at.desc(), Article.id.desc())
            )
            .scalars()
            .all()
        )
        report["summary"]["articles_scanned"] = len(articles)
        backup_roots = _candidate_backup_roots(args)
        backup_index = _build_backup_index(backup_roots)
        report["backup_roots"] = [str(path) for path in backup_roots]
        report["summary"]["backup_stems"] = len(backup_index)

        url_map: dict[str, str] = {}
        slug_url_map: dict[str, str] = {}
        for article in articles:
            image = article.image
            if image is None:
                report["summary"]["articles_skipped_no_image"] += 1
                report["items"].append(
                    {
                        "article_id": article.id,
                        "slug": article.slug,
                        "status": "skipped_no_image",
                    }
                )
                continue

            old_public_url = _safe_str(image.public_url)
            canonical_key = build_article_r2_asset_object_key(
                article,
                asset_role="hero",
                timestamp=image.created_at or article.created_at,
            )

            item_payload: dict[str, Any] = {
                "article_id": article.id,
                "image_id": image.id,
                "slug": article.slug,
                "old_public_url": old_public_url or None,
                "new_object_key": canonical_key,
            }

            if not apply_mode and not rewrite_only_mode:
                predicted_url = _join_url(mystery_public_base, canonical_key) if mystery_public_base else ""
                if old_public_url and predicted_url and old_public_url != predicted_url:
                    url_map[old_public_url] = predicted_url
                if predicted_url:
                    slug_url_map[_safe_str(article.slug).lower()] = predicted_url
                item_payload["status"] = "planned"
                item_payload["predicted_public_url"] = predicted_url or None
                item_payload["backup_source_available"] = _lookup_backup_binary(
                    backup_index=backup_index,
                    slug=article.slug,
                ) is not None
                report["summary"]["articles_planned"] += 1
                report["items"].append(item_payload)
                continue

            if rewrite_only_mode:
                try:
                    if not mystery_public_base:
                        raise RuntimeError("mystery_public_base_url_missing")
                    new_public_url = _join_url(mystery_public_base, canonical_key)
                    image.public_url = new_public_url
                    current_meta = dict(image.image_metadata or {}) if isinstance(image.image_metadata, dict) else {}
                    current_meta["canonical_object_key"] = canonical_key
                    current_meta["migration_source"] = "rewrite-only"
                    image.image_metadata = current_meta
                    article.inline_media = []
                    article_meta = dict(article.render_metadata or {}) if isinstance(article.render_metadata, dict) else {}
                    article_meta["mystery_canonical_object_key"] = canonical_key
                    article.render_metadata = article_meta
                    db.add(image)
                    db.add(article)
                    db.commit()

                    if old_public_url and old_public_url != new_public_url:
                        url_map[old_public_url] = new_public_url
                    slug_url_map[_safe_str(article.slug).lower()] = new_public_url
                    item_payload["status"] = "rewritten_only"
                    item_payload["new_public_url"] = new_public_url
                    report["summary"]["articles_migrated"] += 1
                    report["summary"]["articles_rewritten_only"] += 1
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    item_payload["status"] = "failed"
                    item_payload["error"] = str(exc)
                    detail = _safe_str(getattr(exc, "detail", ""))
                    if detail:
                        item_payload["error_detail"] = detail
                    report["summary"]["articles_failed"] += 1

                report["items"].append(item_payload)
                continue

            try:
                source_binary, source_ref = _load_source_binary(
                    db,
                    file_path=image.file_path,
                    public_url=image.public_url,
                    slug=article.slug,
                    backup_index=backup_index,
                )
                webp_binary = _convert_to_webp(source_binary)
                file_path, new_public_url, delivery_meta = save_public_binary(
                    db,
                    subdir="images/mystery",
                    filename=f"{article.slug}.webp",
                    content=webp_binary,
                    object_key=canonical_key,
                )
                image.file_path = file_path
                image.public_url = new_public_url
                current_meta = dict(image.image_metadata or {}) if isinstance(image.image_metadata, dict) else {}
                current_meta["delivery"] = delivery_meta
                current_meta["canonical_object_key"] = canonical_key
                current_meta["migration_source"] = source_ref
                image.image_metadata = current_meta
                article.inline_media = []
                article_meta = dict(article.render_metadata or {}) if isinstance(article.render_metadata, dict) else {}
                article_meta["mystery_canonical_object_key"] = canonical_key
                article.render_metadata = article_meta
                db.add(image)
                db.add(article)
                db.commit()

                if old_public_url and old_public_url != new_public_url:
                    url_map[old_public_url] = new_public_url
                slug_url_map[_safe_str(article.slug).lower()] = new_public_url
                item_payload["status"] = "migrated"
                item_payload["source"] = source_ref
                item_payload["new_public_url"] = new_public_url
                report["summary"]["articles_migrated"] += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                item_payload["status"] = "failed"
                item_payload["error"] = str(exc)
                detail = _safe_str(getattr(exc, "detail", ""))
                if detail:
                    item_payload["error_detail"] = detail
                report["summary"]["articles_failed"] += 1

            report["items"].append(item_payload)

        report["summary"]["url_mappings"] = len(url_map)
        if not url_map and not slug_url_map:
            return report

        key_url_map = _build_key_url_map(url_map)

        article_rewrite_count = 0
        for article in articles:
            rewritten_html, replaced_count = _rewrite_text_urls(
                article.assembled_html or "",
                direct_map=url_map,
                key_map=key_url_map,
                slug_map=slug_url_map,
            )
            if replaced_count <= 0:
                continue
            article_rewrite_count += 1
            if apply_mode or rewrite_only_mode:
                article.assembled_html = rewritten_html
                db.add(article)

        synced_rows = (
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

        if mystery_public_base:
            for row in synced_rows:
                candidate_urls: list[str] = []
                thumb = _safe_str(row.thumbnail_url)
                if thumb:
                    candidate_urls.append(thumb)
                candidate_urls.extend(URL_RE.findall(row.content_html or ""))

                layout_info = None
                for candidate_url in candidate_urls:
                    layout_info = _extract_mystery_layout_info(candidate_url)
                    if layout_info is not None:
                        break

                post_slug = _extract_post_slug_from_url(row.url, fallback=row.title or "")
                if not post_slug:
                    continue

                if layout_info is not None:
                    category, year, month, _ = layout_info
                else:
                    published_at = row.published_at.astimezone(timezone.utc) if row.published_at else datetime.now(timezone.utc)
                    category = "casefile"
                    year = f"{published_at.year:04d}"
                    month = f"{published_at.month:02d}"

                canonical_key = f"assets/the-midnight-archives/{category}/{year}/{month}/{post_slug}/{post_slug}.webp"
                canonical_url = _join_url(mystery_public_base, canonical_key)
                slug_url_map.setdefault(post_slug, canonical_url)
                for candidate_url in candidate_urls:
                    slug_token = _slug_key_token_from_url(candidate_url)
                    if slug_token:
                        slug_url_map.setdefault(slug_token, canonical_url)

        synced_rewrite_count = 0
        for row in synced_rows:
            rewritten_content, content_hits = _rewrite_text_urls(
                row.content_html or "",
                direct_map=url_map,
                key_map=key_url_map,
                slug_map=slug_url_map,
            )
            current_thumb = _safe_str(row.thumbnail_url)
            rewritten_thumb = (
                _rewrite_url(current_thumb, direct_map=url_map, key_map=key_url_map, slug_map=slug_url_map)
                if current_thumb
                else current_thumb
            )
            changed = content_hits > 0 or rewritten_thumb != current_thumb
            if not changed:
                continue
            synced_rewrite_count += 1
            if apply_mode or rewrite_only_mode:
                row.content_html = rewritten_content
                row.thumbnail_url = rewritten_thumb or None
                row.synced_at = datetime.now(timezone.utc)
                db.add(row)

        if apply_mode or rewrite_only_mode:
            db.commit()

        report["summary"]["article_assembled_html_rewrites"] = article_rewrite_count
        report["summary"]["synced_post_rewrites"] = synced_rewrite_count
        return report


def main() -> int:
    args = parse_args()
    report = run(args)
    report_path = (
        Path(args.report_path)
        if _safe_str(args.report_path)
        else PROJECT_ROOT / "storage" / "reports" / f"migrate-mystery-assets-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(report_path))
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

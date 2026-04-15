from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

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
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts


CODEX_WRITE_PROMPT_VERSION = "0414"
CODEX_WRITE_STATUS_SEEDED = "seeded"
CODEX_WRITE_STATUS_READY = "ready"
CODEX_WRITE_STATUS_PUBLISHED = "published"
CODEX_WRITE_STATUS_FAILED = "failed"
CODEX_WRITE_STATUS_SKIPPED = "skipped"
CODEX_WRITE_BANNED_TOKENS = (
    "quick brief",
    "core focus",
    "key entities",
    "internal archive",
    "기준 시각",
    "재정리했다",
    "품질 개선",
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_IMAGE_RE = re.compile(r"(?is)<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']")
HTML_HEADING_RE = re.compile(r"<h([23])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
MD_HEADING_RE = re.compile(r"^\s*##+\s+(.+?)\s*$", re.MULTILINE)
WS_RE = re.compile(r"\s+")


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
    return _repo_root() / "refactoring" / "codex_write" / "packages" / "codex_write" / "cloudflare"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_space(value: Any) -> str:
    return WS_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip()


def _plain_text(value: str | None) -> str:
    return _normalize_space(HTML_TAG_RE.sub(" ", value or ""))


def _body_char_length(value: str | None) -> int:
    return len(_plain_text(value))


def _extract_headings(value: str | None) -> list[str]:
    headings: list[str] = []
    for _level, raw in HTML_HEADING_RE.findall(value or ""):
        heading = _normalize_space(HTML_TAG_RE.sub(" ", raw or ""))
        if heading:
            headings.append(heading)
    for raw in MD_HEADING_RE.findall(value or ""):
        heading = _normalize_space(raw)
        if heading:
            headings.append(heading)
    return headings


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


def _sanitize_filename_token(value: str, fallback: str) -> str:
    token = re.sub(r"[^0-9A-Za-z._-]+", "-", _normalize_space(value))
    token = re.sub(r"-{2,}", "-", token).strip("-._")
    return token[:120] or fallback


def _prompt_paths_for_category(category_slug: str) -> list[str]:
    relative_dir = get_cloudflare_prompt_category_relative_path(category_slug).as_posix()
    base = f"prompts/channels/cloudflare/dongri-archive/{relative_dir}"
    return [
        f"{base}/topic_discovery.md",
        f"{base}/article_generation.md",
        f"{base}/image_prompt_generation.md",
    ]


def _find_channel(db: Session) -> ManagedChannel:
    channel = db.execute(
        select(ManagedChannel).where(ManagedChannel.provider == "cloudflare").order_by(ManagedChannel.id.desc())
    ).scalar_one_or_none()
    if channel is None:
        raise ValueError("Cloudflare managed channel is not configured.")
    return channel


def _list_target_posts(
    db: Session,
    *,
    category_slugs: Sequence[str] | None = None,
    slug: str | None = None,
    limit: int | None = None,
) -> list[SyncedCloudflarePost]:
    channel = _find_channel(db)
    stmt = (
        select(SyncedCloudflarePost)
        .where(
            SyncedCloudflarePost.managed_channel_id == channel.id,
            SyncedCloudflarePost.status.in_(["published", "live"]),
        )
        .order_by(SyncedCloudflarePost.published_at.desc().nullslast(), SyncedCloudflarePost.id.desc())
    )
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
    if limit is not None and limit > 0:
        return filtered[:limit]
    return filtered


def _extract_tag_names(detail: dict[str, Any], row: SyncedCloudflarePost) -> list[str]:
    raw_tags = detail.get("tags")
    values: list[str] = []
    seen: set[str] = set()
    if isinstance(raw_tags, list):
        for item in raw_tags:
            if isinstance(item, dict):
                candidate = _normalize_space(item.get("name") or item.get("label") or item.get("slug"))
            else:
                candidate = _normalize_space(item)
            if not candidate:
                continue
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            values.append(candidate)
    for raw_label in row.labels or []:
        candidate = _normalize_space(raw_label)
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(candidate)
    return values


def _category_root_parts(category_slug: str) -> tuple[str, str]:
    relative_dir = get_cloudflare_prompt_category_relative_path(category_slug)
    parts = list(relative_dir.parts)
    if not parts:
        return ("미분류", "general")
    if len(parts) == 1:
        return ("미분류", parts[0])
    return (parts[0], parts[-1])


def _package_path(
    *,
    base_dir: Path,
    category_slug: str,
    slug: str,
    remote_post_id: str,
) -> Path:
    relative_dir = get_cloudflare_prompt_category_relative_path(category_slug)
    filename = _sanitize_filename_token(slug, remote_post_id or "post")
    return base_dir / relative_dir / f"{filename}.json"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"codex_write JSON must be an object: {path}")
    return payload


def _report_path(base_dir: Path, prefix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return base_dir / "reports" / datetime.now().strftime("%Y%m%d") / f"{prefix}-{stamp}.json"


def _inline_image_from_detail(detail: dict[str, Any], *, cover_image_url: str) -> tuple[str, str]:
    current_content = str(
        detail.get("contentMarkdown")
        or detail.get("content")
        or detail.get("markdown")
        or ""
    )
    image_urls = _extract_existing_image_urls(current_content)
    inline_url = ""
    for candidate in image_urls:
        if candidate and candidate != cover_image_url:
            inline_url = candidate
            break
    inline_alt = _normalize_space(detail.get("title") or "")
    return inline_url, inline_alt


def _seed_package_from_post(row: SyncedCloudflarePost, detail: dict[str, Any]) -> dict[str, Any]:
    category_slug = _normalize_space(row.canonical_category_slug or row.category_slug)
    category_name = _normalize_space(row.canonical_category_name or row.category_name or category_slug)
    root_category_name, category_folder = _category_root_parts(category_slug)
    title = _normalize_space(detail.get("title") or row.title)
    excerpt = _normalize_space(detail.get("excerpt") or row.excerpt_text)
    meta_description = _normalize_space(detail.get("seoDescription") or excerpt or title)
    seo_title = _normalize_space(detail.get("seoTitle") or title)
    current_content = str(
        detail.get("contentMarkdown")
        or detail.get("content")
        or detail.get("markdown")
        or ""
    )
    cover_image_url = _normalize_space(detail.get("coverImage") or row.thumbnail_url)
    cover_alt = _normalize_space(detail.get("coverAlt") or meta_description or title)
    inline_image_url, inline_alt = _inline_image_from_detail(detail, cover_image_url=cover_image_url)
    faq_section = detail.get("faqSection")
    if not isinstance(faq_section, list):
        faq_section = []

    return {
        "remote_post_id": _normalize_space(row.remote_post_id),
        "slug": _normalize_space(row.slug),
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
            "render_metadata": row.render_metadata or {},
        },
        "title": title,
        "excerpt": excerpt,
        "meta_description": meta_description,
        "seo_title": seo_title,
        "html_article": _strip_generated_body_images(current_content),
        "faq_section": faq_section,
        "tag_names": _extract_tag_names(detail, row),
        "cover_image": {
            "url": cover_image_url,
            "alt": cover_alt,
        },
        "inline_image": {
            "url": inline_image_url,
            "alt": inline_alt or title,
        },
        "render_metadata": row.render_metadata or {},
        "publish_state": {
            "status": CODEX_WRITE_STATUS_SEEDED,
            "last_published_at": None,
            "last_error": None,
        },
    }


def export_codex_write_packages(
    db: Session,
    *,
    category_slugs: Sequence[str] | None = None,
    slug: str | None = None,
    limit: int | None = None,
    overwrite: bool = False,
    sync_before: bool = True,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    root = get_codex_write_root(base_dir=base_dir)
    sync_result: dict[str, Any] | None = None
    if sync_before:
        sync_result = sync_cloudflare_posts(db, include_non_published=True)

    rows = _list_target_posts(db, category_slugs=category_slugs, slug=slug, limit=limit)
    items: list[dict[str, Any]] = []
    created_count = 0
    skipped_count = 0

    for row in rows:
        remote_post_id = _normalize_space(row.remote_post_id)
        category_slug_value = _normalize_space(row.canonical_category_slug or row.category_slug)
        slug_value = _normalize_space(row.slug)
        package_path = _package_path(
            base_dir=root,
            category_slug=category_slug_value,
            slug=slug_value,
            remote_post_id=remote_post_id,
        )
        if package_path.exists() and not overwrite:
            skipped_count += 1
            items.append(
                {
                    "status": CODEX_WRITE_STATUS_SKIPPED,
                    "reason": "exists",
                    "remote_post_id": remote_post_id,
                    "slug": slug_value,
                    "category_slug": category_slug_value,
                    "path": str(package_path),
                }
            )
            continue

        detail = _fetch_integration_post_detail(db, remote_post_id=remote_post_id)
        package = _seed_package_from_post(row, detail)
        _write_json(package_path, package)
        created_count += 1
        items.append(
            {
                "status": CODEX_WRITE_STATUS_SEEDED,
                "reason": "exported",
                "remote_post_id": remote_post_id,
                "slug": slug_value,
                "category_slug": category_slug_value,
                "path": str(package_path),
            }
        )

    report_path = _report_path(root, "export")
    _write_json(
        report_path,
        {
            "generated_at": _utc_now_iso(),
            "sync_before": bool(sync_before),
            "sync_result": sync_result,
            "category_slugs": list(category_slugs or []),
            "slug": _normalize_space(slug),
            "created_count": created_count,
            "skipped_count": skipped_count,
            "items": items,
        },
    )
    return {
        "status": "ok",
        "root": str(root),
        "created_count": created_count,
        "skipped_count": skipped_count,
        "report_path": str(report_path),
        "items": items,
    }


def _package_files_for_publish(
    *,
    base_dir: Path,
    category_slugs: Sequence[str] | None = None,
    slug: str | None = None,
    path: Path | None = None,
    limit: int | None = None,
) -> list[Path]:
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
    if limit is not None and limit > 0:
        files = files[:limit]
    return files


def _normalize_tag_names(tag_names: Sequence[Any], *, category_name: str, title: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in [category_name, *tag_names]:
        candidate = _normalize_space(raw).replace("#", " ")
        candidate = _normalize_space(candidate)
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(candidate)
        if len(values) >= 12:
            break
    if values:
        return values

    tokens = re.findall(r"[A-Za-z0-9가-힣]{2,}", title or "")
    for token in tokens:
        candidate = _normalize_space(token)
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(candidate)
        if len(values) >= 4:
            break
    return values


def _validate_codex_write_package(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("remote_post_id", "slug", "category_slug", "title", "excerpt", "meta_description", "html_article"):
        if not _normalize_space(payload.get(key)):
            errors.append(f"missing:{key}")

    category_slug = _normalize_space(payload.get("category_slug"))
    plain_length = _body_char_length(str(payload.get("html_article") or ""))
    max_length = 4500 if category_slug == "나스닥의-흐름" else 4000
    if plain_length < 3000 or plain_length > max_length:
        errors.append(f"body_length:{plain_length}")

    headings = _extract_headings(str(payload.get("html_article") or ""))
    if not headings or headings[-1] != "마무리 기록":
        errors.append("closing_record_missing")

    faq_section = payload.get("faq_section")
    if not isinstance(faq_section, list) or len(faq_section) == 0:
        errors.append("faq_missing")

    cover_image = payload.get("cover_image") if isinstance(payload.get("cover_image"), dict) else {}
    inline_image = payload.get("inline_image") if isinstance(payload.get("inline_image"), dict) else {}
    if not _normalize_space(cover_image.get("url")):
        errors.append("cover_image_missing")
    if not _normalize_space(inline_image.get("url")):
        errors.append("inline_image_missing")

    combined = " ".join(
        [
            _normalize_space(payload.get("title")),
            _normalize_space(payload.get("excerpt")),
            _normalize_space(payload.get("meta_description")),
            _normalize_space(payload.get("html_article")),
        ]
    ).casefold()
    for token in CODEX_WRITE_BANNED_TOKENS:
        if token.casefold() in combined:
            errors.append(f"banned_token:{token}")
    return errors


def publish_codex_write_packages(
    db: Session,
    *,
    category_slugs: Sequence[str] | None = None,
    slug: str | None = None,
    path: Path | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    sync_after: bool = True,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    root = get_codex_write_root(base_dir=base_dir)
    package_files = _package_files_for_publish(
        base_dir=root,
        category_slugs=category_slugs,
        slug=slug,
        path=path,
        limit=limit,
    )
    categories = [item for item in list_cloudflare_categories(db) if bool(item.get("isLeaf"))]
    categories_by_slug = {
        _normalize_space(item.get("slug")): {
            "id": _normalize_space(item.get("id")),
            "name": _normalize_space(item.get("name")),
        }
        for item in categories
        if _normalize_space(item.get("slug")) and _normalize_space(item.get("id"))
    }

    items: list[dict[str, Any]] = []
    updated_count = 0
    failed_count = 0
    skipped_count = 0
    touched = False

    for package_path in package_files:
        payload = _load_json(package_path)
        errors = _validate_codex_write_package(payload)
        remote_post_id = _normalize_space(payload.get("remote_post_id"))
        slug_value = _normalize_space(payload.get("slug"))
        category_slug_value = _normalize_space(payload.get("category_slug"))
        category_meta = categories_by_slug.get(category_slug_value)
        if category_meta is None:
            errors.append(f"unknown_category:{category_slug_value}")

        publish_state = payload.get("publish_state")
        if not isinstance(publish_state, dict):
            publish_state = {}
            payload["publish_state"] = publish_state

        if errors:
            failed_count += 1
            publish_state["status"] = CODEX_WRITE_STATUS_FAILED
            publish_state["last_error"] = ";".join(errors)
            _write_json(package_path, payload)
            items.append(
                {
                    "status": CODEX_WRITE_STATUS_FAILED,
                    "path": str(package_path),
                    "remote_post_id": remote_post_id,
                    "slug": slug_value,
                    "category_slug": category_slug_value,
                    "errors": errors,
                }
            )
            continue

        title = _normalize_space(payload.get("title"))
        excerpt = _normalize_space(payload.get("excerpt"))
        meta_description = _normalize_space(payload.get("meta_description"))
        seo_title = _normalize_space(payload.get("seo_title") or title)
        body = _strip_generated_body_images(
            _sanitize_cloudflare_public_body(
                str(payload.get("html_article") or ""),
                category_slug=category_slug_value,
                title=title,
            )
        )
        inline_image = payload.get("inline_image") if isinstance(payload.get("inline_image"), dict) else {}
        inline_url = _normalize_space(inline_image.get("url"))
        inline_alt = _normalize_space(inline_image.get("alt") or title)
        if inline_url:
            body = _insert_markdown_inline_image(body, f"![{inline_alt}]({inline_url})")

        cover_image = payload.get("cover_image") if isinstance(payload.get("cover_image"), dict) else {}
        tag_names = _normalize_tag_names(
            payload.get("tag_names") if isinstance(payload.get("tag_names"), list) else [],
            category_name=_normalize_space(category_meta.get("name")) if category_meta else category_slug_value,
            title=title,
        )
        update_payload: dict[str, Any] = {
            "title": title,
            "content": _prepare_markdown_body(title, body),
            "excerpt": excerpt,
            "seoTitle": seo_title,
            "seoDescription": meta_description,
            "tagNames": tag_names,
            "categoryId": _normalize_space(category_meta.get("id")) if category_meta else "",
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

        if dry_run:
            skipped_count += 1
            publish_state["status"] = CODEX_WRITE_STATUS_READY
            publish_state["last_error"] = None
            _write_json(package_path, payload)
            items.append(
                {
                    "status": CODEX_WRITE_STATUS_READY,
                    "path": str(package_path),
                    "remote_post_id": remote_post_id,
                    "slug": slug_value,
                    "category_slug": category_slug_value,
                    "updated_url": _normalize_space(payload.get("published_url")),
                }
            )
            continue

        response = _integration_request(
            db,
            method="PUT",
            path=f"/api/integrations/posts/{remote_post_id}",
            json_payload=update_payload,
            timeout=120.0,
        )
        updated_post = _integration_data_or_raise(response)
        if not isinstance(updated_post, dict):
            raise ValueError(f"Cloudflare update payload invalid for {remote_post_id}")

        touched = True
        updated_count += 1
        publish_state["status"] = CODEX_WRITE_STATUS_PUBLISHED
        publish_state["last_published_at"] = _utc_now_iso()
        publish_state["last_error"] = None
        payload["published_url"] = _normalize_space(updated_post.get("publicUrl") or payload.get("published_url"))
        _write_json(package_path, payload)
        items.append(
            {
                "status": CODEX_WRITE_STATUS_PUBLISHED,
                "path": str(package_path),
                "remote_post_id": remote_post_id,
                "slug": slug_value,
                "category_slug": category_slug_value,
                "updated_url": payload["published_url"],
            }
        )

    sync_result: dict[str, Any] | None = None
    if touched and sync_after and not dry_run:
        sync_result = sync_cloudflare_posts(db, include_non_published=True)

    report_path = _report_path(root, "publish")
    _write_json(
        report_path,
        {
            "generated_at": _utc_now_iso(),
            "dry_run": bool(dry_run),
            "category_slugs": list(category_slugs or []),
            "slug": _normalize_space(slug),
            "updated_count": updated_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "sync_result": sync_result,
            "items": items,
        },
    )
    return {
        "status": "ok" if failed_count == 0 else ("partial" if updated_count > 0 else "failed"),
        "root": str(root),
        "updated_count": updated_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "report_path": str(report_path),
        "sync_result": sync_result,
        "items": items,
    }

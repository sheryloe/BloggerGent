from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text


REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal
from app.services.cloudflare.cloudflare_channel_service import (
    _fetch_integration_post_detail,
    _integration_data_or_raise,
    _integration_request,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts


PREAPRIL_CUTOFF = datetime(2026, 4, 1, tzinfo=timezone.utc)
MEDIA_PREFIX = "https://api.dongriarchive.com/assets/assets/media/cloudflare/dongri-archive/"
COPY_HEADER_RE = re.compile(r"^COPY\s+public\.synced_cloudflare_posts\s*\((.+)\)\s+FROM\s+stdin;$", re.IGNORECASE)
HTML_IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
MD_IMG_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
HTML_IMG_REPLACE = re.compile(r"(<img[^>]+src=[\"'])([^\"']+)([\"'])", re.IGNORECASE)
MD_IMG_REPLACE = re.compile(r"(!\[[^\]]*]\()([^)]+)(\))")

PROBLEM_OLD_IDS: list[str] = [
    "911bfe71-167e-4a39-a3d5-88ae0a5851da",
    "bcf9f846-8f39-488e-ba40-a8aa96991215",
    "d2d43727-21dd-461a-a94b-4b50d366de62",
    "2c535674-5686-40e4-971f-1b4deb5b8ff4",
    "dbf9b80f-74ed-464f-9714-24a11aa6f489",
]

OLD_TO_NEW: dict[str, str] = {
    "911bfe71-167e-4a39-a3d5-88ae0a5851da": "efeb240c-daaf-4e51-be08-238218a398dc",
    "bcf9f846-8f39-488e-ba40-a8aa96991215": "a18a222c-a1bc-4ede-88e7-cc47299f0761",
    "d2d43727-21dd-461a-a94b-4b50d366de62": "7a55f8cc-8a2e-442c-aa50-dfc6deb91bae",
    "2c535674-5686-40e4-971f-1b4deb5b8ff4": "13a7469e-b70a-46a0-b118-a3ca916a9bce",
    "dbf9b80f-74ed-464f-9714-24a11aa6f489": "9cc5574c-cdde-4d6d-994a-e7b91b6f98f0",
}


@dataclass
class ManifestRow:
    remote_post_id: str
    slug: str
    title: str
    url: str
    status: str
    published_at: str
    created_at_remote: str
    updated_at_remote: str
    category_slug: str
    category_name: str
    thumbnail_url: str

    def to_dict(self) -> dict[str, str]:
        return {
            "remote_post_id": self.remote_post_id,
            "slug": self.slug,
            "title": self.title,
            "url": self.url,
            "status": self.status,
            "published_at": self.published_at,
            "created_at_remote": self.created_at_remote,
            "updated_at_remote": self.updated_at_remote,
            "category_slug": self.category_slug,
            "category_name": self.category_name,
            "thumbnail_url": self.thumbnail_url,
        }


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _decode_copy_text(value: str) -> str:
    if value == r"\N":
        return ""
    return (
        value.replace(r"\t", "\t")
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\f", "\f")
        .replace(r"\v", "\v")
        .replace(r"\\", "\\")
    )


def _safe_parse_dt(raw: str) -> datetime | None:
    value = _normalize_space(raw)
    if not value:
        return None
    normalized = value.replace(" ", "T")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_runtime_env() -> None:
    env_path = REPO_ROOT / "env" / "runtime.settings.env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if not key:
                continue
            os.environ.setdefault(key, value.strip())
    os.environ.setdefault("DATABASE_URL", "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent")
    os.environ.setdefault("STORAGE_ROOT", str(REPO_ROOT / "storage"))


def _parse_manifest_rows(dump_path: Path) -> list[ManifestRow]:
    if not dump_path.exists():
        raise FileNotFoundError(f"Dump file not found: {dump_path}")

    columns: list[str] = []
    in_copy = False
    candidates: list[ManifestRow] = []

    with dump_path.open("r", encoding="utf-16", errors="replace", newline="") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if not in_copy:
                match = COPY_HEADER_RE.match(line.strip())
                if not match:
                    continue
                columns = [column.strip() for column in match.group(1).split(",")]
                in_copy = True
                continue

            if line == r"\.":
                break

            if not line:
                continue
            values = line.split("\t")
            if len(values) < len(columns):
                values.extend([r"\N"] * (len(columns) - len(values)))
            row = {columns[idx]: _decode_copy_text(values[idx]) for idx in range(min(len(columns), len(values)))}

            remote_post_id = _normalize_space(row.get("remote_post_id"))
            if not remote_post_id:
                continue
            published_at = _normalize_space(row.get("published_at"))
            created_at_remote = _normalize_space(row.get("created_at_remote"))
            updated_at_remote = _normalize_space(row.get("updated_at_remote"))
            base_dt = _safe_parse_dt(published_at) or _safe_parse_dt(created_at_remote) or _safe_parse_dt(updated_at_remote)
            if base_dt is None or base_dt >= PREAPRIL_CUTOFF:
                continue

            candidates.append(
                ManifestRow(
                    remote_post_id=remote_post_id,
                    slug=_normalize_space(row.get("slug")),
                    title=_normalize_space(row.get("title")),
                    url=_normalize_space(row.get("url")),
                    status=_normalize_space(row.get("status")).lower(),
                    published_at=published_at,
                    created_at_remote=created_at_remote,
                    updated_at_remote=updated_at_remote,
                    category_slug=_normalize_space(row.get("category_slug")),
                    category_name=_normalize_space(row.get("category_name")),
                    thumbnail_url=_normalize_space(row.get("thumbnail_url")),
                ),
            )

    deduped: dict[str, ManifestRow] = {}
    for row in candidates:
        current = deduped.get(row.remote_post_id)
        if current is None:
            deduped[row.remote_post_id] = row
            continue
        current_dt = _safe_parse_dt(current.updated_at_remote) or _safe_parse_dt(current.published_at) or datetime.min.replace(
            tzinfo=timezone.utc,
        )
        row_dt = _safe_parse_dt(row.updated_at_remote) or _safe_parse_dt(row.published_at) or datetime.min.replace(
            tzinfo=timezone.utc,
        )
        if row_dt >= current_dt:
            deduped[row.remote_post_id] = row

    normalized = sorted(
        deduped.values(),
        key=lambda item: (_safe_parse_dt(item.published_at) or datetime.min.replace(tzinfo=timezone.utc), item.remote_post_id),
    )
    return normalized


def _extract_inline_image_url(content: str) -> str:
    body = str(content or "")
    html_match = HTML_IMG_RE.search(body)
    if html_match:
        return _normalize_space(html_match.group(1))
    md_match = MD_IMG_RE.search(body)
    if md_match:
        return _normalize_space(md_match.group(1))
    return ""


def _replace_first_inline_image(content: str, new_url: str) -> str:
    body = str(content or "")
    if not body or not _normalize_space(new_url):
        return body
    replaced_html = HTML_IMG_REPLACE.sub(rf"\1{new_url}\3", body, count=1)
    if replaced_html != body:
        return replaced_html
    replaced_md = MD_IMG_REPLACE.sub(rf"\1{new_url}\3", body, count=1)
    if replaced_md != body:
        return replaced_md
    return body + f"\n\n<p><img src=\"{new_url}\" alt=\"본문 이미지\" /></p>\n"


def _extract_tag_names(detail: dict[str, Any]) -> list[str]:
    raw_tags = detail.get("tags")
    if not isinstance(raw_tags, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for tag in raw_tags:
        if isinstance(tag, dict):
            name = _normalize_space(tag.get("name") or tag.get("label") or tag.get("slug"))
        else:
            name = _normalize_space(tag)
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _url_status(url: str, timeout: float = 20.0) -> int:
    target = _normalize_space(url)
    if not target:
        return 0
    try:
        response = httpx.get(target, follow_redirects=True, timeout=timeout)
        return int(response.status_code)
    except Exception:
        return 0


def _is_valid_media_url(url: str) -> bool:
    value = _normalize_space(url)
    return value.startswith(MEDIA_PREFIX)


def _build_update_payload(old_detail: dict[str, Any], *, cover_url: str, inline_url: str) -> dict[str, Any]:
    old_title = _normalize_space(old_detail.get("title"))
    old_excerpt = _normalize_space(old_detail.get("excerpt"))
    old_seo_title = _normalize_space(old_detail.get("seoTitle")) or old_title
    old_seo_description = _normalize_space(old_detail.get("seoDescription")) or old_excerpt or old_title
    old_slug = _normalize_space(old_detail.get("slug"))
    old_content = str(old_detail.get("content") or old_detail.get("contentMarkdown") or "")
    old_cover_alt = _normalize_space(old_detail.get("coverAlt")) or old_seo_description or old_title
    category_payload = old_detail.get("category") if isinstance(old_detail.get("category"), dict) else {}
    category_id = _normalize_space(category_payload.get("id"))

    payload: dict[str, Any] = {
        "title": old_title,
        "content": _replace_first_inline_image(old_content, inline_url),
        "excerpt": old_excerpt,
        "seoTitle": old_seo_title,
        "seoDescription": old_seo_description,
        "tagNames": _extract_tag_names(old_detail),
        "status": "published",
        "coverImage": cover_url,
        "coverAlt": old_cover_alt,
    }
    if old_slug:
        payload["slug"] = old_slug
    if category_id:
        payload["categoryId"] = category_id
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _build_report_dir(base_report_dir: Path | None) -> Path:
    day = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
    if base_report_dir is not None:
        target = base_report_dir
    else:
        target = REPO_ROOT / "codex_write" / "cloudflare" / "reports" / day
    target.mkdir(parents=True, exist_ok=True)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore pre-April Cloudflare posts without generation/model calls.")
    parser.add_argument(
        "--dump-path",
        default=str(REPO_ROOT / "backup" / "db-pre-change-20260408-141406.sql"),
        help="Path to pre-change SQL dump (UTF-16).",
    )
    parser.add_argument("--execute", action="store_true", help="Apply PUT updates for the 5 problematic old posts.")
    parser.add_argument("--skip-sync", action="store_true", help="Skip sync_cloudflare_posts after updates.")
    parser.add_argument("--report-dir", default="", help="Optional custom report directory.")
    args = parser.parse_args()

    _load_runtime_env()
    dump_path = Path(args.dump_path).resolve()
    report_dir = _build_report_dir(Path(args.report_dir).resolve() if args.report_dir else None)
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    report_base = report_dir / f"restore-preapril-77-{timestamp}"

    manifest_rows = _parse_manifest_rows(dump_path)
    manifest_payload = [row.to_dict() for row in manifest_rows]
    _write_json(report_base.with_name(report_base.name + "-manifest.json"), manifest_payload)

    remote_ids = [row.remote_post_id for row in manifest_rows]
    manifest_by_id = {row.remote_post_id: row for row in manifest_rows}

    status_rows: list[dict[str, Any]] = []
    old_snapshots: dict[str, dict[str, Any]] = {}
    detail_cache: dict[str, dict[str, Any]] = {}
    published_count = 0
    draft_count = 0
    error_count = 0

    with SessionLocal() as db:
        for remote_post_id in remote_ids:
            try:
                detail = _fetch_integration_post_detail(db, remote_post_id)
                detail_cache[remote_post_id] = detail
                status_value = _normalize_space(detail.get("status")).lower()
                if status_value in {"published", "live"}:
                    published_count += 1
                elif status_value == "draft":
                    draft_count += 1
                status_rows.append(
                    {
                        "remote_post_id": remote_post_id,
                        "status": status_value,
                        "slug": _normalize_space(detail.get("slug")),
                        "public_url": _normalize_space(detail.get("publicUrl") or detail.get("url")),
                        "cover_image": _normalize_space(detail.get("coverImage")),
                        "inline_image": _extract_inline_image_url(str(detail.get("content") or "")),
                    },
                )
            except Exception as exc:
                error_count += 1
                status_rows.append(
                    {
                        "remote_post_id": remote_post_id,
                        "status": "fetch_failed",
                        "error": str(exc),
                    },
                )

        restore_rows: list[dict[str, Any]] = []
        for old_id in PROBLEM_OLD_IDS:
            new_id = OLD_TO_NEW.get(old_id, "")
            old_detail = detail_cache.get(old_id) or _fetch_integration_post_detail(db, old_id)
            new_detail = detail_cache.get(new_id) or _fetch_integration_post_detail(db, new_id)
            detail_cache[old_id] = old_detail
            detail_cache[new_id] = new_detail
            old_snapshots[old_id] = old_detail

            new_cover = _normalize_space(new_detail.get("coverImage"))
            new_inline = _extract_inline_image_url(str(new_detail.get("content") or ""))
            new_cover_status = _url_status(new_cover)
            new_inline_status = _url_status(new_inline)
            new_public_url = _normalize_space(new_detail.get("publicUrl") or new_detail.get("url"))
            new_public_status = _url_status(new_public_url)

            old_manifest = manifest_by_id.get(old_id)
            old_url = old_manifest.url if old_manifest else _normalize_space(old_detail.get("publicUrl") or old_detail.get("url"))
            before_cover = _normalize_space(old_detail.get("coverImage"))
            before_inline = _extract_inline_image_url(str(old_detail.get("content") or ""))
            before_status = _normalize_space(old_detail.get("status")).lower()
            before_url_status = _url_status(old_url)

            validation_errors: list[str] = []
            if not _is_valid_media_url(new_cover):
                validation_errors.append("new_cover_invalid_prefix")
            if not _is_valid_media_url(new_inline):
                validation_errors.append("new_inline_invalid_prefix")
            if new_cover_status != 200:
                validation_errors.append(f"new_cover_http_{new_cover_status}")
            if new_inline_status != 200:
                validation_errors.append(f"new_inline_http_{new_inline_status}")
            if new_public_status != 200:
                validation_errors.append(f"new_public_http_{new_public_status}")

            update_payload = _build_update_payload(old_detail, cover_url=new_cover, inline_url=new_inline)
            after_status = before_status
            after_public_url = old_url
            after_cover = before_cover
            after_inline = before_inline
            after_url_status = before_url_status
            publish_result = "skipped"
            publish_error = ""

            if not validation_errors and args.execute:
                try:
                    response = _integration_request(
                        db,
                        method="PUT",
                        path=f"/api/integrations/posts/{old_id}",
                        json_payload=update_payload,
                        timeout=120.0,
                    )
                    updated = _integration_data_or_raise(response)
                    if not isinstance(updated, dict):
                        raise ValueError("invalid_update_response")
                    publish_result = "updated"
                    after_status = _normalize_space(updated.get("status")).lower()
                    after_public_url = _normalize_space(updated.get("publicUrl") or updated.get("url")) or old_url
                    after_cover = _normalize_space(updated.get("coverImage")) or new_cover
                    after_inline = _extract_inline_image_url(str(updated.get("content") or update_payload.get("content") or "")) or new_inline
                    after_url_status = _url_status(after_public_url or old_url)
                except Exception as exc:
                    publish_result = "failed"
                    publish_error = str(exc)
            elif not args.execute:
                publish_result = "dry_run"

            restore_rows.append(
                {
                    "remote_post_id": old_id,
                    "mapped_new_remote_post_id": new_id,
                    "old_url": old_url,
                    "new_url": new_public_url,
                    "status_before": before_status,
                    "status_after": after_status,
                    "cover_before": before_cover,
                    "cover_after": after_cover if publish_result in {"updated", "dry_run"} else before_cover,
                    "inline_before": before_inline,
                    "inline_after": after_inline if publish_result in {"updated", "dry_run"} else before_inline,
                    "old_url_http_before": before_url_status,
                    "old_url_http_after": after_url_status,
                    "new_url_http": new_public_status,
                    "new_cover_http": new_cover_status,
                    "new_inline_http": new_inline_status,
                    "validation_errors": validation_errors,
                    "publish_result": publish_result,
                    "publish_error": publish_error,
                },
            )

        if args.execute and not args.skip_sync:
            sync_result = sync_cloudflare_posts(db)
            db.commit()
        else:
            sync_result = {"status": "skipped"}
            db.rollback()

        manifest_id_array = [row.remote_post_id for row in manifest_rows]
        db_rows = db.execute(
            text(
                """
                SELECT remote_post_id, slug, status, url, thumbnail_url
                FROM synced_cloudflare_posts
                WHERE remote_post_id = ANY(:ids)
                ORDER BY remote_post_id
                """,
            ),
            {"ids": manifest_id_array},
        ).mappings().all()
        old_rows = db.execute(
            text(
                """
                SELECT remote_post_id, slug, status, url, thumbnail_url
                FROM synced_cloudflare_posts
                WHERE remote_post_id = ANY(:ids)
                ORDER BY remote_post_id
                """,
            ),
            {"ids": PROBLEM_OLD_IDS},
        ).mappings().all()

    _write_json(report_base.with_name(report_base.name + "-status.json"), status_rows)
    _write_json(report_base.with_name(report_base.name + "-old-snapshots.json"), old_snapshots)
    _write_json(report_base.with_name(report_base.name + "-restore.json"), restore_rows)
    _write_csv(
        report_base.with_name(report_base.name + "-restore.csv"),
        restore_rows,
        fieldnames=[
            "remote_post_id",
            "mapped_new_remote_post_id",
            "old_url",
            "new_url",
            "status_before",
            "status_after",
            "cover_before",
            "cover_after",
            "inline_before",
            "inline_after",
            "old_url_http_before",
            "old_url_http_after",
            "new_url_http",
            "new_cover_http",
            "new_inline_http",
            "validation_errors",
            "publish_result",
            "publish_error",
        ],
    )

    published_norm = [row for row in status_rows if row.get("status") in {"published", "live"}]
    draft_norm = [row for row in status_rows if row.get("status") == "draft"]

    summary_payload = {
        "mode": "execute" if args.execute else "dry_run",
        "no_generation_or_model_calls": True,
        "generation_calls": 0,
        "dump_path": str(dump_path),
        "manifest_count": len(manifest_rows),
        "status_scan": {
            "published_or_live": len(published_norm),
            "draft": len(draft_norm),
            "fetch_failed": error_count,
        },
        "problem_old_ids_expected": PROBLEM_OLD_IDS,
        "problem_old_to_new_mapping": OLD_TO_NEW,
        "restore_rows": restore_rows,
        "sync_result": sync_result,
        "db_verification": {
            "manifest_rows_in_synced_table": len(db_rows),
            "old_problem_rows_in_synced_table": len(old_rows),
            "rows_preview": [dict(row) for row in old_rows],
        },
        "artifacts": {
            "manifest_json": str(report_base.with_name(report_base.name + "-manifest.json")),
            "status_json": str(report_base.with_name(report_base.name + "-status.json")),
            "old_snapshots_json": str(report_base.with_name(report_base.name + "-old-snapshots.json")),
            "restore_json": str(report_base.with_name(report_base.name + "-restore.json")),
            "restore_csv": str(report_base.with_name(report_base.name + "-restore.csv")),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write_json(report_base.with_name(report_base.name + "-summary.json"), summary_payload)
    print(json.dumps(summary_payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

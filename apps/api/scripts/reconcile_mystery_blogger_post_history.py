from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.entities import BloggerPost, PostStatus


BLOG_ID = 35
SITEMAP_URL = "https://dongdonggri.blogspot.com/sitemap.xml"
MOCK_HOST = "mock-blogger.local"


@dataclass(slots=True)
class BloggerPostRow:
    id: int
    published_url: str
    post_status: PostStatus
    response_payload: dict


def _normalize_url(url: str | None) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    scheme = "https" if parsed.scheme in {"http", "https"} else parsed.scheme
    netloc = (parsed.netloc or "").strip().lower()
    path = (parsed.path or "").rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _host(url: str | None) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    return (urlsplit(raw).netloc or "").strip().lower()


def _load_public_urls() -> set[str]:
    response = httpx.get(SITEMAP_URL, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    xml = response.text
    urls: set[str] = set()
    for chunk in xml.split("<loc>")[1:]:
        candidate = chunk.split("</loc>", 1)[0].strip()
        normalized = _normalize_url(candidate)
        if "/2026/" in normalized:
            urls.add(normalized)
    return urls


def _iter_rows() -> Iterable[BloggerPostRow]:
    with SessionLocal() as db:
        records = (
            db.execute(
                select(
                    BloggerPost.id,
                    BloggerPost.published_url,
                    BloggerPost.post_status,
                    BloggerPost.response_payload,
                ).where(BloggerPost.blog_id == BLOG_ID)
            )
            .all()
        )
    for row in records:
        yield BloggerPostRow(
            id=int(row.id),
            published_url=str(row.published_url or ""),
            post_status=row.post_status,
            response_payload=dict(row.response_payload or {}),
        )


def _collect_candidates(public_urls: set[str]) -> dict:
    published_rows = [row for row in _iter_rows() if row.post_status == PostStatus.PUBLISHED]
    normalize_updates: list[dict] = []
    delete_candidates: list[dict] = []
    published_db_urls: set[str] = set()
    for row in published_rows:
        normalized_url = _normalize_url(row.published_url)
        published_db_urls.add(normalized_url)
        if row.published_url and row.published_url != normalized_url:
            normalize_updates.append(
                {
                    "id": row.id,
                    "before": row.published_url,
                    "after": normalized_url,
                }
            )
        if normalized_url and normalized_url not in public_urls:
            delete_candidates.append(
                {
                    "id": row.id,
                    "published_url": row.published_url,
                    "normalized_url": normalized_url,
                    "host": _host(row.published_url),
                    "delete_safe": _host(row.published_url) == MOCK_HOST,
                }
            )
    missing_urls = sorted(public_urls - published_db_urls)
    return {
        "published_count": len(published_rows),
        "public_count": len(public_urls),
        "normalize_updates": normalize_updates,
        "delete_candidates": delete_candidates,
        "missing_urls": missing_urls,
    }


def _apply_changes(candidates: dict) -> dict:
    normalize_updates = candidates["normalize_updates"]
    delete_candidates = candidates["delete_candidates"]
    delete_ids = [item["id"] for item in delete_candidates if item["delete_safe"]]
    unsafe_delete_candidates = [item for item in delete_candidates if not item["delete_safe"]]
    if unsafe_delete_candidates:
        raise RuntimeError(
            "Unsafe delete candidates detected. Refusing to continue: "
            + ", ".join(str(item["id"]) for item in unsafe_delete_candidates)
        )

    normalized_count = 0
    deleted_count = 0
    with SessionLocal() as db:
        rows = {
            row.id: row
            for row in db.execute(
                select(BloggerPost).where(BloggerPost.id.in_([item["id"] for item in normalize_updates] + delete_ids))
            )
            .scalars()
            .all()
        }
        for item in normalize_updates:
            row = rows.get(item["id"])
            if row is None:
                continue
            row.published_url = item["after"]
            payload = dict(row.response_payload or {})
            for field in ("url", "published_url"):
                if str(payload.get(field) or "").strip() == item["before"]:
                    payload[field] = item["after"]
            row.response_payload = payload
            normalized_count += 1
        for delete_id in delete_ids:
            row = rows.get(delete_id)
            if row is None:
                continue
            db.delete(row)
            deleted_count += 1
        db.commit()
    return {
        "normalized_count": normalized_count,
        "deleted_count": deleted_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize and trim BloggerPost history for mystery blog only.")
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    args = parser.parse_args()

    public_urls = _load_public_urls()
    candidates = _collect_candidates(public_urls)
    result = {
        "blog_id": BLOG_ID,
        "mode": args.mode,
        "published_count": candidates["published_count"],
        "public_count": candidates["public_count"],
        "normalize_count": len(candidates["normalize_updates"]),
        "delete_count": len(candidates["delete_candidates"]),
        "safe_delete_count": sum(1 for item in candidates["delete_candidates"] if item["delete_safe"]),
        "unsafe_delete_count": sum(1 for item in candidates["delete_candidates"] if not item["delete_safe"]),
        "missing_count": len(candidates["missing_urls"]),
        "normalize_sample": candidates["normalize_updates"][:10],
        "delete_sample": candidates["delete_candidates"][:10],
        "missing_sample": candidates["missing_urls"][:10],
    }
    if args.mode == "apply":
        result["applied"] = _apply_changes(candidates)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

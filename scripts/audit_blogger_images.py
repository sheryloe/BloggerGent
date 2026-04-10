from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
REPORT_DIR = REPO_ROOT / "storage" / "reports"
PLACEHOLDERS = ("${img}", "${s_img}", "${pImg}")
IMG_SRC_RE = re.compile(r"""<img\b[^>]*src=["']([^"']+)["']""", re.IGNORECASE)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str((REPO_ROOT / "storage").resolve())

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, Image, PostStatus  # noqa: E402
from app.services.blogger_live_audit_service import fetch_and_audit_blogger_post  # noqa: E402
from app.services.providers.factory import get_blogger_provider, get_image_provider  # noqa: E402
from app.services.publishing_service import rebuild_article_html, refresh_article_public_image, upsert_article_blogger_post  # noqa: E402
from app.services.storage_service import save_public_binary  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and repair Blogger image issues.")
    parser.add_argument("--start-date", default="2026-04-01")
    parser.add_argument("--end-date", default="2026-04-30")
    parser.add_argument("--profile-key", choices=("korea_travel", "world_mystery"))
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--sync-blogger", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def _parse_date(value: str) -> date:
    return date.fromisoformat(str(value).strip())


def _effective_post_date(article: Article) -> date | None:
    candidates = [
        article.blogger_post.scheduled_for if article.blogger_post else None,
        article.blogger_post.published_at if article.blogger_post else None,
        article.blogger_post.created_at if article.blogger_post else None,
        article.created_at,
    ]
    for candidate in candidates:
        if candidate is not None:
            return candidate.date()
    return None


def _resolve_inline_url(article: Article) -> str:
    expected_slot = "mystery-inline-3x2" if article.blog and article.blog.profile_key == "world_mystery" else "travel-inline-3x2"
    media_items = article.inline_media if isinstance(article.inline_media, list) else []
    for item in media_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("slot") or "").strip().lower() != expected_slot:
            continue
        delivery = item.get("delivery") if isinstance(item.get("delivery"), dict) else {}
        cloudflare = delivery.get("cloudflare") if isinstance(delivery, dict) else {}
        cloudinary = delivery.get("cloudinary") if isinstance(delivery, dict) else {}
        candidates = [
            str(cloudflare.get("original_url") or "").strip() if isinstance(cloudflare, dict) else "",
            str(cloudinary.get("secure_url_original") or "").strip() if isinstance(cloudinary, dict) else "",
            str(item.get("image_url") or "").strip(),
        ]
        for candidate in candidates:
            if candidate:
                return candidate
    return ""


def _extract_image_urls(html_value: str | None) -> list[str]:
    return [match.strip() for match in IMG_SRC_RE.findall(html_value or "") if match.strip()]


def _strip_existing_image_blocks(html_value: str | None) -> str:
    cleaned = str(html_value or "")
    cleaned = re.sub(r"<figure\b[^>]*>.*?</figure>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<img\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
    for token in PLACEHOLDERS:
        cleaned = re.sub(rf"<p>\s*{re.escape(token)}\s*</p>", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace(token, "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"<p>\s*</p>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _audit_article(article: Article) -> dict[str, Any]:
    html_value = article.assembled_html or article.html_article or ""
    raw_html = article.html_article or ""
    placeholder_detected = [token for token in PLACEHOLDERS if token in raw_html or token in html_value]
    hero_image_url = str(article.image.public_url or "").strip() if article.image else ""
    inline_image_url = _resolve_inline_url(article)
    image_urls = _extract_image_urls(html_value)
    unique_image_urls = sorted(set(image_urls))
    repeated_single_url = len(image_urls) >= 2 and len(unique_image_urls) == 1
    post_url = article.blogger_post.published_url if article.blogger_post else ""
    live_audit = fetch_and_audit_blogger_post(post_url, probe_images=False) if post_url else None
    live_issue_codes = (
        [code for code in str(live_audit.live_image_issue or "").split(",") if code]
        if live_audit is not None
        else []
    )
    live_image_count = live_audit.live_image_count if live_audit is not None else None
    image_missing = (
        live_audit is not None
        and (
            live_image_count != 2
            or live_audit.live_cover_present is not True
            or live_audit.live_inline_present is not True
        )
    ) or (not hero_image_url or not image_urls)
    issue_type: list[str] = []
    if placeholder_detected:
        issue_type.append("placeholder")
    if image_missing:
        issue_type.append("image_missing")
    if repeated_single_url:
        issue_type.append("repeated_single_url")
    for code in live_issue_codes:
        if code not in issue_type:
            issue_type.append(code)
    return {
        "post_url": post_url,
        "article_id": article.id,
        "title": article.title,
        "profile_key": article.blog.profile_key if article.blog else "",
        "issue_type": issue_type,
        "placeholder_detected": placeholder_detected,
        "image_missing": image_missing,
        "repair_action": "none",
        "result": "issue" if issue_type else "ok",
        "error": "",
        "hero_image_url": hero_image_url,
        "inline_image_url": inline_image_url,
        "image_url_count": len(image_urls),
        "unique_image_url_count": len(unique_image_urls),
        "live_image_count": live_image_count,
        "live_cover_present": live_audit.live_cover_present if live_audit is not None else None,
        "live_inline_present": live_audit.live_inline_present if live_audit is not None else None,
        "live_image_issue": live_audit.live_image_issue if live_audit is not None else "",
    }


def _sync_blogger_post(db, article: Article) -> str:
    if not article.blog or not article.blogger_post:
        return "skip:no-linked-post"
    provider = get_blogger_provider(db, article.blog)
    if not hasattr(provider, "update_post") or type(provider).__name__.startswith("Mock"):
        return "skip:mock-provider"
    summary, raw_payload = provider.update_post(
        post_id=article.blogger_post.blogger_post_id,
        title=article.title,
        content=article.assembled_html or article.html_article or "",
        labels=list(article.labels or []),
        meta_description=article.meta_description or "",
    )
    upsert_article_blogger_post(
        db,
        article=article,
        summary=summary,
        raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
    )
    return "updated"


def _attach_generated_hero(db, article: Article) -> str:
    prompt = str(article.image_collage_prompt or "").strip() or article.title.strip()
    if not prompt:
        raise ValueError("hero_prompt_missing")

    image_provider = get_image_provider(db)
    image_bytes, image_raw = image_provider.generate_image(prompt, article.slug)
    file_path, public_url, delivery_meta = save_public_binary(
        db,
        subdir="images",
        filename=f"{article.slug}.webp",
        content=image_bytes,
        provider_override="cloudflare_r2",
    )

    image = article.image
    if image is None:
        image = Image(
            job_id=article.job_id,
            article_id=article.id,
            prompt=prompt,
            file_path=file_path,
            public_url=public_url,
        )
        db.add(image)
        db.flush()

    image.article_id = article.id
    image.prompt = prompt
    image.file_path = file_path
    image.public_url = public_url
    image.width = int(image_raw.get("width", 1536) or 1536)
    image.height = int(image_raw.get("height", 1024) or 1024)
    image.provider = str(image_raw.get("actual_model") or image_raw.get("requested_model") or "gpt-image-1")
    image.image_metadata = {**image_raw, "delivery": delivery_meta}
    article.image_collage_prompt = prompt
    db.add(image)
    db.add(article)
    db.commit()
    db.refresh(article)
    return public_url


def _repair_article(db, article: Article, *, sync_blogger: bool) -> dict[str, Any]:
    row = _audit_article(article)
    if not row["issue_type"]:
        row["result"] = "skipped"
        return row

    hero_image_url = refresh_article_public_image(db, article) or (article.image.public_url if article.image else "")
    inline_image_url = _resolve_inline_url(article)
    if not hero_image_url:
        try:
            hero_image_url = _attach_generated_hero(db, article)
            row["repair_action"] = "regenerate_hero"
        except Exception as exc:  # noqa: BLE001
            row["repair_action"] = "queue_retry"
            row["result"] = "retry-required"
            row["error"] = f"hero_regeneration_failed:{exc}"
            return row
    if "repeated_single_url" in row["issue_type"] and not inline_image_url:
        row["repair_action"] = "queue_retry"
        row["result"] = "retry-required"
        row["error"] = "inline_image_missing"
        return row

    article.html_article = _strip_existing_image_blocks(article.html_article)
    db.add(article)
    db.commit()
    db.refresh(article)
    rebuild_article_html(db, article, hero_image_url)
    db.refresh(article)

    sync_status = "rebuilt"
    if sync_blogger:
        sync_status = f"rebuilt+{_sync_blogger_post(db, article)}"
    repaired = _audit_article(article)
    repaired["repair_action"] = sync_status
    repaired["result"] = "repaired" if not repaired["issue_type"] else "partial"
    return repaired


def _load_articles(db, *, start_date: date, end_date: date, profile_key: str | None, limit: int) -> list[Article]:
    stmt = (
        select(Article)
        .join(Blog, Blog.id == Article.blog_id)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .where(
            Blog.is_active.is_(True),
            Blog.profile_key.in_(("korea_travel", "world_mystery")),
            BloggerPost.post_status.in_((PostStatus.PUBLISHED, PostStatus.SCHEDULED)),
        )
        .options(
            selectinload(Article.blog),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
        )
        .order_by(BloggerPost.created_at.asc(), Article.id.asc())
    )
    if profile_key:
        stmt = stmt.where(Blog.profile_key == profile_key)
    articles = db.execute(stmt).scalars().all()
    filtered: list[Article] = []
    for article in articles:
        effective_date = _effective_post_date(article)
        if effective_date is None:
            continue
        if start_date <= effective_date <= end_date:
            filtered.append(article)
    if limit > 0:
        return filtered[:limit]
    return filtered


def _write_report(prefix: str, rows: list[dict[str, Any]]) -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"{prefix}-{timestamp}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def main() -> int:
    args = parse_args()
    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date)
    with SessionLocal() as db:
        articles = _load_articles(
            db,
            start_date=start_date,
            end_date=end_date,
            profile_key=args.profile_key,
            limit=max(int(args.limit), 0),
        )
        audit_rows = [_audit_article(article) for article in articles]
        repair_rows: list[dict[str, Any]] = []
        if args.repair:
            for article in articles:
                if _audit_article(article)["issue_type"]:
                    repair_rows.append(_repair_article(db, article, sync_blogger=bool(args.sync_blogger)))
    audit_report = _write_report("blogger-image-audit", audit_rows)
    repair_report = _write_report("blogger-image-repair", repair_rows)
    print(
        json.dumps(
            {
                "status": "ok",
                "audited_count": len(audit_rows),
                "repair_count": len(repair_rows),
                "audit_report": audit_report,
                "repair_report": repair_report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
TRAVEL_BLOG_IDS = (34, 36, 37)
TRAVEL_PHASES = {
    "en": (34,),
    "ja": (37,),
    "es": (36,),
}
TRAVEL_PHASE_ORDER = ("en", "ja", "es")
DEFAULT_BATCH_SIZE = 5
DEFAULT_EN_PRIORITY_IDS = (335, 338)
DEFAULT_CANARY_IDS = (369,)
LIVE_HERO_FIGURE_RE = re.compile(
    r"<figure\b[^>]*data-bloggent-role=['\"]hero-figure['\"][^>]*>.*?<img\b[^>]*src=['\"](?P<src>[^'\"]+)['\"]",
    re.IGNORECASE | re.DOTALL,
)
TRAVEL_ASSET_URL_RE = re.compile(
    r"https://api\.dongriarchive\.com/assets/travel-blogger/(?:travel|culture)/[^\"'\s>]+",
    re.IGNORECASE,
)


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = str(raw_line or "").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'").strip('"')


_load_runtime_env(RUNTIME_ENV_PATH)
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or os.environ.get("BLOGGENT_DATABASE_URL") or DEFAULT_DATABASE_URL
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, ContentPlanSlot, Image, JobStatus  # noqa: E402
from app.services.blogger.blogger_live_audit_service import extract_best_article_fragment  # noqa: E402
from app.services.content.blogger_live_publish_validation_service import validate_blogger_live_publish  # noqa: E402
from app.services.platform.publishing_service import rebuild_article_html, refresh_article_public_image, sanitize_blogger_labels_for_article, upsert_article_blogger_post  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402
from app.services.providers.base import ProviderRuntimeError  # noqa: E402
from app.services.integrations.storage_service import is_private_asset_url  # noqa: E402


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def _plain_non_space_len(value: str | None) -> int:
    return len(SPACE_RE.sub("", TAG_RE.sub(" ", str(value or ""))).strip())


def _slug_like(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _title_raw_topic_like(article: Article) -> bool:
    title_slug = _slug_like(article.title)
    article_slug = _slug_like(article.slug)
    if not title_slug or not article_slug:
        return False
    return title_slug == article_slug or title_slug.startswith(article_slug) or article_slug.startswith(title_slug)


def _metadata_retry_count(article: Article) -> int:
    metadata = dict(article.render_metadata or {})
    travel_meta = metadata.get("travel_reassembly")
    if not isinstance(travel_meta, dict):
        return 0
    try:
        return max(int(travel_meta.get("retry_count") or 0), 0)
    except (TypeError, ValueError):
        return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _load_published_articles(db, *, blog_ids: tuple[int, ...]) -> list[Article]:
    return (
        db.execute(
            select(Article)
            .where(Article.blog_id.in_(list(blog_ids)))
            .options(
                selectinload(Article.blog),
                selectinload(Article.job),
                selectinload(Article.image),
                selectinload(Article.blogger_post),
            )
            .order_by(Article.blog_id.asc(), Article.id.asc())
        )
        .scalars()
        .all()
    )


def _eligible_published_articles(articles: list[Article]) -> list[Article]:
    result: list[Article] = []
    for article in articles:
        post = article.blogger_post
        if not post:
            continue
        if not str(post.published_url or "").strip():
            continue
        if not str(post.blogger_post_id or "").strip():
            continue
        result.append(article)
    return result


def _travel_reassembly_status(article: Article) -> str:
    metadata = dict(article.render_metadata or {})
    travel_meta = metadata.get("travel_reassembly")
    if not isinstance(travel_meta, dict):
        return ""
    return str(travel_meta.get("reassembly_status") or "").strip().lower()


def _select_canary_articles(articles: list[Article]) -> list[Article]:
    by_id = {int(article.id): article for article in articles}
    selected: list[Article] = []
    for article_id in DEFAULT_CANARY_IDS:
        article = by_id.get(int(article_id))
        if article is not None:
            selected.append(article)

    seen_ids = {int(article.id) for article in selected}
    for blog_id in (36, 37):
        representative = next((article for article in articles if int(article.blog_id) == blog_id and int(article.id) not in seen_ids), None)
        if representative is not None:
            selected.append(representative)
            seen_ids.add(int(representative.id))
    return selected


def _update_reassembly_metadata(
    db,
    article: Article,
    *,
    status: str,
    failure_reason: str | None,
    live_validation: dict[str, Any] | None,
    published_url: str | None,
    retry_count: int | None = None,
) -> None:
    metadata = dict(article.render_metadata or {})
    travel_meta = dict(metadata.get("travel_reassembly") or {})
    resolved_retry_count = _metadata_retry_count(article) if retry_count is None else max(int(retry_count), 0)
    travel_meta.update(
        {
            "reassembled_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "reassembly_status": status,
            "failure_reason": failure_reason,
            "published_url": published_url,
            "live_validation": live_validation or {},
            "retry_count": resolved_retry_count,
        }
    )
    metadata["travel_reassembly"] = travel_meta
    article.render_metadata = metadata
    db.add(article)
    db.commit()
    db.refresh(article)


def _recover_live_hero_source(db, article: Article, *, published_url: str) -> str:
    normalized_url = str(published_url or "").strip()
    if not normalized_url:
        return ""

    try:
        response = httpx.get(normalized_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return ""

    page_html = response.text
    fragment = extract_best_article_fragment(page_html, expected_title=article.title)
    match = LIVE_HERO_FIGURE_RE.search(fragment) or LIVE_HERO_FIGURE_RE.search(page_html)
    recovered_url = html.unescape(str(match.group("src") if match else "")).strip()
    if not recovered_url:
        candidates = TRAVEL_ASSET_URL_RE.findall(fragment) or TRAVEL_ASSET_URL_RE.findall(page_html)
        recovered_url = html.unescape(str(candidates[0] if candidates else "")).strip()
    if not recovered_url:
        return ""

    image = db.execute(select(Image).where(Image.job_id == article.job_id)).scalar_one_or_none()
    metadata = {
        "recovered_from_live": True,
        "recovered_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "published_url": normalized_url,
        "source": "travel_reassembly_live_scan",
    }
    if image is None:
        image = Image(
            job_id=article.job_id,
            article_id=article.id,
            prompt="Recovered from live travel hero source",
            file_path=recovered_url,
            public_url=recovered_url,
            width=1536,
            height=1024,
            provider="live-repair",
            image_metadata=metadata,
        )
    else:
        image.article_id = article.id
        image.prompt = str(image.prompt or "").strip() or "Recovered from live travel hero source"
        image.file_path = str(image.file_path or "").strip() or recovered_url
        image.public_url = recovered_url
        image.provider = str(image.provider or "").strip() or "live-repair"
        image.image_metadata = dict(image.image_metadata or {}) | metadata
    db.add(image)
    db.commit()
    db.refresh(image)
    db.refresh(article, attribute_names=["image"])
    return str(image.public_url or "").strip()


def _mark_failed_temp(db, article: Article, *, reason: str, retry_count: int) -> None:
    job = getattr(article, "job", None)
    if job is None:
        return
    errors = list(job.error_logs or [])
    errors.append(
        {
            "message": reason,
            "stage": "travel_global_reassembly_v2",
            "temporary": True,
            "retry_count": retry_count,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    job.error_logs = errors
    job.status = JobStatus.FAILED_TEMP
    job.end_time = datetime.now(UTC)
    db.add(job)
    db.commit()


def _hard_delete_article_job(db, article: Article, *, reason: str) -> dict[str, Any]:
    slot_rows = (
        db.execute(
            select(ContentPlanSlot).where(
                (ContentPlanSlot.article_id == int(article.id))
                | (ContentPlanSlot.job_id == int(article.job_id))
            )
        )
        .scalars()
        .all()
    )
    for slot in slot_rows:
        slot.article_id = None
        slot.job_id = None
        db.add(slot)
    job = getattr(article, "job", None)
    if job is not None:
        db.delete(job)
    else:
        db.delete(article)
    db.commit()
    return {
        "deleted": True,
        "delete_reason": reason,
        "nulled_content_plan_slots": len(slot_rows),
    }


def _reassemble_one(
    db,
    article: Article,
    *,
    execute: bool,
    hard_delete_failed_temp: bool = False,
    failed_temp_threshold: int = 2,
) -> dict[str, Any]:
    post = article.blogger_post
    if post is None or not str(post.blogger_post_id or "").strip() or not str(post.published_url or "").strip():
        return {
            "article_id": int(article.id),
            "blog_id": int(article.blog_id),
            "title": article.title,
            "status": "failed",
            "failure_reason": "missing_existing_live_post",
        }

    hero_url = str(article.image.public_url or "").strip() if getattr(article, "image", None) else ""
    if not hero_url or is_private_asset_url(hero_url):
        hero_url = str(refresh_article_public_image(db, article) or "").strip()
    if not hero_url:
        hero_url = _recover_live_hero_source(db, article, published_url=str(post.published_url or "").strip())
    if not hero_url:
        failure_reason = "missing_live_hero_source"
        if execute:
            _update_reassembly_metadata(db, article, status="failed", failure_reason=failure_reason, live_validation=None, published_url=post.published_url)
        return {
            "article_id": int(article.id),
            "blog_id": int(article.blog_id),
            "title": article.title,
            "published_url": post.published_url,
            "status": "failed",
            "failure_reason": failure_reason,
        }

    assembled_html = rebuild_article_html(db, article, hero_url)
    labels = sanitize_blogger_labels_for_article(article, article.labels)

    if not execute:
        return {
            "article_id": int(article.id),
            "blog_id": int(article.blog_id),
            "title": article.title,
            "published_url": str(post.published_url or "").strip(),
            "status": "pending",
            "assembled_visible_chars": len("".join(str(assembled_html or "").split())),
            "blogger_post_id": str(post.blogger_post_id),
            "labels": labels,
        }

    provider = get_blogger_provider(db, article.blog)
    update_summary, update_payload = provider.update_post(
        post_id=str(post.blogger_post_id),
        title=article.title,
        content=assembled_html,
        labels=labels,
        meta_description=article.meta_description,
    )
    blogger_post = upsert_article_blogger_post(db, article=article, summary=update_summary, raw_payload=update_payload)
    published_url = str(blogger_post.published_url or post.published_url or "").strip()

    live_validation = validate_blogger_live_publish(
        published_url=published_url,
        expected_title=article.title,
        expected_hero_url=hero_url,
        assembled_html=assembled_html,
        required_article_h1_count=1,
    )
    failure_reasons = list(live_validation.get("failure_reasons") or [])
    live_chars = int(live_validation.get("article_visible_non_space_chars") or 0)
    if live_chars < 2500:
        failure_reasons.append("article_live_body_under_2500")
    if _title_raw_topic_like(article):
        failure_reasons.append("title_raw_topic_like")
    if not str(getattr(article, "article_pattern_key", "") or getattr(article, "article_pattern_id", "") or "").strip():
        failure_reasons.append("missing_pattern_key")
    if not str(getattr(article, "article_pattern_version_key", "") or getattr(article, "article_pattern_version", "") or "").strip():
        failure_reasons.append("missing_pattern_version")
    if failure_reasons:
        live_validation["failure_reasons"] = failure_reasons
        live_validation["status"] = "failed"
    status = "ok" if str(live_validation.get("status") or "").lower() == "ok" else "failed"
    failure_reason = None if status == "ok" else ",".join(list(live_validation.get("failure_reasons") or [])) or "live_validation_failed"
    retry_count = 0 if status == "ok" else _metadata_retry_count(article) + 1

    _update_reassembly_metadata(
        db,
        article,
        status=status,
        failure_reason=failure_reason,
        live_validation=live_validation,
        published_url=published_url,
        retry_count=retry_count,
    )
    deleted_payload: dict[str, Any] = {"deleted": False}
    if status != "ok" and retry_count >= failed_temp_threshold:
        _mark_failed_temp(db, article, reason=failure_reason or "travel_reassembly_failed", retry_count=retry_count)
    if status != "ok" and hard_delete_failed_temp and retry_count > failed_temp_threshold:
        deleted_payload = _hard_delete_article_job(
            db,
            article,
            reason=failure_reason or "travel_reassembly_failed_threshold_exceeded",
        )

    return {
        "article_id": int(article.id),
        "blog_id": int(article.blog_id),
        "title": article.title,
        "published_url": published_url,
        "status": status,
        "failure_reason": failure_reason,
        "retry_count": retry_count,
        **deleted_payload,
        "live_validation": live_validation,
    }


def _phase_blog_ids(phase: str, blog_ids: tuple[int, ...]) -> tuple[int, ...]:
    normalized = str(phase or "").strip().lower()
    if normalized in TRAVEL_PHASES:
        return tuple(blog_id for blog_id in TRAVEL_PHASES[normalized] if blog_id in blog_ids)
    return blog_ids


def _needs_reassembly(article: Article) -> bool:
    if _travel_reassembly_status(article) != "ok":
        return True
    if _plain_non_space_len(article.assembled_html or article.html_article) < 2500:
        return True
    if not str(getattr(article, "article_pattern_key", "") or getattr(article, "article_pattern_id", "") or "").strip():
        return True
    if not str(getattr(article, "article_pattern_version_key", "") or getattr(article, "article_pattern_version", "") or "").strip():
        return True
    return False


def _select_batch_articles(
    articles: list[Article],
    *,
    phase: str,
    batch_size: int,
    include_ok: bool,
    priority_ids: tuple[int, ...],
) -> list[Article]:
    candidates = list(articles if include_ok else [article for article in articles if _needs_reassembly(article)])
    all_by_id = {int(article.id): article for article in articles}
    selected: list[Article] = []
    if str(phase or "").strip().lower() == "en":
        for article_id in priority_ids:
            article = all_by_id.get(int(article_id))
            if article is not None:
                selected.append(article)
    seen = {int(article.id) for article in selected}
    for article in sorted(candidates, key=lambda item: (int(item.blog_id), int(item.id))):
        if int(article.id) in seen:
            continue
        selected.append(article)
        seen.add(int(article.id))
        if len(selected) >= batch_size:
            break
    return selected[:batch_size]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reassemble published travel posts and revalidate live structure.")
    parser.add_argument("--blog-ids", default="34,36,37")
    parser.add_argument("--article-ids", default="")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-global-reassembly")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--canary-only", action="store_true")
    parser.add_argument("--phase", choices=["en", "ja", "es", "all"], default="en")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--include-ok", action="store_true")
    parser.add_argument("--priority-article-ids", default=",".join(str(item) for item in DEFAULT_EN_PRIORITY_IDS))
    parser.add_argument("--hard-delete-failed-temp", action="store_true")
    parser.add_argument("--failed-temp-threshold", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_root = Path(str(args.report_root)).resolve()
    report_path = report_root / "reports" / f"{args.report_prefix}-{stamp}.json"
    blog_ids = tuple(int(token) for token in str(args.blog_ids).split(",") if token.strip())
    requested_article_ids = tuple(int(token) for token in str(args.article_ids).split(",") if token.strip())
    priority_article_ids = tuple(int(token) for token in str(args.priority_article_ids).split(",") if token.strip())
    phase_blog_ids = blog_ids if args.phase == "all" else _phase_blog_ids(args.phase, blog_ids)

    with SessionLocal() as db:
        all_articles = _eligible_published_articles(_load_published_articles(db, blog_ids=phase_blog_ids))
        if requested_article_ids:
            requested_id_set = {int(article_id) for article_id in requested_article_ids}
            all_articles = [article for article in all_articles if int(article.id) in requested_id_set]
        canary_articles = _select_canary_articles(all_articles) if args.canary_only else []
        pending_bulk_articles = _select_batch_articles(
            all_articles,
            phase=str(args.phase),
            batch_size=max(1, int(args.batch_size or DEFAULT_BATCH_SIZE)),
            include_ok=bool(args.include_ok or requested_article_ids),
            priority_ids=priority_article_ids,
        )

        canary_results = [
            _reassemble_one(
                db,
                article,
                execute=args.execute,
                hard_delete_failed_temp=bool(args.hard_delete_failed_temp),
                failed_temp_threshold=max(1, int(args.failed_temp_threshold or 2)),
            )
            for article in canary_articles
        ]
        canary_failed = bool(args.execute) and any(str(item.get("status") or "").lower() != "ok" for item in canary_results)

        bulk_results: list[dict[str, Any]] = []
        if args.execute and not args.canary_only and not canary_failed:
            bulk_candidates = pending_bulk_articles
            if int(args.limit or 0) > 0:
                bulk_candidates = bulk_candidates[: int(args.limit)]
            for article in bulk_candidates:
                try:
                    bulk_results.append(
                        _reassemble_one(
                            db,
                            article,
                            execute=True,
                            hard_delete_failed_temp=bool(args.hard_delete_failed_temp),
                            failed_temp_threshold=max(1, int(args.failed_temp_threshold or 2)),
                        )
                    )
                except ProviderRuntimeError as exc:
                    oauth_blocked = (
                        str(getattr(exc, "provider", "") or "").lower() == "blogger"
                        or "oauth" in str(exc).lower()
                    )
                    bulk_results.append(
                        {
                            "article_id": int(article.id),
                            "blog_id": int(article.blog_id),
                            "title": article.title,
                            "published_url": article.blogger_post.published_url if article.blogger_post else None,
                            "status": "failed",
                            "failure_reason": "blogger_oauth_unavailable" if oauth_blocked else str(exc),
                            "error": str(exc),
                        }
                    )
                    if oauth_blocked:
                        break
                except Exception as exc:  # noqa: BLE001
                    bulk_results.append(
                        {
                            "article_id": int(article.id),
                            "blog_id": int(article.blog_id),
                            "title": article.title,
                            "published_url": article.blogger_post.published_url if article.blogger_post else None,
                            "status": "failed",
                            "failure_reason": str(exc),
                        }
                    )
        elif not args.execute and not args.canary_only:
            bulk_candidates = pending_bulk_articles
            if int(args.limit or 0) > 0:
                bulk_candidates = bulk_candidates[: int(args.limit)]
            for article in bulk_candidates:
                bulk_results.append(
                    {
                        "article_id": int(article.id),
                        "blog_id": int(article.blog_id),
                        "title": article.title,
                        "published_url": article.blogger_post.published_url if article.blogger_post else None,
                        "stored_visible_chars": _plain_non_space_len(article.assembled_html or article.html_article),
                        "article_pattern_key": getattr(article, "article_pattern_key", None),
                        "article_pattern_version_key": getattr(article, "article_pattern_version_key", None),
                        "status": "pending",
                    }
                )

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "execute" if args.execute else "dry_run",
        "phase": args.phase,
        "phase_blog_ids": list(phase_blog_ids),
        "batch_size": int(args.batch_size or DEFAULT_BATCH_SIZE),
        "hard_delete_failed_temp": bool(args.hard_delete_failed_temp),
        "failed_temp_threshold": max(1, int(args.failed_temp_threshold or 2)),
        "canary_only": bool(args.canary_only),
        "canary_failed": canary_failed,
        "canary_article_ids": [int(article.id) for article in canary_articles],
        "requested_article_ids": list(requested_article_ids),
        "published_article_count": len(all_articles),
        "pending_bulk_article_count": len(pending_bulk_articles),
        "bulk_article_ids": [int(article.id) for article in pending_bulk_articles],
        "canary_results": canary_results,
        "bulk_results": bulk_results,
    }

    if args.write_report:
        _write_json(report_path, report)

    print(
        json.dumps(
            {
                "report_path": str(report_path) if args.write_report else None,
                "mode": report["mode"],
                "phase": report["phase"],
                "phase_blog_ids": report["phase_blog_ids"],
                "batch_size": report["batch_size"],
                "published_article_count": report["published_article_count"],
                "pending_bulk_article_count": report["pending_bulk_article_count"],
                "bulk_article_ids": report["bulk_article_ids"],
                "canary_failed": canary_failed,
                "canary_article_ids": report["canary_article_ids"],
                "bulk_candidate_count": len(bulk_results),
                "passed": sum(1 for item in bulk_results if str(item.get("status") or "").lower() == "ok"),
                "failed": sum(1 for item in bulk_results if str(item.get("status") or "").lower() == "failed"),
                "deleted": sum(1 for item in bulk_results if bool(item.get("deleted"))),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not canary_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.session import SessionLocal
from app.models.entities import (
    Article,
    AuditLog,
    BloggerPost,
    ContentPlanSlot,
    Job,
    JobStatus,
    LogLevel,
    PostStatus,
    PublishMode,
)
from app.schemas.ai import ArticleGenerationOutput
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog
from app.services.content.article_service import ensure_article_editorial_labels, save_article
from app.services.content.html_assembler import assemble_article_html
from app.services.content.travel_translation_state_service import refresh_travel_translation_state
from app.services.content.travel_blog_policy import is_valid_travel_public_hero_url
from app.services.integrations.telegram_service import send_telegram_post_notification
from app.services.ops.job_service import merge_prompt, merge_response, set_status
from app.services.providers.factory import get_blogger_provider
from app.tasks.pipeline import _upsert_blogger_post, _upsert_image

TRAVEL_BLOG_IDS = {34, 36, 37}
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
BROKEN_QUESTION_RUN_RE = re.compile(r"\?{3,}")
BROKEN_LATIN_IN_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]\?[A-Za-zÀ-ÖØ-öø-ÿ]")
JAPANESE_TEXT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
TRAVEL_CANONICAL_PUBLIC_URL_RE = re.compile(
    r"https://api\.dongriarchive\.com/assets/travel-blogger/(?:travel|culture|food|uncategorized)/[a-z0-9][a-z0-9-]*\.webp",
    re.IGNORECASE,
)
LEGACY_COVER_FILE_RE = re.compile(r"^cover(?:-[a-z0-9]+)?\.webp$", re.IGNORECASE)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _report_path(report_root: Path, prefix: str) -> Path:
    out_dir = report_root / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().strftime("%Y%m%d-%H%M%S")
    return out_dir / f"{prefix}-{stamp}.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_db_report(db, report: dict[str, Any]) -> AuditLog:
    payload = json.loads(json.dumps(report, ensure_ascii=False, default=str))
    entry = AuditLog(
        job_id=None,
        stage="travel_app_thread_report",
        level=LogLevel.INFO,
        message="Travel app-thread execution report stored in DB.",
        payload=payload,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _iter_string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for nested in value.values():
            strings.extend(_iter_string_values(nested))
        return strings
    if isinstance(value, (list, tuple)):
        strings = []
        for nested in value:
            strings.extend(_iter_string_values(nested))
        return strings
    return []


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _classify_hero_url(hero_url: str) -> dict[str, str]:
    raw = str(hero_url or "").strip()
    if not raw:
        return {"kind": "missing", "reason": "missing_hero_url"}
    parsed = urlsplit(raw.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0])
    path = str(parsed.path or raw).strip().lstrip("/")
    lowered_path = path.lower()
    file_name = lowered_path.rsplit("/", maxsplit=1)[-1]
    if LEGACY_COVER_FILE_RE.fullmatch(file_name):
        return {"kind": "legacy", "reason": "legacy_cover_hero_url"}
    if lowered_path.startswith("assets/donggri/"):
        return {"kind": "legacy", "reason": "legacy_donggri_asset_url"}
    if lowered_path.startswith("assets/donggri-s-hidden-korea-local-travel-culture/"):
        return {"kind": "legacy", "reason": "legacy_english_travel_asset_url"}
    if not is_valid_travel_public_hero_url(raw):
        return {"kind": "noncanonical", "reason": "noncanonical_travel_hero_url"}
    return {"kind": "canonical", "reason": ""}


def _extract_travel_canonical_urls_from_text(text: str) -> list[str]:
    return _dedupe_strings([match.group(0).rstrip("/") for match in TRAVEL_CANONICAL_PUBLIC_URL_RE.finditer(str(text or ""))])


def _extract_travel_canonical_urls(value: Any) -> list[str]:
    urls: list[str] = []
    for text in _iter_string_values(value):
        if is_valid_travel_public_hero_url(text):
            urls.append(text.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0].rstrip("/"))
        urls.extend(_extract_travel_canonical_urls_from_text(text))
    return _dedupe_strings(urls)


def _load_payload(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("items")
    else:
        items = data
    if not isinstance(items, list):
        raise ValueError("Payload must be a JSON list or an object with items=[...].")
    return [dict(item) for item in items if isinstance(item, dict)]


def _flatten_payload_text(item: dict[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key in ("title", "meta_description", "excerpt", "html_article", "image_collage_prompt"):
        fields[key] = str(item.get(key) or "")
    fields["labels"] = " ".join(str(label) for label in item.get("labels", []) if str(label).strip())
    faq_parts: list[str] = []
    for faq in item.get("faq_section") or []:
        if isinstance(faq, dict):
            faq_parts.append(str(faq.get("question") or ""))
            faq_parts.append(str(faq.get("answer") or ""))
    fields["faq_section"] = " ".join(faq_parts)
    return fields


def _detect_encoding_issues(*, item: dict[str, Any], content_html: str | None = None) -> list[str]:
    target_language = str(item.get("target_language") or "").strip().lower()
    fields = _flatten_payload_text(item)
    if content_html is not None:
        fields = {"live_html": str(content_html or "")}
    issues: list[str] = []
    joined = "\n".join(fields.values())
    if "\ufffd" in joined:
        issues.append("replacement_character_present")
    if BROKEN_QUESTION_RUN_RE.search(joined):
        issues.append("question_mark_run_present")
    if target_language in {"es", "en"} and BROKEN_LATIN_IN_WORD_RE.search(joined):
        issues.append("latin_word_question_mark_present")
    if target_language == "ja":
        if not JAPANESE_TEXT_RE.search(joined):
            issues.append("japanese_text_missing")
        if BROKEN_LATIN_IN_WORD_RE.search(joined):
            issues.append("latin_word_question_mark_present")
    return sorted(set(issues))


def _assert_payload_encoding(item: dict[str, Any]) -> None:
    issues = _detect_encoding_issues(item=item)
    if issues:
        raise ValueError(f"encoding_gate_failed:{','.join(issues)}")


def _validate_hero_url(hero_url: str) -> dict[str, Any]:
    result: dict[str, Any] = {"url": hero_url, "ok": False}
    policy = _classify_hero_url(hero_url)
    result["policy"] = policy
    if policy["kind"] != "canonical":
        result["error"] = policy["reason"]
        return result
    try:
        response = httpx.get(hero_url, follow_redirects=True, timeout=20.0)
        result.update(
            {
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "content_length": len(response.content or b""),
                "ok": response.status_code == 200 and "image/" in response.headers.get("content-type", "").lower(),
            }
        )
    except Exception as exc:  # noqa: BLE001 - operational report needs the exact failure text.
        result["error"] = str(exc)
    return result


def _get_source_article(db, source_article_id: int) -> Article | None:
    if not source_article_id:
        return None
    return (
        db.execute(
            select(Article)
            .where(Article.id == int(source_article_id))
            .options(
                selectinload(Article.image),
                selectinload(Article.blogger_post),
            )
        )
        .scalars()
        .one_or_none()
    )


def _collect_source_article_canonical_hero_candidates(article: Article) -> list[str]:
    values: list[Any] = [
        article.image.public_url if article.image else "",
        article.image.image_metadata if article.image else {},
        article.render_metadata,
        article.inline_media,
        article.html_article,
        article.assembled_html,
        article.blogger_post.response_payload if article.blogger_post else {},
    ]
    candidates: list[str] = []
    for value in values:
        candidates.extend(_extract_travel_canonical_urls(value))
    return _dedupe_strings(candidates)


def _repair_source_article_canonical_hero(db, source_article_id: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_article_id": int(source_article_id or 0),
        "status": "not_found",
        "hero_url": "",
        "candidates": [],
    }
    source_article = _get_source_article(db, int(source_article_id or 0))
    if source_article is None:
        return result

    candidates = _collect_source_article_canonical_hero_candidates(source_article)
    result["status"] = "no_canonical_candidate"
    result["candidates"] = candidates
    for candidate in candidates:
        hero_check = _validate_hero_url(candidate)
        if not hero_check.get("ok"):
            continue
        metadata = dict(source_article.render_metadata or {})
        metadata.update(
            {
                "travel_canonical_hero_recovered_at": _utc_now().isoformat(),
                "travel_canonical_hero_url": candidate,
            }
        )
        source_article.render_metadata = metadata
        if source_article.image is None:
            _upsert_image(
                db,
                job_id=int(source_article.job_id),
                article_id=int(source_article.id),
                prompt=source_article.image_collage_prompt or source_article.title,
                file_path=f"travel-canonical-repair://article/{int(source_article.id)}",
                public_url=candidate,
                provider="travel_canonical_repair",
                meta={
                    "width": 1024,
                    "height": 1024,
                    "travel_canonical_repaired": True,
                    "source_article_id": int(source_article.id),
                },
            )
            db.refresh(source_article)
        else:
            image_metadata = dict(source_article.image.image_metadata or {})
            image_metadata.update(
                {
                    "travel_canonical_repaired": True,
                    "travel_canonical_repaired_at": _utc_now().isoformat(),
                    "previous_public_url": source_article.image.public_url,
                }
            )
            source_article.image.public_url = candidate
            source_article.image.provider = source_article.image.provider or "travel_canonical_repair"
            source_article.image.image_metadata = image_metadata
            db.add(source_article.image)
        db.add(source_article)
        db.commit()
        result.update({"status": "repaired", "hero_url": candidate, "hero_check": hero_check})
        return result
    return result


def _resolve_hero_url_for_item(db, *, item: dict[str, Any], travel_sync: dict[str, Any]) -> dict[str, Any]:
    supplied_hero_url = str(item.get("hero_url") or "").strip()
    supplied_policy = _classify_hero_url(supplied_hero_url)
    supplied_check = _validate_hero_url(supplied_hero_url)
    result: dict[str, Any] = {
        "supplied_hero_url": supplied_hero_url,
        "supplied_policy": supplied_policy,
        "supplied_check": supplied_check,
        "resolved_hero_url": "",
        "ok": False,
        "source_repair": None,
    }
    if supplied_check.get("ok"):
        result.update({"ok": True, "resolved_hero_url": supplied_hero_url, "mode": "supplied_canonical"})
        return result

    source_article_id = int(travel_sync.get("source_article_id") or item.get("source_article_id") or 0)
    repair = _repair_source_article_canonical_hero(db, source_article_id)
    result["source_repair"] = repair
    repaired_url = str(repair.get("hero_url") or "").strip()
    if repaired_url:
        repaired_check = _validate_hero_url(repaired_url)
        result["repaired_check"] = repaired_check
        if repaired_check.get("ok"):
            result.update({"ok": True, "resolved_hero_url": repaired_url, "mode": "source_article_repaired"})
            return result

    reason = str(supplied_check.get("error") or supplied_policy.get("reason") or "hero_url_not_usable")
    result.update({"error": reason, "mode": "unresolved"})
    return result


def _validate_live_post(*, url: str, hero_url: str, item: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url, "ok": False, "has_hero": False, "encoding_issues": []}
    if not url:
        result["error"] = "missing_blogger_url"
        return result
    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=25.0,
            headers={"User-Agent": "Mozilla/5.0 Bloggent Travel live audit"},
        )
        text = response.text or ""
        expected_title = str(item.get("title") or "").strip()
        encoding_issues: list[str] = []
        if expected_title and expected_title not in text:
            encoding_issues.append("expected_title_missing")
        target_language = str(item.get("target_language") or "").strip().lower()
        if target_language == "ja" and expected_title and not JAPANESE_TEXT_RE.search(expected_title):
            encoding_issues.append("expected_japanese_title_missing")
        has_hero = bool(hero_url and hero_url in text)
        result.update(
            {
                "status_code": response.status_code,
                "content_length": len(text),
                "has_hero": has_hero,
                "encoding_issues": encoding_issues,
                "ok": response.status_code == 200 and has_hero and not encoding_issues,
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    return result


def _send_publish_notification(db, *, job: Job, article: Article, post: BloggerPost) -> dict[str, Any]:
    try:
        return send_telegram_post_notification(
            db,
            blog_name=job.blog.name if job.blog else f"blogger:{int(job.blog_id)}",
            article_title=article.title,
            post_url=post.published_url,
            post_status=post.post_status.value,
            scheduled_for=post.scheduled_for,
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {"delivery_status": "failed", "error": str(exc)}


def _classify_blogger_api_exception(exc: Exception) -> dict[str, str]:
    message = str(exc)
    lowered = message.lower()
    if "401" in lowered or "unauthorized" in lowered or "invalid_grant" in lowered or "invalid credentials" in lowered:
        return {"status": "oauth_reconnect_required", "reason": message}
    if "429" in lowered or "rate limit" in lowered or "quota" in lowered or "too many requests" in lowered:
        return {"status": "blogger_rate_limited", "reason": message}
    return {"status": "blogger_api_failed", "reason": message}


def _latest_blog_publish_ref(db, blog_id: int) -> datetime | None:
    row = (
        db.execute(
            select(BloggerPost)
            .where(
                BloggerPost.blog_id == blog_id,
                BloggerPost.post_status.in_([PostStatus.PUBLISHED, PostStatus.SCHEDULED]),
            )
            .order_by(
                desc(BloggerPost.published_at),
                desc(BloggerPost.scheduled_for),
                desc(BloggerPost.updated_at),
                desc(BloggerPost.created_at),
                desc(BloggerPost.id),
            )
            .limit(1)
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    candidates = [
        row.published_at,
        row.scheduled_for,
        row.updated_at,
        row.created_at,
    ]
    normalized: list[datetime] = []
    for value in candidates:
        if value is None:
            continue
        normalized.append(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
    return max(normalized) if normalized else None


def _gap_allowed(db, blog_id: int, min_gap_minutes: int) -> tuple[bool, dict[str, Any]]:
    latest = _latest_blog_publish_ref(db, blog_id)
    if latest is None:
        return True, {"latest_publish_ref": None, "minutes_since": None}
    now = _utc_now()
    minutes_since = (now - latest).total_seconds() / 60
    return minutes_since >= min_gap_minutes, {
        "latest_publish_ref": latest.isoformat(),
        "minutes_since": round(minutes_since, 2),
        "min_gap_minutes": min_gap_minutes,
    }


def _get_job(db, job_id: int) -> Job:
    job = (
        db.execute(
            select(Job)
            .where(Job.id == int(job_id))
            .options(
                selectinload(Job.blog),
                selectinload(Job.topic),
                selectinload(Job.article).selectinload(Article.image),
                selectinload(Job.blogger_post),
            )
        )
        .scalars()
        .one_or_none()
    )
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    return job


def _select_one_item_per_travel_blog(db, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen_blog_ids: set[int] = set()
    for item in items:
        job_id = int(item.get("job_id") or 0)
        row = db.execute(select(Job.id, Job.blog_id).where(Job.id == job_id)).one_or_none()
        if row is None:
            selected.append(item)
            continue
        blog_id = int(row.blog_id)
        if blog_id not in TRAVEL_BLOG_IDS:
            selected.append(item)
            continue
        if blog_id in seen_blog_ids:
            skipped.append(
                {
                    "job_id": job_id,
                    "blog_id": blog_id,
                    "status": "skipped",
                    "reason": "duplicate_blog_in_payload",
                    "hero_url": str(item.get("hero_url") or "").strip(),
                }
            )
            continue
        seen_blog_ids.add(blog_id)
        selected.append(item)
    return selected, skipped


def _build_output(item: dict[str, Any]) -> ArticleGenerationOutput:
    return ArticleGenerationOutput(
        title=str(item["title"]).strip(),
        meta_description=str(item["meta_description"]).strip(),
        labels=[str(label).strip() for label in item.get("labels", []) if str(label).strip()],
        slug=str(item["slug"]).strip(),
        excerpt=str(item["excerpt"]).strip(),
        html_article=str(item["html_article"]).strip(),
        faq_section=list(item.get("faq_section") or []),
        image_collage_prompt=str(item["image_collage_prompt"]).strip(),
    )


def _apply_one(
    db,
    *,
    item: dict[str, Any],
    publish: bool,
    min_gap_minutes: int,
    update_existing: bool,
    send_telegram_for_existing: bool,
) -> dict[str, Any]:
    job_id = int(item["job_id"])
    job = _get_job(db, job_id)
    blog_id = int(job.blog_id)
    result: dict[str, Any] = {
        "job_id": job_id,
        "blog_id": blog_id,
        "status": "started",
        "article_id": None,
        "blogger_url": "",
        "telegram_status": None,
        "hero_url": str(item.get("hero_url") or "").strip(),
    }

    if blog_id not in TRAVEL_BLOG_IDS:
        result.update({"status": "skipped", "reason": "not_travel_blog"})
        return result
    if job.status == JobStatus.COMPLETED and not update_existing:
        result.update({"status": "skipped", "reason": "already_completed"})
        if job.blogger_post:
            result["blogger_url"] = job.blogger_post.published_url
        if job.article:
            result["article_id"] = int(job.article.id)
        return result
    allowed_statuses = {JobStatus.PENDING, JobStatus.GENERATING_ARTICLE, JobStatus.PUBLISHING}
    if update_existing:
        allowed_statuses.add(JobStatus.COMPLETED)
    if job.status not in allowed_statuses:
        result.update({"status": "skipped", "reason": f"unsupported_job_status:{job.status.value}"})
        return result

    travel_sync = dict((job.raw_prompts or {}).get("travel_sync") or {})
    if not travel_sync:
        result.update({"status": "skipped", "reason": "missing_travel_sync_prompt"})
        return result

    try:
        _assert_payload_encoding(item)
    except ValueError as exc:
        result.update({"status": "failed", "reason": str(exc)})
        return result

    hero_resolution = _resolve_hero_url_for_item(db, item=item, travel_sync=travel_sync)
    result["hero_resolution"] = hero_resolution
    if not hero_resolution.get("ok"):
        result.update(
            {
                "status": "skipped",
                "reason": str(hero_resolution.get("error") or "source_hero_not_canonical_or_recoverable"),
            }
        )
        return result
    hero_url = str(hero_resolution["resolved_hero_url"])
    result["hero_url"] = hero_url
    item = {**item, "hero_url": hero_url}

    allowed, gap_payload = _gap_allowed(db, blog_id, min_gap_minutes)
    result["gap_check"] = gap_payload
    existing_post_for_gap = job.blogger_post
    existing_article_for_gap = job.article
    can_update_existing_despite_gap = bool(
        update_existing
        and existing_post_for_gap is not None
        and existing_article_for_gap is not None
        and existing_post_for_gap.post_status in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}
    )
    if not allowed and not can_update_existing_despite_gap:
        existing_post = existing_post_for_gap
        existing_article = existing_article_for_gap
        if existing_post is not None and existing_article is not None and existing_post.post_status in {
            PostStatus.PUBLISHED,
            PostStatus.SCHEDULED,
        }:
            slot = db.execute(select(ContentPlanSlot).where(ContentPlanSlot.job_id == job.id)).scalar_one_or_none()
            if slot is not None:
                slot.status = "published"
                slot.article_id = int(existing_article.id)
                slot.last_run_at = _utc_now()
                slot.result_payload = {
                    **dict(slot.result_payload or {}),
                    "blogger_url": existing_post.published_url,
                    "post_status": existing_post.post_status.value,
                    "finalized_existing_post": True,
                    "gap_check_bypassed_for_existing_post": True,
                }
                db.add(slot)
                db.commit()
            if not update_existing:
                telegram_result = {"delivery_status": "skipped_existing_post"}
                if send_telegram_for_existing:
                    telegram_result = _send_publish_notification(
                        db,
                        job=job,
                        article=existing_article,
                        post=existing_post,
                    )
                    merge_response(db, job, "telegram_retry", telegram_result)
                live_check = _validate_live_post(
                    url=existing_post.published_url,
                    hero_url=hero_url,
                    item=item,
                )
                set_status(
                    db,
                    job,
                    JobStatus.COMPLETED,
                    "Travel sync article finalized from existing Blogger post after previous publish.",
                    {
                        "article_id": int(existing_article.id),
                        "blogger_url": existing_post.published_url,
                        "hero_url": hero_url,
                    },
                )
                result.update(
                    {
                        "status": "published",
                        "article_id": int(existing_article.id),
                        "blogger_post_id": int(existing_post.id),
                        "remote_post_id": existing_post.blogger_post_id,
                        "blogger_url": existing_post.published_url,
                        "telegram_status": telegram_result.get("delivery_status"),
                        "telegram": telegram_result,
                        "live_check": live_check,
                    }
                )
                if not live_check.get("ok"):
                    result["status"] = "live_validation_failed"
                elif send_telegram_for_existing and telegram_result.get("delivery_status") != "sent":
                    result["status"] = "telegram_retry_required"
                return result
        result.update({"status": "skipped", "reason": "blog_gap_not_elapsed"})
        return result

    hero_check = _validate_hero_url(hero_url)
    result["hero_check"] = hero_check
    if not hero_check.get("ok"):
        result.update({"status": "failed", "reason": str(hero_check.get("error") or "hero_url_not_200")})
        return result

    output = _build_output(item)
    merge_prompt(
        db,
        job,
        "codex_app_thread_payload",
        {
            "generated_at": _utc_now().isoformat(),
            "generator": "codex_desktop_thread",
            "source_article_id": travel_sync.get("source_article_id"),
            "source_language": travel_sync.get("source_language"),
            "target_language": travel_sync.get("target_language"),
        },
    )
    set_status(db, job, JobStatus.GENERATING_ARTICLE, "Travel article JSON generated by Codex desktop thread.")
    merge_response(db, job, "article_generation", output.model_dump())

    article = save_article(db, job=job, topic=job.topic, output=output)
    db.refresh(article)
    saved_item = {
        **item,
        "title": article.title,
        "meta_description": article.meta_description,
        "excerpt": article.excerpt,
        "html_article": article.html_article,
        "labels": list(article.labels or []),
        "faq_section": list(article.faq_section or []),
        "image_collage_prompt": article.image_collage_prompt,
    }
    saved_issues = _detect_encoding_issues(item=saved_item)
    if saved_issues:
        set_status(
            db,
            job,
            JobStatus.PENDING,
            "Travel article failed DB encoding gate; job left pending for repair.",
            {"encoding_issues": saved_issues},
        )
        result.update({"status": "failed", "reason": f"db_encoding_gate_failed:{','.join(saved_issues)}"})
        return result
    article.inline_media = []
    render_metadata = dict(article.render_metadata or {})
    render_metadata.update(
        {
            "travel_app_thread_generated": True,
            "travel_sync_source_article_id": int(travel_sync.get("source_article_id") or 0) or None,
            "travel_sync_source_blog_id": int(travel_sync.get("source_blog_id") or 0) or None,
            "travel_sync_source_language": str(travel_sync.get("source_language") or "").strip().lower() or None,
            "travel_sync_target_language": str(travel_sync.get("target_language") or "").strip().lower() or None,
            "travel_sync_group_key": str(travel_sync.get("group_key") or "").strip() or None,
            "hero_reuse_url": hero_url,
        }
    )
    article.render_metadata = render_metadata
    db.add(article)
    db.commit()
    db.refresh(article)

    image = _upsert_image(
        db,
        job_id=job.id,
        article_id=article.id,
        prompt=output.image_collage_prompt,
        file_path=f"travel-sync-source://article/{travel_sync.get('source_article_id')}",
        public_url=hero_url,
        provider="travel_source_reuse",
        meta={
            "width": 1024,
            "height": 1024,
            "travel_sync_reused": True,
            "source_article_id": int(travel_sync.get("source_article_id") or 0) or None,
            "source_blog_id": int(travel_sync.get("source_blog_id") or 0) or None,
            "target_blog_id": blog_id,
        },
    )
    db.refresh(article)
    labels = ensure_article_editorial_labels(db, article)
    article.assembled_html = assemble_article_html(article, hero_url, related_posts=[])
    db.add(article)
    db.commit()
    db.refresh(article)
    merge_response(
        db,
        job,
        "html_assembly",
        {
            "mode": "codex_app_thread",
            "hero_url": hero_url,
            "image_id": int(image.id),
            "contains_img": "<img" in (article.assembled_html or "").lower(),
        },
    )

    slot = db.execute(select(ContentPlanSlot).where(ContentPlanSlot.job_id == job.id)).scalar_one_or_none()
    if slot is not None:
        slot.article_id = article.id
        slot.status = "generated"
        slot.last_run_at = _utc_now()
        slot.result_payload = {
            **dict(slot.result_payload or {}),
            "article_id": int(article.id),
            "job_id": int(job.id),
            "hero_url": hero_url,
            "generated_by": "codex_app_thread",
        }
        db.add(slot)
        db.commit()

    result["article_id"] = int(article.id)
    if not publish:
        set_status(db, job, JobStatus.PENDING, "Travel article saved by app thread; publish disabled.")
        result.update({"status": "saved", "labels": labels})
        return result

    existing_post = job.blogger_post
    if existing_post is not None and existing_post.post_status in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
        if update_existing:
            set_status(db, job, JobStatus.PUBLISHING, "Updating existing Travel Blogger post from Codex desktop thread.")
            try:
                provider = get_blogger_provider(db, job.blog)
                summary, raw_payload = provider.update_post(
                    post_id=existing_post.blogger_post_id,
                    title=article.title,
                    content=article.assembled_html or article.html_article,
                    labels=labels,
                    meta_description=article.meta_description,
                )
            except Exception as exc:  # noqa: BLE001
                api_error = _classify_blogger_api_exception(exc)
                set_status(
                    db,
                    job,
                    JobStatus.PENDING,
                    "Travel existing post update failed; job left pending for retry.",
                    {"error": api_error["reason"], "blog_id": blog_id, "api_error_status": api_error["status"]},
                )
                result.update({"status": api_error["status"], "reason": api_error["reason"], "operation": "update"})
                return result
            blogger_post = _upsert_blogger_post(
                db,
                job_id=job.id,
                blog_id=blog_id,
                article_id=article.id,
                summary=summary,
                raw_payload=raw_payload,
            )
            merge_response(db, job, "publishing_update", {"summary": summary, "raw_payload": raw_payload})
            set_status(
                db,
                job,
                JobStatus.COMPLETED,
                "Travel sync article updated on existing Blogger post.",
                {"article_id": int(article.id), "blogger_url": summary.get("url", ""), "hero_url": hero_url},
            )
            try:
                sync_report = sync_blogger_posts_for_blog(db, job.blog)
            except Exception as exc:  # noqa: BLE001
                sync_report = {"status": "failed", "error": str(exc)}
            live_check = _validate_live_post(url=summary.get("url", ""), hero_url=hero_url, item=item)
            telegram_result = {"delivery_status": "skipped_update_existing"}
            if send_telegram_for_existing:
                telegram_result = _send_publish_notification(db, job=job, article=article, post=blogger_post)
                merge_response(db, job, "telegram_retry", telegram_result)
            result.update(
                {
                    "status": "updated",
                    "blogger_post_id": int(blogger_post.id),
                    "remote_post_id": blogger_post.blogger_post_id,
                    "blogger_url": summary.get("url", ""),
                    "labels": labels,
                    "telegram_status": telegram_result.get("delivery_status"),
                    "telegram": telegram_result,
                    "sync_report": sync_report,
                    "live_check": live_check,
                }
            )
            if not live_check.get("ok"):
                result["status"] = "live_validation_failed"
            elif send_telegram_for_existing and telegram_result.get("delivery_status") != "sent":
                result["status"] = "telegram_retry_required"
            return result
        if slot is not None:
            slot.status = "published"
            slot.article_id = article.id
            slot.last_run_at = _utc_now()
            slot.result_payload = {
                **dict(slot.result_payload or {}),
                "blogger_url": existing_post.published_url,
                "post_status": existing_post.post_status.value,
                "finalized_existing_post": True,
            }
            db.add(slot)
            db.commit()
        set_status(
            db,
            job,
            JobStatus.COMPLETED,
            "Travel sync article finalized from existing Blogger post.",
            {"article_id": int(article.id), "blogger_url": existing_post.published_url, "hero_url": hero_url},
        )
        try:
            sync_report = sync_blogger_posts_for_blog(db, job.blog)
        except Exception as exc:  # noqa: BLE001
            sync_report = {"status": "failed", "error": str(exc)}
        telegram_result = {"delivery_status": "skipped_existing_post"}
        if send_telegram_for_existing:
            telegram_result = _send_publish_notification(db, job=job, article=article, post=existing_post)
            merge_response(db, job, "telegram_retry", telegram_result)
        live_check = _validate_live_post(url=existing_post.published_url, hero_url=hero_url, item=item)
        result.update(
            {
                "status": "published",
                "blogger_post_id": int(existing_post.id),
                "remote_post_id": existing_post.blogger_post_id,
                "blogger_url": existing_post.published_url,
                "labels": labels,
                "telegram_status": telegram_result.get("delivery_status"),
                "telegram": telegram_result,
                "sync_report": sync_report,
                "live_check": live_check,
            }
        )
        if not live_check.get("ok"):
            result["status"] = "live_validation_failed"
        elif send_telegram_for_existing and telegram_result.get("delivery_status") != "sent":
            result["status"] = "telegram_retry_required"
        return result

    set_status(db, job, JobStatus.PUBLISHING, "Publishing Travel article from Codex desktop thread.")
    try:
        provider = get_blogger_provider(db, job.blog)
        summary, raw_payload = provider.publish(
            title=article.title,
            content=article.assembled_html or article.html_article,
            labels=labels,
            meta_description=article.meta_description,
            slug=article.slug,
            publish_mode=PublishMode.PUBLISH,
        )
    except Exception as exc:  # noqa: BLE001 - keep job retryable for OAuth-only failures.
        api_error = _classify_blogger_api_exception(exc)
        set_status(
            db,
            job,
            JobStatus.PENDING,
            "Travel publish failed; job left pending for retry.",
            {"error": api_error["reason"], "blog_id": blog_id, "api_error_status": api_error["status"]},
        )
        result.update({"status": api_error["status"], "reason": api_error["reason"], "operation": "publish"})
        return result

    blogger_post = _upsert_blogger_post(
        db,
        job_id=job.id,
        blog_id=blog_id,
        article_id=article.id,
        summary=summary,
        raw_payload=raw_payload,
    )
    merge_response(db, job, "publishing", {"summary": summary, "raw_payload": raw_payload})

    telegram_result = _send_publish_notification(db, job=job, article=article, post=blogger_post)
    merge_response(db, job, "telegram", telegram_result)

    if slot is not None:
        slot.status = "published"
        slot.article_id = article.id
        slot.last_run_at = _utc_now()
        slot.result_payload = {
            **dict(slot.result_payload or {}),
            "blogger_url": summary.get("url", ""),
            "post_status": summary.get("postStatus", ""),
            "telegram": telegram_result,
        }
        db.add(slot)
        db.commit()

    set_status(
        db,
        job,
        JobStatus.COMPLETED,
        "Travel sync article published by Codex desktop thread.",
        {"article_id": int(article.id), "blogger_url": summary.get("url", ""), "hero_url": hero_url},
    )

    try:
        sync_report = sync_blogger_posts_for_blog(db, job.blog)
    except Exception as exc:  # noqa: BLE001 - publishing succeeded; sync failure is report-only.
        sync_report = {"status": "failed", "error": str(exc)}
    live_check = _validate_live_post(url=summary.get("url", ""), hero_url=hero_url, item=item)

    result.update(
        {
            "status": "published",
            "blogger_post_id": int(blogger_post.id),
            "remote_post_id": blogger_post.blogger_post_id,
            "blogger_url": summary.get("url", ""),
            "labels": labels,
            "telegram_status": telegram_result.get("delivery_status"),
            "telegram": telegram_result,
            "sync_report": sync_report,
            "live_check": live_check,
        }
    )
    if not live_check.get("ok"):
        result["status"] = "live_validation_failed"
    elif telegram_result.get("delivery_status") != "sent":
        result["status"] = "telegram_retry_required"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Codex desktop-generated Travel sync article payloads.")
    parser.add_argument("--payload-file", required=True)
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-app-thread-apply")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--update-existing", action="store_true")
    parser.add_argument("--send-telegram-for-existing", action="store_true")
    parser.add_argument("--min-gap-minutes", type=int, default=5)
    parser.add_argument(
        "--write-report-file",
        action="store_true",
        help="Write a JSON report file under report-root. Default is DB-only.",
    )
    args = parser.parse_args()

    report_root = Path(args.report_root)
    items = _load_payload(Path(args.payload_file))
    report: dict[str, Any] = {
        "generated_at": _utc_now().isoformat(),
        "payload_file": str(Path(args.payload_file)),
        "publish": bool(args.publish),
        "update_existing": bool(args.update_existing),
        "send_telegram_for_existing": bool(args.send_telegram_for_existing),
        "min_gap_minutes": int(args.min_gap_minutes),
        "items_requested": len(items),
        "items_selected": 0,
        "results": [],
        "translation_state": None,
    }

    with SessionLocal() as db:
        items, pre_skipped_results = _select_one_item_per_travel_blog(db, items)
        report["items_selected"] = len(items)
        report["results"].extend(pre_skipped_results)
        processed_blog_ids: set[int] = set()
        for item in items:
            try:
                result = _apply_one(
                    db,
                    item=item,
                    publish=bool(args.publish),
                    min_gap_minutes=int(args.min_gap_minutes),
                    update_existing=bool(args.update_existing),
                    send_telegram_for_existing=bool(args.send_telegram_for_existing),
                )
                if int(result.get("blog_id") or 0) in TRAVEL_BLOG_IDS:
                    processed_blog_ids.add(int(result["blog_id"]))
            except Exception as exc:  # noqa: BLE001 - keep per-job error visible and continue other blogs.
                result = {
                    "job_id": item.get("job_id"),
                    "blog_id": item.get("target_blog_id"),
                    "status": "failed",
                    "reason": str(exc),
                    "hero_url": item.get("hero_url", ""),
                }
            report["results"].append(result)

        if processed_blog_ids:
            try:
                report["translation_state"] = refresh_travel_translation_state(
                    db,
                    blog_ids=(34, 36, 37),
                    report_root=report_root,
                    write_report=False,
                )
            except Exception as exc:  # noqa: BLE001
                report["translation_state"] = {"status": "failed", "error": str(exc)}

    counts: dict[str, int] = {}
    for result in report["results"]:
        status = str(result.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    report["status_counts"] = counts

    with SessionLocal() as db:
        audit_log = _write_db_report(db, report)
    report_path = ""
    if bool(args.write_report_file):
        path = _report_path(report_root, args.report_prefix)
        _write_json(path, report)
        report_path = str(path)
    print(
        json.dumps(
            {
                "audit_log_id": int(audit_log.id),
                "report_path": report_path,
                "status_counts": counts,
                "results": report["results"],
            },
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

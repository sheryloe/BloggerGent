from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import html
import re
from typing import Any
from zoneinfo import ZoneInfo

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AnalyticsArticleFact, Article, SyncedBloggerPost, WorkflowStageType
from app.services.ops.analytics_service import get_blog_monthly_articles, rebuild_blog_month_rollup
from app.services.content.article_service import canonicalize_editorial_labels, estimate_reading_time, sanitize_blog_html
from app.services.platform.blog_service import ensure_blog_workflow_steps, get_blog, get_workflow_step, render_agent_prompt
from app.services.blogger.blogger_editor_service import BloggerEditorAutomationError, sync_blogger_post_search_description
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog
from app.services.content.content_ops_service import compute_seo_geo_scores
from app.services.content.html_assembler import assemble_article_html
from app.services.content.related_posts import find_related_articles
from app.services.ops.lighthouse_service import LighthouseAuditError, run_lighthouse_audit
from app.services.ops.model_policy_service import CODEX_TEXT_RUNTIME_MODEL
from app.services.providers.codex_cli import CodexCLITextProvider
from app.services.providers.factory import get_blogger_provider, get_runtime_config
from app.services.integrations.telegram_service import send_telegram_post_notification

DEFAULT_TIMEZONE = "Asia/Seoul"
IMG_SRC_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
FIGURE_RE = re.compile(r"(?is)<figure\b[^>]*>.*?</figure>")
IMG_RE = re.compile(r"(?is)<img\b[^>]*>")


def _current_month(*, timezone_name: str) -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    return datetime.now(tz).strftime("%Y-%m")


def _score_below(value: float | None, threshold: float) -> bool:
    if value is None:
        return True
    try:
        return float(value) < float(threshold)
    except (TypeError, ValueError):
        return True


def _extract_image_urls(content_html: str | None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in IMG_SRC_RE.finditer(str(content_html or "")):
        candidate = html.unescape(str(match.group(1) or "").strip())
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _split_cover_and_inline(content_html: str | None, thumbnail_url: str | None) -> tuple[str | None, list[str]]:
    image_urls = _extract_image_urls(content_html)
    if not image_urls and str(thumbnail_url or "").strip():
        return str(thumbnail_url or "").strip(), []
    if not image_urls:
        return None, []
    return image_urls[0], [url for url in image_urls[1:] if url and url != image_urls[0]]


def _strip_generated_body_images(body_html: str | None) -> str:
    cleaned = FIGURE_RE.sub("", str(body_html or ""))
    cleaned = IMG_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _restore_inline_images(body_html: str, image_urls: list[str], *, title: str) -> str:
    if not image_urls:
        return body_html
    figures = "".join(
        (
            '<figure data-bloggent-restore-slot="inline">'
            f'<img src="{html.escape(url, quote=True)}" alt="{html.escape(title, quote=True)}" loading="lazy" decoding="async" />'
            "</figure>"
        )
        for url in image_urls
        if str(url or "").strip()
    )
    if not figures:
        return body_html
    marker = "<!--RELATED_POSTS-->"
    if marker in body_html:
        return body_html.replace(marker, f"{figures}{marker}", 1)
    return f"{body_html}\n{figures}".strip()


def _blogger_refactor_persona_lines(blog: Any) -> list[str]:
    name = str(getattr(blog, "name", "") or "").strip()
    normalized_name = name.casefold()
    primary_language = str(getattr(blog, "primary_language", "") or "").strip().casefold()

    if "midnight" in normalized_name:
        return [
            "- Write only in English. Do not leak Korean UI text, Korean FAQ text, or multilingual boilerplate.",
            "- Persona: a veteran English-language mystery feature writer who separates records, clues, interpretations, and current trace status clearly.",
            "- Keep the body atmospheric but factual. Do not append visible audit notes, compliance notes, or a separate source boilerplate block unless the case truly needs one brief note.",
        ]
    if primary_language.startswith("es"):
        return [
            "- Write only in natural Spanish. No English fallback in headings, FAQ, buttons, or transitional phrases.",
            "- Persona: a seasoned travel writer and Korean-culture fan guiding readers through places with local detail, movement flow, and scene-setting.",
            "- Keep the tone warm, specific, and blog-like. Use concise paragraphs, route logic, and practical decision points instead of memo language.",
        ]
    if primary_language.startswith("ja"):
        return [
            "- Write only in natural Japanese. No English fallback in headings, FAQ, buttons, or transitional phrases.",
            "- Persona: a Korean-Japanese couple local guide who explains Korean neighborhoods with lived detail, pacing, and practical reassurance.",
            "- Keep the prose easy to follow on mobile, with concrete route steps, local context, and calm on-site tips.",
        ]
    return [
        "- Write only in English.",
        "- Persona: a veteran travel-and-history blogger covering Korea with local route knowledge and cultural context.",
        "- Keep the piece readable and specific: strong opening, grounded place detail, and clear visit decisions rather than generic listicles.",
    ]


def _build_context(blog: Any, post: SyncedBloggerPost, row: Any, threshold: float) -> str:
    snapshot = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(post.content_html or ""))).strip()
    if len(snapshot) > 8000:
        snapshot = f"{snapshot[:8000].rstrip()} ...[truncated]"
    lines = [
        "[Refactor context]",
        "- This is an existing published Blogger post rewrite.",
        "- Keep the same topic and user intent, but rewrite the article from scratch with a stronger blog voice and better on-page clarity.",
        "- Do not mention scores, refactor instructions, or internal evaluation in the visible article.",
        f"- Target threshold: SEO/GEO/CTR should aim for {threshold:.0f}+ where content can influence them.",
        f"- Existing title: {post.title}",
        f"- Existing public URL: {post.url or ''}",
        f"- Current scores: SEO={getattr(row, 'seo_score', None)}, GEO={getattr(row, 'geo_score', None)}, CTR={getattr(row, 'ctr_score', None)}, Lighthouse={getattr(row, 'lighthouse_score', None)}",
        "- Existing images will be reused by the system. Do not add image tags.",
        "- The HTML assembler will handle localized FAQ and related-post UI. Keep visible body copy clean and fully in the target language.",
        "- Favor blog rhythm over flat paragraphs: strong lead, clear section purpose, practical lists or comparison blocks where helpful, and a natural closing.",
        *_blogger_refactor_persona_lines(blog),
        "",
        "[Existing snapshot for context only]",
        snapshot,
    ]
    return "\n".join(lines).strip()


def _build_temp_article(
    *,
    blog: Any,
    title: str,
    meta_description: str,
    excerpt: str,
    labels: list[str],
    body_html: str,
    faq_section: list[dict[str, Any]],
    editorial_category_key: str | None,
    editorial_category_label: str | None,
) -> Article:
    article = Article(
        job_id=0,
        blog_id=blog.id,
        title=title,
        meta_description=meta_description,
        labels=labels,
        slug=slugify(title) or "refactor",
        excerpt=excerpt,
        html_article=body_html,
        faq_section=faq_section,
        image_collage_prompt="reused-existing-image",
        editorial_category_key=editorial_category_key,
        editorial_category_label=editorial_category_label,
        inline_media=[],
        assembled_html=None,
        reading_time_minutes=estimate_reading_time(body_html),
    )
    try:
        article.blog = blog
    except Exception:  # noqa: BLE001
        article.__dict__["blog"] = blog
    return article


def _generate_one(candidate: dict[str, Any], *, runtime: Any, threshold: float) -> dict[str, Any]:
    provider = CodexCLITextProvider(runtime=runtime, model=CODEX_TEXT_RUNTIME_MODEL)
    prompt = str(candidate["prompt"])
    last_scores: dict[str, Any] = {}
    last_output = None
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, 3):
        last_output, _raw = provider.generate_article(str(candidate["title"]), prompt)
        last_scores = compute_seo_geo_scores(
            title=last_output.title,
            html_body=last_output.html_article,
            excerpt=last_output.excerpt,
            faq_section=[
                item.model_dump() if hasattr(item, "model_dump") else dict(item)
                for item in (last_output.faq_section or [])
                if isinstance(item, dict) or hasattr(item, "model_dump")
            ],
        )
        passed = not any(
            (
                _score_below(last_scores.get("seo_score"), threshold),
                _score_below(last_scores.get("geo_score"), threshold),
                _score_below(last_scores.get("ctr_score"), threshold),
            )
        )
        attempts.append(
            {
                "attempt": attempt,
                "seo_score": last_scores.get("seo_score"),
                "geo_score": last_scores.get("geo_score"),
                "ctr_score": last_scores.get("ctr_score"),
                "passed": passed,
            }
        )
        if passed or attempt >= 2:
            break
        prompt = (
            f"{candidate['prompt']}\n\n"
            "[Rewrite retry]\n"
            f"- Previous draft is still below target. Current predicted scores: SEO={last_scores.get('seo_score')}, GEO={last_scores.get('geo_score')}, CTR={last_scores.get('ctr_score')}.\n"
            f"- Rewrite again so SEO, GEO, and CTR each clear {threshold:.0f}+ if the content can improve them.\n"
            "- Strengthen specificity, heading clarity, structure, and actionable depth.\n"
        )
    return {
        "candidate": candidate,
        "output": last_output,
        "predicted_scores": last_scores,
        "quality_attempts": attempts,
    }


def _update_synced_fact(
    db: Session,
    *,
    synced_post: SyncedBloggerPost,
    updated_title: str,
    predicted_scores: dict[str, Any],
    lighthouse_scores: dict[str, Any] | None,
    article_pattern_id: str | None,
    article_pattern_version: int | None,
) -> str | None:
    if synced_post.published_at is None:
        return None
    month = synced_post.published_at.strftime("%Y-%m")
    facts = (
        db.execute(
            select(AnalyticsArticleFact).where(
                AnalyticsArticleFact.blog_id == synced_post.blog_id,
                AnalyticsArticleFact.month == month,
                AnalyticsArticleFact.synced_post_id == synced_post.id,
            )
        )
        .scalars()
        .all()
    )
    for fact in facts:
        fact.title = updated_title
        fact.actual_url = synced_post.url or fact.actual_url
        fact.status = synced_post.status or fact.status
        fact.seo_score = predicted_scores.get("seo_score")
        fact.geo_score = predicted_scores.get("geo_score")
        if article_pattern_id:
            fact.article_pattern_id = article_pattern_id
        if isinstance(article_pattern_version, int):
            fact.article_pattern_version = article_pattern_version
        if lighthouse_scores:
            fact.lighthouse_score = lighthouse_scores.get("lighthouse_score")
            fact.lighthouse_accessibility_score = lighthouse_scores.get("accessibility_score")
            fact.lighthouse_best_practices_score = lighthouse_scores.get("best_practices_score")
            fact.lighthouse_seo_score = lighthouse_scores.get("seo_score")
        db.add(fact)
    return month


def refactor_blogger_low_score_posts(
    db: Session,
    *,
    blog_id: int,
    execute: bool = False,
    threshold: float = 80.0,
    month: str | None = None,
    remote_post_ids: list[str] | None = None,
    limit: int | None = None,
    sync_before: bool = True,
    run_lighthouse: bool = True,
    send_telegram: bool = False,
    parallel_workers: int = 1,
) -> dict[str, Any]:
    blog = get_blog(db, blog_id)
    if blog is None:
        raise LookupError("Blog not found")
    if not (blog.blogger_blog_id or "").strip():
        raise ValueError("Blogger blog id is not configured.")

    blog = ensure_blog_workflow_steps(db, blog)
    article_step = get_workflow_step(blog, WorkflowStageType.ARTICLE_GENERATION)
    if article_step is None:
        raise ValueError("Article generation workflow step is not configured.")

    normalized_threshold = max(min(float(threshold), 100.0), 0.0)
    normalized_month = str(month or "").strip() or _current_month(timezone_name=DEFAULT_TIMEZONE)
    normalized_remote_post_ids = {str(item or "").strip() for item in (remote_post_ids or []) if str(item or "").strip()}
    safe_limit = max(int(limit), 1) if limit is not None else None

    sync_before_result: dict[str, Any] | None = None
    if sync_before:
        sync_before_result = sync_blogger_posts_for_blog(db, blog)

    report = get_blog_monthly_articles(
        db,
        blog_id=blog.id,
        month=None if normalized_remote_post_ids else normalized_month,
        status="published",
        page=1,
        page_size=max(safe_limit or 1000, 1000),
    )
    items = list(report.items or [])
    synced_ids = {int(item.synced_post_id) for item in items if item.synced_post_id is not None}
    synced_posts = {
        post.id: post
        for post in (
            db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.id.in_(list(synced_ids)))).scalars().all()
            if synced_ids
            else []
        )
    }

    candidates: list[dict[str, Any]] = []
    for row in items:
        if str(row.status or "").strip().lower() not in {"published", "live"}:
            continue
        if row.synced_post_id is None:
            continue
        if not any(
            (
                _score_below(row.seo_score, normalized_threshold),
                _score_below(row.geo_score, normalized_threshold),
                _score_below(row.ctr_score, normalized_threshold),
                _score_below(row.lighthouse_score, normalized_threshold),
            )
        ):
            continue
        synced_post = synced_posts.get(int(row.synced_post_id))
        if synced_post is None:
            continue
        editorial_key, editorial_label, _labels = canonicalize_editorial_labels(
            profile_key=str(getattr(blog, "profile_key", "") or ""),
            primary_language=str(getattr(blog, "primary_language", "") or ""),
            editorial_category_key=None,
            editorial_category_label=None,
            labels=list(synced_post.labels or []),
            title=synced_post.title,
            summary=synced_post.excerpt_text,
        )
        prompt = render_agent_prompt(
            db,
            blog,
            article_step,
            keyword=synced_post.title or "",
            title=synced_post.title or "",
            summary=synced_post.excerpt_text or "",
            planner_brief=_build_context(blog, synced_post, row, normalized_threshold),
            editorial_category_key=editorial_key or "",
            editorial_category_label=editorial_label or "",
            editorial_category_guidance="",
        )
        cover_image_url, inline_image_urls = _split_cover_and_inline(synced_post.content_html, synced_post.thumbnail_url)
        candidates.append(
            {
                "fact_id": int(row.id),
                "synced_post_id": int(synced_post.id),
                "remote_post_id": str(synced_post.remote_post_id or "").strip(),
                "title": synced_post.title,
                "url": synced_post.url,
                "published_at": row.published_at,
                "seo_score": row.seo_score,
                "geo_score": row.geo_score,
                "ctr": row.ctr,
                "ctr_score": row.ctr_score,
                "lighthouse_score": row.lighthouse_score,
                "labels": list(synced_post.labels or []),
                "editorial_category_key": editorial_key,
                "editorial_category_label": editorial_label,
                "prompt": prompt,
                "cover_image_url": cover_image_url,
                "inline_image_urls": inline_image_urls,
            }
        )
    if normalized_remote_post_ids:
        candidates = [
            candidate
            for candidate in candidates
            if str(candidate.get("remote_post_id") or "").strip() in normalized_remote_post_ids
        ]

    candidates.sort(
        key=lambda item: (
            min(
                [
                    value
                    for value in (
                        item.get("seo_score"),
                        item.get("geo_score"),
                        item.get("ctr_score"),
                        item.get("lighthouse_score"),
                    )
                    if isinstance(value, (int, float))
                ]
                or [999.0]
            ),
            str(item.get("published_at") or ""),
            str(item.get("title") or "").casefold(),
        )
    )
    total_candidates = len(candidates)
    if safe_limit is not None:
        candidates = candidates[:safe_limit]

    if not execute:
        return {
            "status": "ok",
            "execute": False,
            "blog_id": blog.id,
            "blog_name": blog.name,
            "threshold": normalized_threshold,
            "month": normalized_month,
            "parallel_workers": max(int(parallel_workers or 1), 1),
            "task_id": None,
            "total_candidates": total_candidates,
            "processed_count": len(candidates),
            "updated_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "sync_before_result": sync_before_result,
            "sync_after_result": None,
            "summary_after": None,
            "items": [
                {
                    **candidate,
                    "refactor_candidate": True,
                    "action": "dry_run",
                    "updated_title": None,
                    "updated_url": None,
                    "predicted_seo_score": None,
                    "predicted_geo_score": None,
                    "predicted_ctr_score": None,
                    "lighthouse_after": None,
                    "article_pattern_id": None,
                    "article_pattern_version": None,
                    "quality_gate": None,
                    "search_description_sync": None,
                    "telegram": None,
                    "error": None,
                }
                for candidate in candidates
            ],
        }

    runtime = get_runtime_config(db)
    drafts: dict[int, dict[str, Any]] = {}
    draft_errors: dict[int, str] = {}
    worker_count = max(int(parallel_workers or 1), 1)
    if worker_count == 1 or len(candidates) <= 1:
        for candidate in candidates:
            try:
                drafts[int(candidate["synced_post_id"])] = _generate_one(candidate, runtime=runtime, threshold=normalized_threshold)
            except Exception as exc:  # noqa: BLE001
                draft_errors[int(candidate["synced_post_id"])] = str(exc)
    else:
        with ThreadPoolExecutor(max_workers=min(worker_count, len(candidates))) as executor:
            futures = {
                executor.submit(_generate_one, candidate, runtime=runtime, threshold=normalized_threshold): candidate
                for candidate in candidates
            }
            for future in as_completed(futures):
                candidate = futures[future]
                try:
                    drafts[int(candidate["synced_post_id"])] = future.result()
                except Exception as exc:  # noqa: BLE001
                    draft_errors[int(candidate["synced_post_id"])] = str(exc)

    provider = get_blogger_provider(db, blog)
    updated_remote_ids: list[str] = []
    updated_meta: dict[str, dict[str, Any]] = {}
    result_items: list[dict[str, Any]] = []
    updated_count = 0
    failed_count = 0

    for candidate in candidates:
        synced_post_id = int(candidate["synced_post_id"])
        if synced_post_id in draft_errors:
            failed_count += 1
            result_items.append(
                {
                    **candidate,
                    "refactor_candidate": True,
                    "action": "failed",
                    "updated_title": None,
                    "updated_url": None,
                    "predicted_seo_score": None,
                    "predicted_geo_score": None,
                    "predicted_ctr_score": None,
                    "lighthouse_after": None,
                    "article_pattern_id": None,
                    "article_pattern_version": None,
                    "quality_gate": None,
                    "search_description_sync": None,
                    "telegram": None,
                    "error": draft_errors[synced_post_id],
                }
            )
            continue

        draft = drafts.get(synced_post_id)
        if draft is None:
            failed_count += 1
            result_items.append(
                {
                    **candidate,
                    "refactor_candidate": True,
                    "action": "failed",
                    "updated_title": None,
                    "updated_url": None,
                    "predicted_seo_score": None,
                    "predicted_geo_score": None,
                    "predicted_ctr_score": None,
                    "lighthouse_after": None,
                    "article_pattern_id": None,
                    "article_pattern_version": None,
                    "quality_gate": None,
                    "search_description_sync": None,
                    "telegram": None,
                    "error": "draft_missing",
                }
            )
            continue

        output = draft["output"]
        predicted_scores = dict(draft.get("predicted_scores") or {})
        try:
            editorial_key, editorial_label, resolved_labels = canonicalize_editorial_labels(
                profile_key=str(getattr(blog, "profile_key", "") or ""),
                primary_language=str(getattr(blog, "primary_language", "") or ""),
                editorial_category_key=str(candidate.get("editorial_category_key") or "").strip() or None,
                editorial_category_label=str(candidate.get("editorial_category_label") or "").strip() or None,
                labels=list(output.labels or []),
                title=output.title,
                summary=output.excerpt,
            )
            faq_section = [
                item.model_dump() if hasattr(item, "model_dump") else dict(item)
                for item in (output.faq_section or [])
                if isinstance(item, dict) or hasattr(item, "model_dump")
            ]
            body_html = sanitize_blog_html(_strip_generated_body_images(output.html_article))
            body_html = _restore_inline_images(
                body_html,
                list(candidate.get("inline_image_urls") or []),
                title=output.title,
            )
            temp_article = _build_temp_article(
                blog=blog,
                title=output.title,
                meta_description=output.meta_description,
                excerpt=output.excerpt,
                labels=resolved_labels,
                body_html=body_html,
                faq_section=faq_section,
                editorial_category_key=editorial_key,
                editorial_category_label=editorial_label,
            )
            try:
                related_posts = find_related_articles(db, temp_article, limit=3)
            except Exception:  # noqa: BLE001
                related_posts = []
            assembled_html = assemble_article_html(
                temp_article,
                str(candidate.get("cover_image_url") or ""),
                related_posts=related_posts,
            )
            summary, raw_payload = provider.update_post(
                post_id=str(candidate["remote_post_id"]),
                title=output.title,
                content=assembled_html,
                labels=resolved_labels,
                meta_description=output.meta_description,
            )
            updated_url = str(summary.get("url") or candidate.get("url") or "").strip() or None

            search_description_sync = None
            try:
                sync_result = sync_blogger_post_search_description(
                    db,
                    blogger_blog_id=str(blog.blogger_blog_id or ""),
                    blogger_post_id=str(candidate["remote_post_id"]),
                    description=output.meta_description,
                )
                search_description_sync = {
                    "status": sync_result.status,
                    "message": sync_result.message,
                    "editor_url": sync_result.editor_url,
                }
            except BloggerEditorAutomationError as exc:
                search_description_sync = {"status": "skipped", "message": exc.message}

            lighthouse_after = None
            if run_lighthouse and updated_url:
                try:
                    lighthouse_result = run_lighthouse_audit(updated_url)
                    lighthouse_after = {"status": "ok", **dict(lighthouse_result.get("scores") or {})}
                except LighthouseAuditError as exc:
                    lighthouse_after = {"status": "failed", "error": str(exc)}

            telegram = None
            if send_telegram and updated_url:
                telegram = send_telegram_post_notification(
                    db,
                    blog_name=blog.name,
                    article_title=output.title,
                    post_url=updated_url,
                    post_status="published",
                )

            updated_remote_ids.append(str(candidate["remote_post_id"]))
            updated_meta[str(candidate["remote_post_id"])] = {
                "predicted_scores": predicted_scores,
                "lighthouse_after": lighthouse_after,
                "updated_title": output.title,
                "article_pattern_id": getattr(output, "article_pattern_id", None),
                "article_pattern_version": getattr(output, "article_pattern_version", None),
            }
            updated_count += 1
            result_items.append(
                {
                    **candidate,
                    "refactor_candidate": True,
                    "action": "updated",
                    "updated_title": output.title,
                    "updated_url": updated_url,
                    "predicted_seo_score": predicted_scores.get("seo_score"),
                    "predicted_geo_score": predicted_scores.get("geo_score"),
                    "predicted_ctr_score": predicted_scores.get("ctr_score"),
                    "lighthouse_after": lighthouse_after,
                    "article_pattern_id": getattr(output, "article_pattern_id", None),
                    "article_pattern_version": getattr(output, "article_pattern_version", None),
                    "quality_gate": {
                        "attempts": list(draft.get("quality_attempts") or []),
                        "threshold": normalized_threshold,
                    },
                    "search_description_sync": search_description_sync,
                    "telegram": telegram,
                    "error": None,
                    "raw_payload": raw_payload if isinstance(raw_payload, dict) else {},
                }
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed_count += 1
            result_items.append(
                {
                    **candidate,
                    "refactor_candidate": True,
                    "action": "failed",
                    "updated_title": None,
                    "updated_url": None,
                    "predicted_seo_score": predicted_scores.get("seo_score"),
                    "predicted_geo_score": predicted_scores.get("geo_score"),
                    "predicted_ctr_score": predicted_scores.get("ctr_score"),
                    "lighthouse_after": None,
                    "article_pattern_id": getattr(output, "article_pattern_id", None),
                    "article_pattern_version": getattr(output, "article_pattern_version", None),
                    "quality_gate": {
                        "attempts": list(draft.get("quality_attempts") or []),
                        "threshold": normalized_threshold,
                    },
                    "search_description_sync": None,
                    "telegram": None,
                    "error": str(exc),
                }
            )

    sync_after_result = None
    summary_after = None
    if updated_remote_ids:
        sync_after_result = sync_blogger_posts_for_blog(db, blog)
        refreshed_posts = (
            db.execute(
                select(SyncedBloggerPost).where(
                    SyncedBloggerPost.blog_id == blog.id,
                    SyncedBloggerPost.remote_post_id.in_(updated_remote_ids),
                )
            )
            .scalars()
            .all()
        )
        touched_months: set[str] = set()
        for synced_post in refreshed_posts:
            payload = updated_meta.get(str(synced_post.remote_post_id or "").strip())
            if not payload:
                continue
            lighthouse_after = payload.get("lighthouse_after")
            touched_month = _update_synced_fact(
                db,
                synced_post=synced_post,
                updated_title=str(payload.get("updated_title") or synced_post.title).strip() or synced_post.title,
                predicted_scores=dict(payload.get("predicted_scores") or {}),
                lighthouse_scores=lighthouse_after if isinstance(lighthouse_after, dict) and lighthouse_after.get("status") == "ok" else None,
                article_pattern_id=str(payload.get("article_pattern_id") or "").strip() or None,
                article_pattern_version=payload.get("article_pattern_version")
                if isinstance(payload.get("article_pattern_version"), int)
                else None,
            )
            if touched_month:
                touched_months.add(touched_month)
        db.commit()
        for touched_month in sorted(touched_months):
            rebuild_blog_month_rollup(db, blog.id, touched_month, commit=False)
        if touched_months:
            db.commit()
        summary_after = {
            "blog_id": blog.id,
            "blog_name": blog.name,
            "month": normalized_month,
            "updated_remote_ids": updated_remote_ids,
        }

    processed_count = len(result_items)
    skipped_count = max(processed_count - updated_count - failed_count, 0)
    status_value = "ok" if failed_count == 0 else ("partial" if updated_count > 0 else "failed")
    return {
        "status": status_value,
        "execute": True,
        "blog_id": blog.id,
        "blog_name": blog.name,
        "threshold": normalized_threshold,
        "month": normalized_month,
        "parallel_workers": worker_count,
        "task_id": None,
        "total_candidates": total_candidates,
        "processed_count": processed_count,
        "updated_count": updated_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "sync_before_result": sync_before_result,
        "sync_after_result": sync_after_result,
        "summary_after": summary_after,
        "items": result_items,
    }

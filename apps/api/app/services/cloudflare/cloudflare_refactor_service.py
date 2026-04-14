from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import re
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import SyncedCloudflarePost
from app.services.content.article_pattern_service import apply_pattern_defaults, select_cloudflare_article_pattern
from app.services.cloudflare.cloudflare_channel_service import (
    CODEX_TEXT_RUNTIME_KIND,
    CODEX_TEXT_RUNTIME_MODEL,
    DEFAULT_CATEGORY_TIMEZONE,
    _append_no_inline_image_rule,
    _assess_cloudflare_quality_gate,
    _build_cloudflare_render_metadata,
    _build_cloudflare_master_article_prompt,
    _build_mysteria_blogger_source_block,
    _build_prompt_map,
    _category_hard_gate,
    _cloudflare_require_cover_image,
    _default_prompt_for_stage,
    _effective_quality_thresholds_for_category,
    _ensure_unique_title,
    _fetch_integration_post_detail,
    _insert_markdown_inline_image,
    _integration_data_or_raise,
    _integration_request,
    _list_integration_posts,
    _prepare_markdown_body,
    _quality_gate_thresholds,
    _route_cloudflare_text_model,
    _safe_float,
    _sanitize_cloudflare_public_body,
    _strip_generated_body_images,
    get_cloudflare_prompt_bundle,
    get_runtime_config,
    list_cloudflare_categories,
)
from app.services.cloudflare.cloudflare_performance_service import get_cloudflare_performance_summary
from app.services.cloudflare.cloudflare_sync_service import list_synced_cloudflare_posts, sync_cloudflare_posts
from app.services.providers.codex_cli import CodexCLITextProvider
from app.services.providers.mock import MockArticleProvider
from app.services.integrations.settings_service import get_settings_map


def _current_cloudflare_month(*, timezone_name: str) -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo(DEFAULT_CATEGORY_TIMEZONE)
    return datetime.now(tz).strftime("%Y-%m")


def _matches_cloudflare_refactor_filters(
    row: dict[str, Any],
    *,
    month: str,
    category_slugs: set[str],
    threshold: float,
) -> bool:
    status_value = str(row.get("status") or "").strip().lower()
    if status_value not in {"published", "live"}:
        return False
    published_at = str(row.get("published_at") or "").strip()
    if published_at and not published_at.startswith(month):
        return False
    if category_slugs:
        row_category_values = {
            str(row.get("canonical_category_slug") or "").strip(),
            str(row.get("category_slug") or "").strip(),
        }
        if not row_category_values.intersection(category_slugs):
            return False
    for key in ("seo_score", "geo_score", "ctr", "lighthouse_score"):
        score = row.get(key)
        if score is None:
            continue
        try:
            if float(score) < threshold:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _cloudflare_refactor_priority(row: dict[str, Any]) -> tuple[float, str, str]:
    scores: list[float] = []
    for key in ("seo_score", "geo_score", "ctr", "lighthouse_score"):
        value = row.get(key)
        try:
            if value is not None:
                scores.append(float(value))
        except (TypeError, ValueError):
            continue
    min_score = min(scores) if scores else 999.0
    published_at = str(row.get("published_at") or "").strip()
    title = str(row.get("title") or "").strip()
    return (min_score, published_at, title.casefold())


def _truncate_refactor_context(value: str | None, *, limit: int = 12000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


def _extract_existing_image_urls(content: str | None) -> list[str]:
    text = str(content or "").strip()
    if not text:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'!\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)', text):
        candidate = str(match.group(1) or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    for match in re.finditer(r'(?is)<img\b[^>]*\bsrc=[\'"]([^\'"]+)[\'"]', text):
        candidate = str(match.group(1) or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _restore_existing_inline_images(body_markdown: str, image_urls: Sequence[str], *, title: str) -> str:
    restored = str(body_markdown or "").strip()
    for index, raw_url in enumerate(image_urls, start=1):
        url = str(raw_url or "").strip()
        if not url:
            continue
        alt_text = title if index == 1 else f"{title} image {index}"
        restored = _insert_markdown_inline_image(restored, f"![{alt_text}]({url})")
    return restored


def _suggest_cloudflare_target_category_slug(
    current_category_slug: str,
    *,
    existing_title: str,
    existing_body: str,
) -> str:
    normalized_slug = str(current_category_slug or "").strip()
    combined = f"{existing_title}\n{existing_body}".casefold()
    if normalized_slug == "주식의-흐름":
        if any(token in combined for token in ("ionq", "아이온큐", "sandisk", "샌디스크", "sndk")):
            return "나스닥의-흐름"
    return normalized_slug


def _cloudflare_refactor_subject_rule(category_slug: str) -> str:
    if category_slug == "여행과-기록":
        return "Choose one real place and one routeable visit flow. Use place names, movement, timing, and on-site atmosphere."
    if category_slug == "축제와-현장":
        return "Choose one real event or field experience. Cover timing, route, food, stay, and caution points."
    if category_slug == "문화와-공간":
        return "Anchor the article on one real exhibition, artist, museum, gallery, or cultural venue with representative works and viewing points."
    if category_slug == "미스테리아-스토리":
        return "Build around one real case, record set, legend, or traceable mystery with records, clues, interpretations, and current tracking."
    if category_slug == "동그리의-생각":
        return "Keep a reflective monologue voice and end on a personal closing note instead of a report-like summary."
    if category_slug == "나스닥의-흐름":
        return "Center the piece on one real Nasdaq-listed company only, using exactly two voices: Donggri aggressive, Hamni conservative."
    return "Tighten the article around one concrete subject that clearly fits the category instead of a vague meta guide."


def _build_cloudflare_refactor_context_block(
    *,
    row: dict[str, Any],
    detail: dict[str, Any],
    threshold: float,
    original_category_slug: str,
    target_category_slug: str,
    current_body: str,
) -> str:
    lines = [
        "\n\n[Refactor context]",
        "- This is an existing published Cloudflare post rewrite.",
        "- Keep the category fit strict, but do not preserve a vague, self-referential, or meta-guide angle just because the current version uses it.",
        "- If the current version reads like a blog introduction, archive introduction, category introduction, or a generic how-this-blog-works guide, discard that angle and rebuild around one concrete real-world subject that truly fits the category.",
        "- Do not mention internal score systems, quality gates, or refactor instructions in the visible article.",
        f"- Threshold target for this rewrite: keep SEO/GEO/CTR/Lighthouse above {threshold:.0f} where content can influence them.",
        f"- Existing title: {str(detail.get('title') or row.get('title') or '').strip()}",
        f"- Existing excerpt: {str(detail.get('excerpt') or row.get('excerpt') or '').strip()}",
        f"- Existing public URL: {str(detail.get('publicUrl') or row.get('published_url') or '').strip()}",
        f"- Current scores: SEO={row.get('seo_score')}, GEO={row.get('geo_score')}, CTR={row.get('ctr')}, Lighthouse={row.get('lighthouse_score')}",
        f"- Current category slug: {original_category_slug}",
        f"- Rewrite target category slug: {target_category_slug}",
        f"- Category rewrite rule: {_cloudflare_refactor_subject_rule(target_category_slug)}",
        "- Keep the category fit much tighter than the current version.",
    ]
    if target_category_slug != original_category_slug:
        lines.append("- This rewrite must move into the target category above because the current bucket is too broad for the actual subject.")
    snapshot = _truncate_refactor_context(current_body, limit=12000)
    if snapshot:
        lines.extend(
            [
                "- Existing body snapshot for context only. Do not lightly paraphrase it; write a materially improved new article.",
                snapshot,
            ]
        )
    return "\n".join(lines)


def _cloudflare_refactor_similarity_corpus(
    integration_posts: Sequence[dict[str, Any]],
    *,
    exclude_remote_id: str,
    exclude_url: str,
) -> list[dict[str, str]]:
    normalized_exclude_id = str(exclude_remote_id or "").strip()
    normalized_exclude_url = str(exclude_url or "").strip()
    corpus: list[dict[str, str]] = []
    for index, post in enumerate(integration_posts):
        remote_id = str(post.get("id") or post.get("remote_id") or "").strip()
        public_url = str(post.get("publicUrl") or post.get("url") or "").strip()
        if normalized_exclude_id and remote_id == normalized_exclude_id:
            continue
        if normalized_exclude_url and public_url == normalized_exclude_url:
            continue
        corpus.append(
            {
                "key": f"existing-{index + 1}",
                "title": str(post.get("title") or "").strip(),
                "body_html": str(post.get("contentMarkdown") or post.get("content") or post.get("excerpt") or "").strip(),
                "url": public_url,
            }
        )
    return corpus


def _get_cloudflare_refactor_provider(*, runtime: Any, model: str):
    if str(getattr(runtime, "provider_mode", "") or "").strip().lower() == "live":
        return CodexCLITextProvider(runtime=runtime, model=model)
    return MockArticleProvider()


def _generate_cloudflare_refactor_draft(
    candidate: dict[str, Any],
    *,
    runtime: Any,
    article_model: str,
    retry_model: str,
    quality_gate_enabled: bool,
) -> dict[str, Any]:
    existing_title = str(candidate.get("existing_title") or "").strip() or "Untitled"
    category_slug = str(candidate.get("category_slug") or "").strip()
    article_prompt = str(candidate.get("article_prompt") or "").strip()
    pattern_selection = candidate.get("pattern_selection")
    similarity_corpus = list(candidate.get("similarity_corpus") or [])
    refactor_thresholds = dict(candidate.get("refactor_thresholds") or {})

    provider = _get_cloudflare_refactor_provider(runtime=runtime, model=article_model)
    article_output, _article_raw = provider.generate_article(existing_title, article_prompt)
    article_output = apply_pattern_defaults(article_output, pattern_selection)
    article_output.html_article = _sanitize_cloudflare_public_body(
        article_output.html_article,
        category_slug=category_slug,
        title=article_output.title,
    )

    quality_attempts: list[dict[str, Any]] = []
    for quality_attempt in range(1, 3):
        quality_assessment = _assess_cloudflare_quality_gate(
            title=article_output.title,
            body_markdown=article_output.html_article,
            excerpt=article_output.excerpt,
            faq_section=[
                item.model_dump() if hasattr(item, "model_dump") else dict(item)
                for item in (article_output.faq_section or [])
                if isinstance(item, dict) or hasattr(item, "model_dump")
            ],
            similarity_corpus=similarity_corpus,
            thresholds=refactor_thresholds,
            category_slug=category_slug,
        )
        quality_assessment["attempt"] = quality_attempt
        quality_attempts.append(quality_assessment)
        if quality_assessment["passed"] or not quality_gate_enabled or quality_attempt >= 2:
            break
        retry_prompt = (
            article_prompt
            + "\n\n[Quality gate retry instruction]\n"
            + f"- Previous draft failed: {', '.join(quality_assessment.get('reasons', [])) or 'quality thresholds'}.\n"
            + "- Rewrite with a materially different structure, stronger category fit, clearer headings, and higher click intent.\n"
            + "- Do not mention internal scores or quality gates in the visible article.\n"
        )
        retry_provider = _get_cloudflare_refactor_provider(runtime=runtime, model=retry_model)
        article_output, _article_raw = retry_provider.generate_article(existing_title, retry_prompt)
        article_output = apply_pattern_defaults(article_output, pattern_selection)
        article_output.html_article = _sanitize_cloudflare_public_body(
            article_output.html_article,
            category_slug=category_slug,
            title=article_output.title,
        )

    final_quality = quality_attempts[-1] if quality_attempts else {
        "passed": True,
        "reasons": [],
        "similarity_score": 0.0,
        "most_similar_url": "",
        "seo_score": None,
        "geo_score": None,
        "ctr_score": None,
        "attempt": 1,
    }
    quality_gate_payload = {
        "enabled": quality_gate_enabled,
        "passed": bool(final_quality.get("passed")),
        "attempts": quality_attempts,
        "reason": ",".join(final_quality.get("reasons", [])),
        "scores": {
            "similarity_score": final_quality.get("similarity_score"),
            "most_similar_url": final_quality.get("most_similar_url"),
            "seo_score": final_quality.get("seo_score"),
            "geo_score": final_quality.get("geo_score"),
            "ctr_score": final_quality.get("ctr_score"),
        },
        "thresholds": {
            "similarity_threshold": refactor_thresholds.get("similarity_threshold"),
            "min_seo_score": refactor_thresholds.get("min_seo_score"),
            "min_geo_score": refactor_thresholds.get("min_geo_score"),
            "min_ctr_score": refactor_thresholds.get("min_ctr_score"),
        },
    }
    if not quality_gate_enabled:
        quality_gate_payload["passed"] = True
        quality_gate_payload["reason"] = "disabled"

    return {
        "article_output": article_output,
        "quality_gate": quality_gate_payload,
    }


def _prepare_cloudflare_refactor_candidate(
    db: Session,
    row: dict[str, Any],
    *,
    prompt_bundle: dict[str, Any],
    categories_by_slug: dict[str, dict[str, Any]],
    categories_by_id: dict[str, dict[str, Any]],
    integration_posts: Sequence[dict[str, Any]],
    current_date: str,
    normalized_threshold: float,
    quality_thresholds: dict[str, float],
) -> dict[str, Any]:
    remote_id = str(row.get("remote_id") or "").strip()
    current_url = str(row.get("published_url") or "").strip()
    detail = _fetch_integration_post_detail(db, remote_post_id=remote_id)
    detail_category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
    original_category_slug = (
        str(detail_category.get("slug") or "").strip()
        or str(row.get("canonical_category_slug") or row.get("category_slug") or "").strip()
    )
    existing_title = str(detail.get("title") or row.get("title") or "").strip()
    existing_excerpt = str(detail.get("excerpt") or row.get("excerpt") or "").strip()
    existing_raw_content = str(detail.get("contentMarkdown") or detail.get("content") or detail.get("markdown") or existing_excerpt).strip()
    existing_image_urls = _extract_existing_image_urls(existing_raw_content)
    existing_cover_image_url = str(detail.get("coverImage") or "").strip()
    existing_cover_alt = str(detail.get("coverAlt") or "").strip()
    existing_inline_image_urls = [url for url in existing_image_urls if url and url != existing_cover_image_url]
    existing_body = _strip_generated_body_images(existing_raw_content)
    category_slug = _suggest_cloudflare_target_category_slug(
        original_category_slug,
        existing_title=existing_title,
        existing_body=existing_body,
    )

    category = categories_by_slug.get(category_slug)
    if category is None:
        category = categories_by_id.get(str(detail_category.get("id") or "").strip())
    if category is None and category_slug != original_category_slug:
        category = categories_by_slug.get(original_category_slug)
        category_slug = original_category_slug
    if category is None:
        raise ValueError(f"Cloudflare category not found for remote_id={remote_id}")

    category_id = str(category.get("id") or "").strip()
    category_slug = str(category.get("slug") or "").strip()
    category_name = str(category.get("name") or category_slug).strip() or category_slug
    prompt_map = _build_prompt_map(prompt_bundle, category_id)
    article_prompt_template = prompt_map.get("article_generation") or _default_prompt_for_stage(category, "article_generation")

    mysteria_source_block = _build_mysteria_blogger_source_block(
        db,
        category_id=category_id,
        category_slug=category_slug,
        pair_size=2,
        preview_limit=6,
    )
    if mysteria_source_block:
        article_prompt_template = f"{article_prompt_template}\n\n{mysteria_source_block}"

    planner_brief_block = _build_cloudflare_refactor_context_block(
        row=row,
        detail=detail,
        threshold=normalized_threshold,
        original_category_slug=original_category_slug,
        target_category_slug=category_slug,
        current_body=existing_body,
    )
    category_gate = _category_hard_gate(category_slug, category_name)
    article_prompt = _build_cloudflare_master_article_prompt(
        db,
        category=category,
        keyword=existing_title,
        current_date=current_date,
        planner_brief=planner_brief_block,
        prompt_template=article_prompt_template,
    )
    article_prompt = _append_no_inline_image_rule(f"{article_prompt}{category_gate}")

    pattern_selection = select_cloudflare_article_pattern(db, category_slug=category_slug)
    similarity_corpus = _cloudflare_refactor_similarity_corpus(
        integration_posts,
        exclude_remote_id=remote_id,
        exclude_url=current_url,
    )
    effective_quality_thresholds = _effective_quality_thresholds_for_category(category_slug, quality_thresholds)
    refactor_thresholds = dict(effective_quality_thresholds)
    refactor_thresholds["min_seo_score"] = max(_safe_float(refactor_thresholds.get("min_seo_score"), 0.0), normalized_threshold)
    refactor_thresholds["min_geo_score"] = max(_safe_float(refactor_thresholds.get("min_geo_score"), 0.0), normalized_threshold)
    refactor_thresholds["min_ctr_score"] = max(_safe_float(refactor_thresholds.get("min_ctr_score"), 0.0), normalized_threshold)

    other_titles = [
        str(post.get("title") or "").strip()
        for post in integration_posts
        if str(post.get("id") or post.get("remote_id") or "").strip() != remote_id
    ]

    return {
        "row": row,
        "remote_id": remote_id,
        "current_url": current_url,
        "original_category_slug": original_category_slug,
        "category_id": category_id,
        "category_slug": category_slug,
        "category_name": category_name,
        "existing_title": existing_title,
        "existing_cover_image_url": existing_cover_image_url,
        "existing_cover_alt": existing_cover_alt,
        "existing_inline_image_urls": existing_inline_image_urls,
        "article_prompt": article_prompt,
        "pattern_selection": pattern_selection,
        "similarity_corpus": similarity_corpus,
        "refactor_thresholds": refactor_thresholds,
        "other_titles": other_titles,
    }

def refactor_cloudflare_low_score_posts(
    db: Session,
    *,
    execute: bool = False,
    queue: bool = False,
    threshold: float = 80.0,
    month: str | None = None,
    category_slugs: list[str] | None = None,
    remote_ids: list[str] | None = None,
    limit: int | None = None,
    sync_before: bool = True,
    parallel_workers: int = 1,
) -> dict[str, Any]:
    settings_map = get_settings_map(db)
    schedule_timezone = (settings_map.get("schedule_timezone") or DEFAULT_CATEGORY_TIMEZONE).strip() or DEFAULT_CATEGORY_TIMEZONE
    normalized_month = str(month or "").strip() or _current_cloudflare_month(timezone_name=schedule_timezone)
    normalized_category_slugs = {str(item or "").strip() for item in (category_slugs or []) if str(item or "").strip()}
    normalized_remote_ids = {str(item or "").strip() for item in (remote_ids or []) if str(item or "").strip()}
    normalized_threshold = max(min(float(threshold), 100.0), 0.0)
    safe_limit = max(int(limit), 1) if limit is not None else None
    worker_count = max(int(parallel_workers or 1), 1)

    sync_before_result: dict[str, Any] | None = None
    if sync_before:
        sync_before_result = sync_cloudflare_posts(db, include_non_published=True)

    rows = list_synced_cloudflare_posts(db, include_non_published=True)
    candidates = [
        row
        for row in rows
        if _matches_cloudflare_refactor_filters(
            row,
            month=normalized_month,
            category_slugs=normalized_category_slugs,
            threshold=normalized_threshold,
        )
    ]
    if normalized_remote_ids:
        candidates = [row for row in candidates if str(row.get("remote_id") or "").strip() in normalized_remote_ids]
    candidates.sort(key=_cloudflare_refactor_priority)
    total_candidates = len(candidates)
    if safe_limit is not None:
        candidates = candidates[:safe_limit]

    if not execute:
        return {
            "status": "ok",
            "execute": False,
            "threshold": normalized_threshold,
            "month": normalized_month,
            "parallel_workers": worker_count,
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
                    "remote_id": str(row.get("remote_id") or "").strip(),
                    "category_slug": str(row.get("canonical_category_slug") or row.get("category_slug") or "").strip() or None,
                    "category_name": str(row.get("canonical_category_name") or row.get("category_name") or "").strip() or None,
                    "title": str(row.get("title") or "").strip() or "Untitled",
                    "url": str(row.get("published_url") or "").strip() or None,
                    "published_at": str(row.get("published_at") or "").strip() or None,
                    "seo_score": _safe_float(row.get("seo_score"), 0.0) if row.get("seo_score") is not None else None,
                    "geo_score": _safe_float(row.get("geo_score"), 0.0) if row.get("geo_score") is not None else None,
                    "ctr": _safe_float(row.get("ctr"), 0.0) if row.get("ctr") is not None else None,
                    "lighthouse_score": _safe_float(row.get("lighthouse_score"), 0.0) if row.get("lighthouse_score") is not None else None,
                    "refactor_candidate": True,
                    "action": "dry_run",
                    "updated_title": None,
                    "updated_url": None,
                    "article_pattern_id": row.get("article_pattern_id"),
                    "article_pattern_version": row.get("article_pattern_version"),
                    "quality_gate": None,
                    "error": None,
                }
                for row in candidates
            ],
        }

    runtime = get_runtime_config(db)
    require_cover_image = _cloudflare_require_cover_image(settings_map)
    categories = [item for item in list_cloudflare_categories(db) if bool(item.get("isLeaf"))]
    categories_by_slug = {str(item.get("slug") or "").strip(): item for item in categories if str(item.get("slug") or "").strip()}
    categories_by_id = {str(item.get("id") or "").strip(): item for item in categories if str(item.get("id") or "").strip()}
    prompt_bundle = get_cloudflare_prompt_bundle(db)
    integration_posts = _list_integration_posts(db)
    current_date = datetime.now(ZoneInfo(schedule_timezone)).date().isoformat()
    quality_thresholds = _quality_gate_thresholds(settings_map)
    quality_gate_enabled = bool(quality_thresholds.get("enabled", 1.0))
    article_model = _route_cloudflare_text_model(
        db,
        requested_model=CODEX_TEXT_RUNTIME_MODEL,
        allow_large=True,
        stage_name="cloudflare_refactor",
        runtime=runtime,
        provider_hint=CODEX_TEXT_RUNTIME_KIND,
    )
    retry_model = _route_cloudflare_text_model(
        db,
        requested_model=CODEX_TEXT_RUNTIME_MODEL,
        allow_large=True,
        stage_name="seo_rewrite",
        runtime=runtime,
        provider_hint=CODEX_TEXT_RUNTIME_KIND,
    )

    prepared_candidates: list[dict[str, Any]] = []
    preparation_errors: dict[str, str] = {}
    for row in candidates:
        remote_id = str(row.get("remote_id") or "").strip()
        try:
            prepared_candidates.append(
                _prepare_cloudflare_refactor_candidate(
                    db,
                    row,
                    prompt_bundle=prompt_bundle,
                    categories_by_slug=categories_by_slug,
                    categories_by_id=categories_by_id,
                    integration_posts=integration_posts,
                    current_date=current_date,
                    normalized_threshold=normalized_threshold,
                    quality_thresholds=quality_thresholds,
                )
            )
        except Exception as exc:  # noqa: BLE001
            preparation_errors[remote_id] = str(exc)

    drafts: dict[str, dict[str, Any]] = {}
    draft_errors: dict[str, str] = {}
    if worker_count == 1 or len(prepared_candidates) <= 1:
        for candidate in prepared_candidates:
            remote_id = str(candidate.get("remote_id") or "").strip()
            try:
                drafts[remote_id] = _generate_cloudflare_refactor_draft(
                    candidate,
                    runtime=runtime,
                    article_model=article_model,
                    retry_model=retry_model,
                    quality_gate_enabled=quality_gate_enabled,
                )
            except Exception as exc:  # noqa: BLE001
                draft_errors[remote_id] = str(exc)
    else:
        with ThreadPoolExecutor(max_workers=min(worker_count, len(prepared_candidates))) as executor:
            futures = {
                executor.submit(
                    _generate_cloudflare_refactor_draft,
                    candidate,
                    runtime=runtime,
                    article_model=article_model,
                    retry_model=retry_model,
                    quality_gate_enabled=quality_gate_enabled,
                ): candidate
                for candidate in prepared_candidates
            }
            for future in as_completed(futures):
                candidate = futures[future]
                remote_id = str(candidate.get("remote_id") or "").strip()
                try:
                    drafts[remote_id] = future.result()
                except Exception as exc:  # noqa: BLE001
                    draft_errors[remote_id] = str(exc)

    updated_count = 0
    failed_count = 0
    items: list[dict[str, Any]] = []
    updated_pattern_map: dict[str, dict[str, int | str | None]] = {}
    prepared_candidates_by_remote_id = {
        str(candidate.get("remote_id") or "").strip(): candidate
        for candidate in prepared_candidates
    }

    for row in candidates:
        remote_id = str(row.get("remote_id") or "").strip()
        current_url = str(row.get("published_url") or "").strip()
        candidate = prepared_candidates_by_remote_id.get(remote_id)
        draft = drafts.get(remote_id)

        if remote_id in preparation_errors:
            failed_count += 1
            items.append(
                {
                    "remote_id": remote_id,
                    "category_slug": str(row.get("canonical_category_slug") or row.get("category_slug") or "").strip() or None,
                    "category_name": str(row.get("canonical_category_name") or row.get("category_name") or "").strip() or None,
                    "title": str(row.get("title") or "").strip() or "Untitled",
                    "url": current_url or None,
                    "published_at": str(row.get("published_at") or "").strip() or None,
                    "seo_score": row.get("seo_score"),
                    "geo_score": row.get("geo_score"),
                    "ctr": row.get("ctr"),
                    "lighthouse_score": row.get("lighthouse_score"),
                    "refactor_candidate": True,
                    "action": "failed",
                    "updated_title": None,
                    "updated_url": None,
                    "article_pattern_id": row.get("article_pattern_id"),
                    "article_pattern_version": row.get("article_pattern_version"),
                    "quality_gate": None,
                    "error": preparation_errors[remote_id],
                }
            )
            continue

        if remote_id in draft_errors:
            failed_count += 1
            items.append(
                {
                    "remote_id": remote_id,
                    "category_slug": str((candidate or {}).get("category_slug") or row.get("canonical_category_slug") or row.get("category_slug") or "").strip() or None,
                    "category_name": str((candidate or {}).get("category_name") or row.get("canonical_category_name") or row.get("category_name") or "").strip() or None,
                    "title": str((candidate or {}).get("existing_title") or row.get("title") or "").strip() or "Untitled",
                    "url": current_url or None,
                    "published_at": str(row.get("published_at") or "").strip() or None,
                    "seo_score": row.get("seo_score"),
                    "geo_score": row.get("geo_score"),
                    "ctr": row.get("ctr"),
                    "lighthouse_score": row.get("lighthouse_score"),
                    "refactor_candidate": True,
                    "action": "failed",
                    "updated_title": None,
                    "updated_url": None,
                    "article_pattern_id": row.get("article_pattern_id"),
                    "article_pattern_version": row.get("article_pattern_version"),
                    "quality_gate": None,
                    "error": draft_errors[remote_id],
                }
            )
            continue

        if candidate is None or draft is None:
            failed_count += 1
            items.append(
                {
                    "remote_id": remote_id,
                    "category_slug": str((candidate or {}).get("category_slug") or row.get("canonical_category_slug") or row.get("category_slug") or "").strip() or None,
                    "category_name": str((candidate or {}).get("category_name") or row.get("canonical_category_name") or row.get("category_name") or "").strip() or None,
                    "title": str((candidate or {}).get("existing_title") or row.get("title") or "").strip() or "Untitled",
                    "url": current_url or None,
                    "published_at": str(row.get("published_at") or "").strip() or None,
                    "seo_score": row.get("seo_score"),
                    "geo_score": row.get("geo_score"),
                    "ctr": row.get("ctr"),
                    "lighthouse_score": row.get("lighthouse_score"),
                    "refactor_candidate": True,
                    "action": "failed",
                    "updated_title": None,
                    "updated_url": None,
                    "article_pattern_id": row.get("article_pattern_id"),
                    "article_pattern_version": row.get("article_pattern_version"),
                    "quality_gate": None,
                    "error": "draft_missing",
                }
            )
            continue

        try:
            article_output = draft["article_output"]
            quality_gate_payload = dict(draft.get("quality_gate") or {})
            if not bool(quality_gate_payload.get("passed")):
                failed_count += 1
                items.append(
                    {
                        "remote_id": remote_id,
                        "category_slug": candidate["category_slug"],
                        "category_name": candidate["category_name"],
                        "title": str(candidate.get("existing_title") or row.get("title") or "").strip() or "Untitled",
                        "url": current_url or None,
                        "published_at": str(row.get("published_at") or "").strip() or None,
                        "seo_score": row.get("seo_score"),
                        "geo_score": row.get("geo_score"),
                        "ctr": row.get("ctr"),
                        "lighthouse_score": row.get("lighthouse_score"),
                        "refactor_candidate": True,
                        "action": "failed",
                        "updated_title": None,
                        "updated_url": None,
                        "article_pattern_id": getattr(article_output, "article_pattern_id", None),
                        "article_pattern_version": getattr(article_output, "article_pattern_version", None),
                        "quality_gate": quality_gate_payload,
                        "error": "quality_gate_failed",
                    }
                )
                continue

            title = _ensure_unique_title(article_output.title, list(candidate.get("other_titles") or []))
            cover_alt = (article_output.meta_description or title).strip()[:180]
            cover_image_url = str(candidate.get("existing_cover_image_url") or "").strip()
            image_warning = ""
            if cover_image_url:
                cover_alt = str(candidate.get("existing_cover_alt") or "").strip() or cover_alt
                image_warning = "reused_existing_cover_image"

            if require_cover_image and not cover_image_url:
                failed_count += 1
                items.append(
                    {
                        "remote_id": remote_id,
                        "category_slug": candidate["category_slug"],
                        "category_name": candidate["category_name"],
                        "title": str(candidate.get("existing_title") or row.get("title") or "").strip() or "Untitled",
                        "url": current_url or None,
                        "published_at": str(row.get("published_at") or "").strip() or None,
                        "seo_score": row.get("seo_score"),
                        "geo_score": row.get("geo_score"),
                        "ctr": row.get("ctr"),
                        "lighthouse_score": row.get("lighthouse_score"),
                        "refactor_candidate": True,
                        "action": "failed",
                        "updated_title": None,
                        "updated_url": None,
                        "article_pattern_id": getattr(article_output, "article_pattern_id", None),
                        "article_pattern_version": getattr(article_output, "article_pattern_version", None),
                        "quality_gate": quality_gate_payload,
                        "error": image_warning or "cover_image_missing",
                    }
                )
                continue

            body_markdown = _strip_generated_body_images(
                _sanitize_cloudflare_public_body(
                    article_output.html_article,
                    category_slug=str(candidate.get("category_slug") or "").strip(),
                    title=title,
                )
            )
            existing_inline_image_urls = list(candidate.get("existing_inline_image_urls") or [])
            if existing_inline_image_urls:
                body_markdown = _restore_existing_inline_images(
                    body_markdown,
                    existing_inline_image_urls,
                    title=title,
                )
                image_warning = "; ".join(value for value in (image_warning, "reused_existing_inline_images") if value)

            tag_names: list[str] = []
            seen_tag_keys: set[str] = set()
            for raw_tag in [candidate["category_name"], *(article_output.labels or [])]:
                normalized_tag = str(raw_tag or "").replace("#", " ").strip()
                normalized_tag = " ".join(normalized_tag.split())
                if not normalized_tag:
                    continue
                tag_key = normalized_tag.casefold()
                if tag_key in seen_tag_keys:
                    continue
                seen_tag_keys.add(tag_key)
                tag_names.append(normalized_tag)
                if len(tag_names) >= 20:
                    break

            update_payload = {
                "title": title,
                "content": _prepare_markdown_body(title, body_markdown),
                "excerpt": article_output.excerpt,
                "seoTitle": title,
                "seoDescription": article_output.meta_description,
                "tagNames": tag_names,
                "categoryId": candidate["category_id"],
                "status": "published",
            }
            if cover_image_url:
                update_payload["coverImage"] = cover_image_url
                update_payload["coverAlt"] = cover_alt
            render_metadata = _build_cloudflare_render_metadata(
                article_output=article_output,
                planner_brief={},
                title=title,
            )
            if render_metadata:
                update_payload["metadata"] = render_metadata

            update_response = _integration_request(
                db,
                method="PUT",
                path=f"/api/integrations/posts/{remote_id}",
                json_payload=update_payload,
                timeout=120.0,
            )
            updated_post = _integration_data_or_raise(update_response)
            if not isinstance(updated_post, dict):
                raise ValueError("Cloudflare update post returned an invalid payload.")

            updated_pattern_map[remote_id] = {
                "article_pattern_id": getattr(article_output, "article_pattern_id", None),
                "article_pattern_version": getattr(article_output, "article_pattern_version", None),
            }
            updated_count += 1
            items.append(
                {
                    "remote_id": remote_id,
                    "category_slug": candidate["category_slug"],
                    "category_name": candidate["category_name"],
                    "title": str(candidate.get("existing_title") or row.get("title") or "").strip() or "Untitled",
                    "url": current_url or None,
                    "published_at": str(row.get("published_at") or "").strip() or None,
                    "seo_score": row.get("seo_score"),
                    "geo_score": row.get("geo_score"),
                    "ctr": row.get("ctr"),
                    "lighthouse_score": row.get("lighthouse_score"),
                    "refactor_candidate": True,
                    "action": "updated",
                    "updated_title": str(updated_post.get("title") or title).strip() or title,
                    "updated_url": str(updated_post.get("publicUrl") or current_url).strip() or None,
                    "article_pattern_id": getattr(article_output, "article_pattern_id", None),
                    "article_pattern_version": getattr(article_output, "article_pattern_version", None),
                    "quality_gate": quality_gate_payload,
                    "error": image_warning or None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            items.append(
                {
                    "remote_id": remote_id,
                    "category_slug": str(candidate.get("category_slug") or row.get("canonical_category_slug") or row.get("category_slug") or "").strip() or None,
                    "category_name": str(candidate.get("category_name") or row.get("canonical_category_name") or row.get("category_name") or "").strip() or None,
                    "title": str(candidate.get("existing_title") or row.get("title") or "").strip() or "Untitled",
                    "url": current_url or None,
                    "published_at": str(row.get("published_at") or "").strip() or None,
                    "seo_score": row.get("seo_score"),
                    "geo_score": row.get("geo_score"),
                    "ctr": row.get("ctr"),
                    "lighthouse_score": row.get("lighthouse_score"),
                    "refactor_candidate": True,
                    "action": "failed",
                    "updated_title": None,
                    "updated_url": None,
                    "article_pattern_id": row.get("article_pattern_id"),
                    "article_pattern_version": row.get("article_pattern_version"),
                    "quality_gate": draft.get("quality_gate"),
                    "error": str(exc),
                }
            )

    sync_after_result: dict[str, Any] | None = None
    summary_after: dict[str, Any] | None = None
    if updated_pattern_map:
        try:
            sync_after_result = sync_cloudflare_posts(db, include_non_published=True)
            synced_rows = (
                db.execute(
                    select(SyncedCloudflarePost).where(
                        SyncedCloudflarePost.remote_post_id.in_(list(updated_pattern_map.keys()))
                    )
                )
                .scalars()
                .all()
            )
            synced_changed = False
            for synced_row in synced_rows:
                metadata = updated_pattern_map.get(str(synced_row.remote_post_id or "").strip())
                if not metadata:
                    continue
                pattern_id = str(metadata.get("article_pattern_id") or "").strip() or None
                pattern_version = metadata.get("article_pattern_version")
                if pattern_id and synced_row.article_pattern_id != pattern_id:
                    synced_row.article_pattern_id = pattern_id
                    synced_changed = True
                if isinstance(pattern_version, int) and synced_row.article_pattern_version != pattern_version:
                    synced_row.article_pattern_version = pattern_version
                    synced_changed = True
            if synced_changed:
                db.commit()
        except Exception as exc:  # noqa: BLE001
            sync_after_result = {"status": "failed", "reason": str(exc)}

    try:
        summary_after = get_cloudflare_performance_summary(db, month=normalized_month)
    except Exception as exc:  # noqa: BLE001
        summary_after = {"status": "failed", "reason": str(exc), "month": normalized_month}

    processed_count = len(items)
    skipped_count = max(processed_count - updated_count - failed_count, 0)
    status_value = "ok" if failed_count == 0 else ("partial" if updated_count > 0 else "failed")
    return {
        "status": status_value,
        "execute": True,
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
        "items": items,
    }


from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from celery import Task
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.entities import (
    Article,
    Blog,
    BloggerPost,
    Image,
    JobStatus,
    LogLevel,
    PostStatus,
    PublishMode,
    Topic,
    WorkflowStageType,
)
from app.services.content.article_service import (
    build_article_r2_asset_object_key,
    build_collage_prompt,
    ensure_article_editorial_labels,
    save_article,
)
from app.services.content.article_pattern_service import apply_pattern_defaults, select_blogger_article_pattern
from app.services.ops.audit_service import add_log, count_logs_since
from app.services.platform.blog_service import get_blog, get_workflow_step, render_agent_prompt, stage_label
from app.services.content.content_guard_service import (
    DuplicateContentError,
    build_duplicate_exclusion_prompt,
    filter_duplicate_topic_items,
)
from app.services.content.content_ops_service import (
    compute_seo_geo_scores,
    compute_similarity_analysis,
    persist_article_quality_cache,
    review_article_draft,
    review_article_publish_state,
)
from app.services.integrations.google_sheet_service import (
    DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS,
    DEFAULT_TOPIC_NOVELTY_ANGLE_THRESHOLD,
    DEFAULT_TOPIC_NOVELTY_CLUSTER_THRESHOLD,
    DEFAULT_TOPIC_SOFT_PENALTY_THRESHOLD,
    TopicHistoryEntry,
    assess_topic_novelty_against_history,
    build_sheet_topic_exclusion_prompt,
    list_sheet_topic_history_entries,
    sync_google_sheet_snapshot,
)
from app.services.content.html_assembler import assemble_article_html, upsert_language_switch_html
from app.services.ops.job_service import (
    create_job,
    increment_attempt,
    load_job,
    merge_prompt,
    merge_response,
    record_failure,
    set_status,
)
from app.services.content.multilingual_bundle_service import (
    SUPPORTED_LANGUAGES,
    build_language_switch_block,
    resolve_blog_bundle_language,
)
from app.services.ops.analytics_service import upsert_article_fact
from app.services.providers.base import ProviderRuntimeError
from app.services.providers.factory import (
    get_article_provider,
    get_blogger_provider,
    get_image_provider,
    get_runtime_config,
    get_topic_provider,
)
from app.services.content.publish_trust_gate_service import (
    assess_publish_trust_requirements,
    enforce_publish_trust_requirements,
    ensure_trust_gate_appendix,
)
from app.services.ops.openai_usage_service import (
    FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
    route_openai_free_tier_text_model,
    resolve_free_tier_text_model,
)
from app.services.ops.model_policy_service import CODEX_TEXT_RUNTIME_KIND, CODEX_TEXT_RUNTIME_MODEL
from app.services.content.related_posts import find_related_articles
from app.services.integrations.settings_service import get_settings_map, upsert_settings
from app.services.integrations.storage_service import save_html, save_public_binary
from app.services.integrations.telegram_service import send_telegram_post_notification
from app.services.content.topic_discovery_run_service import create_topic_discovery_run
from app.services.content.topic_guard_service import (
    TopicGuardConflictError,
    annotate_topic_items,
    assert_topic_guard,
    current_publish_target_datetime,
    rebuild_topic_memories_for_blog,
)
from app.services.content.topic_service import upsert_topics
from app.services.content.wikimedia_service import fetch_wikimedia_media

OPENAI_TOPIC_REQUEST_STAGE = "OPENAI_TOPIC_REQUEST"
GEMINI_TOPIC_REQUEST_STAGE = "GEMINI_TOPIC_REQUEST"
GEMINI_TOPIC_LIMIT_BLOCKED_STAGE = "GEMINI_TOPIC_LIMIT_BLOCKED"
PIPELINE_CONTROL_KEY = "pipeline_control"
PIPELINE_SCHEDULE_KEY = "pipeline_schedule"
TRAVEL_INLINE_PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "prompts" / "travel_inline_collage_prompt.md"
MYSTERY_INLINE_PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "prompts" / "mystery_inline_collage_prompt.md"

PIPELINE_STOP_ALLOWED = {
    JobStatus.GENERATING_ARTICLE,
    JobStatus.GENERATING_IMAGE_PROMPT,
    JobStatus.GENERATING_IMAGE,
    JobStatus.ASSEMBLING_HTML,
}

PIPELINE_STAGE_LABELS = {
    JobStatus.GENERATING_ARTICLE: "article generation",
    JobStatus.GENERATING_IMAGE_PROMPT: "image prompt generation",
    JobStatus.GENERATING_IMAGE: "image generation",
    JobStatus.ASSEMBLING_HTML: "html assembly",
}

TRAVEL_EDITORIAL_GUIDANCE = {
    "travel": "Focus on practical routes, movement logic, transit choices, and local neighborhood travel value.",
    "culture": "Focus on festivals, exhibitions, events, heritage venues, and culturally meaningful visits.",
    "food": "Focus on trending Korean food, local restaurants, markets, cafe culture, and practical dining decisions.",
}

MYSTERY_EDITORIAL_GUIDANCE = {
    "case-files": "Focus on documented cases, investigations, timelines, evidence, and unresolved factual questions.",
    "legends-lore": "Focus on folklore, legends, myth narratives, SCP-style fictional universes, and cultural interpretation.",
    "mystery-archives": "Focus on archival records, historical enigmas, expedition logs, and document-based reconstruction.",
}

TRAVEL_BLOSSOM_FORCE_DATE = date(2026, 3, 28)
TRAVEL_BLOSSOM_AUTONOMY_START_DATE = date(2026, 3, 29)
BLOSSOM_KEYWORDS = (
    "cherry blossom",
    "cherry-blossom",
    "blossom",
    "sakura",
    "벚꽃",
    "왕벚꽃",
    "겹벚꽃",
    "봄꽃",
)


class QualityGateError(Exception):
    def __init__(self, message: str, *, payload: dict | None = None) -> None:
        super().__init__(message)
        self.payload = payload or {}


def _is_enabled_setting(raw_value: str | bool | None, default: bool = False) -> bool:
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _require_enabled_step(blog, stage_type: WorkflowStageType):
    step = get_workflow_step(blog, stage_type)
    if not step:
        raise ValueError(f"{blog.name} blog is missing '{stage_label(stage_type)}' stage.")
    if not step.is_enabled:
        raise ValueError(f"{blog.name} blog has '{stage_label(stage_type)}' stage disabled.")
    return step


def _get_optional_enabled_step(blog, stage_type: WorkflowStageType):
    step = get_workflow_step(blog, stage_type)
    if step and step.is_enabled:
        return step
    return None


def _stage_allows_large_text_model(stage_type: WorkflowStageType) -> bool:
    return stage_type in {
        WorkflowStageType.TOPIC_DISCOVERY,
        WorkflowStageType.ARTICLE_GENERATION,
        WorkflowStageType.IMAGE_PROMPT_GENERATION,
    }


def _default_stage_text_model(*, stage_type: WorkflowStageType, runtime) -> str:
    if str(getattr(runtime, "text_runtime_kind", "") or "").strip().lower() == CODEX_TEXT_RUNTIME_KIND:
        return str(getattr(runtime, "text_runtime_model", "") or CODEX_TEXT_RUNTIME_MODEL).strip() or CODEX_TEXT_RUNTIME_MODEL
    if stage_type == WorkflowStageType.TOPIC_DISCOVERY:
        return runtime.topic_discovery_model or FREE_TIER_DEFAULT_LARGE_TEXT_MODEL
    if stage_type == WorkflowStageType.ARTICLE_GENERATION:
        return FREE_TIER_DEFAULT_LARGE_TEXT_MODEL
    return runtime.openai_text_model


def _resolve_stage_text_model(*, stage_type: WorkflowStageType, configured_model: str | None, runtime) -> str:
    if str(getattr(runtime, "text_runtime_kind", "") or "").strip().lower() == CODEX_TEXT_RUNTIME_KIND:
        return str(configured_model or getattr(runtime, "text_runtime_model", "") or CODEX_TEXT_RUNTIME_MODEL).strip() or CODEX_TEXT_RUNTIME_MODEL
    allow_large = _stage_allows_large_text_model(stage_type)
    fallback_model = configured_model or _default_stage_text_model(stage_type=stage_type, runtime=runtime)
    return resolve_free_tier_text_model(fallback_model, allow_large=allow_large)


def _resolve_stage_text_model_for_call(
    db,
    *,
    stage_type: WorkflowStageType,
    configured_model: str | None,
    runtime,
    job=None,
    provider_hint: str | None = None,
) -> str:
    fallback_model = configured_model or _default_stage_text_model(stage_type=stage_type, runtime=runtime)
    normalized_provider_hint = str(provider_hint or getattr(runtime, "text_runtime_kind", "") or "").strip().lower()
    if normalized_provider_hint == CODEX_TEXT_RUNTIME_KIND:
        return str(fallback_model or getattr(runtime, "text_runtime_model", "") or CODEX_TEXT_RUNTIME_MODEL).strip() or CODEX_TEXT_RUNTIME_MODEL
    allow_large = _stage_allows_large_text_model(stage_type)

    if runtime.provider_mode != "live":
        return resolve_free_tier_text_model(fallback_model, allow_large=allow_large)

    decision = route_openai_free_tier_text_model(
        db,
        requested_model=fallback_model,
        allow_large=allow_large,
        minimum_remaining_tokens=1,
    )
    if decision.reasons:
        add_log(
            db,
            job=job,
            stage=f"model_router:{stage_type.value}",
            message=f"Model routing applied for stage '{stage_type.value}'.",
            payload=decision.to_payload(),
        )
    return decision.resolved_model


def _is_travel_blog(blog) -> bool:
    return blog.profile_key == "korea_travel" or (blog.content_category or "").lower() == "travel"


def _parse_float_setting(raw_value: str | float | int | None, fallback: float) -> float:
    try:
        return float(str(raw_value if raw_value is not None else fallback).strip())
    except (TypeError, ValueError):
        return fallback


def _quality_gate_thresholds(settings_map: dict[str, str]) -> dict[str, float]:
    return {
        "enabled": 1.0 if _is_enabled_setting(settings_map.get("quality_gate_enabled"), default=True) else 0.0,
        "similarity_threshold": _parse_float_setting(settings_map.get("quality_gate_similarity_threshold"), 65.0),
        "min_seo_score": _parse_float_setting(settings_map.get("quality_gate_min_seo_score"), 70.0),
        "min_geo_score": _parse_float_setting(settings_map.get("quality_gate_min_geo_score"), 60.0),
    }


def _quality_gate_fail_reasons(
    *,
    similarity_score: float,
    seo_score: float,
    geo_score: float,
    similarity_threshold: float,
    min_seo_score: float,
    min_geo_score: float,
) -> list[str]:
    reasons: list[str] = []
    if similarity_score >= similarity_threshold:
        reasons.append("similarity_threshold")
    if seo_score < min_seo_score:
        reasons.append("seo_below_min")
    if geo_score < min_geo_score:
        reasons.append("geo_below_min")
    return reasons


def _is_blossom_topic_keyword(keyword: str | None) -> bool:
    lowered = (keyword or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in BLOSSOM_KEYWORDS)


def _load_daily_topic_mix_counter(raw_value: str | None, *, today: str) -> dict[str, int]:
    try:
        payload = json.loads(raw_value or "{}")
    except Exception:  # noqa: BLE001
        payload = {}
    if str(payload.get("date") or "") != today:
        return {"total_topics": 0, "blossom_topics": 0}
    try:
        total_topics = max(int(payload.get("total_topics") or 0), 0)
    except (TypeError, ValueError):
        total_topics = 0
    try:
        blossom_topics = max(int(payload.get("blossom_topics") or 0), 0)
    except (TypeError, ValueError):
        blossom_topics = 0
    return {
        "total_topics": total_topics,
        "blossom_topics": blossom_topics,
    }


def _dump_daily_topic_mix_counter(*, today: str, counter: dict[str, int]) -> str:
    return json.dumps(
        {
            "date": today,
            "total_topics": max(int(counter.get("total_topics") or 0), 0),
            "blossom_topics": max(int(counter.get("blossom_topics") or 0), 0),
        },
        ensure_ascii=False,
    )


def _would_exceed_blossom_cap(*, counter: dict[str, int], is_blossom: bool, cap_ratio: float) -> bool:
    if not is_blossom:
        return False
    normalized_cap = max(min(cap_ratio, 1.0), 0.0)
    if normalized_cap <= 0.0:
        return True
    if normalized_cap >= 1.0:
        return False
    total_next = max(int(counter.get("total_topics") or 0), 0) + 1
    blossom_next = max(int(counter.get("blossom_topics") or 0), 0) + 1
    max_allowed_blossom = max(1, math.floor(float(total_next) * normalized_cap))
    return blossom_next > max_allowed_blossom


def _increment_daily_mix_counter(counter: dict[str, int], *, is_blossom: bool) -> None:
    counter["total_topics"] = max(int(counter.get("total_topics") or 0), 0) + 1
    if is_blossom:
        counter["blossom_topics"] = max(int(counter.get("blossom_topics") or 0), 0) + 1


def _build_blossom_cap_prompt(*, blocked_keywords: list[str], cap_ratio: float, limit: int = 20) -> str:
    if not blocked_keywords:
        return ""
    unique_keywords: list[str] = []
    seen: set[str] = set()
    for raw in blocked_keywords:
        value = (raw or "").strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_keywords.append(value)
        if len(unique_keywords) >= max(limit, 1):
            break
    if not unique_keywords:
        return ""
    bullet_list = "\n".join(f"- {value}" for value in unique_keywords)
    return (
        "\n\n[Daily topic mix cap]\n"
        f"- Cherry blossom topics are capped at {cap_ratio * 100:.0f}% for this channel today.\n"
        "- Discover a different non-blossom cluster and angle.\n"
        "- Do not return cherry blossom, blossom festival, sakura, spring bloom, or petal-viewing topics in this attempt.\n"
        "- Blocked blossom topics in this run:\n"
        f"{bullet_list}"
    )


def _resolve_editorial_guidance(
    *,
    blog,
    editorial_category_key: str | None,
    editorial_category_label: str | None,
    editorial_category_guidance: str | None,
) -> tuple[str, str, str]:
    key = (editorial_category_key or "").strip().lower()
    label = (editorial_category_label or "").strip()
    guidance = (editorial_category_guidance or "").strip()

    if key and label and guidance:
        return key, label, guidance

    if blog.profile_key == "korea_travel":
        if not key:
            key = "travel"
        if not label:
            label = {"travel": "Travel", "culture": "Culture", "food": "Food"}.get(key, "Travel")
        if not guidance:
            guidance = TRAVEL_EDITORIAL_GUIDANCE.get(key, TRAVEL_EDITORIAL_GUIDANCE["travel"])
        return key, label, guidance

    if blog.profile_key == "world_mystery":
        if not key:
            key = "case-files"
        if not label:
            label = {
                "case-files": "Case Files",
                "legends-lore": "Legends & Lore",
                "mystery-archives": "Mystery Archives",
            }.get(key, "Case Files")
        if not guidance:
            guidance = MYSTERY_EDITORIAL_GUIDANCE.get(key, MYSTERY_EDITORIAL_GUIDANCE["case-files"])
        return key, label, guidance

    return key, label, guidance


def _travel_3x3_prompt_missing_requirements(prompt: str) -> list[str]:
    lowered = (prompt or "").strip().lower()
    missing: list[str] = []
    if not any(token in lowered for token in ("3x3", "3 x 3", "9-panel", "nine-panel")):
        missing.append("missing_3x3_or_9panel")
    if not any(token in lowered for token in ("collage", "grid", "panel")):
        missing.append("missing_collage_grid_terms")
    if "center panel" not in lowered and "middle panel" not in lowered:
        missing.append("missing_center_panel_emphasis")
    if "gutter" not in lowered and "border" not in lowered:
        missing.append("missing_visible_gutter_or_border")
    return missing


def _travel_3x3_size_missing_requirements(width: int, height: int) -> list[str]:
    missing: list[str] = []
    if width <= 0 or height <= 0:
        missing.append("invalid_dimensions")
    elif width >= height:
        missing.append("not_portrait_ratio")
    return missing


def _build_travel_3x3_retry_prompt(*, keyword: str, title: str, original_prompt: str) -> str:
    return (
        "Create one composite editorial 3x3 travel collage with exactly 9 distinct rectangular photo panels. "
        "The center panel must be visually dominant and noticeably larger than each surrounding panel. "
        "Use clean visible white gutters between panels. "
        "Do not blend panels into one continuous scene. "
        "No text overlays, no logos. "
        f"Topic: {keyword}. Title context: {title}. "
        f"Story direction: {original_prompt}"
    )


def _build_travel_inline_3x2_prompt(*, keyword: str, title: str, original_prompt: str) -> str:
    try:
        template = TRAVEL_INLINE_PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        template = ""
    if template:
        return (
            template.replace("{keyword}", keyword)
            .replace("{title}", title)
            .replace("{story_direction}", original_prompt)
            .strip()
        )
    return (
        "Create one supporting travel collage image for in-article placement. "
        "Layout must be a 3x2 grid with exactly 6 distinct rectangular panels. "
        "Use visible white gutters between panels and coherent documentary-style travel photography. "
        "No text overlays, no logos, no watermark. "
        f"Topic: {keyword}. Title context: {title}. "
        f"Story direction: {original_prompt}"
    )


def _build_blogger_inline_3x2_prompt(
    *,
    blog,
    keyword: str,
    article_title: str,
    article_excerpt: str,
    article_context: str,
    original_prompt: str,
    editorial_category_label: str,
    inline_collage_prompt: str | None,
) -> str:
    if str(inline_collage_prompt or "").strip():
        return str(inline_collage_prompt).strip()

    safe_story_direction = (original_prompt or "").strip()
    if len(safe_story_direction) > 220:
        safe_story_direction = safe_story_direction[:220].rstrip()

    is_mystery = blog.profile_key == "world_mystery" or (blog.content_category or "").lower() == "mystery"
    language = _normalize_supported_language(resolve_blog_bundle_language(blog) or blog.primary_language)
    language_persona_hint = (
        "Japanese 20-40 independent travelers prioritizing route flow, crowd avoidance, and budget control."
        if language == "ja"
        else "Global Spanish-speaking travelers; keep hooks clear and practical without regional slang lock-in."
        if language == "es"
        else "US-first travelers with UK/EU planning expectations mixed in."
    )
    profile_hint = "documentary mystery" if is_mystery else "travel editorial"
    subject_focus = "evidence, records, place atmosphere, and theory comparison" if is_mystery else (
        "route flow, timing decisions, neighborhood atmosphere, and practical movement"
    )
    return (
        "Create one supporting in-article collage image. "
        "Layout must be a 3x2 grid with exactly 6 distinct panels and visible white gutters. "
        "Match the article topic and keep the scene documentary, realistic, and editorial. "
        f"Focus on {subject_focus}. "
        f"Persona hint: {language_persona_hint} "
        "No text overlays, no logos, no watermark. "
        f"Profile: {profile_hint}. Category: {editorial_category_label or profile_hint}. "
        f"Topic: {keyword}. Title: {article_title}. Excerpt: {article_excerpt}. Story direction: {safe_story_direction}"
    )


def _blogger_inline_collage_enabled(settings_map: dict[str, str], blog) -> bool:
    if blog.profile_key == "world_mystery" or (blog.content_category or "").lower() == "mystery":
        return _is_enabled_setting(settings_map.get("mystery_inline_collage_enabled"), default=True)
    if _is_travel_blog(blog):
        return _is_enabled_setting(settings_map.get("travel_inline_collage_enabled"), default=True)
    return False


def _append_blogger_seo_trust_guard(prompt: str, *, blog, current_date: str) -> str:
    profile_key = str(getattr(blog, "profile_key", "") or "").strip().lower()
    if profile_key not in {"korea_travel", "world_mystery"}:
        return prompt

    common_rules = [
        "[SEO trust + source integrity guard]",
        f'- Include one explicit absolute-date timestamp line: "As of {current_date}".',
        "- Add one dedicated section that separates confirmed facts from unverified details.",
        "- Add one dedicated section for source/verification path with 2-5 concrete source channels.",
        '- If no verifiable source URL exists, explicitly say "No verified source URL yet".',
        "- Never present assumptions, rumors, or secondary reposts as confirmed facts.",
        "- Avoid clickbait superlatives unless directly supported by verifiable evidence.",
    ]
    if profile_key == "world_mystery":
        common_rules.append("- For SCP or fiction-universe topics, clearly label fiction context near the top.")
    if profile_key == "korea_travel":
        common_rules.append("- For schedule, price, entry, and transport details, use recheck wording when uncertain.")

    return f"{prompt}\n\n" + "\n".join(common_rules) + "\n"


def _append_no_inline_image_rule(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "[Inline image policy]\n"
        "- Do not output inline image tags or markdown image syntax in article body.\n"
        "- Never include <img>, <figure>, ![...](...) or collage marker text in body content.\n"
        "- If the output schema includes inline_collage_prompt, use that separate field for one mid-article supporting collage.\n"
        "- Keep raw image markup out of body content because the system inserts visuals after generation.\n"
    )


def _append_hero_only_visual_rule(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "[Hero image policy]\n"
        "- Generate one hero-cover image prompt only.\n"
        "- Use one composite 3x3 collage with exactly 9 distinct panels.\n"
        "- Keep visible white gutters between panels and make the center panel visually dominant.\n"
        "- Do not request inline, middle, secondary, or body images.\n"
        "- Do not include panel marker text inside article content.\n"
    )


def _extract_planner_brief_payload(job) -> dict:
    raw_prompts = job.raw_prompts if isinstance(getattr(job, "raw_prompts", None), dict) else {}
    planner_brief = raw_prompts.get("planner_brief")
    if isinstance(planner_brief, dict):
        return planner_brief
    return {}


def _format_planner_brief_for_prompt(planner_brief_payload: dict) -> str:
    if not planner_brief_payload:
        return "No planner brief provided."

    lines: list[str] = [
        f"Topic: {str(planner_brief_payload.get('topic') or '').strip()}",
        f"Audience: {str(planner_brief_payload.get('audience') or '').strip()}",
        f"Information level: {str(planner_brief_payload.get('information_level') or '').strip()}",
        f"Category: {str(planner_brief_payload.get('category_name') or planner_brief_payload.get('category_key') or '').strip()}",
    ]
    bundle_key = str(planner_brief_payload.get("bundle_key") or "").strip()
    if bundle_key:
        lines.append(f"Bundle key: {bundle_key}")

    facts = planner_brief_payload.get("facts")
    if isinstance(facts, list) and facts:
        lines.append("Confirmed facts:")
        lines.extend(f"- {str(item).strip()}" for item in facts if str(item).strip())

    prohibited_claims = planner_brief_payload.get("prohibited_claims")
    if isinstance(prohibited_claims, list) and prohibited_claims:
        lines.append("Prohibited claims:")
        lines.extend(f"- {str(item).strip()}" for item in prohibited_claims if str(item).strip())

    notes = str(planner_brief_payload.get("context_notes") or "").strip()
    if notes:
        lines.append(f"Context notes: {notes}")

    scheduled_for = str(planner_brief_payload.get("scheduled_for") or "").strip()
    if scheduled_for:
        lines.append(f"Scheduled for: {scheduled_for}")

    recommended_publish_at = str(planner_brief_payload.get("recommended_publish_at") or "").strip()
    if recommended_publish_at:
        lines.append(f"Recommended publish time: {recommended_publish_at}")

    cleaned = [line for line in lines if line and not line.endswith(": ")]
    return "\n".join(cleaned) if cleaned else "No planner brief provided."


def _normalize_supported_language(value: str | None) -> str | None:
    lowered = str(value or "").strip().lower()
    if lowered in SUPPORTED_LANGUAGES:
        return lowered
    if lowered.startswith("en"):
        return "en"
    if lowered.startswith("ja"):
        return "ja"
    if lowered.startswith("es"):
        return "es"
    return None


def _resolve_article_language(article: Article) -> str | None:
    blog = getattr(article, "blog", None)
    resolved = _normalize_supported_language(resolve_blog_bundle_language(blog) if blog else None)
    if resolved:
        return resolved
    if blog is not None:
        return _normalize_supported_language(getattr(blog, "primary_language", None))
    return None


def _list_bundle_articles(db, *, bundle_key: str) -> list[Article]:
    normalized_bundle_key = str(bundle_key or "").strip()
    if not normalized_bundle_key:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    candidates = (
        db.execute(
            select(Article)
            .where(Article.created_at >= cutoff)
            .options(
                selectinload(Article.job),
                selectinload(Article.blog),
                selectinload(Article.blogger_post),
            )
            .order_by(Article.created_at.desc())
        )
        .scalars()
        .all()
    )
    selected: list[Article] = []
    for article in candidates:
        if not article.job:
            continue
        planner_brief = _extract_planner_brief_payload(article.job)
        if str(planner_brief.get("bundle_key") or "").strip() != normalized_bundle_key:
            continue
        selected.append(article)
    return selected


def _build_bundle_language_url_map(bundle_articles: list[Article]) -> dict[str, str]:
    url_map: dict[str, str] = {}
    for article in bundle_articles:
        language = _resolve_article_language(article)
        if language not in SUPPORTED_LANGUAGES:
            continue
        post = article.blogger_post
        if post is None:
            continue
        if post.post_status not in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
            continue
        url = str(post.published_url or "").strip()
        if url and language not in url_map:
            url_map[language] = url
    return url_map


def _sync_multilingual_bundle_links(
    db,
    *,
    bundle_key: str,
) -> dict:
    normalized_bundle_key = str(bundle_key or "").strip()
    if not normalized_bundle_key:
        return {"status": "skipped", "reason": "bundle_key_missing"}

    bundle_articles = _list_bundle_articles(db, bundle_key=normalized_bundle_key)
    if not bundle_articles:
        return {"status": "skipped", "reason": "bundle_articles_not_found", "bundle_key": normalized_bundle_key}

    url_map = _build_bundle_language_url_map(bundle_articles)
    missing_languages = [lang for lang in SUPPORTED_LANGUAGES if not url_map.get(lang)]
    if missing_languages:
        return {
            "status": "pending",
            "bundle_key": normalized_bundle_key,
            "available_languages": sorted(url_map.keys()),
            "missing_languages": missing_languages,
        }

    updated_articles = 0
    updated_remote_posts = 0
    failures: list[dict[str, str]] = []

    for article in bundle_articles:
        language = _resolve_article_language(article)
        if language not in SUPPORTED_LANGUAGES:
            continue
        post = article.blogger_post
        if post is None or not post.blogger_post_id:
            continue
        if not article.blog:
            continue

        language_switch_block = build_language_switch_block(
            current_language=language,
            urls_by_language=url_map,
        )
        if not language_switch_block:
            continue

        current_html = (article.assembled_html or article.html_article or "").strip()
        if not current_html:
            continue
        updated_html = upsert_language_switch_html(current_html, language_switch_block).strip()
        if updated_html == current_html:
            continue

        labels = ensure_article_editorial_labels(db, article, commit=False)
        article.assembled_html = updated_html
        db.add(article)
        db.commit()
        db.refresh(article)
        updated_articles += 1

        try:
            provider = get_blogger_provider(db, article.blog)
            summary, raw_payload = provider.update_post(
                post_id=post.blogger_post_id,
                title=article.title,
                content=updated_html,
                labels=labels,
                meta_description=article.meta_description,
            )
            _upsert_blogger_post(
                db,
                job_id=article.job_id,
                blog_id=article.blog_id,
                article_id=article.id,
                summary=summary,
                raw_payload=raw_payload,
            )
            updated_remote_posts += 1
        except Exception as exc:  # noqa: BLE001
            failures.append(
                {
                    "article_id": str(article.id),
                    "blog_id": str(article.blog_id),
                    "message": str(exc),
                }
            )

    return {
        "status": "applied" if not failures else "partial",
        "bundle_key": normalized_bundle_key,
        "updated_articles": updated_articles,
        "updated_remote_posts": updated_remote_posts,
        "url_map": url_map,
        "failures": failures,
    }


def _assess_blogger_quality_gate(
    db,
    *,
    blog,
    article,
    thresholds: dict[str, float],
) -> dict[str, object]:
    article_body = (article.assembled_html or article.html_article or "").strip()
    seo_geo = compute_seo_geo_scores(
        title=article.title,
        html_body=article_body,
        excerpt=article.excerpt,
        faq_section=list(article.faq_section or []),
    )

    candidates = db.execute(
        select(Article, BloggerPost)
        .join(Blog, Blog.id == Article.blog_id)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .where(
            Blog.profile_key == blog.profile_key,
            Article.id != article.id,
            BloggerPost.post_status.in_([PostStatus.PUBLISHED, PostStatus.SCHEDULED]),
        )
    ).all()

    similarity_score = 0.0
    most_similar_url = ""
    if candidates:
        similarity_items = [
            {
                "key": "current",
                "title": article.title,
                "body_html": article_body,
                "url": "",
            }
        ]
        for candidate_article, candidate_post in candidates:
            similarity_items.append(
                {
                    "key": f"article-{candidate_article.id}",
                    "title": candidate_article.title,
                    "body_html": (candidate_article.assembled_html or candidate_article.html_article or ""),
                    "url": candidate_post.published_url or "",
                }
            )
        similarity_map = compute_similarity_analysis(similarity_items)
        current_payload = similarity_map.get("current", {})
        similarity_score = float(current_payload.get("similarity_score", 0.0) or 0.0)
        most_similar_url = str(current_payload.get("most_similar_url") or "").strip()

    seo_score = float(seo_geo.get("seo_score", 0) or 0)
    geo_score = float(seo_geo.get("geo_score", 0) or 0)
    reasons = _quality_gate_fail_reasons(
        similarity_score=similarity_score,
        seo_score=seo_score,
        geo_score=geo_score,
        similarity_threshold=float(thresholds["similarity_threshold"]),
        min_seo_score=float(thresholds["min_seo_score"]),
        min_geo_score=float(thresholds["min_geo_score"]),
    )
    trust_assessment = assess_publish_trust_requirements(article_body)
    for trust_reason in trust_assessment.get("reasons", []):
        if trust_reason not in reasons:
            reasons.append(str(trust_reason))
    return {
        "similarity_score": round(similarity_score, 1),
        "most_similar_url": most_similar_url,
        "seo_score": int(round(seo_score)),
        "geo_score": int(round(geo_score)),
        "reasons": reasons,
        "passed": len(reasons) == 0,
        "plain_text_length": int(seo_geo.get("plain_text_length", 0) or 0),
        "trust_gate": trust_assessment,
    }


def _build_quality_gate_retry_prompt(
    *,
    base_prompt: str,
    failed_assessment: dict[str, object],
) -> str:
    reasons = ", ".join(failed_assessment.get("reasons", [])) or "quality gate thresholds"
    similar_url = str(failed_assessment.get("most_similar_url") or "").strip()
    similarity_score = failed_assessment.get("similarity_score", 0)
    return (
        f"{base_prompt}\n\n"
        "[Quality gate retry instruction]\n"
        "- Rewrite this article with a different structure and paragraph flow while preserving factual topic intent.\n"
        f"- Prior attempt failed on: {reasons}.\n"
        f"- Similarity score was {similarity_score}.\n"
        f"- Most similar existing URL: {similar_url or 'N/A'}.\n"
        "- Increase uniqueness of opening and section ordering.\n"
        "- Keep SEO/GEO utility strong with concrete entities, actionable checkpoints, and clear headings.\n"
    )


def _sync_quality_sheet_best_effort(db, *, profile_key: str) -> dict[str, object]:
    try:
        return sync_google_sheet_snapshot(db, initial=False)
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "reason": str(exc)}


def _run_blogger_quality_gate(
    db,
    *,
    blog,
    job,
    topic,
    article,
    initial_output,
    article_configured_model: str | None,
    article_provider_hint: str | None,
    runtime,
    base_prompt: str,
    thresholds: dict[str, float],
):
    if not bool(thresholds.get("enabled", 1.0)):
        return article, initial_output, {
            "enabled": False,
            "passed": True,
            "attempts": [],
            "reason": "disabled",
            "sheet_sync": _sync_quality_sheet_best_effort(db, profile_key=blog.profile_key),
        }

    assessments: list[dict[str, object]] = []
    working_article = article
    working_output = initial_output
    for attempt in range(1, 3):
        assessment = _assess_blogger_quality_gate(
            db,
            blog=blog,
            article=working_article,
            thresholds=thresholds,
        )
        assessment["attempt"] = attempt
        assessments.append(assessment)
        if bool(assessment.get("passed")):
            break
        if attempt >= 2:
            break

        retry_prompt = _build_quality_gate_retry_prompt(base_prompt=base_prompt, failed_assessment=assessment)
        merge_prompt(db, job, "quality_gate_retry_prompt", retry_prompt)
        retry_model = _resolve_stage_text_model_for_call(
            db,
            stage_type=WorkflowStageType.ARTICLE_GENERATION,
            configured_model=article_configured_model,
            runtime=runtime,
            job=job,
            provider_hint=article_provider_hint,
        )
        retry_provider = get_article_provider(
            db,
            model_override=retry_model,
            provider_hint=article_provider_hint,
            allow_large=True,
        )
        retry_output, retry_raw = retry_provider.generate_article(job.keyword_snapshot, retry_prompt)
        retry_output = apply_pattern_defaults(
            retry_output,
            select_blogger_article_pattern(
                db,
                blog_id=blog.id,
                profile_key=blog.profile_key,
                editorial_category_key=(topic.editorial_category_key if topic else None),
            ),
        )
        merge_response(
            db,
            job,
            "quality_gate_retry_response",
            {
                "attempt": attempt + 1,
                "raw": retry_raw,
            },
        )
        working_article = save_article(db, job=job, topic=topic, output=retry_output)
        working_output = retry_output
        working_article.inline_media = []
        db.add(working_article)
        db.commit()
        db.refresh(working_article)

    final_assessment = assessments[-1]
    gate_payload = {
        "enabled": True,
        "passed": bool(final_assessment.get("passed")),
        "attempts": assessments,
        "scores": {
            "similarity_score": final_assessment.get("similarity_score"),
            "most_similar_url": final_assessment.get("most_similar_url"),
            "seo_score": final_assessment.get("seo_score"),
            "geo_score": final_assessment.get("geo_score"),
        },
        "thresholds": {
            "similarity_threshold": thresholds["similarity_threshold"],
            "min_seo_score": thresholds["min_seo_score"],
            "min_geo_score": thresholds["min_geo_score"],
        },
        "reason": ",".join(final_assessment.get("reasons", [])),
        "sheet_sync": _sync_quality_sheet_best_effort(db, profile_key=blog.profile_key),
    }
    persist_article_quality_cache(
        db,
        article=working_article,
        similarity_score=(
            float(final_assessment.get("similarity_score"))
            if final_assessment.get("similarity_score") is not None
            else None
        ),
        most_similar_url=str(final_assessment.get("most_similar_url") or ""),
        seo_score=(
            int(final_assessment.get("seo_score"))
            if final_assessment.get("seo_score") is not None
            else None
        ),
        geo_score=(
            int(final_assessment.get("geo_score"))
            if final_assessment.get("geo_score") is not None
            else None
        ),
        quality_status="ok" if gate_payload["passed"] else "quality_gate_failed",
        rewrite_attempts=max(0, len(assessments) - 1),
    )
    db.commit()
    db.refresh(working_article)
    if not gate_payload["passed"]:
        raise QualityGateError("quality_gate_failed", payload=gate_payload)
    return working_article, working_output, gate_payload


def _upsert_image(
    db,
    *,
    job_id: int,
    article_id: int,
    prompt: str,
    file_path: str,
    public_url: str,
    provider: str,
    meta: dict,
) -> Image:
    image = db.execute(select(Image).where(Image.job_id == job_id)).scalar_one_or_none()
    payload = {
        "article_id": article_id,
        "prompt": prompt,
        "file_path": file_path,
        "public_url": public_url,
        "width": int(meta.get("width", 1536)),
        "height": int(meta.get("height", 1024)),
        "provider": provider,
        "image_metadata": meta,
    }
    if image:
        for key, value in payload.items():
            setattr(image, key, value)
    else:
        image = Image(job_id=job_id, **payload)
        db.add(image)
    db.commit()
    db.refresh(image)
    return image


def _upsert_blogger_post(
    db,
    *,
    job_id: int,
    blog_id: int,
    article_id: int,
    summary: dict,
    raw_payload: dict,
) -> BloggerPost:
    post = db.execute(select(BloggerPost).where(BloggerPost.job_id == job_id)).scalar_one_or_none()
    published_at = _parse_datetime(summary.get("published"))
    scheduled_for = _parse_datetime(summary.get("scheduledFor"))

    post_status_value = summary.get("postStatus")
    if post_status_value:
        post_status = PostStatus(post_status_value)
    else:
        post_status = PostStatus.DRAFT if bool(summary.get("isDraft", True)) else PostStatus.PUBLISHED

    payload = {
        "blog_id": blog_id,
        "article_id": article_id,
        "blogger_post_id": summary.get("id", f"job-{job_id}"),
        "published_url": summary.get("url", ""),
        "published_at": published_at,
        "is_draft": post_status == PostStatus.DRAFT,
        "post_status": post_status,
        "scheduled_for": scheduled_for,
        "response_payload": raw_payload,
    }
    if post:
        for key, value in payload.items():
            setattr(post, key, value)
    else:
        post = BloggerPost(job_id=job_id, **payload)
        db.add(post)
    db.commit()
    db.refresh(post)
    return post


def _coerce_non_negative_int(raw_value: str | int | None, fallback: int) -> int:
    try:
        parsed = int(str(raw_value if raw_value is not None else fallback).strip())
    except (TypeError, ValueError):
        return fallback
    return max(parsed, 0)


def _parse_datetime(value: str | datetime | None, *, timezone_name: str = "UTC") -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def _resolve_topic_provider(runtime, provider_hint: str | None = None) -> str:
    provider = (provider_hint or runtime.topic_discovery_provider or getattr(runtime, "text_runtime_kind", "") or "openai").strip().lower()
    if provider == "openai_text":
        return "openai"
    return provider


def _enforce_topic_provider_limits(
    db,
    *,
    blog,
    provider_hint: str | None = None,
    model_override: str | None = None,
) -> str:
    runtime = get_runtime_config(db)
    provider = _resolve_topic_provider(runtime, provider_hint)
    if runtime.provider_mode != "live":
        return provider

    if provider == "openai":
        add_log(
            db,
            job=None,
            stage=OPENAI_TOPIC_REQUEST_STAGE,
            message=f"{blog.name} topic discovery is requesting OpenAI.",
            payload={
                "blog_id": blog.id,
                "blog_slug": blog.slug,
                "provider": "openai",
                "model": model_override or runtime.topic_discovery_model or runtime.openai_text_model,
            },
        )
        return provider

    if not runtime.gemini_api_key:
        return provider

    settings_map = get_settings_map(db)
    minute_limit = _coerce_non_negative_int(settings_map.get("gemini_requests_per_minute_limit"), 2)
    daily_limit = _coerce_non_negative_int(settings_map.get("gemini_daily_request_limit"), 6)
    now = datetime.now(timezone.utc)

    if minute_limit > 0:
        recent_count = count_logs_since(db, stage=GEMINI_TOPIC_REQUEST_STAGE, since=now - timedelta(minutes=1))
        if recent_count >= minute_limit:
            message = "Gemini per-minute topic discovery limit reached."
            detail = f"Recent 1-minute requests: {recent_count}, limit: {minute_limit}."
            add_log(
                db,
                job=None,
                stage=GEMINI_TOPIC_LIMIT_BLOCKED_STAGE,
                message=message,
                level=LogLevel.WARNING,
                payload={"blog_id": blog.id, "window": "1m", "count": recent_count, "limit": minute_limit, "provider": "gemini"},
            )
            raise ProviderRuntimeError(provider="gemini", status_code=429, message=message, detail=detail)

    if daily_limit > 0:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_count = count_logs_since(db, stage=GEMINI_TOPIC_REQUEST_STAGE, since=today_start)
        if daily_count >= daily_limit:
            message = "Gemini daily topic discovery limit reached."
            detail = f"Today requests: {daily_count}, daily limit: {daily_limit}."
            add_log(
                db,
                job=None,
                stage=GEMINI_TOPIC_LIMIT_BLOCKED_STAGE,
                message=message,
                level=LogLevel.WARNING,
                payload={"blog_id": blog.id, "window": "1d", "count": daily_count, "limit": daily_limit, "provider": "gemini"},
            )
            raise ProviderRuntimeError(provider="gemini", status_code=429, message=message, detail=detail)

    add_log(
        db,
        job=None,
        stage=GEMINI_TOPIC_REQUEST_STAGE,
        message=f"{blog.name} topic discovery is requesting Gemini.",
        payload={
            "blog_id": blog.id,
            "blog_slug": blog.slug,
            "provider": "gemini",
            "model": model_override or runtime.gemini_model,
        },
    )
    return provider


def _normalize_stop_after(raw_value: str | JobStatus | None) -> JobStatus | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, JobStatus):
        return raw_value if raw_value in PIPELINE_STOP_ALLOWED else None

    value = str(raw_value).strip()
    if not value or value.lower() in {"none", "full", "disabled"}:
        return None

    try:
        status = JobStatus(value)
    except ValueError:
        return None
    return status if status in PIPELINE_STOP_ALLOWED else None


def _resolve_stop_after(settings_map: dict[str, str], *, override: str | JobStatus | None = None) -> JobStatus | None:
    if override is not None:
        return _normalize_stop_after(override)
    return _normalize_stop_after(settings_map.get("pipeline_stop_after"))


def _serialize_pipeline_control(stop_after: JobStatus | None) -> dict[str, str | None]:
    return {"stop_after": stop_after.value if stop_after else None}


def _job_stop_after(job) -> JobStatus | None:
    control = dict(job.raw_prompts or {}).get(PIPELINE_CONTROL_KEY, {})
    if isinstance(control, dict):
        return _normalize_stop_after(control.get("stop_after"))
    return None


def _serialize_publish_schedule(
    *,
    mode: PublishMode,
    scheduled_for: datetime | None,
    slot_index: int,
    interval_minutes: int,
    topic_count: int,
) -> dict[str, str | int | None]:
    return {
        "mode": mode.value,
        "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
        "slot_index": slot_index,
        "interval_minutes": interval_minutes,
        "topic_count": topic_count,
    }


def _job_publish_schedule(job) -> dict:
    schedule = dict(job.raw_prompts or {}).get(PIPELINE_SCHEDULE_KEY, {})
    return schedule if isinstance(schedule, dict) else {}


def _resolve_publish_target_datetime(job) -> datetime | None:
    schedule = _job_publish_schedule(job)
    return _parse_datetime(schedule.get("scheduled_for"))


def _complete_early_if_needed(db, job, *, completed_stage: JobStatus, blog) -> bool:
    stop_after = _job_stop_after(job)
    if stop_after != completed_stage:
        return False

    payload = {
        "mode": "partial",
        "stop_after_status": stop_after.value,
        "completed_stage": completed_stage.value,
    }
    merge_response(db, job, PIPELINE_CONTROL_KEY, payload)
    finished_stage_label = PIPELINE_STAGE_LABELS.get(completed_stage, completed_stage.value)
    set_status(
        db,
        job,
        JobStatus.STOPPED,
        f"{blog.name} pipeline stopped after {finished_stage_label} stage.",
        payload=payload,
    )
    return True


def _resolve_publish_mode(
    *,
    publish_mode: str | None,
    scheduled_start: str | datetime | None,
) -> PublishMode:
    if publish_mode:
        return PublishMode(publish_mode)
    if scheduled_start is not None:
        return PublishMode.PUBLISH
    return PublishMode.DRAFT


def _resolve_topic_count(settings_map: dict[str, str], requested: int | None) -> int:
    fallback = _coerce_non_negative_int(settings_map.get("topics_per_run"), 9) or 9
    if requested is None:
        return min(max(fallback, 1), 20)
    return min(max(int(requested), 1), 20)


def _resolve_publish_interval_minutes(settings_map: dict[str, str], requested: int | None) -> int:
    fallback = _coerce_non_negative_int(settings_map.get("publish_interval_minutes"), 60) or 60
    if requested is None:
        return max(fallback, 1)
    return max(int(requested), 1)


def _resolve_first_publish_datetime(
    settings_map: dict[str, str],
    *,
    scheduled_start: str | datetime | None,
) -> datetime:
    timezone_name = settings_map.get("schedule_timezone", "Asia/Seoul")
    parsed = _parse_datetime(scheduled_start, timezone_name=timezone_name)
    if parsed:
        return parsed.replace(second=0, microsecond=0)

    delay_minutes = _coerce_non_negative_int(settings_map.get("first_publish_delay_minutes"), 60)
    return (datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)).replace(second=0, microsecond=0)


def _resolve_topic_history_settings(settings_map: dict[str, str]) -> tuple[int, float, float, int]:
    lookback_days = max(
        _coerce_non_negative_int(settings_map.get("topic_history_lookback_days"), DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS),
        1,
    )
    cluster_threshold = _parse_float_setting(
        settings_map.get("topic_novelty_cluster_threshold"),
        DEFAULT_TOPIC_NOVELTY_CLUSTER_THRESHOLD,
    )
    angle_threshold = _parse_float_setting(
        settings_map.get("topic_novelty_angle_threshold"),
        DEFAULT_TOPIC_NOVELTY_ANGLE_THRESHOLD,
    )
    penalty_threshold = max(
        _coerce_non_negative_int(settings_map.get("topic_soft_penalty_threshold"), DEFAULT_TOPIC_SOFT_PENALTY_THRESHOLD),
        1,
    )
    return lookback_days, cluster_threshold, angle_threshold, penalty_threshold


def _list_db_topic_history_entries(
    db,
    *,
    blog_id: int,
    lookback_days: int,
    limit: int,
) -> list[TopicHistoryEntry]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(int(lookback_days or 1), 1))
    entries: list[TopicHistoryEntry] = []
    seen: set[str] = set()

    topics = (
        db.execute(
            select(Topic)
            .where(Topic.blog_id == blog_id)
            .order_by(Topic.created_at.desc())
            .limit(max(limit * 3, 100))
        )
        .scalars()
        .all()
    )
    for topic in topics:
        created_at = topic.created_at or datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        created_at = created_at.astimezone(timezone.utc)
        if created_at < cutoff:
            continue
        keyword = (topic.keyword or "").strip()
        if not keyword:
            continue
        dedupe_key = keyword.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entries.append(
            TopicHistoryEntry(
                keyword=keyword,
                topic_cluster=(topic.topic_cluster_label or "").strip(),
                topic_angle=(topic.topic_angle_label or "").strip(),
                category=(topic.editorial_category_label or "").strip(),
                profile="",
                blog="",
                published_at=created_at.isoformat(),
                source="db_topic",
            )
        )
        if len(entries) >= max(limit, 1):
            return entries

    articles = (
        db.execute(
            select(Article)
            .where(Article.blog_id == blog_id)
            .order_by(Article.created_at.desc())
            .limit(max(limit * 3, 100))
        )
        .scalars()
        .all()
    )
    for article in articles:
        created_at = article.created_at or datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        created_at = created_at.astimezone(timezone.utc)
        if created_at < cutoff:
            continue
        title = (article.title or "").strip()
        if not title:
            continue
        dedupe_key = title.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entries.append(
            TopicHistoryEntry(
                keyword=title,
                topic_cluster=(article.editorial_category_label or "").strip(),
                topic_angle="",
                category=(article.editorial_category_label or "").strip(),
                profile="",
                blog="",
                published_at=created_at.isoformat(),
                source="db_article",
            )
        )
        if len(entries) >= max(limit, 1):
            break
    return entries


def _build_topic_history_prompt(entries: list[TopicHistoryEntry], *, limit: int = 28) -> str:
    if not entries:
        return ""
    unique_values: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        value = entry.keyword.strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_values.append(value)
        if len(unique_values) >= max(limit, 1):
            break
    if not unique_values:
        return ""
    bullet_list = "\n".join(f"- {value}" for value in unique_values)
    return (
        "\n\nHard exclusion list from persisted history memory.\n"
        "Do not rephrase existing topics below.\n"
        "If main cluster overlaps, choose a clearly different angle and user task.\n"
        f"{bullet_list}"
    )


def _build_runtime_duplicate_exclusion_prompt(
    *,
    attempted_keywords: list[str],
    limit: int = 24,
) -> str:
    normalized: list[str] = []
    for raw in attempted_keywords:
        keyword = (raw or "").strip()
        if not keyword:
            continue
        lowered = keyword.lower()
        if lowered in normalized:
            continue
        normalized.append(lowered)
        if len(normalized) >= limit:
            break

    if not normalized:
        return ""

    bullet_list = "\n".join(f"- {value}" for value in normalized)
    return (
        "\n\nWithin this run, do not return topics that duplicate or lightly rephrase "
        "any of the following already-attempted keywords:\n"
        f"{bullet_list}"
    )


def _build_runtime_blocked_exclusion_prompt(
    *,
    skipped_duplicates: list[dict[str, str]],
    metadata_by_keyword: dict[str, dict[str, str]],
    limit: int = 24,
) -> str:
    blocked_keywords: list[str] = []
    blocked_cluster_angles: list[str] = []
    seen_keyword: set[str] = set()
    seen_cluster_angle: set[str] = set()

    for item in reversed(skipped_duplicates):
        keyword = (item.get("keyword") or "").strip()
        if keyword and keyword.lower() not in seen_keyword:
            seen_keyword.add(keyword.lower())
            blocked_keywords.append(keyword)
            if len(blocked_keywords) >= limit:
                break

        metadata = metadata_by_keyword.get(keyword, {})
        cluster = (metadata.get("topic_cluster_label") or metadata.get("topic_cluster_key") or "").strip()
        angle = (metadata.get("topic_angle_label") or metadata.get("topic_angle_key") or "").strip()
        if cluster and angle:
            pair = f"{cluster} | {angle}"
            if pair.lower() not in seen_cluster_angle:
                seen_cluster_angle.add(pair.lower())
                blocked_cluster_angles.append(pair)

    if not blocked_keywords and not blocked_cluster_angles:
        return ""

    sections: list[str] = [
        "\n\nHard block from current run duplicate guard.",
        "Generate a materially different topic cluster and angle.",
    ]
    if blocked_keywords:
        keyword_list = "\n".join(f"- {value}" for value in blocked_keywords[:limit])
        sections.append("Do not return these blocked keywords again:\n" + keyword_list)
    if blocked_cluster_angles:
        cluster_list = "\n".join(f"- {value}" for value in blocked_cluster_angles[:limit])
        sections.append("Avoid these blocked cluster|angle pairs:\n" + cluster_list)
    return "\n".join(sections)


def _resolve_schedule_timezone(settings_map: dict[str, str]) -> ZoneInfo:
    timezone_name = (settings_map.get("schedule_timezone") or "Asia/Seoul").strip() or "Asia/Seoul"
    try:
        return ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Seoul")


def _build_travel_topic_discovery_override_prompt(*, blog, now_local: datetime) -> str:
    if blog.profile_key != "korea_travel":
        return ""

    local_date = now_local.date()
    if local_date == TRAVEL_BLOSSOM_FORCE_DATE:
        return (
            "\n\n[Runtime Editorial Override]\n"
            "- Date lock: 2026-03-28 (Asia/Seoul).\n"
            "- For this run, travel topics MUST be cherry blossom themed.\n"
            "- Keep topics local and practical: neighborhood routes, local festivals, crowd timing, transit, and walking plans.\n"
            "- Avoid generic nationwide roundup listicles."
        )

    if local_date >= TRAVEL_BLOSSOM_AUTONOMY_START_DATE:
        return (
            "\n\n[Runtime Editorial Mode]\n"
            "- Date mode: from 2026-03-29 onward.\n"
            "- Use autonomous topic discovery from current prompt rules and editorial category guidance.\n"
            "- Cherry blossom may appear only when justified by trend value; it is not a forced lock."
        )

    return ""


def discover_topics_and_enqueue(
    db,
    blog_id: int,
    publish_mode: str | None = None,
    stop_after: str | JobStatus | None = None,
    topic_count: int | None = None,
    scheduled_start: str | datetime | None = None,
    publish_interval_minutes: int | None = None,
    editorial_category_key: str | None = None,
    editorial_category_label: str | None = None,
    editorial_category_guidance: str | None = None,
) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise ValueError(f"Blog {blog_id} not found")

    settings_map = get_settings_map(db)
    resolved_topic_count = _resolve_topic_count(settings_map, topic_count)
    resolved_publish_interval = _resolve_publish_interval_minutes(settings_map, publish_interval_minutes)
    mode = _resolve_publish_mode(publish_mode=publish_mode, scheduled_start=scheduled_start)
    first_publish_at = (
        _resolve_first_publish_datetime(settings_map, scheduled_start=scheduled_start)
        if mode == PublishMode.PUBLISH
        else None
    )

    topic_step = _require_enabled_step(blog, WorkflowStageType.TOPIC_DISCOVERY)
    runtime = get_runtime_config(db)
    topic_model = _resolve_stage_text_model(
        stage_type=WorkflowStageType.TOPIC_DISCOVERY,
        configured_model=topic_step.provider_model or runtime.topic_discovery_model,
        runtime=runtime,
    )
    resolved_editorial_key, resolved_editorial_label, resolved_editorial_guidance = _resolve_editorial_guidance(
        blog=blog,
        editorial_category_key=editorial_category_key,
        editorial_category_label=editorial_category_label,
        editorial_category_guidance=editorial_category_guidance,
    )
    topic_provider_name = _enforce_topic_provider_limits(
        db,
        blog=blog,
        provider_hint=topic_step.provider_hint,
        model_override=topic_model,
    )
    base_exclusion_prompt = build_duplicate_exclusion_prompt(db, blog_id=blog.id)
    max_discovery_attempts = max(8, resolved_topic_count * 6)

    skip_reasons_by_keyword: dict[str, list[str]] = {}
    queued_keywords: set[str] = set()
    discovered_items_all = []
    prompts_used: list[str] = []
    raw_responses_used: list[dict] = []
    metadata_by_keyword: dict[str, dict[str, str]] = {}
    skipped_duplicates: list[dict[str, str]] = []
    attempted_keywords: list[str] = []
    base_target_datetime = current_publish_target_datetime(db)
    now_local = datetime.now(_resolve_schedule_timezone(settings_map))
    travel_topic_override_prompt = _build_travel_topic_discovery_override_prompt(blog=blog, now_local=now_local)
    is_travel_profile = _is_travel_blog(blog)
    local_today = now_local.date().isoformat()
    travel_blossom_cap_ratio = _parse_float_setting(settings_map.get("travel_blossom_cap_ratio"), 0.2)
    (
        topic_history_lookback_days,
        topic_novelty_cluster_threshold,
        topic_novelty_angle_threshold,
        topic_soft_penalty_threshold,
    ) = _resolve_topic_history_settings(settings_map)
    travel_mix_counter = _load_daily_topic_mix_counter(
        settings_map.get("travel_daily_topic_mix_counts"),
        today=local_today,
    )
    blossom_blocked_keywords: list[str] = []
    sheet_history_entries: list[TopicHistoryEntry] = []
    topic_history_source = "none"
    try:
        sheet_exclusion_prompt = build_sheet_topic_exclusion_prompt(
            db,
            profile_key=blog.profile_key or "",
            blog_name=blog.name or "",
            lookback_days=topic_history_lookback_days,
            limit=28,
        )
        sheet_history_entries = list_sheet_topic_history_entries(
            db,
            profile_key=blog.profile_key or "",
            blog_name=blog.name or "",
            lookback_days=topic_history_lookback_days,
            limit=180,
        )
        topic_history_source = "sheet" if sheet_history_entries else "sheet_empty"
    except Exception:  # noqa: BLE001
        sheet_exclusion_prompt = ""
        sheet_history_entries = []
        topic_history_source = "sheet_error"

    if not sheet_history_entries:
        sheet_history_entries = _list_db_topic_history_entries(
            db,
            blog_id=blog.id,
            lookback_days=topic_history_lookback_days,
            limit=180,
        )
        if sheet_history_entries and not sheet_exclusion_prompt:
            sheet_exclusion_prompt = _build_topic_history_prompt(sheet_history_entries, limit=28)
        if sheet_history_entries:
            topic_history_source = "db_fallback"

    stop_after_status = _resolve_stop_after(settings_map, override=stop_after)
    job_ids: list[int] = []
    queued_cluster_angle_pairs: set[tuple[str, str]] = set()
    selected_topic_contexts: list[dict[str, object]] = []

    for attempt_index in range(max_discovery_attempts):
        remaining_topics = resolved_topic_count - len(selected_topic_contexts)
        if remaining_topics <= 0:
            break

        requested_topic_count = (
            remaining_topics if attempt_index == 0 else max(remaining_topics * 3, remaining_topics + 1)
        )
        runtime_exclusion_prompt = _build_runtime_duplicate_exclusion_prompt(attempted_keywords=attempted_keywords)
        runtime_blocked_prompt = _build_runtime_blocked_exclusion_prompt(
            skipped_duplicates=skipped_duplicates,
            metadata_by_keyword=metadata_by_keyword,
            limit=24,
        )
        blossom_cap_prompt = (
            _build_blossom_cap_prompt(
                blocked_keywords=blossom_blocked_keywords,
                cap_ratio=travel_blossom_cap_ratio,
            )
            if is_travel_profile
            else ""
        )
        prompt = (
            render_agent_prompt(
                db,
                blog,
                topic_step,
                topic_count=str(requested_topic_count),
                editorial_category_key=resolved_editorial_key,
                editorial_category_label=resolved_editorial_label,
                editorial_category_guidance=resolved_editorial_guidance,
            )
            + base_exclusion_prompt
            + sheet_exclusion_prompt
            + runtime_exclusion_prompt
            + runtime_blocked_prompt
            + blossom_cap_prompt
            + travel_topic_override_prompt
        )

        if runtime.provider_mode == "live" and topic_provider_name in {"openai", CODEX_TEXT_RUNTIME_KIND}:
            topic_model = _resolve_stage_text_model_for_call(
                db,
                stage_type=WorkflowStageType.TOPIC_DISCOVERY,
                configured_model=topic_step.provider_model or runtime.topic_discovery_model,
                runtime=runtime,
                provider_hint=topic_step.provider_hint,
            )

        provider = get_topic_provider(
            db,
            provider_hint=topic_step.provider_hint,
            model_override=topic_model,
        )
        payload, raw_response = provider.discover_topics(prompt)
        discovered_items = list(payload.topics or [])[:requested_topic_count]
        prompts_used.append(prompt)
        raw_responses_used.append(raw_response)
        discovered_items_all.extend(discovered_items)
        attempted_keywords.extend(item.keyword for item in discovered_items)
        for item in discovered_items:
            skip_reasons_by_keyword.setdefault(item.keyword, [])

        if not discovered_items:
            continue

        descriptor_by_keyword = annotate_topic_items(db, blog=blog, items=discovered_items)
        metadata_by_keyword.update(
            {
                keyword: {
                    "topic_cluster_label": descriptor.topic_cluster_label,
                    "topic_angle_label": descriptor.topic_angle_label,
                    "distinct_reason": descriptor.distinct_reason,
                    "topic_cluster_key": descriptor.topic_cluster_key,
                    "topic_angle_key": descriptor.topic_angle_key,
                    "editorial_category_key": resolved_editorial_key,
                    "editorial_category_label": resolved_editorial_label,
                }
                for keyword, descriptor in descriptor_by_keyword.items()
            }
        )

        guarded_topics = []
        for item in discovered_items:
            descriptor = descriptor_by_keyword[item.keyword]
            if first_publish_at:
                slot_index = len(selected_topic_contexts) + len(guarded_topics)
                target_publish_datetime = first_publish_at + timedelta(minutes=resolved_publish_interval * slot_index)
            else:
                target_publish_datetime = base_target_datetime
            try:
                assert_topic_guard(
                    db,
                    blog_id=blog.id,
                    descriptor=descriptor,
                    target_datetime=target_publish_datetime,
                )
                guarded_topics.append(item)
            except TopicGuardConflictError as exc:
                skipped_duplicates.append(
                    {
                        "keyword": item.keyword,
                        "reason": exc.violation.message,
                    }
                )
                skip_reasons_by_keyword.setdefault(item.keyword, []).append(exc.violation.message)

        novelty_passed_topics = []
        for item in guarded_topics:
            metadata = metadata_by_keyword.get(item.keyword, {})
            novelty = assess_topic_novelty_against_history(
                keyword=item.keyword,
                topic_cluster=(metadata.get("topic_cluster_label") or metadata.get("topic_cluster_key") or ""),
                topic_angle=(metadata.get("topic_angle_label") or metadata.get("topic_angle_key") or ""),
                history_entries=sheet_history_entries,
                cluster_threshold=topic_novelty_cluster_threshold,
                angle_threshold=topic_novelty_angle_threshold,
            )
            metadata["novelty_score"] = novelty.get("novelty_score")
            metadata["novelty_penalty_points"] = novelty.get("penalty_points")
            metadata["novelty_penalty_reason"] = novelty.get("penalty_reason")
            metadata["novelty_matched_history_item"] = novelty.get("matched_history_item")
            metadata["novelty_similarity"] = novelty.get("similarity")
            metadata["topic_history_source"] = topic_history_source
            metadata_by_keyword[item.keyword] = metadata

            penalty_points = int(novelty.get("penalty_points") or 0)
            if penalty_points >= topic_soft_penalty_threshold:
                skip_payload = {
                    "keyword": item.keyword,
                    "reason": "history_soft_penalty_threshold_exceeded",
                    "matched_history_item": novelty.get("matched_history_item"),
                    "penalty_reason": novelty.get("penalty_reason"),
                    "novelty_score": novelty.get("novelty_score"),
                    "penalty_points": penalty_points,
                }
                skipped_duplicates.append(skip_payload)
                skip_reasons_by_keyword.setdefault(item.keyword, []).append(
                    "history_soft_penalty_threshold_exceeded"
                )
                continue

            novelty_passed_topics.append(item)

        filtered_topics, duplicate_skips = filter_duplicate_topic_items(
            db,
            blog_id=blog.id,
            items=novelty_passed_topics,
            metadata_by_keyword=metadata_by_keyword,
        )
        skipped_duplicates.extend(duplicate_skips)
        for skip in duplicate_skips:
            skip_reasons_by_keyword.setdefault(skip["keyword"], []).append(skip["reason"])

        blossom_filtered_topics = []
        for candidate in filtered_topics:
            candidate_is_blossom = _is_blossom_topic_keyword(candidate.keyword)
            if is_travel_profile and _would_exceed_blossom_cap(
                counter=travel_mix_counter,
                is_blossom=candidate_is_blossom,
                cap_ratio=travel_blossom_cap_ratio,
            ):
                reason = "blossom_cap_blocked"
                skipped_duplicates.append({"keyword": candidate.keyword, "reason": reason})
                skip_reasons_by_keyword.setdefault(candidate.keyword, []).append(reason)
                blossom_blocked_keywords.append(candidate.keyword)
                continue
            _increment_daily_mix_counter(travel_mix_counter, is_blossom=candidate_is_blossom)
            blossom_filtered_topics.append(candidate)

        topics = upsert_topics(
            db,
            blog,
            blossom_filtered_topics,
            source=topic_provider_name,
            metadata_by_keyword=metadata_by_keyword,
        )

        for topic_index, topic in enumerate(topics):
            topic_cluster_key = (metadata_by_keyword.get(topic.keyword, {}).get("topic_cluster_key") or "").strip().lower()
            topic_angle_key = (
                (metadata_by_keyword.get(topic.keyword, {}).get("topic_angle_key") or "").strip().lower()
                or (metadata_by_keyword.get(topic.keyword, {}).get("topic_angle_label") or "").strip().lower()
            )
            cluster_angle_pair = (topic_cluster_key, topic_angle_key)
            if topic_cluster_key and topic_angle_key and cluster_angle_pair in queued_cluster_angle_pairs:
                reason = (
                    "Another topic with the same main cluster and angle is already queued in this batch. "
                    "Different angles for the same topic cluster are allowed."
                )
                skipped_duplicates.append({"keyword": topic.keyword, "reason": reason})
                skip_reasons_by_keyword.setdefault(topic.keyword, []).append(reason)
                continue

            slot_index = len(selected_topic_contexts)
            scheduled_for = (
                first_publish_at + timedelta(minutes=resolved_publish_interval * slot_index)
                if first_publish_at
                else None
            )

            if topic_cluster_key and topic_angle_key:
                queued_cluster_angle_pairs.add(cluster_angle_pair)

            selected_topic_contexts.append(
                {
                    "topic": topic,
                    "prompt": prompt,
                    "raw_response": raw_response,
                    "scheduled_for": scheduled_for,
                }
            )

            if len(selected_topic_contexts) >= resolved_topic_count:
                for leftover_topic in topics[topic_index + 1 :]:
                    reason = "Target topic count is already filled for this run."
                    skipped_duplicates.append({"keyword": leftover_topic.keyword, "reason": reason})
                    skip_reasons_by_keyword.setdefault(leftover_topic.keyword, []).append(reason)
                break

    if len(selected_topic_contexts) < resolved_topic_count:
        raise ValueError(
            "topic_selection_incomplete: "
            f"selected {len(selected_topic_contexts)} of {resolved_topic_count} unique topics "
            f"after {max_discovery_attempts} regeneration attempts."
        )

    for slot_index, context in enumerate(selected_topic_contexts):
        topic = context["topic"]
        prompt = context["prompt"]
        raw_response = context["raw_response"]
        scheduled_for = context["scheduled_for"]

        try:
            job = create_job(
                db,
                blog_id=blog.id,
                keyword=topic.keyword,
                topic_id=topic.id,
                publish_mode=mode,
                initial_status=JobStatus.DISCOVERING_TOPICS,
                target_datetime=scheduled_for or base_target_datetime,
                raw_prompts={
                    topic_step.stage_type.value: prompt,
                    PIPELINE_CONTROL_KEY: _serialize_pipeline_control(stop_after_status),
                    PIPELINE_SCHEDULE_KEY: _serialize_publish_schedule(
                        mode=mode,
                        scheduled_for=scheduled_for,
                        slot_index=slot_index,
                        interval_minutes=resolved_publish_interval,
                        topic_count=resolved_topic_count,
                    ),
                },
                raw_responses={
                    topic_step.stage_type.value: raw_response,
                    "duplicate_filter": {
                        "skipped": skipped_duplicates,
                        "history_source": topic_history_source,
                        "history_lookback_days": topic_history_lookback_days,
                        "soft_penalty_threshold": topic_soft_penalty_threshold,
                    },
                },
            )
        except DuplicateContentError as exc:
            skipped_duplicates.append({"keyword": topic.keyword, "reason": str(exc)})
            skip_reasons_by_keyword.setdefault(topic.keyword, []).append(str(exc))
            raise ValueError(
                "topic_selection_conflict_during_queue: "
                f"'{topic.keyword}' became duplicate while creating queued jobs."
            ) from exc

        set_status(
            db,
            job,
            JobStatus.PENDING,
            f"{blog.name} topic queued for pipeline execution.",
            {
                "blog_id": blog.id,
                "topic_id": topic.id,
                "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            },
        )
        run_job.delay(job.id)
        job_ids.append(job.id)
        queued_keywords.add(topic.keyword)

    provider_name = provider.__class__.__name__.lower()
    if "gemini" in provider_name:
        provider_label = "gemini"
        model_label = topic_step.provider_model or runtime.gemini_model
    elif "mock" in provider_name:
        provider_label = "mock"
        model_label = None
    else:
        provider_label = provider_name.replace("provider", "")
        model_label = topic_model

    unique_discovered_by_keyword = {}
    for item in discovered_items_all:
        unique_discovered_by_keyword.setdefault(item.keyword, item)

    run_items = []
    for item in unique_discovered_by_keyword.values():
        keyword = item.keyword
        status = "queued" if keyword in queued_keywords else "skipped"
        run_items.append(
            {
                "keyword": keyword,
                "reason": item.reason,
                "trend_score": item.trend_score,
                "status": status,
                "skip_reasons": [] if status == "queued" else skip_reasons_by_keyword.get(keyword, []),
                "metadata": metadata_by_keyword.get(keyword, {}),
            }
        )

    if len(prompts_used) == 1:
        run_prompt = prompts_used[0]
    else:
        run_prompt = "\n\n".join(f"[attempt {index + 1}]\n{value}" for index, value in enumerate(prompts_used))

    if len(raw_responses_used) == 1:
        run_raw_response = raw_responses_used[0]
    else:
        run_raw_response = {"attempts": raw_responses_used}

    create_topic_discovery_run(
        db,
        blog_id=blog.id,
        provider=provider_label,
        model=model_label,
        prompt=run_prompt,
        raw_response=run_raw_response,
        items=run_items,
        job_ids=job_ids,
    )

    if is_travel_profile:
        upsert_settings(
            db,
            {
                "travel_daily_topic_mix_counts": _dump_daily_topic_mix_counter(
                    today=local_today,
                    counter=travel_mix_counter,
                )
            },
        )

    return {
        "blog_id": blog.id,
        "blog_name": blog.name,
        "queued_topics": len(job_ids),
        "job_ids": job_ids,
        "stop_after_status": stop_after_status.value if stop_after_status else None,
        "topic_count": resolved_topic_count,
        "discovery_attempts": len(prompts_used),
        "message": (
            f"{blog.name} topic discovery complete. "
            f"Queued {len(job_ids)} jobs, skipped {len(skipped_duplicates)} duplicates/blocked items. "
            f"Discovery attempts: {len(prompts_used)}."
        ),
        "skip_reason_breakdown": {
            "blossom_cap_blocked": len(
                [item for item in skipped_duplicates if (item.get("reason") or "").strip() == "blossom_cap_blocked"]
            ),
            "duplicate_or_guard_blocked": len(
                [item for item in skipped_duplicates if (item.get("reason") or "").strip() != "blossom_cap_blocked"]
            ),
        },
        "topic_history_source": topic_history_source,
        "topic_history_lookback_days": topic_history_lookback_days,
        "topic_soft_penalty_threshold": topic_soft_penalty_threshold,
        "editorial_category_key": resolved_editorial_key,
        "editorial_category_label": resolved_editorial_label,
    }


def _publish_article(
    db,
    *,
    provider,
    article,
    job,
    scheduled_for: datetime | None,
) -> tuple[dict, dict, str]:
    labels = ensure_article_editorial_labels(db, article)
    publish_content = (article.assembled_html or article.html_article or "").strip()
    publish_content, trust_assessment = ensure_trust_gate_appendix(publish_content)
    if publish_content != (article.assembled_html or "").strip():
        article.assembled_html = publish_content
        db.add(article)
        db.commit()
        db.refresh(article)
    enforce_publish_trust_requirements(
        publish_content,
        context=f"blogger_job_{job.id}_article_{article.id}",
    )
    should_schedule = (
        job.publish_mode == PublishMode.PUBLISH
        and scheduled_for is not None
        and scheduled_for > datetime.now(timezone.utc)
    )

    existing_post = article.blogger_post
    if existing_post and existing_post.post_status in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
        return (
            {
                "id": existing_post.blogger_post_id,
                "url": existing_post.published_url,
                "published": (existing_post.published_at or datetime.now(timezone.utc)).isoformat(),
                "isDraft": existing_post.is_draft,
                "postStatus": existing_post.post_status.value,
                "scheduledFor": existing_post.scheduled_for.isoformat() if existing_post.scheduled_for else None,
            },
            {"mode": "already_exists"},
            "already_exists",
        )

    if existing_post and hasattr(provider, "update_post"):
        update_summary, update_payload = provider.update_post(
            post_id=existing_post.blogger_post_id,
            title=article.title,
            content=article.assembled_html or article.html_article,
            labels=labels,
            meta_description=article.meta_description,
        )

        if should_schedule and hasattr(provider, "publish_draft"):
            publish_summary, publish_payload = provider.publish_draft(
                existing_post.blogger_post_id,
                publish_date=scheduled_for.isoformat() if scheduled_for else None,
            )
            return publish_summary, {"update": update_payload, "publish": publish_payload}, "schedule"

        if job.publish_mode == PublishMode.PUBLISH and existing_post.is_draft and hasattr(provider, "publish_draft"):
            publish_summary, publish_payload = provider.publish_draft(existing_post.blogger_post_id)
            return publish_summary, {"update": update_payload, "publish": publish_payload}, "publish"

        return update_summary, update_payload, "update"

    if should_schedule and hasattr(provider, "publish_draft"):
        draft_summary, draft_payload = provider.publish(
            title=article.title,
            content=article.assembled_html or article.html_article,
            labels=labels,
            meta_description=article.meta_description,
            slug=article.slug,
            publish_mode=PublishMode.DRAFT,
        )
        publish_summary, publish_payload = provider.publish_draft(
            draft_summary["id"],
            publish_date=scheduled_for.isoformat() if scheduled_for else None,
        )
        return publish_summary, {"create": draft_payload, "publish": publish_payload}, "schedule"

    publish_target_mode = PublishMode.PUBLISH if job.publish_mode == PublishMode.PUBLISH else PublishMode.DRAFT
    summary, raw_payload = provider.publish(
        title=article.title,
        content=article.assembled_html or article.html_article,
        labels=labels,
        meta_description=article.meta_description,
        slug=article.slug,
        publish_mode=publish_target_mode,
    )
    if publish_target_mode == PublishMode.DRAFT:
        return summary, raw_payload, "draft"
    return summary, raw_payload, "publish"

def execute_job_pipeline(db, *, job_id: int) -> None:
    job = load_job(db, job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")
    if not job.blog:
        raise ValueError(f"Job {job_id} is missing blog information")

    blog = job.blog
    topic = job.topic if job.topic_id else None
    settings_map = get_settings_map(db)
    runtime = get_runtime_config(db)
    request_saver_mode = _is_enabled_setting(settings_map.get("openai_request_saver_mode"), default=True)
    inline_collage_enabled = _blogger_inline_collage_enabled(settings_map, blog)
    is_mystery_blog = blog.profile_key == "world_mystery" or (blog.content_category or "").lower() == "mystery"
    planner_brief_payload = _extract_planner_brief_payload(job)
    planner_brief_text = _format_planner_brief_for_prompt(planner_brief_payload)
    bundle_key = str(planner_brief_payload.get("bundle_key") or "").strip()

    article_step = _require_enabled_step(blog, WorkflowStageType.ARTICLE_GENERATION)
    image_generation_step = _require_enabled_step(blog, WorkflowStageType.IMAGE_GENERATION)
    html_assembly_step = _require_enabled_step(blog, WorkflowStageType.HTML_ASSEMBLY)
    publishing_step = _require_enabled_step(blog, WorkflowStageType.PUBLISHING)
    image_prompt_step = _get_optional_enabled_step(blog, WorkflowStageType.IMAGE_PROMPT_GENERATION)
    related_posts_step = _get_optional_enabled_step(blog, WorkflowStageType.RELATED_POSTS)

    image_provider = get_image_provider(db, model_override=image_generation_step.provider_model)
    topic_editorial_key = (topic.editorial_category_key if topic else "").strip()
    topic_editorial_label = (topic.editorial_category_label if topic else "").strip()
    topic_editorial_guidance = (
        TRAVEL_EDITORIAL_GUIDANCE.get(topic_editorial_key)
        if blog.profile_key == "korea_travel"
        else MYSTERY_EDITORIAL_GUIDANCE.get(topic_editorial_key)
        if blog.profile_key == "world_mystery"
        else ""
    ) or ""

    set_status(db, job, JobStatus.GENERATING_ARTICLE, f"{blog.name} generating article content.")
    article_pattern_selection = select_blogger_article_pattern(
        db,
        blog_id=blog.id,
        profile_key=blog.profile_key,
        editorial_category_key=topic_editorial_key,
    )
    rendered_article_prompt = render_agent_prompt(
        db,
        blog,
        article_step,
        keyword=job.keyword_snapshot,
        planner_brief=planner_brief_text,
        editorial_category_key=topic_editorial_key,
        editorial_category_label=topic_editorial_label,
        editorial_category_guidance=topic_editorial_guidance,
    )
    rendered_article_prompt = _append_blogger_seo_trust_guard(
        rendered_article_prompt,
        blog=blog,
        current_date=datetime.now(_resolve_schedule_timezone(settings_map)).date().isoformat(),
    )
    rendered_article_prompt = _append_no_inline_image_rule(rendered_article_prompt)
    merge_prompt(db, job, article_step.stage_type.value, rendered_article_prompt)
    article_model = _resolve_stage_text_model_for_call(
        db,
        stage_type=WorkflowStageType.ARTICLE_GENERATION,
        configured_model=article_step.provider_model,
        runtime=runtime,
        job=job,
        provider_hint=article_step.provider_hint,
    )
    article_provider = get_article_provider(
        db,
        model_override=article_model,
        provider_hint=article_step.provider_hint,
        allow_large=True,
    )
    article_output, article_raw = article_provider.generate_article(job.keyword_snapshot, rendered_article_prompt)
    article_output = apply_pattern_defaults(article_output, article_pattern_selection)
    merge_response(db, job, article_step.stage_type.value, article_raw)
    article = save_article(db, job=job, topic=topic, output=article_output)
    article.inline_media = []
    db.add(article)
    db.commit()
    db.refresh(article)
    if _complete_early_if_needed(db, job, completed_stage=JobStatus.GENERATING_ARTICLE, blog=blog):
        return

    quality_gate_thresholds = _quality_gate_thresholds(settings_map)
    try:
        article, final_article_output, quality_gate_payload = _run_blogger_quality_gate(
            db,
            blog=blog,
            job=job,
            topic=topic,
            article=article,
            initial_output=article_output,
            article_configured_model=article_step.provider_model,
            article_provider_hint=article_step.provider_hint,
            runtime=runtime,
            base_prompt=rendered_article_prompt,
            thresholds=quality_gate_thresholds,
        )
    except QualityGateError as exc:
        merge_response(
            db,
            job,
            "quality_gate",
            {
                "enabled": bool(quality_gate_thresholds.get("enabled", 1.0)),
                "passed": False,
                "reason": "quality_gate_failed",
                **(exc.payload or {}),
            },
        )
        raise

    merge_response(db, job, "quality_gate", quality_gate_payload)

    set_status(
        db,
        job,
        JobStatus.GENERATING_IMAGE_PROMPT,
        f"{blog.name} preparing visual prompt.",
    )

    if is_mystery_blog:
        rendered_visual_prompt = (
            (article.image_collage_prompt or "").strip()
            or f"Documentary style mystery cover image for {job.keyword_snapshot}."
        )
        rendered_visual_prompt = _append_hero_only_visual_rule(rendered_visual_prompt)
        merge_response(
            db,
            job,
            WorkflowStageType.IMAGE_PROMPT_GENERATION.value,
            {
                "prompt": rendered_visual_prompt,
                "source": "wikimedia_mode",
                "skipped": True,
                "reason": "Mystery profile uses Wikimedia Commons images instead of generated collage.",
            },
        )
    elif image_prompt_step and not request_saver_mode:
        rendered_visual_prompt_request = render_agent_prompt(
            db,
            blog,
            image_prompt_step,
            keyword=job.keyword_snapshot,
            article_title=article.title,
            article_excerpt=article.excerpt,
            planner_brief=planner_brief_text,
            editorial_category_key=topic_editorial_key,
            editorial_category_label=topic_editorial_label,
            editorial_category_guidance=topic_editorial_guidance,
            article_context="\n".join(
                [
                    f"Title: {article.title}",
                    f"Excerpt: {article.excerpt}",
                    f"Labels: {', '.join(article.labels or [])}",
                    f"Article HTML: {article.html_article}",
                ]
            ),
        )
        rendered_visual_prompt_request = _append_hero_only_visual_rule(rendered_visual_prompt_request)
        merge_prompt(db, job, image_prompt_step.stage_type.value, rendered_visual_prompt_request)
        prompt_refinement_model = _resolve_stage_text_model_for_call(
            db,
            stage_type=WorkflowStageType.IMAGE_PROMPT_GENERATION,
            configured_model=image_prompt_step.provider_model,
            runtime=runtime,
            job=job,
            provider_hint=image_prompt_step.provider_hint,
        )
        prompt_refinement_provider = get_article_provider(
            db,
            model_override=prompt_refinement_model,
            provider_hint=image_prompt_step.provider_hint,
            allow_large=False,
        )
        rendered_visual_prompt, visual_prompt_raw = prompt_refinement_provider.generate_visual_prompt(
            rendered_visual_prompt_request
        )
        rendered_visual_prompt = _append_hero_only_visual_rule(rendered_visual_prompt)
        merge_response(
            db,
            job,
            image_prompt_step.stage_type.value,
            {"prompt": rendered_visual_prompt, "raw": visual_prompt_raw, "source": "agent"},
        )
    else:
        rendered_visual_prompt = (article.image_collage_prompt or "").strip() or build_collage_prompt(article)
        rendered_visual_prompt = _append_hero_only_visual_rule(rendered_visual_prompt)
        source = "article_generation_request_saver" if request_saver_mode else "article_fallback"
        if image_prompt_step and request_saver_mode:
            merge_prompt(
                db,
                job,
                image_prompt_step.stage_type.value,
                "[request_saver_mode] Reused article.image_collage_prompt without extra LLM call.",
            )
        merge_response(
            db,
            job,
            WorkflowStageType.IMAGE_PROMPT_GENERATION.value,
            {
                "prompt": rendered_visual_prompt,
                "source": source,
                "request_saved": request_saver_mode,
            },
        )

    article.image_collage_prompt = rendered_visual_prompt
    db.add(article)
    db.commit()
    db.refresh(article)
    inline_collage_prompt_value = str(getattr(final_article_output, "inline_collage_prompt", "") or "").strip()
    inline_article_context = "\n".join(
        [
            f"Title: {article.title}",
            f"Excerpt: {article.excerpt}",
            f"Labels: {', '.join(article.labels or [])}",
            f"Article HTML: {article.html_article}",
        ]
    )
    if _complete_early_if_needed(db, job, completed_stage=JobStatus.GENERATING_IMAGE_PROMPT, blog=blog):
        return

    set_status(
        db,
        job,
        JobStatus.GENERATING_IMAGE,
        f"{blog.name} preparing hero/inline images.",
    )

    def _generate_and_store(prompt_value: str, *, asset_role: str = "hero") -> tuple[Image, str]:
        image_bytes, image_raw = image_provider.generate_image(prompt_value, article.slug)
        object_key = build_article_r2_asset_object_key(
            article,
            asset_role=asset_role,
            content=image_bytes,
        )
        file_path, public_url, delivery_meta = save_public_binary(
            db,
            subdir="images",
            filename=f"{article.slug}.webp",
            content=image_bytes,
            object_key=object_key,
        )
        image = _upsert_image(
            db,
            job_id=job.id,
            article_id=article.id,
            prompt=prompt_value,
            file_path=file_path,
            public_url=public_url,
            provider=image_generation_step.provider_hint
            or image_provider.__class__.__name__.replace("Provider", "").lower(),
            meta={**image_raw, "delivery": delivery_meta},
        )
        return image, public_url

    hero_image_url = ""
    if is_mystery_blog:
        media_target = _coerce_non_negative_int(settings_map.get("wikimedia_image_count"), 3) or 3
        media_items = fetch_wikimedia_media(job.keyword_snapshot, count=media_target)
        article.inline_media = []
        db.add(article)
        db.commit()
        db.refresh(article)
        hero_image_url = (
            str(media_items[0].get("image_url") or media_items[0].get("thumb_url") or "")
            if media_items
            else ""
        )

        fallback_image_payload: dict | None = None
        if not hero_image_url:
            fallback_prompt = (
                (rendered_visual_prompt or "").strip()
                or f"Documentary style mystery cover image for {job.keyword_snapshot}."
            )
            fallback_image, fallback_public_url = _generate_and_store(fallback_prompt, asset_role="hero")
            hero_image_url = fallback_public_url
            fallback_image_payload = {
                "reason": "wikimedia_empty_result",
                "prompt": fallback_prompt,
                "public_url": fallback_public_url,
                "provider": fallback_image.provider,
                "width": fallback_image.width,
                "height": fallback_image.height,
                "delivery": (
                    fallback_image.image_metadata.get("delivery")
                    if isinstance(fallback_image.image_metadata, dict)
                    else None
                ),
            }

        merge_response(
            db,
            job,
            image_generation_step.stage_type.value,
            {
                "provider": "wikimedia_commons",
                "collected": len(media_items),
                "hero_image_url": hero_image_url or None,
                "items": media_items,
                "fallback_generated_image": fallback_image_payload,
            },
        )
        if inline_collage_enabled:
            inline_prompt = _build_blogger_inline_3x2_prompt(
                blog=blog,
                keyword=job.keyword_snapshot,
                article_title=article.title,
                article_excerpt=article.excerpt,
                article_context=inline_article_context,
                original_prompt=rendered_visual_prompt,
                editorial_category_label=topic_editorial_label,
                inline_collage_prompt=inline_collage_prompt_value,
            )
            try:
                inline_bytes, inline_raw = image_provider.generate_image(inline_prompt, f"{article.slug}-inline-3x2")
                inline_object_key = build_article_r2_asset_object_key(
                    article,
                    asset_role="inline-3x2",
                    content=inline_bytes,
                )
                inline_file_path, inline_public_url, inline_delivery = save_public_binary(
                    db,
                    subdir="images",
                    filename=f"{article.slug}-inline-3x2.webp",
                    content=inline_bytes,
                    object_key=inline_object_key,
                )
                article.inline_media = [
                    {
                        "slot": "mystery-inline-3x2",
                        "kind": "collage",
                        "image_url": inline_public_url,
                        "file_path": inline_file_path,
                        "prompt": inline_prompt,
                        "width": int(inline_raw.get("width", 0) or 0),
                        "height": int(inline_raw.get("height", 0) or 0),
                        "delivery": inline_delivery,
                    }
                ]
                db.add(article)
                db.commit()
                db.refresh(article)
                merge_response(
                    db,
                    job,
                    image_generation_step.stage_type.value,
                    {
                        "inline_collage": {
                            "status": "created",
                            "slot": "mystery-inline-3x2",
                            "public_url": inline_public_url,
                            "prompt": inline_prompt,
                            "width": int(inline_raw.get("width", 0) or 0),
                            "height": int(inline_raw.get("height", 0) or 0),
                            "delivery": inline_delivery,
                        }
                    },
                )
            except Exception as inline_exc:  # noqa: BLE001
                article.inline_media = []
                db.add(article)
                db.commit()
                db.refresh(article)
                merge_response(
                    db,
                    job,
                    image_generation_step.stage_type.value,
                    {
                        "inline_collage": {
                            "status": "failed",
                            "slot": "mystery-inline-3x2",
                            "prompt": inline_prompt,
                            "reason": str(inline_exc),
                        }
                    },
                )
        else:
            article.inline_media = []
            db.add(article)
            db.commit()
            db.refresh(article)
            merge_response(
                db,
                job,
                image_generation_step.stage_type.value,
                {
                    "inline_collage": {
                        "status": "skipped",
                        "slot": "mystery-inline-3x2",
                        "reason": "policy_disabled",
                    }
                },
            )
    else:
        generation_attempts: list[dict] = []
        image, hero_image_url = _generate_and_store(rendered_visual_prompt, asset_role="hero")
        generation_attempts.append(
            {
                "attempt": 1,
                "prompt": rendered_visual_prompt,
                "width": image.width,
                "height": image.height,
                "provider": image.provider,
            }
        )

        panel_gate_payload: dict | None = None
        inline_collage_payload: dict | None = None
        if _is_travel_blog(blog):
            prompt_missing = _travel_3x3_prompt_missing_requirements(rendered_visual_prompt)
            size_missing = _travel_3x3_size_missing_requirements(int(image.width or 0), int(image.height or 0))
            panel_gate_payload = {
                "policy": "travel_3x3_center_emphasis",
                "passed": not prompt_missing and not size_missing,
                "prompt_missing": prompt_missing,
                "size_missing": size_missing,
            }
            if not panel_gate_payload["passed"]:
                retry_prompt = _build_travel_3x3_retry_prompt(
                    keyword=job.keyword_snapshot,
                    title=article.title,
                    original_prompt=rendered_visual_prompt,
                )
                retry_image, retry_public_url = _generate_and_store(retry_prompt, asset_role="hero-retry")
                retry_prompt_missing = _travel_3x3_prompt_missing_requirements(retry_prompt)
                retry_size_missing = _travel_3x3_size_missing_requirements(
                    int(retry_image.width or 0),
                    int(retry_image.height or 0),
                )
                retry_passed = not retry_prompt_missing and not retry_size_missing

                generation_attempts.append(
                    {
                        "attempt": 2,
                        "prompt": retry_prompt,
                        "width": retry_image.width,
                        "height": retry_image.height,
                        "provider": retry_image.provider,
                    }
                )
                panel_gate_payload["retry"] = {
                    "passed": retry_passed,
                    "prompt_missing": retry_prompt_missing,
                    "size_missing": retry_size_missing,
                }

                image = retry_image
                hero_image_url = retry_public_url
                rendered_visual_prompt = retry_prompt
                article.image_collage_prompt = retry_prompt
                db.add(article)
                db.commit()
                db.refresh(article)

                if not retry_passed:
                    merge_response(
                        db,
                        job,
                        image_generation_step.stage_type.value,
                        {
                            "public_url": hero_image_url,
                            "provider": image.provider,
                            "delivery": (
                                image.image_metadata.get("delivery")
                                if isinstance(image.image_metadata, dict)
                                else None
                            ),
                            "attempts": generation_attempts,
                            "panel_gate": panel_gate_payload,
                        },
                    )
                    raise ValueError(
                        "travel_3x3_panel_gate_failed: generated image did not satisfy 3x3/center-emphasis requirements."
                    )

            if inline_collage_enabled:
                inline_prompt = _build_blogger_inline_3x2_prompt(
                    blog=blog,
                    keyword=job.keyword_snapshot,
                    article_title=article.title,
                    article_excerpt=article.excerpt,
                    article_context=inline_article_context,
                    original_prompt=rendered_visual_prompt,
                    editorial_category_label=topic_editorial_label,
                    inline_collage_prompt=inline_collage_prompt_value,
                )
                try:
                    inline_bytes, inline_raw = image_provider.generate_image(inline_prompt, f"{article.slug}-inline-3x2")
                    inline_object_key = build_article_r2_asset_object_key(
                        article,
                        asset_role="inline-3x2",
                        content=inline_bytes,
                    )
                    inline_file_path, inline_public_url, inline_delivery = save_public_binary(
                        db,
                        subdir="images",
                        filename=f"{article.slug}-inline-3x2.webp",
                        content=inline_bytes,
                        object_key=inline_object_key,
                    )
                    article.inline_media = [
                        {
                            "slot": "travel-inline-3x2",
                            "kind": "collage",
                            "image_url": inline_public_url,
                            "file_path": inline_file_path,
                            "prompt": inline_prompt,
                            "width": int(inline_raw.get("width", 0) or 0),
                            "height": int(inline_raw.get("height", 0) or 0),
                            "delivery": inline_delivery,
                        }
                    ]
                    db.add(article)
                    db.commit()
                    db.refresh(article)
                    inline_collage_payload = {
                        "status": "created",
                        "slot": "travel-inline-3x2",
                        "public_url": inline_public_url,
                        "prompt": inline_prompt,
                        "width": int(inline_raw.get("width", 0) or 0),
                        "height": int(inline_raw.get("height", 0) or 0),
                        "delivery": inline_delivery,
                    }
                except Exception as inline_exc:  # noqa: BLE001
                    article.inline_media = []
                    db.add(article)
                    db.commit()
                    db.refresh(article)
                    inline_collage_payload = {
                        "status": "failed",
                        "slot": "travel-inline-3x2",
                        "prompt": inline_prompt,
                        "reason": str(inline_exc),
                    }
            else:
                article.inline_media = []
                db.add(article)
                db.commit()
                db.refresh(article)
                inline_collage_payload = {
                    "status": "skipped",
                    "slot": "travel-inline-3x2",
                    "reason": "policy_disabled",
                }

        merge_response(
            db,
            job,
            image_generation_step.stage_type.value,
            {
                "public_url": hero_image_url,
                "provider": image.provider,
                "delivery": (
                    image.image_metadata.get("delivery")
                    if isinstance(image.image_metadata, dict)
                    else None
                ),
                "attempts": generation_attempts,
                "panel_gate": panel_gate_payload,
                "inline_collage": inline_collage_payload,
            },
        )

    if _complete_early_if_needed(db, job, completed_stage=JobStatus.GENERATING_IMAGE, blog=blog):
        return

    related_posts: list[dict] = []
    if related_posts_step:
        set_status(
            db,
            job,
            JobStatus.FINDING_RELATED_POSTS,
            f"{blog.name} finding related posts.",
        )
        related_posts = find_related_articles(db, article)
        merge_response(db, job, related_posts_step.stage_type.value, related_posts)
    else:
        merge_response(
            db,
            job,
            WorkflowStageType.RELATED_POSTS.value,
            {"enabled": False, "items": []},
        )

    set_status(
        db,
        job,
        JobStatus.ASSEMBLING_HTML,
        f"{blog.name} assembling final HTML.",
    )
    db.refresh(article, attribute_names=["blog"])
    language_switch_html = ""
    if bundle_key:
        url_map = _build_bundle_language_url_map(_list_bundle_articles(db, bundle_key=bundle_key))
        if len(url_map) == len(SUPPORTED_LANGUAGES):
            current_language = _normalize_supported_language(resolve_blog_bundle_language(blog) or blog.primary_language)
            if current_language:
                language_switch_html = build_language_switch_block(
                    current_language=current_language,
                    urls_by_language=url_map,
                )

    assembled_html = assemble_article_html(
        article,
        hero_image_url,
        related_posts,
        language_switch_html=language_switch_html,
    )
    assembled_html, trust_assessment = ensure_trust_gate_appendix(assembled_html)
    article.assembled_html = assembled_html
    db.add(article)
    db.commit()
    db.refresh(article)
    html_path, html_url = save_html(slug=article.slug, html=assembled_html)
    merge_response(db, job, html_assembly_step.stage_type.value, {"file_path": html_path, "public_url": html_url})
    review_article_draft(db, article.id, trigger="pipeline_html_assembly")
    if _complete_early_if_needed(db, job, completed_stage=JobStatus.ASSEMBLING_HTML, blog=blog):
        return

    set_status(db, job, JobStatus.PUBLISHING, f"{blog.name} publishing article to Blogger.")
    provider = get_blogger_provider(db, blog)
    scheduled_for = _resolve_publish_target_datetime(job) if job.publish_mode == PublishMode.PUBLISH else None
    summary, raw_payload, publish_action = _publish_article(
        db,
        provider=provider,
        article=article,
        job=job,
        scheduled_for=scheduled_for,
    )
    blogger_post = _upsert_blogger_post(
        db,
        job_id=job.id,
        blog_id=blog.id,
        article_id=article.id,
        summary=summary,
        raw_payload=raw_payload,
    )
    language_sync_result = {"status": "skipped", "reason": "bundle_key_missing"}
    if bundle_key:
        try:
            language_sync_result = _sync_multilingual_bundle_links(db, bundle_key=bundle_key)
        except Exception as exc:  # noqa: BLE001
            language_sync_result = {
                "status": "failed",
                "bundle_key": bundle_key,
                "message": str(exc),
            }
    rebuild_topic_memories_for_blog(db, blog)

    telegram_result = None
    if blogger_post.published_url and blogger_post.post_status in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
        upsert_article_fact(db, article.id, commit=True)
        review_article_publish_state(db, article.id, trigger="pipeline_publish")
        telegram_result = send_telegram_post_notification(
            db,
            blog_name=blog.name,
            article_title=article.title,
            post_url=blogger_post.published_url,
            post_status=blogger_post.post_status.value,
            scheduled_for=blogger_post.scheduled_for,
        )

    merge_response(
        db,
        job,
        publishing_step.stage_type.value,
        {
            "mode": publish_action,
            "publish_mode_requested": job.publish_mode.value,
            "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            "summary": summary,
            "telegram": telegram_result,
            "multilingual_bundle_sync": language_sync_result,
        },
    )
    set_status(
        db,
        job,
        JobStatus.COMPLETED,
        f"{blog.name} article published successfully.",
        {
            "article_id": article.id,
            "post_status": blogger_post.post_status.value,
            "published_url": blogger_post.published_url,
            "scheduled_for": blogger_post.scheduled_for.isoformat() if blogger_post.scheduled_for else None,
        },
    )


@celery_app.task(bind=True, name="app.tasks.pipeline.run_job", max_retries=2, default_retry_delay=30)
def run_job(self: Task, job_id: int, force_retry: bool = False) -> dict:
    db = SessionLocal()
    try:
        job = load_job(db, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if force_retry:
            job.status = JobStatus.PENDING
            job.end_time = None
            db.add(job)
            db.commit()

        increment_attempt(db, job)
        execute_job_pipeline(db, job_id=job_id)
        final_job = load_job(db, job_id)
        return {
            "job_id": job_id,
            "status": "stopped" if final_job and final_job.status == JobStatus.STOPPED else "completed",
        }
    except DuplicateContentError as exc:
        db.rollback()
        job = load_job(db, job_id)
        if job:
            record_failure(db, job, exc)
        return {"job_id": job_id, "status": "failed", "error": str(exc)}
    except Exception as exc:
        db.rollback()
        job = load_job(db, job_id)
        non_retryable = (
            isinstance(exc, ProviderRuntimeError)
            and exc.provider == "blogger"
            and exc.status_code in {401, 403}
        )
        if isinstance(exc, QualityGateError):
            non_retryable = True
        if job and self.request.retries < self.max_retries and not non_retryable:
            errors = list(job.error_logs or [])
            errors.append(
                {
                    "message": str(exc),
                    "detail": getattr(exc, "detail", None),
                    "attempt": job.attempt_count,
                    "temporary": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            job.error_logs = errors
            job.status = JobStatus.PENDING
            db.add(job)
            db.commit()
            raise self.retry(exc=exc, countdown=min(30 * (2 ** self.request.retries), 180))
        if job:
            record_failure(db, job, exc)
        return {"job_id": job_id, "status": "failed", "error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.pipeline.discover_topics_and_enqueue")
def discover_topics_and_enqueue_task(
    blog_id: int,
    publish_mode: str | None = None,
    stop_after: str | None = None,
    topic_count: int | None = None,
    scheduled_start: str | None = None,
    publish_interval_minutes: int | None = None,
    editorial_category_key: str | None = None,
    editorial_category_label: str | None = None,
    editorial_category_guidance: str | None = None,
) -> dict:
    db = SessionLocal()
    try:
        return discover_topics_and_enqueue(
            db,
            blog_id=blog_id,
            publish_mode=publish_mode,
            stop_after=stop_after,
            topic_count=topic_count,
            scheduled_start=scheduled_start,
            publish_interval_minutes=publish_interval_minutes,
            editorial_category_key=editorial_category_key,
            editorial_category_label=editorial_category_label,
            editorial_category_guidance=editorial_category_guidance,
        )
    finally:
        db.close()

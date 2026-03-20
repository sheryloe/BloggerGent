from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from celery import Task
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.entities import BloggerPost, Image, JobStatus, LogLevel, PostStatus, PublishMode, WorkflowStageType
from app.services.article_service import build_collage_prompt, save_article
from app.services.audit_service import add_log, count_logs_since
from app.services.blog_service import get_blog, get_workflow_step, render_agent_prompt, stage_label
from app.services.content_guard_service import (
    DuplicateContentError,
    build_duplicate_exclusion_prompt,
    filter_duplicate_topic_items,
)
from app.services.html_assembler import assemble_article_html
from app.services.job_service import (
    create_job,
    increment_attempt,
    load_job,
    merge_prompt,
    merge_response,
    record_failure,
    set_status,
)
from app.services.providers.base import ProviderRuntimeError
from app.services.providers.factory import (
    get_article_provider,
    get_blogger_provider,
    get_image_provider,
    get_runtime_config,
    get_topic_provider,
)
from app.services.related_posts import find_related_articles
from app.services.settings_service import get_settings_map
from app.services.storage_service import save_html, save_public_binary
from app.services.telegram_service import send_telegram_post_notification
from app.services.topic_discovery_run_service import create_topic_discovery_run
from app.services.topic_guard_service import (
    TopicGuardConflictError,
    annotate_topic_items,
    assert_topic_guard,
    current_publish_target_datetime,
    rebuild_topic_memories_for_blog,
)
from app.services.topic_service import upsert_topics
from app.services.wikimedia_service import fetch_wikimedia_media

OPENAI_TOPIC_REQUEST_STAGE = "OPENAI_TOPIC_REQUEST"
GEMINI_TOPIC_REQUEST_STAGE = "GEMINI_TOPIC_REQUEST"
GEMINI_TOPIC_LIMIT_BLOCKED_STAGE = "GEMINI_TOPIC_LIMIT_BLOCKED"
PIPELINE_CONTROL_KEY = "pipeline_control"
PIPELINE_SCHEDULE_KEY = "pipeline_schedule"

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
    provider = (provider_hint or runtime.topic_discovery_provider or "openai").strip().lower()
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

def discover_topics_and_enqueue(
    db,
    blog_id: int,
    publish_mode: str | None = None,
    stop_after: str | JobStatus | None = None,
    topic_count: int | None = None,
    scheduled_start: str | datetime | None = None,
    publish_interval_minutes: int | None = None,
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
    topic_provider_name = _enforce_topic_provider_limits(
        db,
        blog=blog,
        provider_hint=topic_step.provider_hint,
        model_override=topic_step.provider_model,
    )
    provider = get_topic_provider(
        db,
        provider_hint=topic_step.provider_hint,
        model_override=topic_step.provider_model,
    )
    prompt = render_agent_prompt(
        blog,
        topic_step,
        topic_count=str(resolved_topic_count),
    ) + build_duplicate_exclusion_prompt(db, blog_id=blog.id)

    payload, raw_response = provider.discover_topics(prompt)
    discovered_items = list(payload.topics or [])[:resolved_topic_count]

    skip_reasons_by_keyword: dict[str, list[str]] = {item.keyword: [] for item in discovered_items}
    queued_keywords: set[str] = set()
    descriptor_by_keyword = annotate_topic_items(db, blog=blog, items=discovered_items)
    metadata_by_keyword = {
        keyword: {
            "topic_cluster_label": descriptor.topic_cluster_label,
            "topic_angle_label": descriptor.topic_angle_label,
            "distinct_reason": descriptor.distinct_reason,
            "topic_cluster_key": descriptor.topic_cluster_key,
            "topic_angle_key": descriptor.topic_angle_key,
        }
        for keyword, descriptor in descriptor_by_keyword.items()
    }

    guarded_topics = []
    skipped_duplicates: list[dict[str, str]] = []
    base_target_datetime = current_publish_target_datetime(db)
    for item in discovered_items:
        descriptor = descriptor_by_keyword[item.keyword]
        if first_publish_at:
            target_publish_datetime = first_publish_at + timedelta(minutes=resolved_publish_interval * len(guarded_topics))
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

    filtered_topics, duplicate_skips = filter_duplicate_topic_items(
        db,
        blog_id=blog.id,
        items=guarded_topics,
        metadata_by_keyword=metadata_by_keyword,
    )
    skipped_duplicates.extend(duplicate_skips)
    for skip in duplicate_skips:
        skip_reasons_by_keyword.setdefault(skip["keyword"], []).append(skip["reason"])

    topics = upsert_topics(
        db,
        blog,
        filtered_topics,
        source=topic_provider_name,
        metadata_by_keyword=metadata_by_keyword,
    )

    stop_after_status = _resolve_stop_after(settings_map, override=stop_after)
    job_ids: list[int] = []
    queued_cluster_angle_pairs: set[tuple[str, str]] = set()

    for topic in topics:
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

        slot_index = len(job_ids)
        scheduled_for = (
            first_publish_at + timedelta(minutes=resolved_publish_interval * slot_index)
            if first_publish_at
            else None
        )

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
                    "duplicate_filter": {"skipped": skipped_duplicates},
                },
            )
        except DuplicateContentError as exc:
            skipped_duplicates.append({"keyword": topic.keyword, "reason": str(exc)})
            skip_reasons_by_keyword.setdefault(topic.keyword, []).append(str(exc))
            continue

        if topic_cluster_key and topic_angle_key:
            queued_cluster_angle_pairs.add(cluster_angle_pair)

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

    runtime = get_runtime_config(db)
    provider_name = provider.__class__.__name__.lower()
    if "gemini" in provider_name:
        provider_label = "gemini"
        model_label = topic_step.provider_model or runtime.gemini_model
    elif "mock" in provider_name:
        provider_label = "mock"
        model_label = None
    else:
        provider_label = provider_name.replace("provider", "")
        model_label = topic_step.provider_model or runtime.topic_discovery_model or runtime.openai_text_model

    run_items = []
    for item in discovered_items:
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

    create_topic_discovery_run(
        db,
        blog_id=blog.id,
        provider=provider_label,
        model=model_label,
        prompt=prompt,
        raw_response=raw_response,
        items=run_items,
        job_ids=job_ids,
    )

    return {
        "blog_id": blog.id,
        "blog_name": blog.name,
        "queued_topics": len(job_ids),
        "job_ids": job_ids,
        "stop_after_status": stop_after_status.value if stop_after_status else None,
        "topic_count": resolved_topic_count,
        "message": (
            f"{blog.name} topic discovery complete. "
            f"Queued {len(job_ids)} jobs, skipped {len(skipped_duplicates)} duplicates/blocked items."
        ),
    }


def _publish_article(
    *,
    provider,
    article,
    job,
    scheduled_for: datetime | None,
) -> tuple[dict, dict, str]:
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
            labels=article.labels,
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
            labels=article.labels,
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
        labels=article.labels,
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
    request_saver_mode = _is_enabled_setting(settings_map.get("openai_request_saver_mode"), default=True)
    is_mystery_blog = blog.profile_key == "world_mystery" or (blog.content_category or "").lower() == "mystery"

    article_step = _require_enabled_step(blog, WorkflowStageType.ARTICLE_GENERATION)
    image_generation_step = _require_enabled_step(blog, WorkflowStageType.IMAGE_GENERATION)
    html_assembly_step = _require_enabled_step(blog, WorkflowStageType.HTML_ASSEMBLY)
    publishing_step = _require_enabled_step(blog, WorkflowStageType.PUBLISHING)
    image_prompt_step = _get_optional_enabled_step(blog, WorkflowStageType.IMAGE_PROMPT_GENERATION)
    related_posts_step = _get_optional_enabled_step(blog, WorkflowStageType.RELATED_POSTS)

    article_provider = get_article_provider(db, model_override=article_step.provider_model)
    image_provider = get_image_provider(db, model_override=image_generation_step.provider_model)

    set_status(db, job, JobStatus.GENERATING_ARTICLE, f"{blog.name} generating article content.")
    rendered_article_prompt = render_agent_prompt(blog, article_step, keyword=job.keyword_snapshot)
    merge_prompt(db, job, article_step.stage_type.value, rendered_article_prompt)
    article_output, article_raw = article_provider.generate_article(job.keyword_snapshot, rendered_article_prompt)
    merge_response(db, job, article_step.stage_type.value, article_raw)
    article = save_article(db, job=job, topic=topic, output=article_output)
    article.inline_media = []
    db.add(article)
    db.commit()
    db.refresh(article)
    if _complete_early_if_needed(db, job, completed_stage=JobStatus.GENERATING_ARTICLE, blog=blog):
        return

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
            blog,
            image_prompt_step,
            keyword=job.keyword_snapshot,
            article_title=article.title,
            article_excerpt=article.excerpt,
            article_context="\n".join(
                [
                    f"Title: {article.title}",
                    f"Excerpt: {article.excerpt}",
                    f"Labels: {', '.join(article.labels or [])}",
                    f"Article HTML: {article.html_article}",
                ]
            ),
        )
        merge_prompt(db, job, image_prompt_step.stage_type.value, rendered_visual_prompt_request)
        prompt_refinement_provider = get_article_provider(db, model_override=image_prompt_step.provider_model)
        rendered_visual_prompt, visual_prompt_raw = prompt_refinement_provider.generate_visual_prompt(
            rendered_visual_prompt_request
        )
        merge_response(
            db,
            job,
            image_prompt_step.stage_type.value,
            {"prompt": rendered_visual_prompt, "raw": visual_prompt_raw, "source": "agent"},
        )
    else:
        rendered_visual_prompt = (article.image_collage_prompt or "").strip() or build_collage_prompt(article)
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
    if _complete_early_if_needed(db, job, completed_stage=JobStatus.GENERATING_IMAGE_PROMPT, blog=blog):
        return

    set_status(
        db,
        job,
        JobStatus.GENERATING_IMAGE,
        f"{blog.name} preparing hero/inline images.",
    )

    hero_image_url = ""
    if is_mystery_blog:
        media_target = _coerce_non_negative_int(settings_map.get("wikimedia_image_count"), 3) or 3
        media_items = fetch_wikimedia_media(job.keyword_snapshot, count=media_target)
        article.inline_media = media_items
        db.add(article)
        db.commit()
        db.refresh(article)
        hero_image_url = (
            str(media_items[0].get("image_url") or media_items[0].get("thumb_url") or "")
            if media_items
            else ""
        )
        merge_response(
            db,
            job,
            image_generation_step.stage_type.value,
            {
                "provider": "wikimedia_commons",
                "collected": len(media_items),
                "hero_image_url": hero_image_url or None,
                "items": media_items,
            },
        )
    else:
        image_bytes, image_raw = image_provider.generate_image(rendered_visual_prompt, article.slug)
        file_path, public_url, delivery_meta = save_public_binary(
            db,
            subdir="images",
            filename=f"{article.slug}.png",
            content=image_bytes,
        )
        image = _upsert_image(
            db,
            job_id=job.id,
            article_id=article.id,
            prompt=rendered_visual_prompt,
            file_path=file_path,
            public_url=public_url,
            provider=image_generation_step.provider_hint or image_provider.__class__.__name__.replace("Provider", "").lower(),
            meta={**image_raw, "delivery": delivery_meta},
        )
        hero_image_url = public_url
        merge_response(
            db,
            job,
            image_generation_step.stage_type.value,
            {
                "public_url": public_url,
                "provider": image.provider,
                "delivery": delivery_meta,
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
    assembled_html = assemble_article_html(article, hero_image_url, related_posts)
    article.assembled_html = assembled_html
    db.add(article)
    db.commit()
    db.refresh(article)
    html_path, html_url = save_html(slug=article.slug, html=assembled_html)
    merge_response(db, job, html_assembly_step.stage_type.value, {"file_path": html_path, "public_url": html_url})
    if _complete_early_if_needed(db, job, completed_stage=JobStatus.ASSEMBLING_HTML, blog=blog):
        return

    set_status(db, job, JobStatus.PUBLISHING, f"{blog.name} publishing article to Blogger.")
    provider = get_blogger_provider(db, blog)
    scheduled_for = _resolve_publish_target_datetime(job) if job.publish_mode == PublishMode.PUBLISH else None
    summary, raw_payload, publish_action = _publish_article(
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
    rebuild_topic_memories_for_blog(db, blog)

    telegram_result = None
    if blogger_post.published_url and blogger_post.post_status in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
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
        )
    finally:
        db.close()


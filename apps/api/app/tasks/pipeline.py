from __future__ import annotations

from datetime import datetime, timedelta, timezone

from celery import Task
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.entities import BloggerPost, Image, JobStatus, LogLevel, PublishMode, WorkflowStageType
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
    get_image_provider,
    get_runtime_config,
    get_topic_provider,
)
from app.services.related_posts import find_related_articles
from app.services.settings_service import get_settings_map
from app.services.storage_service import save_html, save_public_binary
from app.services.topic_service import upsert_topics

GEMINI_TOPIC_REQUEST_STAGE = "GEMINI_TOPIC_REQUEST"
GEMINI_TOPIC_LIMIT_BLOCKED_STAGE = "GEMINI_TOPIC_LIMIT_BLOCKED"
PIPELINE_CONTROL_KEY = "pipeline_control"

PIPELINE_STOP_ALLOWED = {
    JobStatus.GENERATING_ARTICLE,
    JobStatus.GENERATING_IMAGE_PROMPT,
    JobStatus.GENERATING_IMAGE,
    JobStatus.ASSEMBLING_HTML,
}

PIPELINE_STAGE_LABELS = {
    JobStatus.GENERATING_ARTICLE: "본문 생성",
    JobStatus.GENERATING_IMAGE_PROMPT: "이미지 프롬프트 생성",
    JobStatus.GENERATING_IMAGE: "이미지 생성",
    JobStatus.ASSEMBLING_HTML: "HTML 조립",
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
        raise ValueError(f"{blog.name} 블로그에 '{stage_label(stage_type)}' 단계가 없습니다.")
    if not step.is_enabled:
        raise ValueError(f"{blog.name} 블로그의 '{stage_label(stage_type)}' 단계가 비활성화되어 있습니다.")
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
    published_at = summary.get("published")
    if isinstance(published_at, str):
        published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    payload = {
        "blog_id": blog_id,
        "article_id": article_id,
        "blogger_post_id": summary.get("id", f"job-{job_id}"),
        "published_url": summary.get("url", ""),
        "published_at": published_at,
        "is_draft": bool(summary.get("isDraft", True)),
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


def _coerce_non_negative_int(raw_value: str | None, fallback: int) -> int:
    try:
        parsed = int(str(raw_value or fallback).strip())
    except (TypeError, ValueError):
        return fallback
    return max(parsed, 0)


def _enforce_gemini_topic_limits(db, *, blog) -> None:
    runtime = get_runtime_config(db)
    if runtime.provider_mode != "live" or not runtime.gemini_api_key:
        return

    settings_map = get_settings_map(db)
    minute_limit = _coerce_non_negative_int(settings_map.get("gemini_requests_per_minute_limit"), 2)
    daily_limit = _coerce_non_negative_int(settings_map.get("gemini_daily_request_limit"), 6)
    now = datetime.now(timezone.utc)

    if minute_limit > 0:
        recent_count = count_logs_since(db, stage=GEMINI_TOPIC_REQUEST_STAGE, since=now - timedelta(minutes=1))
        if recent_count >= minute_limit:
            message = "Gemini 분당 요청 제한에 도달했습니다."
            detail = f"최근 1분 동안 {recent_count}회 요청되어 제한 {minute_limit}회를 초과했습니다."
            add_log(
                db,
                job=None,
                stage=GEMINI_TOPIC_LIMIT_BLOCKED_STAGE,
                message=message,
                level=LogLevel.WARNING,
                payload={"blog_id": blog.id, "window": "1m", "count": recent_count, "limit": minute_limit},
            )
            raise ProviderRuntimeError(provider="gemini", status_code=429, message=message, detail=detail)

    if daily_limit > 0:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_count = count_logs_since(db, stage=GEMINI_TOPIC_REQUEST_STAGE, since=today_start)
        if daily_count >= daily_limit:
            message = "Gemini 일일 요청 제한에 도달했습니다."
            detail = f"오늘 이미 {daily_count}회 요청되어 일일 제한 {daily_limit}회에 도달했습니다."
            add_log(
                db,
                job=None,
                stage=GEMINI_TOPIC_LIMIT_BLOCKED_STAGE,
                message=message,
                level=LogLevel.WARNING,
                payload={"blog_id": blog.id, "window": "1d", "count": daily_count, "limit": daily_limit},
            )
            raise ProviderRuntimeError(provider="gemini", status_code=429, message=message, detail=detail)

    add_log(
        db,
        job=None,
        stage=GEMINI_TOPIC_REQUEST_STAGE,
        message=f"{blog.name} 블로그 주제 발굴을 위해 Gemini를 호출했습니다.",
        payload={"blog_id": blog.id, "blog_slug": blog.slug, "model": runtime.gemini_model},
    )


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
        f"{blog.name} 파이프라인을 {finished_stage_label} 단계까지 실행하고 중지했습니다.",
        payload=payload,
    )
    return True


def discover_topics_and_enqueue(
    db,
    blog_id: int,
    publish_mode: str | None = None,
    stop_after: str | JobStatus | None = None,
) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise ValueError(f"Blog {blog_id} not found")

    topic_step = _require_enabled_step(blog, WorkflowStageType.TOPIC_DISCOVERY)
    provider = get_topic_provider(db, model_override=topic_step.provider_model)
    prompt = render_agent_prompt(blog, topic_step) + build_duplicate_exclusion_prompt(db, blog_id=blog.id)
    _enforce_gemini_topic_limits(db, blog=blog)
    payload, raw_response = provider.discover_topics(prompt)
    filtered_topics, skipped_duplicates = filter_duplicate_topic_items(db, blog_id=blog.id, items=payload.topics)
    topics = upsert_topics(db, blog, filtered_topics)

    settings_map = get_settings_map(db)
    mode_value = publish_mode or "draft"
    mode = PublishMode(mode_value)
    stop_after_status = _resolve_stop_after(settings_map, override=stop_after)

    job_ids: list[int] = []
    for topic in topics:
        try:
            job = create_job(
                db,
                blog_id=blog.id,
                keyword=topic.keyword,
                topic_id=topic.id,
                publish_mode=mode,
                initial_status=JobStatus.DISCOVERING_TOPICS,
                raw_prompts={
                    topic_step.stage_type.value: prompt,
                    PIPELINE_CONTROL_KEY: _serialize_pipeline_control(stop_after_status),
                },
                raw_responses={
                    topic_step.stage_type.value: raw_response,
                    "duplicate_filter": {"skipped": skipped_duplicates},
                },
            )
        except DuplicateContentError as exc:
            skipped_duplicates.append({"keyword": topic.keyword, "reason": str(exc)})
            continue
        set_status(
            db,
            job,
            JobStatus.PENDING,
            f"{blog.name} 블로그용 주제를 확보하고 파이프라인 대기열에 등록했습니다.",
            {"blog_id": blog.id, "topic_id": topic.id},
        )
        run_job.delay(job.id)
        job_ids.append(job.id)

    return {
        "blog_id": blog.id,
        "blog_name": blog.name,
        "queued_topics": len(job_ids),
        "job_ids": job_ids,
        "stop_after_status": stop_after_status.value if stop_after_status else None,
        "message": f"{blog.name} 블로그 주제 수집과 작업 등록을 완료했습니다. 중복 후보 {len(skipped_duplicates)}개는 제외했습니다.",
    }


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

    article_step = _require_enabled_step(blog, WorkflowStageType.ARTICLE_GENERATION)
    image_generation_step = _require_enabled_step(blog, WorkflowStageType.IMAGE_GENERATION)
    html_assembly_step = _require_enabled_step(blog, WorkflowStageType.HTML_ASSEMBLY)
    publishing_step = _require_enabled_step(blog, WorkflowStageType.PUBLISHING)
    image_prompt_step = _get_optional_enabled_step(blog, WorkflowStageType.IMAGE_PROMPT_GENERATION)
    related_posts_step = _get_optional_enabled_step(blog, WorkflowStageType.RELATED_POSTS)

    article_provider = get_article_provider(db, model_override=article_step.provider_model)
    image_provider = get_image_provider(db, model_override=image_generation_step.provider_model)
    set_status(db, job, JobStatus.GENERATING_ARTICLE, f"{blog.name} 블로그용 본문을 생성하고 있습니다.")
    rendered_article_prompt = render_agent_prompt(blog, article_step, keyword=job.keyword_snapshot)
    merge_prompt(db, job, article_step.stage_type.value, rendered_article_prompt)
    article_output, article_raw = article_provider.generate_article(job.keyword_snapshot, rendered_article_prompt)
    merge_response(db, job, article_step.stage_type.value, article_raw)
    article = save_article(db, job=job, topic=topic, output=article_output)
    if _complete_early_if_needed(db, job, completed_stage=JobStatus.GENERATING_ARTICLE, blog=blog):
        return

    set_status(
        db,
        job,
        JobStatus.GENERATING_IMAGE_PROMPT,
        f"{blog.name} 블로그용 대표 이미지 프롬프트를 준비하고 있습니다.",
    )
    if image_prompt_step and not request_saver_mode:
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
                "[request_saver_mode] Skipped a separate image prompt LLM call and reused article.image_collage_prompt.",
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
        f"{blog.name} 블로그의 대표 이미지를 생성하고 있습니다.",
    )
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
    merge_response(
        db,
        job,
        image_generation_step.stage_type.value,
        {"public_url": public_url, "provider": image.provider, "delivery": delivery_meta},
    )
    if _complete_early_if_needed(db, job, completed_stage=JobStatus.GENERATING_IMAGE, blog=blog):
        return

    related_posts: list[dict] = []
    if related_posts_step:
        set_status(
            db,
            job,
            JobStatus.FINDING_RELATED_POSTS,
            f"{blog.name} 블로그와 관련된 글을 찾고 있습니다.",
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
        f"{blog.name} 블로그용 최종 HTML을 조립하고 있습니다.",
    )
    db.refresh(article, attribute_names=["blog"])
    assembled_html = assemble_article_html(article, public_url, related_posts)
    article.assembled_html = assembled_html
    db.add(article)
    db.commit()
    db.refresh(article)
    html_path, html_url = save_html(slug=article.slug, html=assembled_html)
    merge_response(db, job, html_assembly_step.stage_type.value, {"file_path": html_path, "public_url": html_url})
    if _complete_early_if_needed(db, job, completed_stage=JobStatus.ASSEMBLING_HTML, blog=blog):
        return

    merge_response(
        db,
        job,
        publishing_step.stage_type.value,
        {
            "mode": "manual_publish_pending",
            "publish_mode_requested": job.publish_mode.value,
            "message": "초안 생성이 완료되었습니다. 생성 글 목록의 공개 게시 버튼으로 최종 게시를 진행하세요.",
        },
    )
    set_status(
        db,
        job,
        JobStatus.COMPLETED,
        f"{blog.name} 글 초안을 완성했습니다. 생성 글 목록의 공개 게시 버튼에서 최종 게시를 진행하세요.",
        {"article_id": article.id, "publish_action": "manual_button"},
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
        if job and self.request.retries < self.max_retries:
            errors = list(job.error_logs or [])
            errors.append(
                {
                    "message": str(exc),
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
def discover_topics_and_enqueue_task(blog_id: int, publish_mode: str | None = None, stop_after: str | None = None) -> dict:
    db = SessionLocal()
    try:
        return discover_topics_and_enqueue(db, blog_id=blog_id, publish_mode=publish_mode, stop_after=stop_after)
    finally:
        db.close()

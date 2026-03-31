from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
import re
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Article, SyncedBloggerPost, TrainingRun
from app.services.settings_service import get_settings_map, upsert_settings

ACTIVE_STATES = {"queued", "running"}
PAUSED_STATE = "paused"
COMPLETED_STATE = "completed"
FAILED_STATE = "failed"

DEFAULT_SESSION_HOURS = 4.0
DEFAULT_SAVE_EVERY_MINUTES = 20
DEFAULT_SCHEDULE_TIME = "03:00"
DEFAULT_SCHEDULE_TIMEZONE = "Asia/Seoul"

SCHEDULE_ENABLED_KEY = "training_schedule_enabled"
SCHEDULE_TIME_KEY = "training_schedule_time"
SCHEDULE_TIMEZONE_KEY = "training_schedule_timezone"
SCHEDULE_LAST_RUN_ON_KEY = "training_schedule_last_run_on"
REAL_ENGINE_ENABLED_KEY = "training_use_real_engine"

DATA_SCOPE_LABEL = "synced_blogger_posts.content_html + articles.html_article + content_ops.curated_learning"
MAX_LOG_LINES = 80
HTML_TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
CHECKPOINT_FORMAT_V1 = "training/checkpoint-v1"
CHECKPOINT_VERSION = 1


class TrainingServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class TrainingSchedule:
    enabled: bool
    time: str
    timezone: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_bool(value: str | bool | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _normalize_hhmm(raw: str) -> str:
    value = (raw or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        raise TrainingServiceError("time must be HH:MM format.", status_code=422)
    hours, minutes = [int(part) for part in value.split(":", maxsplit=1)]
    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        raise TrainingServiceError("time must be a valid 24-hour value.", status_code=422)
    return f"{hours:02d}:{minutes:02d}"


def _normalize_timezone(raw: str) -> str:
    candidate = (raw or "").strip() or DEFAULT_SCHEDULE_TIMEZONE
    try:
        ZoneInfo(candidate)
    except Exception as exc:  # noqa: BLE001
        raise TrainingServiceError("timezone is invalid.", status_code=422) from exc
    return candidate


def is_real_training_engine_enabled(db: Session) -> bool:
    settings_map = get_settings_map(db)
    return _as_bool(settings_map.get(REAL_ENGINE_ENABLED_KEY), default=False)


def _normalize_session_hours(value: float | int | None) -> float:
    try:
        parsed = float(value if value is not None else DEFAULT_SESSION_HOURS)
    except (TypeError, ValueError) as exc:
        raise TrainingServiceError("session_hours must be a number.", status_code=422) from exc
    if parsed <= 0 or parsed > 24:
        raise TrainingServiceError("session_hours must be between 0 and 24.", status_code=422)
    return round(parsed, 3)


def _normalize_save_every_minutes(value: int | None) -> int:
    if value is None:
        return DEFAULT_SAVE_EVERY_MINUTES
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TrainingServiceError("save_every_minutes must be an integer.", status_code=422) from exc
    if parsed < 1 or parsed > 180:
        raise TrainingServiceError("save_every_minutes must be between 1 and 180.", status_code=422)
    return parsed


def _append_log(run: TrainingRun, message: str) -> None:
    logs = list(run.log_tail or [])
    logs.append(f"{_utc_now().isoformat()} {message}")
    if len(logs) > MAX_LOG_LINES:
        logs = logs[-MAX_LOG_LINES:]
    run.log_tail = logs


def _strip_html(value: str) -> str:
    without_tags = HTML_TAG_RE.sub(" ", value or "")
    return WS_RE.sub(" ", without_tags).strip()


def _training_base_dir() -> Path:
    return Path(settings.storage_root) / "training"


def _dataset_dir() -> Path:
    return _training_base_dir() / "datasets"


def _run_dir(run_id: int) -> Path:
    return _training_base_dir() / "runs" / f"run-{run_id}"


def _checkpoints_dir(run_id: int) -> Path:
    return _run_dir(run_id) / "checkpoints"


def _dataset_snapshot_paths(run_id: int) -> tuple[Path, Path]:
    timestamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    base = _dataset_dir() / f"run-{run_id}-{timestamp}"
    return base.with_suffix(".jsonl"), base.with_suffix(".manifest.json")


def _append_curated_learning_snapshot(db: Session, fp, manifest_sources: dict[str, int]) -> int:
    settings_map = get_settings_map(db)
    curated_path_raw = (settings_map.get("content_ops_learning_snapshot_path") or "").strip()
    if not curated_path_raw:
        return 0

    curated_path = Path(curated_path_raw)
    if not curated_path.is_file():
        return 0

    count = 0
    with curated_path.open("r", encoding="utf-8") as curated_fp:
        for line in curated_fp:
            candidate = line.strip()
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
            count += 1

    manifest_sources["content_ops_curated_learning"] = count
    return count


def _build_dataset_snapshot(db: Session, run_id: int) -> tuple[str, str, int]:
    dataset_jsonl_path, manifest_path = _dataset_snapshot_paths(run_id)
    dataset_jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    synced_rows = db.execute(
        select(
            SyncedBloggerPost.id,
            SyncedBloggerPost.blog_id,
            SyncedBloggerPost.remote_post_id,
            SyncedBloggerPost.title,
            SyncedBloggerPost.content_html,
        ).order_by(SyncedBloggerPost.id.asc())
    ).all()
    article_rows = db.execute(
        select(
            Article.id,
            Article.blog_id,
            Article.title,
            Article.html_article,
            Article.meta_description,
            Article.excerpt,
        ).order_by(Article.id.asc())
    ).all()

    manifest_sources = {
        "synced_blogger_posts": len(synced_rows),
        "articles": len(article_rows),
    }

    count = 0
    with dataset_jsonl_path.open("w", encoding="utf-8") as fp:
        for row in synced_rows:
            text = _strip_html(row.content_html or "")
            if not text:
                continue
            fp.write(
                json.dumps(
                    {
                        "source": "synced_blogger_posts",
                        "item_id": row.remote_post_id or f"synced-{row.id}",
                        "blog_id": row.blog_id,
                        "title": row.title,
                        "text": text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            count += 1

        count += _append_curated_learning_snapshot(db, fp, manifest_sources)

        for row in article_rows:
            text = _strip_html(row.html_article or "")
            if not text:
                continue
            fp.write(
                json.dumps(
                    {
                        "source": "articles",
                        "item_id": f"article-{row.id}",
                        "blog_id": row.blog_id,
                        "title": row.title,
                        "meta_description": row.meta_description,
                        "excerpt": row.excerpt,
                        "text": text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            count += 1

    if count == 0:
        raise TrainingServiceError("No training source content is available yet.", status_code=422)

    manifest = {
        "created_at": _utc_now().isoformat(),
        "run_id": run_id,
        "scope": DATA_SCOPE_LABEL,
        "dataset_jsonl_path": str(dataset_jsonl_path),
        "item_count": count,
        "sources": manifest_sources,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(manifest_path), str(dataset_jsonl_path), count


def _load_checkpoint_payload(run: TrainingRun, checkpoint_path: str) -> dict[str, Any]:
    path = Path(checkpoint_path)
    if not path.is_file():
        raise TrainingServiceError("Checkpoint file is not available.", status_code=409)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # noqa: BLE001
        raise TrainingServiceError(f"Failed to read checkpoint: {exc}", status_code=409) from exc
    if not isinstance(payload, dict):
        raise TrainingServiceError("Checkpoint payload format is invalid.", status_code=409)
    return payload


def _validate_resume_state(run: TrainingRun) -> dict[str, Any]:
    if not run.last_checkpoint:
        raise TrainingServiceError("No checkpoint is available for the paused run.", status_code=409)

    payload = _load_checkpoint_payload(run, run.last_checkpoint)

    resume_state = payload.get("resume_state")
    if resume_state is not None and not isinstance(resume_state, dict):
        raise TrainingServiceError("Checkpoint resume_state is malformed.", status_code=409)

    checkpoint_version = payload.get("checkpoint_version", 0)
    if checkpoint_version is None:
        checkpoint_version = 0
    if not isinstance(checkpoint_version, int):
        raise TrainingServiceError("Checkpoint version is malformed.", status_code=409)
    if checkpoint_version > CHECKPOINT_VERSION:
        raise TrainingServiceError("Checkpoint version is not supported.", status_code=409)

    artifact_format = payload.get("artifact_format")
    if artifact_format is not None and artifact_format != CHECKPOINT_FORMAT_V1:
        raise TrainingServiceError("Checkpoint format is not supported.", status_code=409)

    checkpoint_run_id = payload.get("run_id")
    if checkpoint_run_id is not None and checkpoint_run_id != run.id:
        raise TrainingServiceError("Checkpoint belongs to a different training run.", status_code=409)

    return payload


def list_recent_runs(db: Session, *, limit: int = 5) -> list[TrainingRun]:
    return (
        db.execute(select(TrainingRun).order_by(TrainingRun.id.desc()).limit(max(1, min(limit, 20))))
        .scalars()
        .all()
    )


def get_latest_run(db: Session) -> TrainingRun | None:
    return db.execute(select(TrainingRun).order_by(TrainingRun.id.desc()).limit(1)).scalar_one_or_none()


def get_run(db: Session, run_id: int) -> TrainingRun | None:
    return db.execute(select(TrainingRun).where(TrainingRun.id == run_id)).scalar_one_or_none()


def get_active_run(db: Session) -> TrainingRun | None:
    return (
        db.execute(
            select(TrainingRun)
            .where(TrainingRun.state.in_(ACTIVE_STATES))
            .order_by(TrainingRun.id.desc())
            .limit(1)
        )
        .scalar_one_or_none()
    )


def _resolve_total_steps(item_count: int) -> int:
    return max(120, min(6000, item_count * 4))


def start_training_run(
    db: Session,
    *,
    session_hours: float | int | None = None,
    save_every_minutes: int | None = None,
    trigger_source: str = "manual",
) -> TrainingRun:
    if get_active_run(db):
        raise TrainingServiceError("Another training run is already queued or running.", status_code=409)

    resolved_session_hours = _normalize_session_hours(session_hours)
    resolved_save_every = _normalize_save_every_minutes(save_every_minutes)
    run = TrainingRun(
        state="queued",
        trigger_source=trigger_source,
        session_hours=resolved_session_hours,
        save_every_minutes=resolved_save_every,
        current_step=0,
        total_steps=0,
        dataset_item_count=0,
        pause_requested=False,
        elapsed_seconds=0,
        checkpoint_count=0,
        log_tail=[],
    )
    _append_log(run, "Run queued.")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        manifest_path, dataset_path, item_count = _build_dataset_snapshot(db, run.id)
    except TrainingServiceError as exc:
        run.state = FAILED_STATE
        run.last_error = exc.message
        run.ended_at = _utc_now()
        _append_log(run, f"Dataset snapshot failed: {exc.message}")
        db.add(run)
        db.commit()
        raise

    run.dataset_manifest_path = manifest_path
    run.dataset_jsonl_path = dataset_path
    run.dataset_item_count = item_count
    run.total_steps = _resolve_total_steps(item_count)
    _append_log(
        run,
        f"Dataset snapshot saved ({item_count} items). Session={resolved_session_hours}h, save every {resolved_save_every}m.",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def resume_training_run(
    db: Session,
    *,
    session_hours: float | int | None = None,
    save_every_minutes: int | None = None,
) -> TrainingRun:
    if get_active_run(db):
        raise TrainingServiceError("Another training run is already queued or running.", status_code=409)

    run = (
        db.execute(select(TrainingRun).where(TrainingRun.state == PAUSED_STATE).order_by(TrainingRun.id.desc()).limit(1))
        .scalar_one_or_none()
    )
    if not run:
        raise TrainingServiceError("No paused run is available.", status_code=404)

    if run.current_step >= run.total_steps and run.total_steps > 0:
        raise TrainingServiceError("The latest paused run is already complete.", status_code=409)

    checkpoint_payload = _validate_resume_state(run)
    checkpoint_step = checkpoint_payload.get("current_step")
    checkpoint_time = checkpoint_payload.get("saved_at")
    _append_log(
        run,
        f"Resume queued from checkpoint {Path(run.last_checkpoint).name} "
        f"(step={checkpoint_step}, saved_at={checkpoint_time}).",
    )

    run.state = "queued"
    run.pause_requested = False
    run.last_error = None
    run.ended_at = None
    run.session_deadline_at = None
    run.session_hours = _normalize_session_hours(session_hours if session_hours is not None else run.session_hours)
    run.save_every_minutes = _normalize_save_every_minutes(
        save_every_minutes if save_every_minutes is not None else run.save_every_minutes
    )
    _append_log(run, "Resume queued from latest checkpoint.")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def request_pause_run(db: Session) -> TrainingRun:
    run = get_active_run(db)
    if not run:
        raise TrainingServiceError("No active training run is available.", status_code=404)

    if run.state == "queued":
        run.state = PAUSED_STATE
        run.ended_at = _utc_now()
        run.pause_requested = False
        _append_log(run, "Run paused before worker start.")
    else:
        run.pause_requested = True
        _append_log(run, "Pause requested. Worker will checkpoint and pause.")

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def mark_run_started(db: Session, *, run_id: int, task_id: str | None) -> TrainingRun:
    run = get_run(db, run_id)
    if not run:
        raise TrainingServiceError("Training run not found.", status_code=404)
    if run.state not in {"queued", "running"}:
        raise TrainingServiceError("Training run is not runnable.", status_code=409)

    run.state = "running"
    run.pause_requested = False
    if run.started_at is None:
        run.started_at = _utc_now()
    run.session_deadline_at = _utc_now() + timedelta(hours=run.session_hours)
    if task_id:
        run.task_id = task_id
    _append_log(run, "Training session started.")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def create_checkpoint(db: Session, *, run_id: int, reason: str) -> str:
    run = get_run(db, run_id)
    if not run:
        raise TrainingServiceError("Training run not found.", status_code=404)

    checkpoints_dir = _checkpoints_dir(run.id)
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"step-{run.current_step:05d}-{_utc_now().strftime('%Y%m%dT%H%M%SZ')}.json"
    path = checkpoints_dir / file_name
    payload = {
        "run_id": run.id,
        "saved_at": _utc_now().isoformat(),
        "reason": reason,
        "state": run.state,
        "current_step": run.current_step,
        "total_steps": run.total_steps,
        "loss": run.loss,
        "elapsed_seconds": run.elapsed_seconds,
        "dataset_manifest_path": run.dataset_manifest_path,
        "checkpoint_version": CHECKPOINT_VERSION,
        "artifact_format": CHECKPOINT_FORMAT_V1,
        "resume_state": {
            "state": run.state,
            "current_step": run.current_step,
            "total_steps": run.total_steps,
            "loss": run.loss,
            "elapsed_seconds": run.elapsed_seconds,
            "eta_seconds": run.eta_seconds,
            "dataset_manifest_path": run.dataset_manifest_path,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    run.last_checkpoint = str(path)
    run.last_checkpoint_at = _utc_now()
    run.checkpoint_count = int(run.checkpoint_count or 0) + 1
    _append_log(run, f"Checkpoint saved ({reason}).")
    db.add(run)
    db.commit()
    return str(path)


def mark_run_paused(db: Session, *, run_id: int, reason: str) -> TrainingRun:
    run = get_run(db, run_id)
    if not run:
        raise TrainingServiceError("Training run not found.", status_code=404)
    run.state = PAUSED_STATE
    run.pause_requested = False
    run.ended_at = _utc_now()
    run.session_deadline_at = None
    _append_log(run, f"Run paused ({reason}).")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def mark_run_completed(db: Session, *, run_id: int) -> TrainingRun:
    run = get_run(db, run_id)
    if not run:
        raise TrainingServiceError("Training run not found.", status_code=404)
    run.state = COMPLETED_STATE
    run.current_step = max(run.current_step, run.total_steps)
    run.eta_seconds = 0
    run.pause_requested = False
    run.ended_at = _utc_now()
    run.session_deadline_at = None
    _append_log(run, "Run completed.")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def mark_run_failed(db: Session, *, run_id: int, detail: str) -> TrainingRun:
    run = get_run(db, run_id)
    if not run:
        raise TrainingServiceError("Training run not found.", status_code=404)
    run.state = FAILED_STATE
    run.last_error = detail
    run.pause_requested = False
    run.ended_at = _utc_now()
    run.session_deadline_at = None
    _append_log(run, f"Run failed: {detail}")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_training_progress(
    db: Session,
    *,
    run_id: int,
    current_step: int,
    loss: float | None,
    elapsed_seconds: int,
    eta_seconds: int | None,
) -> TrainingRun:
    run = get_run(db, run_id)
    if not run:
        raise TrainingServiceError("Training run not found.", status_code=404)
    run.current_step = current_step
    run.loss = loss
    run.elapsed_seconds = max(0, int(elapsed_seconds))
    run.eta_seconds = max(0, int(eta_seconds)) if eta_seconds is not None else None
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_training_schedule(settings_map: dict[str, str]) -> TrainingSchedule:
    return TrainingSchedule(
        enabled=_as_bool(settings_map.get(SCHEDULE_ENABLED_KEY), default=False),
        time=_normalize_hhmm(settings_map.get(SCHEDULE_TIME_KEY, DEFAULT_SCHEDULE_TIME)),
        timezone=_normalize_timezone(settings_map.get(SCHEDULE_TIMEZONE_KEY, DEFAULT_SCHEDULE_TIMEZONE)),
    )


def update_training_schedule(
    db: Session,
    *,
    enabled: bool,
    time: str,
    timezone_name: str,
) -> TrainingSchedule:
    normalized_time = _normalize_hhmm(time)
    normalized_timezone = _normalize_timezone(timezone_name)
    upsert_settings(
        db,
        {
            SCHEDULE_ENABLED_KEY: "true" if enabled else "false",
            SCHEDULE_TIME_KEY: normalized_time,
            SCHEDULE_TIMEZONE_KEY: normalized_timezone,
        },
    )
    return TrainingSchedule(enabled=enabled, time=normalized_time, timezone=normalized_timezone)


def compute_next_scheduled_at(schedule: TrainingSchedule) -> str | None:
    if not schedule.enabled:
        return None
    timezone_obj = ZoneInfo(schedule.timezone)
    now_local = datetime.now(timezone_obj)
    hours, minutes = [int(part) for part in schedule.time.split(":", maxsplit=1)]
    next_local = now_local.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    if next_local <= now_local:
        next_local += timedelta(days=1)
    return next_local.astimezone(timezone.utc).isoformat()


def serialize_training_status(db: Session) -> dict:
    settings_map = get_settings_map(db)
    schedule = get_training_schedule(settings_map)
    run = get_latest_run(db)

    model_name = (
        (settings_map.get("ollama_text_model") or "").strip()
        or (settings_map.get("article_generation_model") or "").strip()
        or (settings_map.get("openai_text_model") or "").strip()
        or None
    )

    if not run:
        return {
            "state": "idle",
            "current_step": 0,
            "total_steps": 0,
            "loss": None,
            "elapsed_seconds": 0,
            "eta_seconds": None,
            "last_checkpoint": None,
            "next_scheduled_at": compute_next_scheduled_at(schedule),
            "last_error": None,
            "session_hours": DEFAULT_SESSION_HOURS,
            "save_every_minutes": DEFAULT_SAVE_EVERY_MINUTES,
            "pause_requested": False,
            "run_id": None,
            "dataset_item_count": 0,
            "recent_logs": [],
            "schedule": {
                "enabled": schedule.enabled,
                "time": schedule.time,
                "timezone": schedule.timezone,
            },
            "model_name": model_name,
            "data_scope": DATA_SCOPE_LABEL,
        }

    return {
        "state": run.state,
        "current_step": int(run.current_step or 0),
        "total_steps": int(run.total_steps or 0),
        "loss": run.loss,
        "elapsed_seconds": int(run.elapsed_seconds or 0),
        "eta_seconds": run.eta_seconds,
        "last_checkpoint": run.last_checkpoint,
        "next_scheduled_at": compute_next_scheduled_at(schedule),
        "last_error": run.last_error,
        "session_hours": run.session_hours,
        "save_every_minutes": run.save_every_minutes,
        "pause_requested": bool(run.pause_requested),
        "run_id": run.id,
        "dataset_item_count": int(run.dataset_item_count or 0),
        "recent_logs": list(run.log_tail or []),
        "schedule": {
            "enabled": schedule.enabled,
            "time": schedule.time,
            "timezone": schedule.timezone,
        },
        "model_name": model_name,
        "data_scope": DATA_SCOPE_LABEL,
    }

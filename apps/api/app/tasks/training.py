from __future__ import annotations

from datetime import datetime, timezone
import math
import time
from typing import Callable

from celery import Task

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.integrations.telegram_service import send_telegram_ops_notification
from app.services.content.training_service import (
    PAUSED_STATE,
    create_checkpoint,
    is_real_training_engine_enabled,
    get_run,
    mark_run_completed,
    mark_run_failed,
    mark_run_paused,
    mark_run_started,
    update_training_progress,
)


def _next_loss(previous: float | None, step: int) -> float:
    if previous is None:
        baseline = 2.4
    else:
        baseline = previous
    next_value = baseline * 0.995 - 0.0005
    floor = 0.65 + (1.0 / max(80, step + 20))
    return round(max(next_value, floor), 6)


def _run_simulated_training(db: SessionLocal, run_id: int, save_interval_seconds: int, last_save_at: float) -> dict:
    while True:
        run = get_run(db, run_id)
        if not run:
            return {"status": "missing", "run_id": run_id}
        if run.state not in {"queued", "running"}:
            return {"status": "stopped", "state": run.state, "run_id": run_id}

        if run.pause_requested:
            create_checkpoint(db, run_id=run.id, reason="manual_pause")
            mark_run_paused(db, run_id=run.id, reason="manual_pause")
            return {"status": PAUSED_STATE, "reason": "manual_pause", "run_id": run.id}

        if run.session_deadline_at and datetime.now(timezone.utc) >= run.session_deadline_at:
            create_checkpoint(db, run_id=run.id, reason="session_timeout")
            mark_run_paused(db, run_id=run.id, reason="session_timeout")
            return {"status": PAUSED_STATE, "reason": "session_timeout", "run_id": run.id}

        if run.current_step >= run.total_steps and run.total_steps > 0:
            create_checkpoint(db, run_id=run.id, reason="completed")
            mark_run_completed(db, run_id=run.id)
            return {"status": "completed", "run_id": run.id}

        next_step = int(run.current_step or 0) + 1
        elapsed = int(run.elapsed_seconds or 0) + 1
        remaining = max((run.total_steps or 0) - next_step, 0)
        avg_sec_per_step = elapsed / next_step if next_step > 0 else 1.0
        eta_seconds = int(math.ceil(remaining * avg_sec_per_step)) if remaining > 0 else 0
        loss = _next_loss(run.loss, next_step)

        update_training_progress(
            db,
            run_id=run.id,
            current_step=next_step,
            loss=loss,
            elapsed_seconds=elapsed,
            eta_seconds=eta_seconds,
        )

        if time.monotonic() - last_save_at >= save_interval_seconds:
            create_checkpoint(db, run_id=run.id, reason="periodic_save")
            last_save_at = time.monotonic()

        time.sleep(1.0)


def _run_real_training(db: SessionLocal, run_id: int, save_interval_seconds: int, last_save_at: float) -> dict:
    # Adapter slot: switch to actual training pipeline here when training_use_real_engine=true.
    # Keep simulation behavior for now to avoid changing control-plane semantics.
    return _run_simulated_training(db, run_id=run_id, save_interval_seconds=save_interval_seconds, last_save_at=last_save_at)


def _select_training_runner(db) -> Callable[[SessionLocal, int, int, float], dict]:
    if is_real_training_engine_enabled(db):
        return _run_real_training
    return _run_simulated_training


@celery_app.task(bind=True, name="app.tasks.training.run_training_session", max_retries=0)
def run_training_session(self: Task, run_id: int) -> dict:
    db = SessionLocal()
    try:
        run = get_run(db, run_id)
        if not run:
            return {"status": "missing", "run_id": run_id}
        if run.state not in {"queued", "running"}:
            return {"status": "skipped", "state": run.state, "run_id": run_id}

        run = mark_run_started(db, run_id=run.id, task_id=getattr(self.request, "id", None))
        save_interval_seconds = max(60, int(run.save_every_minutes * 60))
        last_save_at = time.monotonic()
        runner = _select_training_runner(db)
        result = runner(db=db, run_id=run.id, save_interval_seconds=save_interval_seconds, last_save_at=last_save_at)
        if result.get("status") == "completed":
            send_telegram_ops_notification(db, title="Training completed", detail=f"run_id={run.id}")
        elif result.get("status") == PAUSED_STATE:
            send_telegram_ops_notification(
                db,
                title="Training paused",
                detail=f"run_id={run.id} reason={result.get('reason', 'unknown')}",
            )
        elif result.get("status") == "failed":
            send_telegram_ops_notification(
                db,
                title="Training failed",
                detail=f"run_id={run.id} detail={result.get('detail', 'unknown')}",
            )
        return result
    except Exception as exc:  # noqa: BLE001
        try:
            mark_run_failed(db, run_id=run_id, detail=str(exc))
        except Exception:  # noqa: BLE001
            db.rollback()
        send_telegram_ops_notification(db, title="Training failed", detail=f"run_id={run_id} detail={exc}")
        return {"status": "failed", "run_id": run_id, "detail": str(exc)}
    finally:
        db.close()

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
REPORT_ROOT = REPO_ROOT / "storage" / "reports"

os.environ.setdefault("DATABASE_URL", "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent")
os.environ.setdefault("STORAGE_ROOT", str(REPO_ROOT / "storage"))
sys.path.insert(0, str(API_ROOT))

from sqlalchemy.orm import joinedload  # noqa: E402

import app.services.planner_service as planner_service  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import ContentPlanDay, ContentPlanSlot, Job, JobStatus, PublishMode  # noqa: E402
from app.services.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.tasks.pipeline import PIPELINE_CONTROL_KEY, run_job  # noqa: E402


READY_BRIEF_FIELDS = ("brief_topic", "brief_audience")


@dataclass(slots=True)
class SlotOutcome:
    provider: str
    channel_id: str
    slot_id: int
    slot_order: int
    status: str
    reason: str | None = None
    article_id: int | None = None
    job_id: int | None = None
    public_url: str | None = None
    title: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run target-day Blogger/Cloudflare publishing batch.")
    parser.add_argument("--target-date", default="2026-04-10")
    parser.add_argument("--skip-blogger", action="store_true")
    parser.add_argument("--skip-cloudflare-generate", action="store_true")
    parser.add_argument("--skip-cloudflare-rewrite", action="store_true")
    parser.add_argument("--rewrite-limit", type=int, default=0)
    return parser.parse_args()


def _slot_needs_brief(slot: ContentPlanSlot) -> bool:
    return any(not str(getattr(slot, field) or "").strip() for field in READY_BRIEF_FIELDS)


def _load_target_days(db, target: date) -> list[ContentPlanDay]:
    return (
        db.query(ContentPlanDay)
        .options(joinedload(ContentPlanDay.slots), joinedload(ContentPlanDay.blog))
        .filter(ContentPlanDay.plan_date == target)
        .order_by(ContentPlanDay.channel_id.asc(), ContentPlanDay.id.asc())
        .all()
    )


def _ensure_day_briefs(db, day: ContentPlanDay) -> dict[str, Any]:
    ordered_slots = sorted(day.slots, key=lambda item: (item.slot_order, item.id))
    if not any(_slot_needs_brief(slot) for slot in ordered_slots):
        return {"status": "skipped", "reason": "already_ready", "plan_day_id": day.id, "channel_id": day.channel_id}

    analysis = planner_service.analyze_day_briefs(db, plan_day_id=day.id)
    applied = planner_service.apply_day_briefs(db, plan_day_id=day.id, run_id=analysis.run.id)
    return {
        "status": "applied",
        "plan_day_id": day.id,
        "channel_id": day.channel_id,
        "run_id": analysis.run.id,
        "applied_slot_ids": list(applied.applied_slot_ids),
        "skipped_slot_ids": list(applied.skipped_slot_ids),
    }


def _mark_blogger_slot_generated(db, slot: ContentPlanSlot, *, reason: str) -> SlotOutcome:
    slot.status = "generated"
    slot.error_message = None
    payload = dict(slot.result_payload or {})
    payload.update(
        {
            "provider": "blogger",
            "status": "html_ready",
            "job_id": slot.job_id,
            "article_id": slot.article_id,
            "reason": reason,
        }
    )
    slot.result_payload = payload
    db.add(slot)
    db.commit()
    db.refresh(slot)
    article = slot.article
    return SlotOutcome(
        provider="blogger",
        channel_id=slot.plan_day.channel_id,
        slot_id=slot.id,
        slot_order=slot.slot_order,
        status="generated",
        reason=reason,
        article_id=slot.article_id,
        job_id=slot.job_id,
        public_url=(article.blogger_post.published_url if article and article.blogger_post else None),
        title=(article.title if article else slot.brief_topic),
    )


def _run_blogger_slot_to_html(db, slot: ContentPlanSlot) -> SlotOutcome:
    db.refresh(slot)
    if slot.article_id and slot.article and str(slot.article.assembled_html or "").strip():
        return _mark_blogger_slot_generated(db, slot, reason="already_html_ready")

    planner_service.run_job.delay = lambda job_id: None
    planner_service.run_slot_generation(db, slot.id, publish_mode_override=PublishMode.PUBLISH)

    db.expire_all()
    slot = (
        db.query(ContentPlanSlot)
        .options(
            joinedload(ContentPlanSlot.plan_day),
            joinedload(ContentPlanSlot.article),
        )
        .filter(ContentPlanSlot.id == slot.id)
        .one()
    )
    if not slot.job_id:
        slot.status = "failed"
        slot.error_message = "planner_job_missing"
        db.add(slot)
        db.commit()
        return SlotOutcome(
            provider="blogger",
            channel_id=slot.plan_day.channel_id,
            slot_id=slot.id,
            slot_order=slot.slot_order,
            status="failed",
            reason="planner_job_missing",
        )

    job = db.query(Job).filter(Job.id == slot.job_id).one()
    prompts = dict(job.raw_prompts or {})
    prompts[PIPELINE_CONTROL_KEY] = {"stop_after": JobStatus.ASSEMBLING_HTML.value}
    job.raw_prompts = prompts
    db.add(job)
    db.commit()

    result = run_job.apply(args=(job.id, False)).get()
    db.expire_all()
    slot = (
        db.query(ContentPlanSlot)
        .options(joinedload(ContentPlanSlot.plan_day), joinedload(ContentPlanSlot.article))
        .filter(ContentPlanSlot.id == slot.id)
        .one()
    )
    job = db.query(Job).filter(Job.id == slot.job_id).one()
    if slot.article_id and slot.article and str(slot.article.assembled_html or "").strip():
        reason = "html_ready" if result.get("status") in {"completed", "stopped"} else f"html_ready_with_{result.get('status')}"
        return _mark_blogger_slot_generated(db, slot, reason=reason)

    slot.status = "failed"
    error_logs = list(job.error_logs or [])
    slot.error_message = str(error_logs[-1].get("message") if error_logs else result.get("error") or "unknown_error")
    db.add(slot)
    db.commit()
    return SlotOutcome(
        provider="blogger",
        channel_id=slot.plan_day.channel_id,
        slot_id=slot.id,
        slot_order=slot.slot_order,
        status="failed",
        reason=slot.error_message,
        article_id=slot.article_id,
        job_id=slot.job_id,
        title=(slot.article.title if slot.article else slot.brief_topic),
    )


def _run_cloudflare_slot_publish(db, slot: ContentPlanSlot) -> SlotOutcome:
    planner_service.run_slot_generation(db, slot.id, publish_mode_override=PublishMode.PUBLISH)
    db.expire_all()
    slot = (
        db.query(ContentPlanSlot)
        .options(joinedload(ContentPlanSlot.plan_day))
        .filter(ContentPlanSlot.id == slot.id)
        .one()
    )
    payload = dict(slot.result_payload or {})
    return SlotOutcome(
        provider="cloudflare",
        channel_id=slot.plan_day.channel_id,
        slot_id=slot.id,
        slot_order=slot.slot_order,
        status=slot.status,
        reason=str(payload.get("error") or "") or None,
        job_id=slot.job_id,
        public_url=str(payload.get("public_url") or "") or None,
        title=str(payload.get("title") or slot.brief_topic or "") or None,
    )


def _run_cloudflare_rewrite(rewrite_limit: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(API_ROOT / "scripts" / "rewrite_cloudflare_low_score_posts.py"),
        "--apply",
        "--score-threshold",
        "80",
        "--min-body-chars",
        "3500",
        "--max-body-chars",
        "4000",
        "--require-threshold-pass",
    ]
    if rewrite_limit > 0:
        command.extend(["--limit", str(rewrite_limit)])
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=os.environ.copy(),
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "command": command,
    }


def main() -> int:
    args = _parse_args()
    target = date.fromisoformat(args.target_date)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "generated_at": _utc_now(),
        "target_date": target.isoformat(),
        "brief_runs": [],
        "blogger": {"status": "skipped" if args.skip_blogger else "pending", "items": []},
        "cloudflare_generation": {"status": "skipped" if args.skip_cloudflare_generate else "pending", "items": []},
        "cloudflare_rewrite": {"status": "skipped" if args.skip_cloudflare_rewrite else "pending"},
    }

    with SessionLocal() as db:
        days = _load_target_days(db, target)
        for day in days:
            report["brief_runs"].append(_ensure_day_briefs(db, day))

        refreshed_days = _load_target_days(db, target)

        if not args.skip_blogger:
            blogger_items: list[SlotOutcome] = []
            for day in [item for item in refreshed_days if item.channel_id.startswith("blogger:")]:
                ordered_slots = sorted(day.slots, key=lambda item: (item.slot_order, item.id))
                for slot in ordered_slots:
                    slot = (
                        db.query(ContentPlanSlot)
                        .options(joinedload(ContentPlanSlot.plan_day), joinedload(ContentPlanSlot.article))
                        .filter(ContentPlanSlot.id == slot.id)
                        .one()
                    )
                    blogger_items.append(_run_blogger_slot_to_html(db, slot))
            report["blogger"]["status"] = "completed"
            report["blogger"]["items"] = [asdict(item) for item in blogger_items]

        if not args.skip_cloudflare_generate:
            cloudflare_items: list[SlotOutcome] = []
            for day in [item for item in refreshed_days if item.channel_id.startswith("cloudflare:")]:
                ordered_slots = sorted(day.slots, key=lambda item: (item.slot_order, item.id))
                for slot in ordered_slots:
                    slot = (
                        db.query(ContentPlanSlot)
                        .options(joinedload(ContentPlanSlot.plan_day))
                        .filter(ContentPlanSlot.id == slot.id)
                        .one()
                    )
                    cloudflare_items.append(_run_cloudflare_slot_publish(db, slot))
            sync_result = sync_cloudflare_posts(db)
            report["cloudflare_generation"]["status"] = "completed"
            report["cloudflare_generation"]["sync_result"] = sync_result
            report["cloudflare_generation"]["items"] = [asdict(item) for item in cloudflare_items]

    if not args.skip_cloudflare_rewrite:
        rewrite_result = _run_cloudflare_rewrite(args.rewrite_limit)
        rewrite_result["status"] = "completed" if rewrite_result["returncode"] == 0 else "failed"
        report["cloudflare_rewrite"] = rewrite_result

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = REPORT_ROOT / f"target-day-publish-batch-{timestamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "target_date": target.isoformat()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.services import cloudflare_channel_service as cloudflare_service
from app.services.integrations.settings_service import get_settings_map, upsert_settings


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    session = SessionLocal()
    get_settings_map(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_schedule_settings(
    db: Session,
    *,
    last_run_slot: str,
    last_attempted_slot: str,
    counts: dict[str, int],
) -> None:
    upsert_settings(
        db,
        {
            "cloudflare_daily_publish_enabled": "true",
            "cloudflare_daily_publish_time": "00:00",
            "cloudflare_daily_publish_interval_hours": "2",
            "cloudflare_daily_publish_weekday_quota": "9",
            "cloudflare_daily_publish_sunday_quota": "7",
            "cloudflare_daily_last_run_slot": last_run_slot,
            "cloudflare_daily_last_attempted_slot": last_attempted_slot,
            "cloudflare_daily_last_run_on": "2026-03-29",
            "cloudflare_daily_category_counts": json.dumps({"date": "2026-03-29", "counts": counts}, ensure_ascii=False),
        },
    )


def _leaf_categories() -> list[dict]:
    return [
        {"id": "cat-alpha", "slug": "alpha", "name": "Alpha", "isLeaf": True},
        {"id": "cat-beta", "slug": "beta", "name": "Beta", "isLeaf": True},
    ]


def test_cloudflare_daily_schedule_marks_failed_slot_as_attempted(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_schedule_settings(
        db,
        last_run_slot="2026-03-29T10:00+09:00",
        last_attempted_slot="2026-03-29T10:00+09:00",
        counts={"alpha": 1, "beta": 0},
    )
    monkeypatch.setattr(cloudflare_service, "sync_cloudflare_prompts_from_files", lambda _db, execute=True: {"status": "ok"})
    monkeypatch.setattr(cloudflare_service, "list_cloudflare_categories", lambda _db: _leaf_categories())
    monkeypatch.setattr(
        cloudflare_service,
        "generate_cloudflare_posts",
        lambda _db, per_category, category_plan, status: {
            "status": "failed",
            "reason": "quality_gate_failed",
            "created_count": 0,
            "failed_count": 1,
            "categories": [],
        },
    )

    result = cloudflare_service.run_cloudflare_daily_schedule(
        db,
        now=datetime(2026, 3, 29, 12, 1, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    values = get_settings_map(db)
    counts = json.loads(values["cloudflare_daily_category_counts"])["counts"]

    assert result["status"] == "failed"
    assert result["reason"] == "generation_created_zero"
    assert result["processed_slots"] == []
    assert values["cloudflare_daily_last_run_slot"] == "2026-03-29T10:00+09:00"
    assert values["cloudflare_daily_last_attempted_slot"] == "2026-03-29T12:00+09:00"
    assert counts["alpha"] == 1


def test_cloudflare_daily_schedule_rotates_category_and_recovers_slot(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_schedule_settings(
        db,
        last_run_slot="2026-03-29T10:00+09:00",
        last_attempted_slot="2026-03-29T10:00+09:00",
        counts={"alpha": 0, "beta": 0},
    )
    monkeypatch.setattr(cloudflare_service, "sync_cloudflare_prompts_from_files", lambda _db, execute=True: {"status": "ok"})
    monkeypatch.setattr(cloudflare_service, "list_cloudflare_categories", lambda _db: _leaf_categories())
    attempted_plans: list[dict[str, int]] = []

    def _fake_generate(_db, per_category, category_plan, status):
        attempted_plans.append(dict(category_plan))
        if len(attempted_plans) == 1:
            return {
                "status": "failed",
                "reason": "quality_gate_failed",
                "created_count": 0,
                "failed_count": 1,
                "categories": [{"category_slug": "alpha", "created": 0}],
            }
        return {
            "status": "ok",
            "created_count": 1,
            "failed_count": 0,
            "categories": [{"category_slug": "beta", "created": 1}],
        }

    monkeypatch.setattr(cloudflare_service, "generate_cloudflare_posts", _fake_generate)

    result = cloudflare_service.run_cloudflare_daily_schedule(
        db,
        now=datetime(2026, 3, 29, 12, 1, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    values = get_settings_map(db)
    counts = json.loads(values["cloudflare_daily_category_counts"])["counts"]

    assert result["status"] == "ok"
    assert result["processed_slots"] == ["2026-03-29T12:00+09:00"]
    assert values["cloudflare_daily_last_run_slot"] == "2026-03-29T12:00+09:00"
    assert values["cloudflare_daily_last_attempted_slot"] == "2026-03-29T12:00+09:00"
    assert counts["beta"] == 1
    assert len(attempted_plans) == 2
    assert set(attempted_plans[0].keys()) == {"alpha"}
    assert set(attempted_plans[1].keys()) == {"beta"}


def test_cloudflare_daily_schedule_skips_already_attempted_failed_slot(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_schedule_settings(
        db,
        last_run_slot="2026-03-29T10:00+09:00",
        last_attempted_slot="2026-03-29T12:00+09:00",
        counts={"alpha": 0, "beta": 0},
    )
    monkeypatch.setattr(cloudflare_service, "sync_cloudflare_prompts_from_files", lambda _db, execute=True: {"status": "ok"})
    monkeypatch.setattr(cloudflare_service, "list_cloudflare_categories", lambda _db: _leaf_categories())
    call_counter = {"count": 0}

    def _fake_generate(_db, per_category, category_plan, status):
        call_counter["count"] += 1
        return {"status": "failed", "created_count": 0, "failed_count": 1, "categories": []}

    monkeypatch.setattr(cloudflare_service, "generate_cloudflare_posts", _fake_generate)

    result = cloudflare_service.run_cloudflare_daily_schedule(
        db,
        now=datetime(2026, 3, 29, 12, 30, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert result["status"] == "idle"
    assert result["reason"] == "no_due_slots"
    assert call_counter["count"] == 0


def test_cloudflare_daily_schedule_uses_latest_due_slot_only_for_backlog(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_schedule_settings(
        db,
        last_run_slot="2026-03-28T22:00+09:00",
        last_attempted_slot="2026-03-28T22:00+09:00",
        counts={"alpha": 0, "beta": 0},
    )
    monkeypatch.setattr(cloudflare_service, "sync_cloudflare_prompts_from_files", lambda _db, execute=True: {"status": "ok"})
    monkeypatch.setattr(cloudflare_service, "list_cloudflare_categories", lambda _db: _leaf_categories())

    attempted_plans: list[dict[str, int]] = []

    def _fake_generate(_db, per_category, category_plan, status):
        attempted_plans.append(dict(category_plan))
        return {
            "status": "failed",
            "reason": "quality_gate_failed",
            "created_count": 0,
            "failed_count": 1,
            "categories": [{"category_slug": next(iter(category_plan.keys())), "created": 0}],
        }

    monkeypatch.setattr(cloudflare_service, "generate_cloudflare_posts", _fake_generate)

    result = cloudflare_service.run_cloudflare_daily_schedule(
        db,
        now=datetime(2026, 3, 29, 12, 30, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    values = get_settings_map(db)

    assert result["status"] == "failed"
    assert result["slot_marker"] == "2026-03-29T12:00+09:00"
    assert values["cloudflare_daily_last_attempted_slot"] == "2026-03-29T12:00+09:00"
    assert len(attempted_plans) >= 1

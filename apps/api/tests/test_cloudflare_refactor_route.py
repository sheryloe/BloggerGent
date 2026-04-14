import pytest

from app.api.routes import cloudflare as cloudflare_route
from app.schemas.api import CloudflareRefactorRequest


def test_refactor_cloudflare_low_score_route_forwards_current_fields(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _capture(db, **kwargs):
        captured["db"] = db
        captured["kwargs"] = kwargs
        return {"status": "ok", "captured": kwargs}

    monkeypatch.setattr(cloudflare_route, "refactor_cloudflare_low_score_posts", _capture)

    payload = CloudflareRefactorRequest(
        execute=True,
        threshold=77.0,
        month="2026-04",
        category_slugs=["travel", "dev"],
        limit=12,
        sync_before=False,
    )

    result = cloudflare_route.refactor_cloudflare_low_score_route(payload, object())

    assert result["status"] == "ok"
    assert captured["kwargs"] == {
        "execute": True,
        "threshold": 77.0,
        "month": "2026-04",
        "category_slugs": ["travel", "dev"],
        "limit": 12,
        "sync_before": False,
        "parallel_workers": 1,
    }


def test_refactor_cloudflare_low_score_route_forwards_queue_parallel_when_supported(monkeypatch) -> None:
    request_fields = getattr(CloudflareRefactorRequest, "model_fields", {})
    if "queue" not in request_fields or "parallel_workers" not in request_fields:
        pytest.skip("Cloudflare refactor queue/parallel fields are not implemented yet.")

    captured: dict[str, object] = {}

    class _Task:
        id = "task-123"

    def _apply_async(*, kwargs, queue):
        captured["kwargs"] = kwargs
        captured["queue"] = queue
        return _Task()

    monkeypatch.setattr(cloudflare_route.run_cloudflare_low_score_refactor, "apply_async", _apply_async)

    payload = CloudflareRefactorRequest(
        execute=True,
        threshold=80.0,
        month="2026-04",
        category_slugs=[],
        limit=10,
        sync_before=True,
        queue=True,
        parallel_workers=4,
    )

    result = cloudflare_route.refactor_cloudflare_low_score_route(payload, object())

    assert result["status"] == "queued"
    assert captured["queue"] == "default"
    assert captured["kwargs"]["parallel_workers"] == 4

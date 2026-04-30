from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.config import settings
from app.services.ops.lighthouse_service import (
    LIGHTHOUSE_10_PERFORMANCE_METRIC_WEIGHTS,
    LIGHTHOUSE_SCORING_METHOD,
    apply_lighthouse_audit_to_article,
    apply_lighthouse_audit_to_cloudflare_post,
    parse_lighthouse_report,
    resolve_lighthouse_report_root,
    run_lighthouse_audit,
    run_required_article_lighthouse_audit,
)


def test_parse_lighthouse_report_uses_official_performance_score_as_primary_score():
    report = {
        "categories": {
            "performance": {"score": 0.83},
            "accessibility": {"score": 0.91},
            "best-practices": {"score": 0.74},
            "seo": {"score": 0.96},
        },
        "audits": {
            "first-contentful-paint": {"numericValue": 1210.4},
            "speed-index": {"numericValue": 2199.2},
            "largest-contentful-paint": {"numericValue": 2488.8},
            "total-blocking-time": {"numericValue": 135.0},
            "cumulative-layout-shift": {"numericValue": 0.04},
        },
        "configSettings": {"formFactor": "mobile"},
        "fetchTime": "2026-04-11T00:00:00.000Z",
        "lighthouseVersion": "12.6.0",
        "finalUrl": "https://example.com/post",
    }

    parsed = parse_lighthouse_report(report)

    assert parsed["lighthouse_score"] == 83.0
    assert parsed["performance_score"] == 83.0
    assert parsed["accessibility_score"] == 91.0
    assert parsed["best_practices_score"] == 74.0
    assert parsed["seo_score"] == 96.0
    assert parsed["scoring_method"] == LIGHTHOUSE_SCORING_METHOD
    assert parsed["performance_metric_weights"] == LIGHTHOUSE_10_PERFORMANCE_METRIC_WEIGHTS
    assert parsed["performance_metrics"] == {
        "first_contentful_paint_ms": 1210.4,
        "speed_index_ms": 2199.2,
        "largest_contentful_paint_ms": 2488.8,
        "total_blocking_time_ms": 135.0,
        "cumulative_layout_shift": 0.04,
    }


def test_parse_lighthouse_report_handles_missing_audits_without_crashing():
    report = {
        "categories": {
            "performance": {"score": 0.7},
            "accessibility": {"score": 0.8},
            "best-practices": {"score": 0.9},
            "seo": {"score": 1.0},
        },
        "audits": {},
    }

    parsed = parse_lighthouse_report(report)

    assert parsed["lighthouse_score"] == 70.0
    assert parsed["performance_metrics"] == {
        "first_contentful_paint_ms": None,
        "speed_index_ms": None,
        "largest_contentful_paint_ms": None,
        "total_blocking_time_ms": None,
        "cumulative_layout_shift": None,
    }


def test_apply_lighthouse_audit_to_article_persists_required_scores():
    article = SimpleNamespace()
    audited_at = datetime(2026, 4, 19, tzinfo=timezone.utc)
    audit = {
        "scores": {
            "lighthouse_score": 88,
            "accessibility_score": 91,
            "best_practices_score": 93,
            "seo_score": 97,
        },
        "weights": {"largest-contentful-paint": 0.25},
    }

    payload = apply_lighthouse_audit_to_article(
        article,
        audit,
        url="https://example.com/post",
        report_path=Path(r"D:\Donggri_Runtime\BloggerGent\storage\_common\analysis\lighthouse\manual.json"),
        audited_at=audited_at,
    )

    assert article.quality_lighthouse_score == 88
    assert article.quality_lighthouse_accessibility_score == 91
    assert article.quality_lighthouse_best_practices_score == 93
    assert article.quality_lighthouse_seo_score == 97
    assert article.quality_lighthouse_last_audited_at == audited_at
    assert payload["status"] == "ok"
    assert payload["form_factor"] == "mobile"


def test_apply_lighthouse_audit_to_cloudflare_post_persists_required_scores():
    post = SimpleNamespace()
    audit = {
        "scores": {
            "lighthouse_score": 76,
            "accessibility_score": 84,
            "best_practices_score": 89,
            "seo_score": 92,
        },
        "weights": {},
    }

    payload = apply_lighthouse_audit_to_cloudflare_post(
        post,
        audit,
        url="https://dongriarchive.com/article",
        report_path=Path(r"D:\Donggri_Runtime\BloggerGent\storage\_common\analysis\lighthouse\cloudflare.json"),
    )

    assert post.lighthouse_score == 76
    assert post.lighthouse_accessibility_score == 84
    assert post.lighthouse_best_practices_score == 89
    assert post.lighthouse_seo_score == 92
    assert post.lighthouse_payload["status"] == "ok"
    assert payload["url"] == "https://dongriarchive.com/article"


def test_resolve_lighthouse_report_root_uses_runtime_storage(monkeypatch):
    monkeypatch.delenv("LIGHTHOUSE_REPORT_ROOT", raising=False)
    monkeypatch.setattr(settings, "storage_root", r"D:\Donggri_Runtime\BloggerGent\storage", raising=False)

    root = resolve_lighthouse_report_root(provider="manual")

    assert str(root).endswith(r"storage\_common\analysis\lighthouse\manual")


def test_run_lighthouse_audit_uses_google_pagespeed_not_local_cli(monkeypatch):
    calls = []

    def fake_pagespeed(url: str, *, strategy: str = "mobile", **kwargs):
        calls.append({"url": url, "strategy": strategy, **kwargs})
        return {
            "url": url,
            "form_factor": strategy,
            "measurement_source": "google_pagespeed_insights_lighthouse",
            "scores": {"lighthouse_score": 91.0},
            "raw_report": {},
        }

    monkeypatch.setattr(
        "app.services.ops.lighthouse_service.run_pagespeed_insights_audit",
        fake_pagespeed,
    )

    result = run_lighthouse_audit("https://example.com/post", form_factor="desktop")

    assert calls == [{"url": "https://example.com/post", "strategy": "desktop"}]
    assert result["measurement_source"] == "google_pagespeed_insights_lighthouse"
    assert result["scores"]["lighthouse_score"] == 91.0


def test_optional_article_lighthouse_measurement_does_not_block(monkeypatch):
    class DummyDb:
        def __init__(self):
            self.added = []
            self.flushed = False

        def add(self, value):
            self.added.append(value)

        def flush(self):
            self.flushed = True

    def fail_pagespeed(*args, **kwargs):
        from app.services.ops.lighthouse_service import LighthouseAuditError

        raise LighthouseAuditError("PageSpeed unavailable")

    monkeypatch.setattr(
        "app.services.ops.lighthouse_service.run_pagespeed_insights_audit",
        fail_pagespeed,
    )
    article = SimpleNamespace()
    db = DummyDb()

    payload = run_required_article_lighthouse_audit(
        db,
        article,
        url="https://example.com/post",
        commit=False,
        required=False,
    )

    assert payload["status"] == "unmeasured"
    assert payload["measurement_source"] == "google_pagespeed_insights_lighthouse"
    assert article.quality_lighthouse_payload == payload
    assert db.added == [article]
    assert db.flushed is True

from app.services.ops.lighthouse_service import (
    LIGHTHOUSE_10_PERFORMANCE_METRIC_WEIGHTS,
    LIGHTHOUSE_SCORING_METHOD,
    parse_lighthouse_report,
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

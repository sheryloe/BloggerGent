from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.content.travel_blog_policy import TRAVEL_PATTERN_VERSION, travel_pattern_missing_requirements


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script_module(module_name: str, relative_path: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed_to_load_module:{module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


travel_audit = _load_script_module("travel_audit_full_content_test_module", "scripts/travel/audit_travel_full_content.py")
travel_sync = _load_script_module("travel_start_today_sync_test_module", "scripts/travel/start_travel_today_sync.py")


def test_travel_pattern_requirements_accept_known_pattern() -> None:
    assert travel_pattern_missing_requirements("travel-01-hidden-path-route", TRAVEL_PATTERN_VERSION) == []


def test_travel_pattern_requirements_reject_unknown_pattern() -> None:
    missing = travel_pattern_missing_requirements("travel-99-unknown-pattern", TRAVEL_PATTERN_VERSION)
    assert "invalid_article_pattern_id" in missing


def test_travel_audit_flags_missing_quality_status_as_secondary_issue() -> None:
    article = SimpleNamespace(
        id=1,
        blog_id=36,
        title="Practical Seoul Forest Spring Route",
        slug="practical-seoul-forest-spring-route",
        assembled_html=f"<article><p>{'a' * 3600}</p></article>",
        html_article="",
        article_pattern_id="travel-01-hidden-path-route",
        article_pattern_version=TRAVEL_PATTERN_VERSION,
        editorial_category_key="travel",
        quality_status=None,
        meta_description="Practical Seoul Forest Spring Route meta description.",
        blog=SimpleNamespace(primary_language="es"),
        blogger_post=SimpleNamespace(published_url="https://example.com/post"),
        image=SimpleNamespace(public_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample.webp"),
    )

    row = travel_audit._row_issue_payload(
        article,
        live_validation={
            "status": "ok",
            "article_title_present": True,
            "article_hero_present": True,
            "article_body_present": True,
            "body_snippet_present": True,
            "article_h1_count": 1,
            "article_hero_occurrence_count": 1,
        },
    )

    assert "missing_quality_status" in row["secondary_issues"]


def test_travel_sync_cli_blocks_scheduled_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        travel_sync,
        "parse_args",
        lambda: argparse.Namespace(publish_mode="scheduled"),
    )

    with pytest.raises(SystemExit) as exc_info:
        travel_sync.main()

    assert "live-validated publish" in str(exc_info.value)


def test_travel_audit_flags_structural_live_issues_from_article_scope() -> None:
    article = SimpleNamespace(
        id=2,
        blog_id=34,
        title="Bucheon Wonmisan Azalea Festival 2026",
        slug="bucheon-wonmisan-azalea-festival-2026",
        assembled_html=f"<article><p>{'a' * 3600}</p></article>",
        html_article="",
        article_pattern_id="travel-01-hidden-path-route",
        article_pattern_version=TRAVEL_PATTERN_VERSION,
        editorial_category_key="travel",
        quality_status="reviewed",
        meta_description="meta",
        blog=SimpleNamespace(primary_language="en"),
        blogger_post=SimpleNamespace(published_url="https://example.com/post"),
        image=SimpleNamespace(public_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample.webp"),
    )

    row = travel_audit._row_issue_payload(
        article,
        live_validation={
            "status": "failed",
            "article_title_present": False,
            "article_hero_present": False,
            "article_body_present": False,
            "article_h1_count": 0,
            "article_hero_occurrence_count": 0,
            "diagnostic_warnings": ["article_body_snippet_mismatch"],
        },
    )

    assert "missing_live_title" in row["issues"]
    assert "missing_live_hero" in row["issues"]
    assert "missing_live_body" in row["issues"]
    assert "article_h1_missing" in row["issues"]
    assert "article_hero_missing" in row["issues"]
    assert "article_body_snippet_mismatch" in row["issues"]

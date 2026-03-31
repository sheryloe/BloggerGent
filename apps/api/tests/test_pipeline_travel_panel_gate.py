from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.tasks.pipeline import (
    _build_travel_topic_discovery_override_prompt,
    _travel_3x3_prompt_missing_requirements,
    _travel_3x3_size_missing_requirements,
)


def test_travel_prompt_requirements_pass_when_all_keywords_present() -> None:
    prompt = (
        "Create a 3x3 9-panel travel collage grid with visible white gutters. "
        "The center panel is dominant and larger than surrounding panels."
    )
    assert _travel_3x3_prompt_missing_requirements(prompt) == []


def test_travel_prompt_requirements_fail_on_missing_center_emphasis() -> None:
    prompt = "Create a 3x3 9-panel travel collage grid with visible white gutters."
    missing = _travel_3x3_prompt_missing_requirements(prompt)
    assert "missing_center_panel_emphasis" in missing


def test_travel_size_requirements_fail_for_landscape_image() -> None:
    missing = _travel_3x3_size_missing_requirements(1792, 1024)
    assert "not_portrait_ratio" in missing


def test_travel_size_requirements_pass_for_portrait_image() -> None:
    assert _travel_3x3_size_missing_requirements(1024, 1536) == []


def test_travel_topic_override_forces_blossom_on_2026_03_28() -> None:
    blog = SimpleNamespace(profile_key="korea_travel")
    now_local = datetime(2026, 3, 28, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    prompt = _build_travel_topic_discovery_override_prompt(blog=blog, now_local=now_local)
    assert "MUST be cherry blossom themed" in prompt
    assert "2026-03-28" in prompt


def test_travel_topic_override_switches_to_autonomous_from_2026_03_29() -> None:
    blog = SimpleNamespace(profile_key="korea_travel")
    now_local = datetime(2026, 3, 29, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    prompt = _build_travel_topic_discovery_override_prompt(blog=blog, now_local=now_local)
    assert "autonomous topic discovery" in prompt
    assert "not a forced lock" in prompt


def test_travel_topic_override_skips_non_travel_profile() -> None:
    blog = SimpleNamespace(profile_key="world_mystery")
    now_local = datetime(2026, 3, 28, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    prompt = _build_travel_topic_discovery_override_prompt(blog=blog, now_local=now_local)
    assert prompt == ""

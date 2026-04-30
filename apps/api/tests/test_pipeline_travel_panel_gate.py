from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.tasks.pipeline import (
    _build_travel_topic_discovery_override_prompt,
)
from app.services.content.travel_blog_policy import (
    travel_panel_prompt_missing_requirements,
    travel_panel_size_missing_requirements,
)


def test_travel_prompt_requirements_pass_when_all_keywords_present() -> None:
    prompt = (
        "Create one single flattened final image with a 4 columns x 3 rows travel collage and exactly 12 visible panels. "
        "Use thin visible white gutters and one dominant anchor panel. "
        "Use varied camera distances with a wide establishing route scene, medium street scene, and close-up local detail. "
        "Avoid generic stock-photo tourism. "
        "Do not generate 12 separate images, do not generate one single hero shot without panel structure, no text, and no logo."
    )
    assert travel_panel_prompt_missing_requirements(prompt) == []


def test_travel_prompt_requirements_fail_on_missing_gutters() -> None:
    prompt = (
        "Create one single flattened final image with a 4 columns x 3 rows travel collage and exactly 12 visible panels, "
        "do not generate 12 separate images, do not generate one single hero shot without panel structure, no text, no logo."
    )
    missing = travel_panel_prompt_missing_requirements(prompt)
    assert "missing_visible_gutters" in missing


def test_travel_size_requirements_fail_for_non_square_image() -> None:
    missing = travel_panel_size_missing_requirements(1792, 1024)
    assert "not_1024_square" in missing


def test_travel_size_requirements_pass_for_square_image() -> None:
    assert travel_panel_size_missing_requirements(1024, 1024) == []


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

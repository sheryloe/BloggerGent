from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_ROOT = REPO_ROOT / "prompts" / "channels" / "cloudflare" / "dongri-archive"

COMMON_SECTIONS = [
    "[Input]",
    "[Mission]",
    "[Category Fit]",
    "[Blog Style]",
    "[Body Rules]",
    "[Content Requirements]",
    "[Output Contract]",
    "[Output Rules]",
    "[Image Prompt Rules]",
]

DISCOVERY_SECTIONS = [
    "[Mission]",
    "[Category Fit]",
    "[Topic Rules]",
    "[Quality Rules]",
    "[Output Rules]",
]

IMAGE_SECTIONS = [
    "[Input]",
    "[Persona Direction for Image (`en`)]",
    "[Output Rules]",
    "[Content Rules]",
]

ACTIVE_CATEGORY_PATHS = {
    "yeohaenggwa-girog": Path("동그리의 기록") / "yeohaenggwa-girog",
    "gaebalgwa-peurogeuraeming": Path("동그리의 기록") / "gaebalgwa-peurogeuraeming",
    "ilsanggwa-memo": Path("동그리의 기록") / "ilsanggwa-memo",
    "salmeul-yuyonghage": Path("생활의 기록") / "salmeul-yuyonghage",
    "salmyi-gireumcil": Path("생활의 기록") / "salmyi-gireumcil",
    "donggeuriyi-saenggag": Path("세상의 기록") / "donggeuriyi-saenggag",
    "miseuteria-seutori": Path("세상의 기록") / "miseuteria-seutori",
    "jusigyi-heureum": Path("시장의 기록") / "jusigyi-heureum",
    "naseudagyi-heureum": Path("시장의 기록") / "naseudagyi-heureum",
    "keuribtoyi-heureum": Path("시장의 기록") / "keuribtoyi-heureum",
    "cugjewa-hyeonjang": Path("정보의 기록") / "cugjewa-hyeonjang",
    "munhwawa-gonggan": Path("정보의 기록") / "munhwawa-gonggan",
}

ARTICLE_EXPECTATIONS: dict[str, list[str]] = {
    "yeohaenggwa-girog": ["Route-first place story", "Naver Maps", "Google Maps"],
    "gaebalgwa-peurogeuraeming": ["Claude", "Codex", "Gemini", "information-provider roles"],
    "ilsanggwa-memo": ["daily-observation frame", "literary observation", "observed tension"],
    "miseuteria-seutori": ["case", "record", "clue", "interpretation", "current tracking"],
    "naseudagyi-heureum": ["Donggri", "언니", "TradingView"],
}

DISCOVERY_EXPECTATIONS: dict[str, list[str]] = {
    "yeohaenggwa-girog": ["동선 실전형 + 장소 감성형", "movement order", "real place"],
    "gaebalgwa-peurogeuraeming": ["Claude", "Codex", "Gemini", "실무 판단 포인트"],
    "ilsanggwa-memo": ["짧은 관찰형", "문학적 관찰감", "scene"],
    "miseuteria-seutori": ["사건", "기록", "단서", "해석", "현재 추적"],
    "naseudagyi-heureum": ["Nasdaq", "동그리", "햄니"],
}

IMAGE_EXPECTATIONS: dict[str, list[str]] = {
    "yeohaenggwa-girog": ["Route-first", "walking the route in order", "hero cover image"],
    "gaebalgwa-peurogeuraeming": ["tool comparison context", "workflow handoff moments", "hero cover image"],
    "ilsanggwa-memo": ["subdued literary daily-scene mood", "quiet scene details", "hero cover image"],
    "miseuteria-seutori": ["Documentary mystery", "evidence-driven", "hero cover image"],
    "naseudagyi-heureum": ["Nasdaq", "single-company market narrative", "hero cover image"],
}


def _prompt_path(category_dir: str, file_name: str) -> Path:
    return PROMPT_ROOT / ACTIVE_CATEGORY_PATHS[category_dir] / file_name


@pytest.mark.parametrize("category_dir", sorted(ACTIVE_CATEGORY_PATHS))
def test_cloudflare_active_article_prompts_follow_blogger_structure(category_dir: str) -> None:
    path = _prompt_path(category_dir, "article_generation.md")
    assert path.exists(), f"missing prompt: {path}"

    text = path.read_text(encoding="utf-8")

    indexes = []
    for section in COMMON_SECTIONS:
        assert section in text, f"{path.name} missing section {section}"
        indexes.append(text.index(section))
    assert indexes == sorted(indexes), f"{path.name} sections are out of order"

    assert "The final body section title must be exactly <h2>마무리 기록</h2>." in text
    assert "Do not output visible meta_description or excerpt lines inside html_article." in text
    assert "Quick brief" in text
    assert "Core focus" in text
    assert "Key entities" in text
    assert "internal archive" in text
    assert "labels: 5 to 7 items" in text

    for needle in ARTICLE_EXPECTATIONS.get(category_dir, []):
        assert needle in text, f"{path.name} missing required phrase: {needle}"


def test_cloudflare_excluded_archive_categories_are_not_part_of_active_alignment() -> None:
    excluded = {
        "gisulyi-girog",
        "jeongboyi-girog",
        "sesangyi-girog",
        "donggeuriyi-girog",
        "sijangyi-girog",
    }
    assert excluded.isdisjoint(set(ACTIVE_CATEGORY_PATHS))


@pytest.mark.parametrize("category_dir", sorted(ACTIVE_CATEGORY_PATHS))
def test_cloudflare_active_topic_discovery_prompts_follow_blogger_structure(category_dir: str) -> None:
    path = _prompt_path(category_dir, "topic_discovery.md")
    assert path.exists(), f"missing prompt: {path}"

    text = path.read_text(encoding="utf-8")

    indexes = []
    for section in DISCOVERY_SECTIONS:
        assert section in text, f"{path.name} missing section {section}"
        indexes.append(text.index(section))
    assert indexes == sorted(indexes), f"{path.name} sections are out of order"

    assert "Current date: {current_date}" in text
    assert "Target audience: {target_audience}" in text
    assert "Blog focus: {content_brief}" in text
    assert "Editorial category guidance: {editorial_category_guidance}" in text
    assert '"topics": [' in text
    assert '"keyword": "string"' in text
    assert '"reason": "string"' in text
    assert '"trend_score": 0.0' in text
    assert "Quick brief" in text
    assert "Core focus" in text
    assert "Key entities" in text
    assert "internal archive" in text

    for needle in DISCOVERY_EXPECTATIONS.get(category_dir, []):
        assert needle in text, f"{path.name} missing required phrase: {needle}"


@pytest.mark.parametrize("category_dir", sorted(ACTIVE_CATEGORY_PATHS))
def test_cloudflare_active_image_prompt_generation_prompts_follow_blogger_structure(category_dir: str) -> None:
    path = _prompt_path(category_dir, "image_prompt_generation.md")
    assert path.exists(), f"missing prompt: {path}"

    text = path.read_text(encoding="utf-8")

    indexes = []
    for section in IMAGE_SECTIONS:
        assert section in text, f"{path.name} missing section {section}"
        indexes.append(text.index(section))
    assert indexes == sorted(indexes), f"{path.name} sections are out of order"

    assert "- Topic: {keyword}" in text
    assert "- Title: {article_title}" in text
    assert "- Excerpt: {article_excerpt}" in text
    assert "- Article context:" in text
    assert "Return plain text only." in text
    assert "3x3 hero collage" in text
    assert "9 distinct panels" in text
    assert "No text, no logos" in text
    assert "supporting inline collage is handled separately downstream" in text

    for needle in IMAGE_EXPECTATIONS.get(category_dir, []):
        assert needle in text, f"{path.name} missing required phrase: {needle}"

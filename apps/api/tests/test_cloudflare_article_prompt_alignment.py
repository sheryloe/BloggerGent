from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_ROOT = REPO_ROOT / "prompts" / "channels" / "cloudflare" / "dongri-archive"

PRN_CATEGORY_PATHS = {
    "yeohaenggwa-girog": Path("동그리의 기록") / "yeohaenggwa-girog",
    "gaebalgwa-peurogeuraeming": Path("동그리의 기록") / "gaebalgwa-peurogeuraeming",
    "ilsanggwa-memo": Path("동그리의 기록") / "ilsanggwa-memo",
    "salmeul-yuyonghage": Path("생활의 기록") / "salmeul-yuyonghage",
    "salmyi-gireumcil": Path("생활의 기록") / "salmyi-gireumcil",
    "donggeuriyi-saenggag": Path("세상의 기록") / "donggeuriyi-saenggag",
    "jusigyi-heureum": Path("시장의 기록") / "jusigyi-heureum",
    "naseudagyi-heureum": Path("시장의 기록") / "naseudagyi-heureum",
    "keuribtoyi-heureum": Path("시장의 기록") / "keuribtoyi-heureum",
    "cugjewa-hyeonjang": Path("정보의 기록") / "cugjewa-hyeonjang",
    "munhwawa-gonggan": Path("정보의 기록") / "munhwawa-gonggan",
}

ARTICLE_SECTIONS = [
    "[Input]",
    "[Mission]",
    "[minimum_korean_body_gate]",
    "[adsense_body_policy]",
    "[allowed_article_patterns]",
    "[pattern_selection_rule]",
    "[image_prompt_policy]",
    "[forbidden_outputs]",
    "[Output JSON]",
]

DISCOVERY_SECTIONS = [
    "[Category Scope]",
    "[Allowed Patterns]",
    "[Output]",
]

IMAGE_SECTIONS = [
    "[Input]",
    "[Category Image Policy]",
    "[Pattern Visual Directions]",
    "[Output]",
]


def _prompt_path(category_dir: str, file_name: str) -> Path:
    return PROMPT_ROOT / PRN_CATEGORY_PATHS[category_dir] / file_name


@pytest.mark.parametrize("category_dir", sorted(PRN_CATEGORY_PATHS))
def test_cloudflare_article_prompts_follow_prn_contract(category_dir: str) -> None:
    path = _prompt_path(category_dir, "article_generation.md")
    assert path.exists(), f"missing prompt: {path}"
    text = path.read_text(encoding="utf-8")

    indexes = []
    for section in ARTICLE_SECTIONS:
        assert section in text, f"{path.name} missing section {section}"
        indexes.append(text.index(section))
    assert indexes == sorted(indexes), f"{path.name} sections are out of order"

    assert "article_pattern_version = 4" in text
    assert "2000" in text
    assert "[가-힣]" in text or "[媛-??" in text
    assert "Do not output raw AdSense code inside `html_article`." in text
    assert "<script" in text
    assert "No body-level H1." in text
    assert "Do not insert `<img>`" in text


@pytest.mark.parametrize("category_dir", sorted(PRN_CATEGORY_PATHS))
def test_cloudflare_topic_discovery_prompts_keep_structured_output(category_dir: str) -> None:
    path = _prompt_path(category_dir, "topic_discovery.md")
    assert path.exists(), f"missing prompt: {path}"
    text = path.read_text(encoding="utf-8")

    indexes = []
    for section in DISCOVERY_SECTIONS:
        assert section in text, f"{path.name} missing section {section}"
        indexes.append(text.index(section))
    assert indexes == sorted(indexes), f"{path.name} sections are out of order"

    assert "recommended_pattern_id" in text
    assert "duplicate_risk" in text
    assert "image_cue" in text


@pytest.mark.parametrize("category_dir", sorted(PRN_CATEGORY_PATHS))
def test_cloudflare_image_prompt_generation_prompts_are_category_specific(category_dir: str) -> None:
    path = _prompt_path(category_dir, "image_prompt_generation.md")
    assert path.exists(), f"missing prompt: {path}"
    text = path.read_text(encoding="utf-8")

    indexes = []
    for section in IMAGE_SECTIONS:
        assert section in text, f"{path.name} missing section {section}"
        indexes.append(text.index(section))
    assert indexes == sorted(indexes), f"{path.name} sections are out of order"

    assert "{title}" in text
    assert "{article_pattern_id}" in text
    assert "{excerpt}" in text
    assert "Return one English image prompt only." in text
    assert "no text" in text.lower()
    assert "no logos" in text.lower()

    if category_dir == "naseudagyi-heureum":
        assert "board" in text.lower() or "보드" in text
    if category_dir == "jusigyi-heureum":
        assert "cartoon" in text.lower()
    if category_dir == "keuribtoyi-heureum":
        assert "cyber" in text.lower() or "on-chain" in text.lower()
    if category_dir in {"cugjewa-hyeonjang", "munhwawa-gonggan"}:
        assert "time/place" in text or "기간" in text or "장소" in text


def test_cloudflare_mysteria_prompt_is_excluded_from_prn_alignment() -> None:
    path = PROMPT_ROOT / "세상의 기록" / "miseuteria-seutori" / "article_generation.md"
    assert path.exists()
    assert "miseuteria-seutori" not in PRN_CATEGORY_PATHS

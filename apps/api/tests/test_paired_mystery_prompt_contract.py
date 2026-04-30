from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = REPO_ROOT / "apps" / "api" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _load_paired_script():
    path = SCRIPT_DIR / "publish_paired_mystery_topics.py"
    spec = importlib.util.spec_from_file_location("publish_paired_mystery_topics", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cloudflare_mysteria_root() -> Path:
    matches = [
        path
        for path in (REPO_ROOT / "prompts" / "channels" / "cloudflare").rglob("miseuteria-seutori")
        if path.is_dir()
    ]
    assert len(matches) == 1
    return matches[0]


def test_mystery_prompt_contracts_match_current_channel_policies() -> None:
    blogger_root = REPO_ROOT / "prompts" / "channels" / "blogger" / "the-midnight-archives"
    cloudflare_root = _cloudflare_mysteria_root()
    blogger_prompt_paths = [
        blogger_root / "mystery_article_generation.md",
        blogger_root / "mystery_collage_prompt.md",
    ]
    cloudflare_prompt_paths = [
        cloudflare_root / "article_generation.md",
        cloudflare_root / "image_prompt_generation.md",
    ]
    required_patterns = {
        "case-timeline",
        "evidence-breakdown",
        "legend-context",
        "scene-investigation",
        "scp-dossier",
    }
    for path in blogger_prompt_paths:
        text = path.read_text(encoding="utf-8-sig")
        assert "3x4" in text
        assert "closing" in text
        assert "inline_collage_prompt" not in text
        assert "8-panel" not in text
        assert "3x3" not in text
        if "article_generation" in path.name or path.name == "mystery_article_generation.md":
            assert "article_pattern_version must be 4" in text
            assert "summary-box" in text
            assert "evidence-table" in text
            assert "hero_image_prompt" in text
            assert "closing_image_prompt" in text
            for pattern in required_patterns:
                assert pattern in text

    for path in cloudflare_prompt_paths:
        text = path.read_text(encoding="utf-8-sig")
        assert "hero_only_mysteria_archive" in text
        assert "image_asset_plan" in text or path.name == "image_prompt_generation.md"
        assert "inline_collage_prompt" not in text
        assert "8-panel" not in text
        assert "3x3" not in text
        if "article_generation" in path.name:
            assert "article_pattern_version must be 4" in text
            for pattern in required_patterns:
                assert pattern in text


def test_mystery_channel_json_contracts_match_current_channel_policies() -> None:
    blogger_channel = json.loads(
        (REPO_ROOT / "prompts" / "channels" / "blogger" / "the-midnight-archives" / "channel.json").read_text(
            encoding="utf-8-sig"
        )
    )
    cloudflare_channel = json.loads((_cloudflare_mysteria_root() / "channel.json").read_text(encoding="utf-8-sig"))

    assert blogger_channel["paired_publish_group"] == "mystery-cloudflare-blogger"
    assert blogger_channel["article_pattern_version"] == 4
    assert blogger_channel["image_slots"] == ["hero", "closing"]
    assert blogger_channel["image_layout_policy"]["hero"] == "3x4-panel-grid-collage"
    assert blogger_channel["image_layout_policy"]["closing"] == "visual-summary"

    assert cloudflare_channel["paired_publish_group"] == "mystery-cloudflare-blogger"
    assert cloudflare_channel["article_pattern_version"] == 4
    assert cloudflare_channel["image_layout_policy"] == "hero_only_mysteria_archive"
    assert cloudflare_channel["image_asset_plan"]["roles"] == ["hero"]
    assert cloudflare_channel["hero_only"] is True
    assert cloudflare_channel["inline_images"] is False


def test_live_verifier_counts_expected_article_images_not_theme_images(monkeypatch) -> None:
    script = _load_paired_script()
    expected = [
        "https://api.dongriarchive.com/assets/the-midnight-archives/casefile/2026/04/topic/topic.webp",
        "https://api.dongriarchive.com/assets/the-midnight-archives/casefile/2026/04/topic/topic-closing.webp",
    ]
    html = (
        "<html><body>"
        f"<img src='{expected[0]}'><img src='{expected[1]}'>"
        "<img src='https://example.com/sidebar.webp'><img src='https://example.com/theme.webp'>"
        f"<p>{'a' * 3100}</p>"
        "</body></html>"
    )

    def fake_probe(url: str, *, timeout: float):
        if url == "https://example.com/post":
            return {"url": url, "status_code": 200, "content_type": "text/html", "ok": True, "text": html}
        return {"url": url, "status_code": 200, "content_type": "image/webp", "ok": True, "text": ""}

    monkeypatch.setattr(script, "_probe", fake_probe)
    result = script._verify_live("https://example.com/post", expected, timeout=1.0)
    assert result["page_image_count"] == 4
    assert result["expected_article_image_count"] == 2
    assert result["pass"] is True


def test_mystery_storage_contract_accepts_hero_and_closing_only() -> None:
    from app.services.integrations.storage_service import _is_valid_mystery_slug_webp_key

    assert _is_valid_mystery_slug_webp_key(
        "assets/the-midnight-archives/casefile/2026/04/topic-slug/topic-slug.webp"
    )
    assert _is_valid_mystery_slug_webp_key(
        "assets/the-midnight-archives/casefile/2026/04/topic-slug/topic-slug-closing.webp"
    )
    assert not _is_valid_mystery_slug_webp_key(
        "assets/the-midnight-archives/casefile/2026/04/topic-slug/cover-1234.webp"
    )


def test_mystery_image_prompt_audit_accepts_final_taos_and_amber_prompts() -> None:
    script = _load_paired_script()
    for spec in script.IMAGE_PROMPT_SPECS:
        hero = script._audit_image_prompt(spec.hero_prompt, spec=spec, slot="hero")
        closing = script._audit_image_prompt(spec.closing_prompt, spec=spec, slot="closing")
        assert hero["pass"] is True
        assert hero["score"] >= 80
        assert closing["pass"] is True
        assert closing["score"] >= 80


def test_mystery_image_prompt_audit_rejects_generic_fallback_prompt() -> None:
    script = _load_paired_script()
    spec = script._prompt_spec_by_key("taos-hum")
    result = script._audit_image_prompt(
        "One realistic 3x4 panel grid collage about New Mexico rooms and night testimony, no text, no logo, 1024x1024.",
        spec=spec,
        slot="hero",
    )
    assert result["pass"] is False
    assert result["score"] < 80


def test_public_image_url_to_object_key() -> None:
    script = _load_paired_script()
    assert (
        script._object_key_from_public_url(
            "https://api.dongriarchive.com/assets/the-midnight-archives/casefile/2026/04/topic/topic.webp"
        )
        == "assets/the-midnight-archives/casefile/2026/04/topic/topic.webp"
    )
    assert (
        script._object_key_from_public_url(
            "https://api.dongriarchive.com/assets/media/cloudflare/dongri-archive/miseuteria-seutori/2026/04/topic/topic-closing.webp"
        )
        == "assets/media/cloudflare/dongri-archive/miseuteria-seutori/2026/04/topic/topic-closing.webp"
    )


def test_image_provider_failure_blocks_fallback_by_default(monkeypatch) -> None:
    script = _load_paired_script()

    class BrokenProvider:
        def generate_image(self, *_args, **_kwargs):
            raise RuntimeError("provider down")

    monkeypatch.setattr(script, "get_image_provider", lambda _db: BrokenProvider())
    spec = script._prompt_spec_by_key("taos-hum")
    audit = script._audit_image_prompt(spec.hero_prompt, spec=spec, slot="hero")
    try:
        script._generate_image_bytes(None, slot="hero", prompt=spec.hero_prompt, slug=spec.blogger_slug, prompt_audit=audit)
    except RuntimeError as exc:
        assert "image_provider_failed_no_fallback" in str(exc)
    else:
        raise AssertionError("fallback should be blocked by default")

from app.services.cloudflare.cloudflare_channel_service import (
    _hash_image_bytes,
    _is_inline_duplicate,
    _replace_cloudflare_image_slot_with_markdown,
)


def test_inline_duplicate_detects_same_bytes() -> None:
    cover_bytes = b"same-image"
    cover_hash = _hash_image_bytes(cover_bytes)
    assert _is_inline_duplicate(cover_hash, b"same-image") is True


def test_inline_duplicate_detects_different_bytes() -> None:
    cover_hash = _hash_image_bytes(b"cover")
    assert _is_inline_duplicate(cover_hash, b"inline") is False


def test_inline_duplicate_handles_missing_inputs() -> None:
    assert _is_inline_duplicate("", b"inline") is False
    assert _is_inline_duplicate(_hash_image_bytes(b"cover"), None) is False


def test_replace_cloudflare_inline_slot_with_markdown_image() -> None:
    body = (
        "<h2>실전 사용법</h2><p>흐름을 정리합니다.</p>"
        '<div class="cf-image-slot" data-cf-image-slot="inline_1"></div>'
        "<pre><code>pwsh -NoProfile -Command \"Write-Output ok\"</code></pre>"
    )

    updated, replaced = _replace_cloudflare_image_slot_with_markdown(
        body,
        slot_role="inline_1",
        image_markdown=(
            '<img src="https://api.dongriarchive.com/assets/media/cloudflare/dongri-archive/dev.webp" '
            'alt="inline" width="100%" loading="lazy" decoding="async" />'
        ),
    )

    assert replaced is True
    assert "cf-image-slot" not in updated
    assert "width=\"100%\"" in updated
    assert "<img" in updated
    assert "<pre><code>" in updated

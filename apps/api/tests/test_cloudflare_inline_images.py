from app.services.cloudflare_channel_service import _hash_image_bytes, _is_inline_duplicate


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

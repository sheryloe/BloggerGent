from scripts.repair_blogger_media_posts_2026_legacy import (
    _remove_unresolved_img_tags,
    _replace_legacy_urls,
)


def test_replace_legacy_urls_prefers_exact_legacy_key_mapping() -> None:
    html = "<p><img src='https://api.dongriarchive.com/assets/media/posts/2026/04/foo/foo.1111.webp' /></p>"
    updated, replacements, unresolved = _replace_legacy_urls(
        html,
        legacy_map={
            "assets/media/posts/2026/04/foo/foo.1111.webp": "https://api.dongriarchive.com/assets/assets/media/google-blogger/blog/foo.webp"
        },
    )
    assert unresolved == []
    assert len(replacements) == 1
    assert "google-blogger" in updated


def test_replace_legacy_urls_normalizes_png_to_webp_mapping() -> None:
    html = "<p><img src='https://api.dongriarchive.com/assets/media/posts/2026/04/bar/bar.2222.png' /></p>"
    updated, replacements, unresolved = _replace_legacy_urls(
        html,
        legacy_map={
            "assets/media/posts/2026/04/bar/bar.2222.webp": "https://api.dongriarchive.com/assets/assets/media/google-blogger/blog/bar.webp"
        },
    )
    assert unresolved == []
    assert len(replacements) == 1
    assert "bar.webp" in updated


def test_remove_unresolved_img_tags_keeps_text_content() -> None:
    html = (
        "<article>"
        "<p>intro text</p>"
        "<img src='https://api.dongriarchive.com/assets/media/posts/2026/04/baz/baz.3333.png' />"
        "<p>body text</p>"
        "</article>"
    )
    updated, removed = _remove_unresolved_img_tags(
        html,
        ["https://api.dongriarchive.com/assets/media/posts/2026/04/baz/baz.3333.png"],
    )
    assert removed == 1
    assert "intro text" in updated
    assert "body text" in updated
    assert "baz.3333.png" not in updated

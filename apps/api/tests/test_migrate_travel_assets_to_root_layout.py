from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.migrate_travel_assets_to_root_layout import (  # noqa: E402
    _discover_article_owned_urls,
    _render_publish_webp,
    _resolve_local_source_for_url,
    _rewrite_article_urls,
)


def test_discover_article_owned_urls_assigns_unique_legacy_slots() -> None:
    article = SimpleNamespace(
        image=SimpleNamespace(public_url="https://api.dongriarchive.com/assets/media/posts/cover.webp", image_metadata={}),
        inline_media=[
            {"image_url": "https://api.dongriarchive.com/assets/media/posts/inline-1.webp"},
        ],
        assembled_html=(
            '<div>'
            '<img src="https://api.dongriarchive.com/assets/media/posts/cover.webp">'
            '<img src="https://api.dongriarchive.com/assets/media/posts/inline-1.webp">'
            '<img src="https://api.dongriarchive.com/assets/media/google-blogger/blog/post/legacy-a.webp">'
            '<img src="https://api.dongriarchive.com/assets/media/google-blogger/blog/post/legacy-b.webp">'
            '</div>'
        ),
        html_article="",
    )

    discovered = _discover_article_owned_urls(article)

    assert discovered == [
        ("https://api.dongriarchive.com/assets/media/posts/cover.webp", "cover"),
        ("https://api.dongriarchive.com/assets/media/posts/inline-1.webp", "inline-01"),
        ("https://api.dongriarchive.com/assets/media/google-blogger/blog/post/legacy-a.webp", "legacy-01"),
        ("https://api.dongriarchive.com/assets/media/google-blogger/blog/post/legacy-b.webp", "legacy-02"),
    ]


def test_render_publish_webp_converts_to_square_webp() -> None:
    source = BytesIO()
    Image.new("RGB", (640, 960), color=(40, 90, 180)).save(source, format="PNG")

    payload = _render_publish_webp(source.getvalue())

    with Image.open(BytesIO(payload)) as converted:
        assert converted.format == "WEBP"
        assert converted.size == (1024, 1024)


def test_resolve_local_source_for_url_prefers_root_exact(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    exact = runtime_root / "cover.png"
    exact.write_bytes(b"root")
    cloudflare_dir = runtime_root / "Cloudflare" / "travel"
    cloudflare_dir.mkdir(parents=True)
    (cloudflare_dir / "cover.png").write_bytes(b"cloudflare")

    match = _resolve_local_source_for_url(
        "https://api.dongriarchive.com/assets/media/posts/cover.png",
        runtime_root,
        {"cover.png": [exact, cloudflare_dir / "cover.png"]},
    )

    assert match.status == "mapped"
    assert match.bucket == "root_exact"
    assert match.source_path == exact


def test_rewrite_article_urls_only_updates_inline_items_with_same_basename() -> None:
    article = SimpleNamespace(
        html_article='<img src="https://old.example/cover.webp">',
        assembled_html='<img src="https://old.example/cover.webp">',
        inline_media=[
            {"image_url": "https://old.example/cover.webp", "kind": "same"},
            {"image_url": "https://old.example/other-inline.webp", "kind": "other"},
        ],
        image=SimpleNamespace(public_url="https://old.example/cover.webp", image_metadata={"hero": "https://old.example/cover.webp"}),
        blogger_post=SimpleNamespace(response_payload={"thumbnail": "https://old.example/cover.webp"}),
    )

    _rewrite_article_urls(article, old_url="https://old.example/cover.webp", new_url="https://new.example/cover.webp")

    assert article.image.public_url == "https://new.example/cover.webp"
    assert article.inline_media[0]["image_url"] == "https://new.example/cover.webp"
    assert article.inline_media[1]["image_url"] == "https://old.example/other-inline.webp"
    assert "https://new.example/cover.webp" in article.html_article

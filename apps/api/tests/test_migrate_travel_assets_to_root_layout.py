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
    _build_local_image_inventory,
    _discover_article_owned_urls,
    _render_publish_webp,
    _resolve_local_source_for_slug,
    _rewrite_article_urls,
    _verify_public_asset,
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


def test_resolve_local_source_for_slug_prefers_root_exact(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    exact = runtime_root / "sample-slug.png"
    exact.write_bytes(b"root")
    cloudflare_dir = runtime_root / "Cloudflare" / "travel"
    cloudflare_dir.mkdir(parents=True)
    (cloudflare_dir / "sample-slug.png").write_bytes(b"cloudflare")
    inventory = _build_local_image_inventory(runtime_root)

    match = _resolve_local_source_for_slug("sample-slug", inventory)

    assert match.status == "mapped"
    assert match.bucket == "root_exact"
    assert match.source_path == exact


def test_resolve_local_source_for_slug_uses_unique_near_slug_and_ignores_cover_tokens(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    (runtime_root / "sample-slug-cover.png").write_bytes(b"cover-derived")
    near = runtime_root / "sample-slug-city-guide.png"
    near.write_bytes(b"near-source")
    inventory = _build_local_image_inventory(runtime_root)

    match = _resolve_local_source_for_slug("sample-slug", inventory)

    assert match.status == "mapped"
    assert match.bucket == "root_near_slug"
    assert match.source_path == near
    assert match.source_slug == "sample-slug-city-guide"


def test_rewrite_article_urls_only_updates_inline_items_with_same_old_key() -> None:
    article = SimpleNamespace(
        html_article='<img src="https://old.example/assets/blog/slug/cover.webp">',
        assembled_html='<img src="https://old.example/assets/blog/slug/cover.webp">',
        inline_media=[
            {"image_url": "https://old.example/assets/blog/slug/cover.webp", "kind": "same"},
            {"image_url": "https://old.example/assets/blog/other/cover.webp", "kind": "other"},
        ],
        image=SimpleNamespace(
            public_url="https://old.example/assets/blog/slug/cover.webp",
            image_metadata={"hero": "https://old.example/assets/blog/slug/cover.webp"},
        ),
        blogger_post=SimpleNamespace(response_payload={"thumbnail": "https://old.example/assets/blog/slug/cover.webp"}),
    )

    _rewrite_article_urls(
        article,
        old_url="https://old.example/assets/blog/slug/cover.webp",
        new_url="https://new.example/assets/travel-blogger/travel/sample-slug.webp",
    )

    assert article.image.public_url == "https://new.example/assets/travel-blogger/travel/sample-slug.webp"
    assert article.inline_media[0]["image_url"] == "https://new.example/assets/travel-blogger/travel/sample-slug.webp"
    assert article.inline_media[1]["image_url"] == "https://old.example/assets/blog/other/cover.webp"
    assert "https://new.example/assets/travel-blogger/travel/sample-slug.webp" in article.html_article


def test_verify_public_asset_uses_integration_fallback_when_direct_bucket_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.migrate_travel_assets_to_root_layout.cloudflare_r2_object_exists",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "scripts.migrate_travel_assets_to_root_layout.cloudflare_r2_object_size",
        lambda *_args, **_kwargs: None,
    )

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "image/webp"}

        @property
        def is_success(self) -> bool:
            return True

    monkeypatch.setattr("scripts.migrate_travel_assets_to_root_layout.httpx.head", lambda *_args, **_kwargs: _FakeResponse())

    verification = _verify_public_asset(
        None,
        object_key="assets/travel-blogger/travel/sample-slug.webp",
        target_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
        verify_http=True,
        upload_payload={
            "upload_path": "integration_fallback",
            "public_url": "https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
        },
        expected_size=4321,
    )

    assert verification["exists"] is True
    assert verification["size"] == 4321
    assert verification["http_ok"] is True
    assert verification["verification_mode"] == "integration_fallback"

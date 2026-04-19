from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.travel.migrate_travel_assets_to_root_layout import (  # noqa: E402
    RebuildAction,
    SourceMatch,
    _article_cover_hash_targets,
    _extract_cover_hash_urls,
    _is_cover_hash_url,
    _merge_local_image_inventory,
    _parse_extra_source_roots,
    _load_focus_article_ids_from_file,
    _load_source_overrides_from_file,
    _collect_unmatched_cleanup_targets,
    _clear_unmatched_references,
    _process_action,
    _parse_article_ids,
    _record_execution_summary,
    _build_local_image_inventory,
    _build_url_map,
    _discover_article_owned_urls,
    _sanitize_empty_image_figures,
    _sanitize_travel_inline_artifacts,
    _report_path,
    _render_publish_webp,
    _resolve_local_source_for_slug,
    _resolve_source_match_for_article,
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

    match = _resolve_local_source_for_slug(
        "sample-slug",
        inventory,
        enable_similar_recovery=False,
        fallback_source_path=None,
    )

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

    match = _resolve_local_source_for_slug(
        "sample-slug",
        inventory,
        enable_similar_recovery=False,
        fallback_source_path=None,
    )

    assert match.status == "mapped"
    assert match.bucket == "root_near_slug"
    assert match.source_path == near
    assert match.source_slug == "sample-slug-city-guide"


def test_resolve_local_source_for_slug_uses_similar_recovery_when_enabled(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    similar = runtime_root / "busan-millak-waterfront-night-market-guide.png"
    similar.write_bytes(b"similar-source")
    inventory = _build_local_image_inventory(runtime_root)

    match = _resolve_local_source_for_slug(
        "navigating-busans-millak-waterfront",
        inventory,
        enable_similar_recovery=True,
        fallback_source_path=None,
    )

    assert match.status == "mapped"
    assert match.bucket == "similar_match"
    assert match.source_path == similar


def test_resolve_local_source_for_slug_uses_fallback_seed_when_missing(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    fallback = tmp_path / "fallback.png"
    fallback.write_bytes(b"fallback")
    inventory = _build_local_image_inventory(runtime_root)

    match = _resolve_local_source_for_slug(
        "completely-missing-slug",
        inventory,
        enable_similar_recovery=True,
        fallback_source_path=fallback,
    )

    assert match.status == "mapped"
    assert match.bucket == "fallback_seed"
    assert match.source_path == fallback


def test_resolve_local_source_for_slug_limits_similar_recovery_budget(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    similar = runtime_root / "travel-guide-for-navigating-waterfront.png"
    similar.write_bytes(b"similar-source")
    fallback = tmp_path / "fallback.png"
    fallback.write_bytes(b"fallback")
    inventory = _build_local_image_inventory(runtime_root)
    budget = {"similar": 1, "fallback": 2}

    first = _resolve_local_source_for_slug(
        "navigating-busans-waterfront",
        inventory,
        enable_similar_recovery=True,
        fallback_source_path=fallback,
        recovery_budget=budget,
    )
    second = _resolve_local_source_for_slug(
        "navigating-busans-waterfront",
        inventory,
        enable_similar_recovery=True,
        fallback_source_path=fallback,
        recovery_budget=budget,
    )

    assert first.status == "mapped"
    assert first.bucket == "similar_match"
    assert second.status == "mapped"
    assert second.bucket == "fallback_seed"


def test_resolve_local_source_for_slug_limits_fallback_recovery_budget(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    fallback = tmp_path / "fallback.png"
    fallback.write_bytes(b"fallback")
    inventory = _build_local_image_inventory(runtime_root)
    budget = {"similar": None, "fallback": 1}

    first = _resolve_local_source_for_slug(
        "completely-missing-slug",
        inventory,
        enable_similar_recovery=False,
        fallback_source_path=fallback,
        recovery_budget=budget,
    )
    second = _resolve_local_source_for_slug(
        "another-completely-missing-slug",
        inventory,
        enable_similar_recovery=False,
        fallback_source_path=fallback,
        recovery_budget=budget,
    )

    assert first.status == "mapped"
    assert first.bucket == "fallback_seed"
    assert second.status == "missing_source"


def test_resolve_local_source_for_slug_keeps_similar_budget_on_miss_then_uses_on_match(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    source = runtime_root / "travel-busan-han-river-guide.png"
    source.write_bytes(b"similar-source")
    inventory = _build_local_image_inventory(runtime_root)
    budget = {"similar": 1, "fallback": 0}

    first = _resolve_local_source_for_slug(
        "unrelated-travel-slug",
        inventory,
        enable_similar_recovery=True,
        fallback_source_path=None,
        recovery_budget=budget,
    )
    assert first.status == "missing_source"
    assert budget["similar"] == 1

    second = _resolve_local_source_for_slug(
        "how-to-travel-busan-han-river-guide",
        inventory,
        enable_similar_recovery=True,
        fallback_source_path=None,
        recovery_budget=budget,
    )
    assert second.status == "mapped"
    assert second.bucket == "similar_match"
    assert budget["similar"] == 0


def test_parse_article_ids_supports_comma_newline_and_duplicates() -> None:
    parsed = _parse_article_ids("101, 102\n103,101,  104\r105")

    assert parsed == (101, 102, 103, 104, 105)


def test_parse_article_ids_ignores_comment_lines() -> None:
    parsed = _parse_article_ids("101,#comment\n102\n#skip\n103")

    assert parsed == (101, 102, 103)


def test_parse_article_ids_raises_for_invalid_token() -> None:
    try:
        _parse_article_ids("101,abc")
    except ValueError as exc:
        assert "Invalid article id token: abc" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_parse_extra_source_roots_deduplicates_and_normalizes(tmp_path: Path) -> None:
    root_a = (tmp_path / "a")
    root_b = (tmp_path / "b")
    root_a.mkdir(parents=True)
    root_b.mkdir(parents=True)

    parsed = _parse_extra_source_roots(f"{root_a}, {root_b}\n{root_a}")

    assert parsed == (root_a.resolve(), root_b.resolve())


def test_load_focus_article_ids_from_file_reads_ids(tmp_path: Path) -> None:
    source = tmp_path / "ids.txt"
    source.write_text("101\n102, 103\n#skip\n104,")

    parsed = _load_focus_article_ids_from_file(str(source))

    assert parsed == (101, 102, 103, 104)


def test_load_source_overrides_from_file_reads_json_list(tmp_path: Path) -> None:
    source = tmp_path / "overrides.json"
    source.write_text(
        """
        [
          {"article_id": 328, "source_path": "C:/tmp/a.png"},
          {"article_id": "365", "source_path": "C:/tmp/b.png"}
        ]
        """.strip(),
        encoding="utf-8",
    )

    parsed = _load_source_overrides_from_file(str(source))

    assert parsed[328] == Path("C:/tmp/a.png").resolve()
    assert parsed[365] == Path("C:/tmp/b.png").resolve()


def test_resolve_source_match_for_article_prioritizes_override(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    (runtime_root / "sample-slug.png").write_bytes(b"root")
    override = runtime_root / "forced-source.png"
    override.write_bytes(b"forced")
    inventory = _build_local_image_inventory(runtime_root)

    match = _resolve_source_match_for_article(
        328,
        "sample-slug",
        inventory,
        source_overrides={328: override},
        enable_similar_recovery=False,
        fallback_source_path=None,
    )

    assert match.status == "mapped"
    assert match.bucket == "override_file"
    assert match.source_path == override


def test_resolve_source_match_for_article_marks_missing_when_override_file_not_found(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    inventory = _build_local_image_inventory(runtime_root)
    missing = runtime_root / "nope.png"

    match = _resolve_source_match_for_article(
        999,
        "sample-slug",
        inventory,
        source_overrides={999: missing},
        enable_similar_recovery=True,
        fallback_source_path=runtime_root / "fallback.png",
    )

    assert match.status == "missing_source"
    assert match.bucket == "override_file"
    assert match.reason == "source_override_missing"


def test_merge_local_image_inventory_includes_extra_root_exact(tmp_path: Path) -> None:
    runtime_root = tmp_path / "images"
    runtime_root.mkdir(parents=True)
    (runtime_root / "sample-slug.png").write_bytes(b"root")
    extra_root = tmp_path / "extra"
    extra_root.mkdir(parents=True)
    (extra_root / "another-slug.png").write_bytes(b"extra")

    merged = _merge_local_image_inventory(
        _build_local_image_inventory(runtime_root),
        _build_local_image_inventory(extra_root),
    )

    assert "sample-slug.png" in merged.root_exact
    assert "another-slug.png" in merged.root_exact


def test_cover_hash_url_detection_and_extraction() -> None:
    html = (
        "<img src='https://api.dongriarchive.com/assets/travel-blogger/travel/slug.webp' />"
        "<img src='https://api.dongriarchive.com/assets/media/posts/cover-8580810ed69d.webp' />"
    )

    assert _is_cover_hash_url("https://api.dongriarchive.com/assets/media/posts/cover-8580810ed69d.webp")
    extracted = _extract_cover_hash_urls(html)
    assert extracted == ["https://api.dongriarchive.com/assets/media/posts/cover-8580810ed69d.webp"]


def test_article_cover_hash_targets_collects_article_and_synced_thumbnail() -> None:
    article = SimpleNamespace(
        html_article="<img src='https://api.dongriarchive.com/assets/media/posts/cover-111122223333.webp' />",
        assembled_html="",
        blogger_post=SimpleNamespace(response_payload={"thumbnail": "https://api.dongriarchive.com/assets/media/posts/cover-aaaabbbbcccc.webp"}),
    )
    synced = SimpleNamespace(thumbnail_url="https://api.dongriarchive.com/assets/media/posts/cover-ddddeeeeffff.webp")

    targets = _article_cover_hash_targets(article, synced)

    assert "https://api.dongriarchive.com/assets/media/posts/cover-111122223333.webp" in targets
    assert "https://api.dongriarchive.com/assets/media/posts/cover-aaaabbbbcccc.webp" in targets
    assert "https://api.dongriarchive.com/assets/media/posts/cover-ddddeeeeffff.webp" in targets


def test_rewrite_article_urls_hero_only_updates_inline_items_with_same_old_key() -> None:
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
        new_url="https://new.example/assets/travel-blogger/travel/sample-slug.webp",
        url_map={
            "https://old.example/assets/blog/slug/cover.webp": "https://new.example/assets/travel-blogger/travel/sample-slug.webp",
        },
        replace_scope="hero_only",
    )

    assert article.image.public_url == "https://new.example/assets/travel-blogger/travel/sample-slug.webp"
    assert article.inline_media[0]["image_url"] == "https://new.example/assets/travel-blogger/travel/sample-slug.webp"
    assert article.inline_media[1]["image_url"] == "https://old.example/assets/blog/other/cover.webp"
    assert "https://new.example/assets/travel-blogger/travel/sample-slug.webp" in article.html_article


def test_rewrite_article_urls_hero_inline_forces_inline_and_delivery_urls() -> None:
    article = SimpleNamespace(
        html_article="<p>body</p>",
        assembled_html="<p>body</p>",
        inline_media=[
            {
                "slot": "travel-inline-3x2",
                "image_url": "",
                "delivery": {"cloudflare": {"original_url": "https://old.example/assets/blog/legacy-inline.webp"}},
            }
        ],
        image=SimpleNamespace(
            public_url="https://old.example/assets/blog/slug/cover.webp",
            image_metadata={
                "delivery": {
                    "cloudflare": {"original_url": "https://old.example/assets/blog/legacy-cover.webp"},
                }
            },
        ),
        blogger_post=SimpleNamespace(response_payload={}),
    )

    _rewrite_article_urls(
        article,
        new_url="https://new.example/assets/travel-blogger/travel/sample-slug.webp",
        url_map={},
        replace_scope="hero_inline",
    )

    assert article.image.public_url == "https://new.example/assets/travel-blogger/travel/sample-slug.webp"
    assert (
        article.image.image_metadata["delivery"]["cloudflare"]["original_url"]
        == "https://new.example/assets/travel-blogger/travel/sample-slug.webp"
    )
    assert article.inline_media[0]["image_url"] == "https://new.example/assets/travel-blogger/travel/sample-slug.webp"
    assert (
        article.inline_media[0]["delivery"]["cloudflare"]["original_url"]
        == "https://new.example/assets/travel-blogger/travel/sample-slug.webp"
    )


def test_sanitize_travel_inline_artifacts_removes_marker_block_without_renderable_img() -> None:
    source = (
        '<p>intro</p>'
        '<!--TRAVEL_INLINE_3X2-->'
        '<figure style="margin:30px 0 30px;"><img src=""></figure>'
        '<p>outro</p>'
    )

    sanitized = _sanitize_travel_inline_artifacts(source)

    assert "<!--TRAVEL_INLINE_3X2-->" not in sanitized
    assert "<figure" not in sanitized
    assert "<p>intro</p><p>outro</p>" == sanitized.replace("\n", "")


def test_sanitize_travel_inline_artifacts_keeps_renderable_figure() -> None:
    source = (
        '<p>intro</p>'
        '<!--TRAVEL_INLINE_3X2--><figure><img src="https://cdn.example.com/hero.webp" /></figure>'
        '<p>outro</p>'
    )
    sanitized = _sanitize_travel_inline_artifacts(source)

    assert "<!--TRAVEL_INLINE_3X2-->" not in sanitized
    assert '<figure><img src="https://cdn.example.com/hero.webp" /></figure>' in sanitized


def test_sanitize_empty_image_figures_removes_non_marker_empty_figure() -> None:
    source = (
        '<p>before</p>'
        '<figure style="margin:0 0 32px;"><img src="" alt="x" /></figure>'
        '<p>after</p>'
    )
    sanitized = _sanitize_empty_image_figures(source)
    assert "<figure" not in sanitized
    assert "<p>before</p><p>after</p>" == sanitized.replace("\n", "")


def test_build_url_map_hero_inline_includes_cover_inline_and_legacy() -> None:
    action = RebuildAction(
        article_id=1,
        blog_id=34,
        post_slug="sample-slug",
        category_key="travel",
        old_url="https://old.example/assets/blog/slug/cover.webp",
        legacy_key="assets/blog/slug/cover.webp",
        target_key="assets/travel-blogger/travel/sample-slug.webp",
        target_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
        source_match=SourceMatch(status="mapped"),
        owned_urls=[
            ("https://old.example/assets/blog/slug/cover.webp", "cover"),
            ("https://old.example/assets/blog/slug/inline-1.webp", "inline-01"),
            ("https://old.example/assets/blog/slug/legacy-a.webp", "legacy-01"),
        ],
    )

    url_map = _build_url_map(
        action,
        replace_scope="hero_inline",
        resolved_public_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
    )

    assert url_map["https://old.example/assets/blog/slug/cover.webp"] == "https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp"
    assert url_map["https://old.example/assets/blog/slug/inline-1.webp"] == "https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp"
    assert url_map["https://old.example/assets/blog/slug/legacy-a.webp"] == "https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp"


def test_report_path_uses_report_root(tmp_path: Path) -> None:
    report_root = tmp_path / "travel"
    output = _report_path("travel-unit-test", report_root)
    assert str(output).startswith(str(report_root / "reports"))


def test_verify_public_asset_uses_integration_fallback_when_direct_bucket_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.travel.migrate_travel_assets_to_root_layout.cloudflare_r2_object_exists",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "scripts.travel.migrate_travel_assets_to_root_layout.cloudflare_r2_object_size",
        lambda *_args, **_kwargs: None,
    )

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "image/webp"}

        @property
        def is_success(self) -> bool:
            return True

    monkeypatch.setattr(
        "scripts.travel.migrate_travel_assets_to_root_layout.httpx.head",
        lambda *_args, **_kwargs: _FakeResponse(),
    )

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


def test_collect_unmatched_cleanup_targets_includes_urls_and_keys() -> None:
    action = RebuildAction(
        article_id=1,
        blog_id=34,
        post_slug="sample-slug",
        category_key="travel",
        old_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
        legacy_key="assets/travel-blogger/travel/sample-slug.webp",
        target_key="assets/travel-blogger/travel/sample-slug.webp",
        target_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
        source_match=SourceMatch(
            status="missing_source",
            source_slug="sample-slug",
            bucket="missing",
            candidates=[],
        ),
        owned_urls=[
            ("https://cdn.example.com/assets/media/posts/legacy-a.webp", "legacy-01"),
            ("https://cdn.example.com/assets/media/posts/legacy-b.webp", "legacy-02"),
        ],
    )

    targets, key_targets = _collect_unmatched_cleanup_targets(action)

    assert "https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp" in targets
    assert "https://cdn.example.com/assets/media/posts/legacy-a.webp" in targets
    assert "https://cdn.example.com/assets/media/posts/legacy-b.webp" in targets
    assert "assets/travel-blogger/travel/sample-slug.webp" in key_targets
    assert "assets/media/posts/legacy-a.webp" in key_targets
    assert "assets/media/posts/legacy-b.webp" in key_targets


def test_clear_unmatched_references_removes_target_urls_only(tmp_path: Path) -> None:
    article = SimpleNamespace(
        image=SimpleNamespace(
            public_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
            image_metadata={
                "delivery": {
                    "cloudflare": {
                        "public_url": "https://api.dongriarchive.com/assets/media/posts/sample.webp",
                        "original_url": "https://api.dongriarchive.com/assets/media/posts/sample.webp",
                    }
                }
            },
        ),
        html_article='<img src="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp"><img src="https://api.dongriarchive.com/assets/media/posts/keep.webp">',
        assembled_html='<img src="https://api.dongriarchive.com/assets/media/posts/legacy.webp">',
        inline_media=[
            {"image_url": "https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp"},
            {"image_url": "https://api.dongriarchive.com/assets/media/posts/keep-inline.webp"},
        ],
        blogger_post=SimpleNamespace(response_payload={"thumbnail": "https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp"}),
    )

    _clear_unmatched_references(
        article=article,
        targets={
            "https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
            "assets/media/posts/legacy.webp",
        },
        key_targets={"assets/media/posts/sample.webp", "assets/media/posts/legacy.webp"},
    )

    assert article.image.public_url == ""
    assert article.html_article == '<img src=""><img src="https://api.dongriarchive.com/assets/media/posts/keep.webp">'
    assert article.assembled_html == '<img src="">'
    assert article.inline_media[0]["image_url"] == ""
    assert article.inline_media[1]["image_url"] == "https://api.dongriarchive.com/assets/media/posts/keep-inline.webp"
    assert article.blogger_post.response_payload["thumbnail"] == ""
    assert article.image.image_metadata["delivery"]["cloudflare"]["public_url"] == ""


def test_process_action_missing_source_clears_db_refs_and_deletes_legacy(monkeypatch, tmp_path: Path) -> None:
    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeDb:
        def __init__(self, synced_row):
            self.synced_row = synced_row
            self.add_calls = []
            self.commit_calls = 0
            self.rollback_calls = 0

        def execute(self, *_args, **_kwargs):
            return _FakeResult(self.synced_row)

        def add(self, _obj):
            self.add_calls.append(_obj)

        def commit(self):
            self.commit_calls += 1

        def rollback(self):
            self.rollback_calls += 1

    synced = SimpleNamespace(thumbnail_url="https://api.dongriarchive.com/assets/media/posts/main.webp")
    db = _FakeDb(synced)
    article = SimpleNamespace(
        image=SimpleNamespace(
            public_url="https://api.dongriarchive.com/assets/media/posts/main.webp",
            image_metadata={"delivery": {"cloudflare": {"public_url": "https://api.dongriarchive.com/assets/media/posts/main.webp"}}},
        ),
        html_article='<p><img src="https://api.dongriarchive.com/assets/media/posts/main.webp"></p>',
        assembled_html='<p><img src="https://api.dongriarchive.com/assets/media/posts/main.webp"></p>',
        inline_media=[{"image_url": "https://api.dongriarchive.com/assets/media/posts/main.webp"}],
        blogger_post=SimpleNamespace(
            response_payload={"thumbnail": "https://api.dongriarchive.com/assets/media/posts/main.webp"},
            blogger_post_id="bp-1",
        ),
        blog=SimpleNamespace(id=34),
        blog_id=34,
    )

    action = RebuildAction(
        article_id=1,
        blog_id=34,
        post_slug="sample-slug",
        category_key="travel",
        old_url="https://api.dongriarchive.com/assets/media/posts/main.webp",
        legacy_key="assets/media/posts/main.webp",
        target_key="assets/travel-blogger/travel/sample-slug.webp",
        target_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
        source_match=SourceMatch(
            status="missing_source",
            source_slug="sample-slug",
            bucket="missing",
            candidates=[],
            source_path=None,
        ),
        owned_urls=[
            ("https://api.dongriarchive.com/assets/media/posts/main.webp", "cover"),
            ("https://api.dongriarchive.com/assets/media/posts/legacy.webp", "legacy-01"),
        ],
    )

    upsert_calls: list[dict[str, object]] = []
    deleted: list[str] = []

    monkeypatch.setattr(
        "scripts.travel.migrate_travel_assets_to_root_layout._upsert_mapping",
        lambda *_args, **kwargs: upsert_calls.append(kwargs),
    )
    monkeypatch.setattr(
        "scripts.travel.migrate_travel_assets_to_root_layout.delete_cloudflare_r2_asset",
        lambda _db, object_key: deleted.append(object_key),
    )

    outcome = _process_action(
        db,
        article=article,
        action=action,
        runtime_image_root=tmp_path / "images",
        verify_http=False,
        replace_scope="hero_inline",
        cleanup_adopted_sources=False,
    )

    assert outcome["status"] == "missing_source"
    assert outcome["db_references_cleared"] is True
    assert article.image.public_url == ""
    assert "main.webp" not in (article.html_article + article.assembled_html)
    assert article.inline_media[0]["image_url"] == ""
    assert article.blogger_post.response_payload["thumbnail"] == ""
    assert synced.thumbnail_url is None
    assert outcome["legacy_delete_attempted"] is True
    assert outcome["legacy_deleted"] is True
    assert deleted == ["assets/media/posts/main.webp"]
    assert upsert_calls and upsert_calls[-1]["status"] == "missing_source"


def test_process_action_missing_source_legacy_delete_failure_does_not_abort(monkeypatch) -> None:
    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeDb:
        def __init__(self, synced_row):
            self.synced_row = synced_row
            self.add_calls = []
            self.commit_calls = 0

        def execute(self, *_args, **_kwargs):
            return _FakeResult(self.synced_row)

        def add(self, _obj):
            self.add_calls.append(_obj)

        def commit(self):
            self.commit_calls += 1

        def rollback(self):
            pass

    db = _FakeDb(SimpleNamespace(thumbnail_url="https://api.dongriarchive.com/assets/media/posts/main.webp"))
    article = SimpleNamespace(
        image=SimpleNamespace(
            public_url="https://api.dongriarchive.com/assets/media/posts/main.webp",
            image_metadata={"delivery": {"cloudflare": {"public_url": "https://api.dongriarchive.com/assets/media/posts/main.webp"}}},
        ),
        html_article='<p><img src="https://api.dongriarchive.com/assets/media/posts/main.webp"></p>',
        assembled_html="",
        inline_media=[],
        blogger_post=SimpleNamespace(
            response_payload={"thumbnail": "https://api.dongriarchive.com/assets/media/posts/main.webp"},
            blogger_post_id="bp-2",
        ),
        blog=SimpleNamespace(id=34),
        blog_id=34,
    )
    action = RebuildAction(
        article_id=2,
        blog_id=34,
        post_slug="sample-slug-2",
        category_key="travel",
        old_url="https://api.dongriarchive.com/assets/media/posts/main.webp",
        legacy_key="assets/media/posts/main.webp",
        target_key="assets/travel-blogger/travel/sample-slug-2.webp",
        target_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug-2.webp",
        source_match=SourceMatch(status="missing_source", source_slug="sample-slug-2", bucket="missing", candidates=[], source_path=None),
        owned_urls=[("https://api.dongriarchive.com/assets/media/posts/main.webp", "cover")],
    )

    upsert_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "scripts.travel.migrate_travel_assets_to_root_layout._upsert_mapping",
        lambda *_args, **kwargs: upsert_calls.append(kwargs),
    )
    monkeypatch.setattr(
        "scripts.travel.migrate_travel_assets_to_root_layout.delete_cloudflare_r2_asset",
        lambda _db, object_key: (_ for _ in ()).throw(RuntimeError("delete failed")),
    )
    outcome = _process_action(
        db,
        article=article,
        action=action,
        runtime_image_root=Path("unused"),
        verify_http=False,
        replace_scope="hero_inline",
        cleanup_adopted_sources=False,
    )

    assert outcome["status"] == "missing_source"
    assert outcome["legacy_delete_attempted"] is True
    assert outcome["legacy_deleted"] is False
    assert any(item.startswith("legacy_r2_delete_failed") for item in outcome["cleanup_errors"])
    assert upsert_calls and upsert_calls[-1]["status"] == "missing_source"
    assert article.image.public_url == ""


def test_record_execution_summary_counts_cleanup_success_and_failed() -> None:
    report: dict[str, object] = {
        "language_reports": {},
        "status_counts": {},
    }
    action = RebuildAction(
        article_id=1,
        blog_id=34,
        post_slug="sample-slug",
        category_key="travel",
        old_url="https://old.example/assets/travel-blogger/travel/sample-slug.webp",
        legacy_key="assets/travel-blogger/travel/sample-slug.webp",
        target_key="assets/travel-blogger/travel/sample-slug.webp",
        target_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
        source_match=SourceMatch(status="missing_source", source_slug="sample-slug", bucket="missing"),
        owned_urls=[],
    )

    _record_execution_summary(
        report,
        action=action,
        outcome={
            "status": "missing_source",
            "db_references_cleared": True,
            "cleanup_errors": [],
        },
    )
    summary = report["language_reports"]["english"]
    assert summary["cleanup_success"] == 1
    assert summary["cleanup_failed"] == 0

    _record_execution_summary(
        report,
        action=action,
        outcome={"status": "missing_source", "db_references_cleared": False, "cleanup_errors": ["error"]},
    )
    assert report["language_reports"]["english"]["cleanup_failed"] == 1


def test_record_execution_summary_counts_cleanup_success_when_no_cleanup_targets() -> None:
    report: dict[str, object] = {
        "language_reports": {},
        "status_counts": {},
    }
    action = RebuildAction(
        article_id=2,
        blog_id=34,
        post_slug="sample-slug-2",
        category_key="travel",
        old_url="",
        legacy_key="",
        target_key="assets/travel-blogger/travel/sample-slug-2.webp",
        target_url="https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug-2.webp",
        source_match=SourceMatch(status="missing_source", source_slug="sample-slug-2", bucket="missing", candidates=[]),
        owned_urls=[],
    )

    _record_execution_summary(
        report,
        action=action,
        outcome={
            "status": "missing_source",
            "db_references_cleared": False,
            "cleanup_errors": [],
            "cleanup_targets": {"urls": [], "keys": []},
            "legacy_deleted": False,
            "cleanup_performed": False,
        },
    )
    summary = report["language_reports"]["english"]
    assert summary["cleanup_success"] == 1
    assert summary["cleanup_failed"] == 0

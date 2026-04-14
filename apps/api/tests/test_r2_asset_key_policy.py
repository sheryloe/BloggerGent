from app.services.content.article_service import (
    build_r2_asset_object_key,
    resolve_r2_blog_group,
    resolve_r2_category_key,
)


def test_resolve_r2_blog_group_for_korea_travel_languages() -> None:
    assert resolve_r2_blog_group(profile_key="korea_travel", primary_language="en") == "google-blogger/korea-travel"
    assert resolve_r2_blog_group(profile_key="korea_travel", primary_language="es") == "google-blogger/korea-travel"
    assert resolve_r2_blog_group(profile_key="korea_travel", primary_language="ja") == "google-blogger/korea-travel"


def test_resolve_r2_category_key_for_localized_travel_labels() -> None:
    assert resolve_r2_category_key(
        profile_key="korea_travel",
        primary_language="es",
        labels=["Viajes", "Seoul"],
        title="Ruta en Seul",
        summary="",
    ) == "travel"
    assert resolve_r2_category_key(
        profile_key="korea_travel",
        primary_language="ja",
        labels=["グルメ・カフェ", "韓国"],
        title="釜山グルメ旅",
        summary="",
    ) == "food"


def test_build_r2_asset_object_key_uses_required_layout() -> None:
    object_key = build_r2_asset_object_key(
        profile_key="world_mystery",
        primary_language="en",
        editorial_category_key="case-files",
        post_slug="dyatlov-revisited",
        asset_role="cover",
        content=b"test-bytes",
    )
    assert object_key.startswith("assets/media/google-blogger/world-mystery/mystery/")
    assert "/dyatlov-revisited/" in object_key
    assert object_key.endswith(".webp")


def test_build_r2_asset_object_key_prefers_blog_slug_when_provided() -> None:
    object_key = build_r2_asset_object_key(
        profile_key="korea_travel",
        primary_language="en",
        blog_slug="donggri-el-alma-de-corea",
        editorial_category_key="travel",
        post_slug="seoul-day-route",
        asset_role="cover",
        content=b"slug-priority",
    )
    assert object_key.startswith("assets/media/google-blogger/donggri-el-alma-de-corea/travel/")
    assert "korea-travel" not in object_key
    assert "/seoul-day-route/" in object_key
    assert object_key.endswith(".webp")


def test_build_r2_asset_object_key_supports_cloudflare_channel_slug() -> None:
    object_key = build_r2_asset_object_key(
        profile_key="archive",
        primary_language="ko",
        channel_slug="dongri-archive",
        editorial_category_key="market",
        post_slug="market-flow-2026",
        asset_role="cover",
        content=b"cloudflare-channel",
    )
    assert object_key.startswith("assets/media/cloudflare/dongri-archive/")
    assert "/market-flow-2026/" in object_key
    assert object_key.endswith(".webp")

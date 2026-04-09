from app.services.article_service import (
    build_r2_asset_object_key,
    resolve_r2_blog_group,
    resolve_r2_category_key,
)


def test_resolve_r2_blog_group_for_korea_travel_languages() -> None:
    assert resolve_r2_blog_group(profile_key="korea_travel", primary_language="en") == "korea-travel-en"
    assert resolve_r2_blog_group(profile_key="korea_travel", primary_language="es") == "korea-travel-es"
    assert resolve_r2_blog_group(profile_key="korea_travel", primary_language="ja") == "korea-travel-ja"


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
    assert object_key.startswith("assets/media/world-mystery/mystery/")
    assert "/dyatlov-revisited/" in object_key
    assert object_key.endswith(".webp")

from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

from app.services.content.article_service import (
    build_r2_asset_object_key,
    resolve_r2_blog_group,
    resolve_r2_category_key,
)
from app.services.content.travel_blog_policy import (
    build_travel_asset_object_key,
    get_travel_blog_policy,
    is_valid_travel_canonical_object_key,
)
from app.services.cloudflare.cloudflare_asset_policy import (
    build_cloudflare_local_asset_path,
    build_default_cloudflare_asset_policy,
    build_cloudflare_r2_object_key,
)


def test_resolve_r2_blog_group_for_travel_blog_ids() -> None:
    assert resolve_r2_blog_group(profile_key="korea_travel", blog_id=34, primary_language="en") == "travel-blogger"
    assert resolve_r2_blog_group(profile_key="korea_travel", blog_id=36, primary_language="es") == "travel-blogger"
    assert resolve_r2_blog_group(profile_key="korea_travel", blog_id=37, primary_language="ja") == "travel-blogger"


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
        primary_language="en",
        labels=[],
        title="",
        summary="",
    ) == "uncategorized"


def test_build_r2_asset_object_key_uses_travel_canonical_layout() -> None:
    object_key = build_r2_asset_object_key(
        profile_key="korea_travel",
        blog_id=36,
        primary_language="es",
        blog_slug="ignored-legacy-slug",
        editorial_category_key="travel",
        post_slug="seoul-day-route",
        asset_role="hero",
        content=b"slug-priority",
    )
    assert object_key == "assets/travel-blogger/travel/seoul-day-route.webp"
    assert is_valid_travel_canonical_object_key(object_key)


def test_build_travel_asset_object_key_normalizes_known_cover_roles() -> None:
    policy = get_travel_blog_policy(blog_id=37)
    assert policy is not None
    assert (
        build_travel_asset_object_key(
            policy=policy,
            category_key="culture",
            post_slug="night-seoul",
            asset_role="hero-refresh",
        )
        == "assets/travel-blogger/culture/night-seoul.webp"
    )


def test_is_valid_travel_canonical_object_key_rejects_legacy_cover_folder_layout() -> None:
    assert is_valid_travel_canonical_object_key("assets/travel-blogger/culture/night-seoul.webp")
    assert is_valid_travel_canonical_object_key("assets/travel-blogger/culture/night-seoul/cover.webp") is False
    assert is_valid_travel_canonical_object_key("assets/Travel/culture/night-seoul.webp") is False


@pytest.mark.parametrize("asset_role", ["inline-3x2", "legacy-01"])
def test_build_travel_asset_object_key_blocks_non_cover_roles(asset_role: str) -> None:
    policy = get_travel_blog_policy(blog_id=34)
    assert policy is not None
    with pytest.raises(ValueError):
        build_travel_asset_object_key(
            policy=policy,
            category_key="travel",
            post_slug="night-seoul",
            asset_role=asset_role,
        )


def test_build_r2_asset_object_key_supports_cloudflare_channel_slug() -> None:
    timestamp = datetime(2026, 4, 17, 12, 30, tzinfo=timezone.utc)
    object_key = build_r2_asset_object_key(
        profile_key="archive",
        primary_language="ko",
        channel_slug="dongri-archive",
        category_slug="주식의-흐름",
        post_slug="market-flow-2026",
        asset_role="cover",
        content=b"cloudflare-channel",
        timestamp=timestamp,
    )
    assert object_key == (
        "assets/media/cloudflare/dongri-archive/"
        "jusigyi-heureum/2026/04/"
        "market-flow-2026/market-flow-2026.webp"
    )


def test_build_r2_asset_object_key_for_mystery_uses_slug_filename_contract() -> None:
    object_key = build_r2_asset_object_key(
        profile_key="world_mystery",
        blog_id=35,
        primary_language="en",
        blog_slug="the-midnight-archives",
        editorial_category_key="casefile",
        post_slug="black-dahlia-murder-forensic-advances-cold-case",
        asset_role="hero-refresh",
        content=b"ignored-for-mystery",
    )
    assert object_key.startswith("assets/the-midnight-archives/casefile/")
    assert object_key.endswith(
        "/black-dahlia-murder-forensic-advances-cold-case/black-dahlia-murder-forensic-advances-cold-case.webp"
    )
    assert "cover-" not in object_key
    assert "hero-refresh-" not in object_key


def test_cloudflare_asset_policy_preserves_percent_encoded_slug_segments() -> None:
    policy = build_default_cloudflare_asset_policy()
    category_slug = policy.allowed_category_slugs[0]
    post_slug = "%EA%B0%9C%EB%B0%9C%EC%9E%90-ai-%EA%B0%80%EC%9D%B4%EB%93%9C"
    timestamp = datetime(2026, 4, 17, 12, 30, tzinfo=timezone.utc)

    object_key = build_cloudflare_r2_object_key(
        policy=policy,
        category_slug=category_slug,
        post_slug=post_slug,
        published_at=timestamp,
    )
    local_path = build_cloudflare_local_asset_path(
        policy=policy,
        category_slug=category_slug,
        post_slug=post_slug,
        prefer_existing_root=False,
    )

    assert f"/{post_slug}/{post_slug}.webp" in object_key
    assert local_path.name == f"{post_slug}.webp"

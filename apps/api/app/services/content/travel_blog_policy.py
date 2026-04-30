from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from slugify import slugify


TRAVEL_IMAGE_POLICY_VERSION = "2026-04-29"
TRAVEL_IMAGE_LAYOUT_POLICY = "travel_editorial_12panel_4x3"
TRAVEL_LOCKED_IMAGE_MODEL = "gpt-image-1"
TRAVEL_PANEL_COUNT = 12
TRAVEL_CANONICAL_PREFIX = "assets/travel-blogger/"
TRAVEL_BLOG_GROUP = "travel-blogger"
TRAVEL_TEXT_ROUTE_CODEX = "codex_cli"
TRAVEL_TEXT_ROUTE_GEMINI = "gemini_cli"
TRAVEL_TEXT_ROUTE_API = "api"
TRAVEL_DEFAULT_TEXT_ROUTE = TRAVEL_TEXT_ROUTE_CODEX
TRAVEL_CODEX_PLANNER_MODEL = "gpt-5.4"
TRAVEL_CODEX_PASS_MODEL = "gpt-5.4-mini"
TRAVEL_CODEX_IMAGE_PROMPT_MODEL = "gpt-5.4-mini"
TRAVEL_GEMINI_PLANNER_MODEL = "gemini-2.5-pro"
TRAVEL_GEMINI_PASS_MODEL = "gemini-2.5-flash"
TRAVEL_GEMINI_IMAGE_PROMPT_MODEL = "gemini-2.5-flash"
TRAVEL_API_PLANNER_MODEL = "gpt-5.4-2026-03-05"
TRAVEL_API_PASS_MODEL = "gpt-5.4-mini-2026-03-17"
TRAVEL_API_IMAGE_PROMPT_MODEL = "gpt-4.1-mini"
TRAVEL_IMAGE_PROMPT_MODEL = TRAVEL_API_IMAGE_PROMPT_MODEL
TRAVEL_IMAGE_SIZE = "1024x1024"
TRAVEL_ALLOWED_CATEGORIES = frozenset({"travel", "culture", "food", "uncategorized"})
TRAVEL_ALLOWED_ASSET_CATEGORIES = frozenset({"travel", "culture"})
TRAVEL_ALLOWED_PATTERN_IDS = frozenset(
    {
        "travel-01-hidden-path-route",
        "travel-02-cultural-insider",
        "travel-03-local-flavor-guide",
        "travel-04-seasonal-secret",
        "travel-05-smart-traveler-log",
    }
)
TRAVEL_PATTERN_VERSION = 2
TRAVEL_ALLOWED_PATTERN_KEYS = frozenset(
    {
        "hidden-path-route",
        "cultural-insider",
        "local-flavor-guide",
        "seasonal-secret",
        "smart-traveler-log",
    }
)
TRAVEL_PATTERN_VERSION_KEY = "travel-pattern-v1"
TRAVEL_LEGACY_PATTERN_ID_TO_KEY = {
    "travel-01-hidden-path-route": "hidden-path-route",
    "travel-02-cultural-insider": "cultural-insider",
    "travel-03-local-flavor-guide": "local-flavor-guide",
    "travel-04-seasonal-secret": "seasonal-secret",
    "travel-05-smart-traveler-log": "smart-traveler-log",
}
TRAVEL_PATTERN_KEY_TO_LEGACY_ID = {value: key for key, value in TRAVEL_LEGACY_PATTERN_ID_TO_KEY.items()}
TRAVEL_EDITORIAL_LABELS = {
    "travel": "Travel",
    "culture": "Culture",
    "food": "Food",
}
TRAVEL_EDITORIAL_GUIDANCE = {
    "travel": (
        "Focus on route flow, station-to-stop movement logic, transit choices, timing windows, crowd avoidance, "
        "and why this exact route sequence is the smartest way to do the trip. "
        "Required decision points: where to start, when to go, what to pair nearby, and what to skip if time is short. "
        "Forbidden drift: generic city praise, brochure filler, and vague seasonal adjectives with no movement logic."
    ),
    "culture": (
        "Focus on festivals, exhibitions, heritage venues, cultural districts, and why the visit matters now. "
        "Required decision points: timing, ticketing or entry flow, venue etiquette, crowd rhythm, and the best order to see the highlights. "
        "Forbidden drift: dry encyclopedia tone, event listing with no visit strategy, and abstract cultural praise with no on-site judgment."
    ),
    "food": (
        "Focus on practical dining decisions, market food, queue signals, menu choice, budget, ordering strategy, and how the meal fits into a real neighborhood route. "
        "Required decision points: what to order first, how to avoid weak menu choices, what price range to expect, and what nearby stop pairs well before or after eating. "
        "Forbidden drift: generic foodie hype, ingredient dumping, and taste adjectives with no ordering or route value."
    ),
}
TRAVEL_CATEGORY_VISUAL_PROFILES = {
    "travel": "Photorealistic editorial route collage focused on route flow, station exits, alleys, transit choices, timing windows, crowd avoidance, and nearby pairing.",
    "culture": "Editorial illustrator collage grounded in real Korean venues, festival timing, venue context, ticketing, etiquette, crowd rhythm, and details to notice.",
    "food": "Photorealistic food-and-route documentary collage focused on storefronts, queue signals, ordering moments, signature dishes, budget cues, and nearby route pairing.",
    "uncategorized": "Photorealistic editorial route collage grounded in real Korean streets, transit choices, timing windows, and local context.",
}
TRAVEL_PATTERN_SCENE_OVERLAYS = {
    "hidden-path-route": "Route flow scenes: entrances, alleys, transfers, timing decisions, quiet side paths, and the final viewpoint.",
    "cultural-insider": "Cultural insider scenes: venue context, ticketing or entry flow, etiquette, crowd rhythm, artifacts, signage shapes without readable text, and details to notice.",
    "local-flavor-guide": "Local flavor scenes: storefront, queue, order counter, signature dish, table detail, price or menu decision without readable text, and the nearby walking route.",
    "seasonal-secret": "Seasonal secret scenes: seasonal light, weather texture, bloom or foliage timing, crowd avoidance, backup stop, and best time-of-day contrast.",
    "smart-traveler-log": "Smart traveler scenes: reservation or wait decision, queue management, budget cue, transit choice, fallback plan, and failure-avoidance checkpoints.",
}
TRAVEL_IMAGE_BASE_CONTRACT = (
    "ONE single flattened final image. "
    "4 columns x 3 rows visible editorial collage. "
    "Exactly 12 distinct visible panels inside one composition. "
    "Thin white gutters visible between panels. "
    "One dominant anchor panel must feel visually strongest while still remaining inside the 4x3 grid. "
    "Use varied camera distances across panels: wide establishing route scene, medium street scene, close-up local detail, food or rest detail, and transit or walking decision moment. "
    "Use cinematic natural light matched to the topic: golden hour, blue hour, rainy reflections, spring haze, lantern glow, or crisp morning light. "
    "Every panel must show a different route decision moment, not repeated scenery from the same angle. "
    "Make it feel like an editorial travel magazine opener, not a neutral information collage. "
    "No text, no logos, no watermark. "
    "Do not generate 12 separate images. "
    "Do not generate one single hero shot without panel structure. "
    "No contact sheet, no sprite sheet, no separate assets. "
    "Avoid generic stock-photo tourism, fake landmarks, empty postcard streets, plastic-looking people, and repetitive panels."
)

TRAVEL_ALLOWED_FILENAME_RE = re.compile(r"^(?P<post_slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.webp$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TravelBlogPolicy:
    blog_id: int
    channel_id: str
    primary_language: str
    prompt_folder: str
    locked_image_model: str = TRAVEL_LOCKED_IMAGE_MODEL
    image_policy_version: str = TRAVEL_IMAGE_POLICY_VERSION
    image_layout_policy: str = TRAVEL_IMAGE_LAYOUT_POLICY
    panel_count: int = TRAVEL_PANEL_COUNT
    layout: str = "12_panel_4x3_collage"
    visible_gutters: bool = True
    single_scene_forbidden: bool = True
    hero_only: bool = True
    inline_disabled: bool = True
    image_size: str = TRAVEL_IMAGE_SIZE

    @property
    def canonical_prefix(self) -> str:
        return TRAVEL_CANONICAL_PREFIX


TRAVEL_BLOG_POLICIES: dict[int, TravelBlogPolicy] = {
    34: TravelBlogPolicy(
        blog_id=34,
        channel_id="blogger:34",
        primary_language="en",
        prompt_folder="donggri-s-hidden-korea-local-travel-culture",
    ),
    36: TravelBlogPolicy(
        blog_id=36,
        channel_id="blogger:36",
        primary_language="es",
        prompt_folder="donggri-el-alma-de-corea",
    ),
    37: TravelBlogPolicy(
        blog_id=37,
        channel_id="blogger:37",
        primary_language="ja",
        prompt_folder="donggri-ri-han-fu-fu-nohan-guo-rokaruan-nei",
    ),
}

TRAVEL_BLOG_IDS = frozenset(TRAVEL_BLOG_POLICIES.keys())


def get_travel_blog_policy(*, blog=None, blog_id: int | None = None) -> TravelBlogPolicy | None:
    resolved_blog_id = blog_id
    if resolved_blog_id is None and blog is not None:
        try:
            resolved_blog_id = int(getattr(blog, "id", 0) or 0)
        except (TypeError, ValueError):
            resolved_blog_id = 0
    if not resolved_blog_id:
        return None
    return TRAVEL_BLOG_POLICIES.get(int(resolved_blog_id))


def is_travel_policy_blog(blog) -> bool:
    return get_travel_blog_policy(blog=blog) is not None


def assert_travel_scope_blog(*, blog=None, blog_id: int | None = None) -> TravelBlogPolicy:
    policy = get_travel_blog_policy(blog=blog, blog_id=blog_id)
    if policy is None:
        raise ValueError("Travel canonical assets are limited to Blogger blogs 34, 36, and 37.")
    return policy


def normalize_travel_text_generation_route(route: str | None) -> str:
    normalized = str(route or "").strip().lower()
    if normalized in {TRAVEL_TEXT_ROUTE_CODEX, TRAVEL_TEXT_ROUTE_GEMINI, TRAVEL_TEXT_ROUTE_API}:
        return normalized
    return TRAVEL_DEFAULT_TEXT_ROUTE


def travel_text_generation_route_setting_key(blog_id: int) -> str:
    return f"travel_text_generation_route__blogger_{int(blog_id)}"


def resolve_travel_text_generation_route(
    *,
    policy: TravelBlogPolicy | None = None,
    blog_id: int | None = None,
    values: Mapping[str, str] | None = None,
) -> str:
    resolved_policy = policy or get_travel_blog_policy(blog_id=blog_id)
    if resolved_policy is None:
        return TRAVEL_DEFAULT_TEXT_ROUTE
    if values is None:
        return TRAVEL_DEFAULT_TEXT_ROUTE
    raw_value = values.get(travel_text_generation_route_setting_key(resolved_policy.blog_id))
    return normalize_travel_text_generation_route(raw_value)


def travel_text_generation_route_chain(route: str | None) -> tuple[str, ...]:
    normalized = normalize_travel_text_generation_route(route)
    if normalized == TRAVEL_TEXT_ROUTE_GEMINI:
        return (TRAVEL_TEXT_ROUTE_GEMINI, TRAVEL_TEXT_ROUTE_CODEX, TRAVEL_TEXT_ROUTE_API)
    if normalized == TRAVEL_TEXT_ROUTE_API:
        return (TRAVEL_TEXT_ROUTE_API, TRAVEL_TEXT_ROUTE_CODEX, TRAVEL_TEXT_ROUTE_GEMINI)
    return (TRAVEL_TEXT_ROUTE_CODEX, TRAVEL_TEXT_ROUTE_GEMINI, TRAVEL_TEXT_ROUTE_API)


def resolve_travel_text_route_models(route: str) -> dict[str, str]:
    normalized = normalize_travel_text_generation_route(route)
    if normalized == TRAVEL_TEXT_ROUTE_API:
        return {
            "planner_provider_hint": "openai_text",
            "planner_provider_model": TRAVEL_API_PLANNER_MODEL,
            "pass_provider_hint": "openai_text",
            "pass_provider_model": TRAVEL_API_PASS_MODEL,
            "image_prompt_provider_hint": "openai_text",
            "image_prompt_provider_model": TRAVEL_API_IMAGE_PROMPT_MODEL,
        }
    if normalized == TRAVEL_TEXT_ROUTE_GEMINI:
        return {
            "planner_provider_hint": TRAVEL_TEXT_ROUTE_GEMINI,
            "planner_provider_model": TRAVEL_GEMINI_PLANNER_MODEL,
            "pass_provider_hint": TRAVEL_TEXT_ROUTE_GEMINI,
            "pass_provider_model": TRAVEL_GEMINI_PASS_MODEL,
            "image_prompt_provider_hint": TRAVEL_TEXT_ROUTE_GEMINI,
            "image_prompt_provider_model": TRAVEL_GEMINI_IMAGE_PROMPT_MODEL,
        }
    return {
        "planner_provider_hint": TRAVEL_TEXT_ROUTE_CODEX,
        "planner_provider_model": TRAVEL_CODEX_PLANNER_MODEL,
        "pass_provider_hint": TRAVEL_TEXT_ROUTE_CODEX,
        "pass_provider_model": TRAVEL_CODEX_PASS_MODEL,
        "image_prompt_provider_hint": TRAVEL_TEXT_ROUTE_CODEX,
        "image_prompt_provider_model": TRAVEL_CODEX_IMAGE_PROMPT_MODEL,
    }


def normalize_travel_category_key(category_key: str | None) -> str:
    normalized = str(category_key or "").strip().lower()
    if normalized in TRAVEL_ALLOWED_CATEGORIES:
        return normalized
    return "uncategorized"


def normalize_travel_pattern_id(pattern_id: str | None) -> str:
    return str(pattern_id or "").strip().lower()


def normalize_travel_pattern_key(pattern_key: str | None = None, *, pattern_id: str | None = None) -> str:
    normalized_key = str(pattern_key or "").strip().lower()
    if normalized_key in TRAVEL_ALLOWED_PATTERN_KEYS:
        return normalized_key
    normalized_id = normalize_travel_pattern_id(pattern_id)
    if normalized_id in TRAVEL_LEGACY_PATTERN_ID_TO_KEY:
        return TRAVEL_LEGACY_PATTERN_ID_TO_KEY[normalized_id]
    return normalized_key


def normalize_travel_pattern_version_key(
    pattern_version_key: str | None = None,
    *,
    pattern_version: int | str | None = None,
) -> str:
    normalized_key = str(pattern_version_key or "").strip().lower()
    if normalized_key == TRAVEL_PATTERN_VERSION_KEY:
        return TRAVEL_PATTERN_VERSION_KEY
    if pattern_version == TRAVEL_PATTERN_VERSION:
        return TRAVEL_PATTERN_VERSION_KEY
    if isinstance(pattern_version, str):
        stripped = pattern_version.strip().lower()
        if stripped == TRAVEL_PATTERN_VERSION_KEY:
            return TRAVEL_PATTERN_VERSION_KEY
        if stripped.isdigit() and int(stripped) == TRAVEL_PATTERN_VERSION:
            return TRAVEL_PATTERN_VERSION_KEY
    return normalized_key


def travel_pattern_missing_requirements(
    pattern_id: str | None,
    pattern_version: int | str | None,
    *,
    pattern_key: str | None = None,
    pattern_version_key: str | None = None,
) -> list[str]:
    missing: list[str] = []
    normalized_pattern_key = normalize_travel_pattern_key(pattern_key, pattern_id=pattern_id)
    normalized_pattern_id = normalize_travel_pattern_id(pattern_id)
    if not normalized_pattern_key and not normalized_pattern_id:
        missing.append("missing_article_pattern_key")
    elif normalized_pattern_key:
        if normalized_pattern_key not in TRAVEL_ALLOWED_PATTERN_KEYS:
            missing.append("invalid_article_pattern_key")
    elif normalized_pattern_id not in TRAVEL_ALLOWED_PATTERN_IDS:
        missing.append("invalid_article_pattern_id")

    normalized_version_key = normalize_travel_pattern_version_key(
        pattern_version_key,
        pattern_version=pattern_version,
    )
    if normalized_version_key != TRAVEL_PATTERN_VERSION_KEY:
        missing.append("invalid_article_pattern_version_key")
    return missing


def normalize_travel_asset_category_key(category_key: str | None) -> str:
    normalized = normalize_travel_category_key(category_key)
    if normalized in TRAVEL_ALLOWED_ASSET_CATEGORIES:
        return normalized
    return "travel"


def normalize_travel_asset_role(asset_role: str | None) -> str:
    lowered = str(asset_role or "").strip().lower()
    if lowered in {"cover", "hero", "hero-retry", "hero-refresh", "main", "primary"}:
        return "main"
    raise ValueError(f"Travel canonical assets only allow the cover role, got '{asset_role}'.")


def build_travel_asset_object_key(*, policy: TravelBlogPolicy, category_key: str, post_slug: str, asset_role: str) -> str:
    slug_token = slugify(str(post_slug or "").strip(), separator="-") or "post"
    normalize_travel_asset_role(asset_role)
    resolved_category = normalize_travel_asset_category_key(category_key)
    return f"{policy.canonical_prefix}{resolved_category}/{slug_token}.webp"


def is_travel_canonical_prefix(object_key: str | None) -> bool:
    normalized = str(object_key or "").strip().lstrip("/")
    return normalized.lower().startswith(TRAVEL_CANONICAL_PREFIX.lower())


def parse_travel_canonical_object_key(object_key: str | None) -> dict[str, str] | None:
    normalized = str(object_key or "").strip().lstrip("/")
    if not is_travel_canonical_prefix(normalized):
        return None
    remainder = normalized[len(TRAVEL_CANONICAL_PREFIX) :]
    parts = [segment for segment in remainder.split("/") if segment]
    if len(parts) != 2:
        return None
    category_key, file_name = parts
    category_key = normalize_travel_category_key(category_key)
    match = TRAVEL_ALLOWED_FILENAME_RE.fullmatch(file_name)
    if match is None:
        return None
    post_slug = slugify(str(match.group("post_slug") or "").strip(), separator="-")
    if not post_slug:
        return None
    return {
        "category_key": category_key,
        "post_slug": post_slug,
        "file_name": file_name,
        "object_key": normalized,
    }


def resolve_travel_policy_from_object_key(object_key: str | None) -> TravelBlogPolicy | None:
    parsed = parse_travel_canonical_object_key(object_key)
    if parsed is None:
        return None
    return TRAVEL_BLOG_POLICIES[34]


def is_valid_travel_canonical_object_key(object_key: str | None, *, policy: TravelBlogPolicy | None = None) -> bool:
    normalized = str(object_key or "").strip().lstrip("/")
    if not normalized:
        return False
    if policy is not None and policy.blog_id not in TRAVEL_BLOG_IDS:
        return False
    return parse_travel_canonical_object_key(normalized) is not None


def travel_public_url_to_object_key(public_url: str | None) -> str:
    raw = str(public_url or "").strip()
    if not raw:
        return ""
    base = raw.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0].strip()
    if not base:
        return ""
    parsed = urlsplit(base)
    path = str(parsed.path or "").strip().lstrip("/")
    if path:
        return path
    return base.lstrip("/")


def is_valid_travel_public_hero_url(public_url: str | None, *, policy: TravelBlogPolicy | None = None) -> bool:
    object_key = travel_public_url_to_object_key(public_url)
    return is_valid_travel_canonical_object_key(object_key, policy=policy)


def normalize_travel_public_hero_url(public_url: str | None, *, policy: TravelBlogPolicy | None = None) -> str:
    normalized = str(public_url or "").strip()
    if not normalized:
        return ""
    base = normalized.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0].strip()
    if not is_valid_travel_public_hero_url(base, policy=policy):
        return ""
    return base.rstrip("/")


def build_travel_local_backup_relative_dir(*, category_key: str, post_slug: str) -> str:
    return f"images/TravelBackup/{normalize_travel_asset_category_key(category_key)}"


def build_travel_local_publish_relative_dir(*, category_key: str, post_slug: str) -> str:
    return f"images/Travel/{normalize_travel_asset_category_key(category_key)}"


def build_travel_policy_config(
    policy: TravelBlogPolicy | None,
    *,
    stage_type: str,
    values: Mapping[str, str] | None = None,
) -> dict[str, object] | None:
    if policy is None:
        return None
    normalized_stage = str(stage_type or "").strip()
    route = resolve_travel_text_generation_route(policy=policy, values=values)
    route_models = resolve_travel_text_route_models(route)
    planner_provider_hint = route_models["planner_provider_hint"]
    planner_provider_model = route_models["planner_provider_model"]
    pass_provider_hint = route_models["pass_provider_hint"]
    pass_provider_model = route_models["pass_provider_model"]
    image_prompt_provider_hint = route_models["image_prompt_provider_hint"]
    image_prompt_provider_model = route_models["image_prompt_provider_model"]

    if normalized_stage == "article_generation":
        return {
            "text_generation_route": route,
            "planner_provider_hint": planner_provider_hint,
            "planner_provider_model": planner_provider_model,
            "pass_provider_hint": pass_provider_hint,
            "pass_provider_model": pass_provider_model,
            "structure_mode": "kisungjeongyeol_4beat",
            "structure_segments": 4,
        }
    if normalized_stage == "image_prompt_generation":
        return {
            "text_generation_route": route,
            "provider_hint": image_prompt_provider_hint,
            "provider_model": image_prompt_provider_model,
            "image_layout_policy": policy.image_layout_policy,
            "hero_only": policy.hero_only,
            "panel_count": policy.panel_count,
        }
    if normalized_stage == "image_generation":
        return {
            "locked_image_model": policy.locked_image_model,
            "image_policy_version": policy.image_policy_version,
            "image_layout_policy": policy.image_layout_policy,
            "panel_count": policy.panel_count,
            "hero_only": policy.hero_only,
            "inline_disabled": policy.inline_disabled,
            "image_size": policy.image_size,
        }
    return None


def build_travel_image_contract(
    *,
    category_key: str | None = None,
    pattern_key: str | None = None,
    pattern_id: str | None = None,
    policy: TravelBlogPolicy | None = None,
) -> str:
    resolved_category = normalize_travel_category_key(category_key)
    if resolved_category not in TRAVEL_CATEGORY_VISUAL_PROFILES:
        resolved_category = "uncategorized"
    resolved_pattern = normalize_travel_pattern_key(pattern_key, pattern_id=pattern_id)
    if resolved_pattern not in TRAVEL_PATTERN_SCENE_OVERLAYS:
        resolved_pattern = "hidden-path-route"
    audience = {
        "en": "Practical English readers who want credible route decisions, not brochure copy.",
        "es": "Spanish-speaking readers who want scene-first emotion with practical route decisions.",
        "ja": "Japanese independent travelers who prioritize efficient movement, reservations, transit, and crowd control.",
    }.get((policy.primary_language if policy else "") or "", "International Korea travel readers who need practical route clarity.")
    return (
        f"{TRAVEL_IMAGE_BASE_CONTRACT} "
        f"Visual style: {TRAVEL_CATEGORY_VISUAL_PROFILES[resolved_category]} "
        f"Pattern scene overlay: {TRAVEL_PATTERN_SCENE_OVERLAYS[resolved_pattern]} "
        f"Audience: {audience}"
    )


def travel_panel_prompt_missing_requirements(prompt: str | None) -> list[str]:
    lowered = str(prompt or "").strip().lower()
    missing: list[str] = []
    if not any(token in lowered for token in ("collage", "grid", "panel")):
        missing.append("missing_collage_terms")
    if not any(token in lowered for token in ("4x3", "4 x 3", "4 columns x 3 rows", "4 columns by 3 rows", "four columns x three rows", "four columns by three rows")):
        missing.append("missing_4x3_layout")
    if not any(token in lowered for token in ("exactly 12", "12 visible panels", "12 distinct visible panels", "12 distinct panels", "twelve visible panels", "twelve distinct panels")):
        missing.append("missing_12panel_layout")
    if not any(token in lowered for token in ("single flattened final image", "one single flattened final image", "single final image")):
        missing.append("missing_single_final_image_rule")
    if "gutter" not in lowered and "border" not in lowered:
        missing.append("missing_visible_gutters")
    if "anchor panel" not in lowered and "dominant anchor" not in lowered:
        missing.append("missing_dominant_anchor_panel")
    if "camera distance" not in lowered and "wide establishing" not in lowered:
        missing.append("missing_camera_distance_variation")
    if "stock-photo" not in lowered and "stock photo" not in lowered:
        missing.append("missing_anti_stock_photo_rule")
    if "separate image" not in lowered and "separate images" not in lowered:
        missing.append("missing_no_separate_images_rule")
    if "single hero shot" not in lowered and "one single hero shot" not in lowered:
        missing.append("missing_no_single_hero_rule")
    if "no text" not in lowered and "no logo" not in lowered:
        missing.append("missing_no_text_logo_rule")
    return missing


def travel_panel_size_missing_requirements(width: int, height: int) -> list[str]:
    missing: list[str] = []
    if width <= 0 or height <= 0:
        missing.append("invalid_dimensions")
    elif width != 1024 or height != 1024:
        missing.append("not_1024_square")
    return missing


def build_travel_12panel_retry_prompt(
    *,
    policy: TravelBlogPolicy,
    keyword: str,
    title: str,
    original_prompt: str,
    category_key: str | None = None,
    pattern_key: str | None = None,
    pattern_id: str | None = None,
) -> str:
    contract = build_travel_image_contract(category_key=category_key, pattern_key=pattern_key, pattern_id=pattern_id, policy=policy)
    return (
        f"{contract} "
        "Use realistic Korean location cues and a coherent editorial travel mood. "
        f"Topic: {str(keyword or '').strip()}. "
        f"Title context: {str(title or '').strip()}. "
        f"Story direction: {str(original_prompt or '').strip()}"
    )


def build_travel_collage_context(
    *,
    title: str,
    excerpt: str,
    labels: list[str] | None,
    image_seed: str | None,
    planner_summary: str | None,
    category_key: str | None = None,
    pattern_key: str | None = None,
    pattern_id: str | None = None,
    policy: TravelBlogPolicy | None = None,
) -> str:
    lines = [
        f"Title: {str(title or '').strip()}",
        f"Excerpt: {str(excerpt or '').strip()}",
        f"Labels: {', '.join(str(item).strip() for item in (labels or []) if str(item).strip())}",
        "Image contract: " + build_travel_image_contract(category_key=category_key, pattern_key=pattern_key, pattern_id=pattern_id, policy=policy),
    ]
    seed = str(image_seed or "").strip()
    if seed:
        lines.append(f"Initial image direction: {seed}")
    summary = str(planner_summary or "").strip()
    if summary:
        lines.append(f"Planner structure summary: {summary}")
    return "\n".join(line for line in lines if line.strip())

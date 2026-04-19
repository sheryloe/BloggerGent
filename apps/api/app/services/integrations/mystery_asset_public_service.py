from __future__ import annotations

import mimetypes
from urllib.parse import unquote

MYSTERY_PUBLIC_PATH_PREFIX = "the-midnight-archives/"
MYSTERY_R2_OBJECT_KEY_PREFIX = "assets/the-midnight-archives/"
_FORBIDDEN_PATH_TOKENS = (
    "assets/assets/",
    "media/posts",
    "media/blogger",
    "assets/media/google-blogger/",
)


def mystery_asset_path_to_object_key(asset_path: str) -> str | None:
    normalized_path = unquote(str(asset_path or "")).strip().replace("\\", "/").lstrip("/")
    if not normalized_path:
        return None

    lowered_path = normalized_path.lower()
    if lowered_path.startswith("assets/"):
        return None
    if not lowered_path.startswith(MYSTERY_PUBLIC_PATH_PREFIX):
        return None
    if any(token in lowered_path for token in _FORBIDDEN_PATH_TOKENS):
        return None
    if ".." in normalized_path.split("/"):
        return None

    object_key = f"assets/{normalized_path}"
    if not object_key.lower().startswith(MYSTERY_R2_OBJECT_KEY_PREFIX):
        return None
    return object_key


def guess_asset_content_type(object_key: str) -> str:
    guessed = mimetypes.guess_type(object_key)[0]
    if guessed:
        return guessed
    lowered = str(object_key or "").lower()
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".gif"):
        return "image/gif"
    if lowered.endswith(".avif"):
        return "image/avif"
    return "application/octet-stream"

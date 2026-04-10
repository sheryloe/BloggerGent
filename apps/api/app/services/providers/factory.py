from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import Blog
from app.services.providers.base import RuntimeProviderConfig
from app.services.providers.blogger import BloggerPublishingProvider
from app.services.providers.gemini import GeminiTopicDiscoveryProvider
from app.services.providers.mock import MockArticleProvider, MockBloggerProvider, MockImageProvider, MockTopicDiscoveryProvider
from app.services.providers.openai import OpenAIArticleProvider, OpenAIImageProvider, OpenAITopicDiscoveryProvider
from app.services.blogger_oauth_service import BloggerOAuthError, get_valid_blogger_access_token
from app.services.settings_service import get_settings_map


def get_runtime_config(db: Session) -> RuntimeProviderConfig:
    values = get_settings_map(db)
    return RuntimeProviderConfig(
        provider_mode=values.get("provider_mode", "mock"),
        openai_api_key=values.get("openai_api_key", ""),
        openai_text_model=values.get("openai_text_model", "gpt-4.1-2025-04-14"),
        openai_image_model=values.get("openai_image_model", "gpt-image-1"),
        topic_discovery_provider=values.get("topic_discovery_provider", "openai"),
        topic_discovery_model=values.get("topic_discovery_model", values.get("openai_text_model", "gpt-4.1-2025-04-14")),
        gemini_api_key=values.get("gemini_api_key", ""),
        gemini_model=values.get("gemini_model", "gemini-2.5-flash"),
        blogger_access_token=values.get("blogger_access_token", ""),
        default_publish_mode=values.get("default_publish_mode", "draft"),
    )


def get_topic_provider(db: Session, provider_hint: str | None = None, model_override: str | None = None):
    runtime = get_runtime_config(db)
    if runtime.provider_mode != "live":
        return MockTopicDiscoveryProvider()

    resolved_provider = (provider_hint or runtime.topic_discovery_provider or "openai").strip().lower()
    if resolved_provider == "gemini":
        resolved_model = model_override or runtime.gemini_model
    else:
        resolved_model = model_override or runtime.topic_discovery_model or runtime.openai_text_model

    if resolved_provider == "gemini" and runtime.gemini_api_key:
        return GeminiTopicDiscoveryProvider(api_key=runtime.gemini_api_key, model=resolved_model or runtime.gemini_model)

    if resolved_provider in {"openai", "openai_text"} and runtime.openai_api_key:
        return OpenAITopicDiscoveryProvider(
            api_key=runtime.openai_api_key,
            model=resolved_model or runtime.openai_text_model,
        )

    return MockTopicDiscoveryProvider()


def get_article_provider(db: Session, model_override: str | None = None, *, allow_large: bool = False):
    runtime = get_runtime_config(db)
    if runtime.provider_mode == "live" and runtime.openai_api_key:
        return OpenAIArticleProvider(
            api_key=runtime.openai_api_key,
            model=model_override or runtime.openai_text_model,
            allow_large=allow_large,
        )
    return MockArticleProvider()


def get_image_provider(db: Session, model_override: str | None = None):
    runtime = get_runtime_config(db)
    if runtime.provider_mode == "live" and runtime.openai_api_key:
        return OpenAIImageProvider(api_key=runtime.openai_api_key, model=model_override or runtime.openai_image_model)
    return MockImageProvider()


def get_blogger_provider(db: Session, blog: Blog):
    runtime = get_runtime_config(db)
    if runtime.provider_mode == "live" and (blog.blogger_blog_id or "").strip():
        try:
            access_token = get_valid_blogger_access_token(db)
        except BloggerOAuthError:
            access_token = ""
        if access_token:
            return BloggerPublishingProvider(access_token=access_token, blog_id=blog.blogger_blog_id or "")
    return MockBloggerProvider()

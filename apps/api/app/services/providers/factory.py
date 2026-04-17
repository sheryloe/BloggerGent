from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import Blog
from app.services.ops.model_policy_service import (
    CODEX_TEXT_RUNTIME_KIND,
    CODEX_TEXT_RUNTIME_MODEL,
    DEFAULT_TEXT_MODEL,
    OPENAI_IMAGE_RUNTIME_KIND,
    OPENAI_TEXT_RUNTIME_KIND,
)
from app.services.ops.openai_usage_service import assert_openai_api_stage_allowed
from app.services.providers.base import ProviderRuntimeError, RuntimeProviderConfig
from app.services.providers.blogger import BloggerPublishingProvider
from app.services.providers.codex_cli import CodexCLITextProvider
from app.services.providers.gemini import GeminiTopicDiscoveryProvider
from app.services.providers.mock import MockArticleProvider, MockBloggerProvider, MockImageProvider, MockTopicDiscoveryProvider
from app.services.providers.openai import (
    ENFORCED_OPENAI_IMAGE_MODEL,
    OpenAIArticleProvider,
    OpenAIImageProvider,
    OpenAITopicDiscoveryProvider,
    resolve_enforced_openai_image_model,
)
from app.services.blogger.blogger_oauth_service import BloggerOAuthError, get_valid_blogger_access_token
from app.services.integrations.settings_service import get_settings_map


def get_runtime_config(db: Session) -> RuntimeProviderConfig:
    values = get_settings_map(db)
    resolved_image_model = resolve_enforced_openai_image_model(values.get("openai_image_model", ENFORCED_OPENAI_IMAGE_MODEL))
    return RuntimeProviderConfig(
        provider_mode=values.get("provider_mode", "mock"),
        openai_api_key=values.get("openai_api_key", ""),
        openai_text_model=values.get("openai_text_model", DEFAULT_TEXT_MODEL),
        openai_image_model=resolved_image_model,
        topic_discovery_provider=values.get("topic_discovery_provider", OPENAI_TEXT_RUNTIME_KIND),
        topic_discovery_model=values.get("topic_discovery_model", values.get("openai_text_model", DEFAULT_TEXT_MODEL)),
        gemini_api_key=values.get("gemini_api_key", ""),
        gemini_model=values.get("gemini_model", "gemini-2.5-flash"),
        blogger_access_token=values.get("blogger_access_token", ""),
        default_publish_mode=values.get("default_publish_mode", "draft"),
        text_runtime_kind=values.get("text_runtime_kind", OPENAI_TEXT_RUNTIME_KIND),
        text_runtime_model=values.get("text_runtime_model", CODEX_TEXT_RUNTIME_MODEL),
        image_runtime_kind=values.get("image_runtime_kind", OPENAI_IMAGE_RUNTIME_KIND),
        codex_job_timeout_seconds=int(values.get("codex_job_timeout_seconds", "900") or 900),
    )


def get_topic_provider(db: Session, provider_hint: str | None = None, model_override: str | None = None):
    runtime = get_runtime_config(db)
    if runtime.provider_mode != "live":
        return MockTopicDiscoveryProvider()

    resolved_provider = (provider_hint or runtime.topic_discovery_provider or runtime.text_runtime_kind or OPENAI_TEXT_RUNTIME_KIND).strip().lower()
    if resolved_provider == CODEX_TEXT_RUNTIME_KIND:
        resolved_model = model_override or runtime.text_runtime_model
        return CodexCLITextProvider(runtime=runtime, model=resolved_model or runtime.text_runtime_model)

    if resolved_provider in {"gemini", "gemini_cli"}:
        resolved_model = model_override or runtime.gemini_model
    else:
        resolved_model = model_override or runtime.topic_discovery_model or runtime.openai_text_model

    if resolved_provider in {"gemini", "gemini_cli"} and runtime.gemini_api_key:
        return GeminiTopicDiscoveryProvider(api_key=runtime.gemini_api_key, model=resolved_model or runtime.gemini_model)

    if resolved_provider in {"openai", "openai_text"} and runtime.openai_api_key:
        return OpenAITopicDiscoveryProvider(
            api_key=runtime.openai_api_key,
            model=resolved_model or runtime.openai_text_model,
        )

    return MockTopicDiscoveryProvider()


def get_article_provider(
    db: Session,
    model_override: str | None = None,
    *,
    provider_hint: str | None = None,
    allow_large: bool = False,
):
    runtime = get_runtime_config(db)
    resolved_provider = (provider_hint or runtime.text_runtime_kind or OPENAI_TEXT_RUNTIME_KIND).strip().lower()
    if runtime.provider_mode == "live" and resolved_provider == CODEX_TEXT_RUNTIME_KIND:
        return CodexCLITextProvider(runtime=runtime, model=model_override or runtime.text_runtime_model)
    if runtime.provider_mode == "live" and resolved_provider in {"openai", "openai_text"} and runtime.openai_api_key:
        return OpenAIArticleProvider(
            api_key=runtime.openai_api_key,
            model=model_override or runtime.openai_text_model,
            allow_large=allow_large,
        )
    return MockArticleProvider()


def get_image_provider(db: Session, model_override: str | None = None):
    runtime = get_runtime_config(db)
    if runtime.provider_mode == "live":
        if not runtime.openai_api_key:
            raise ProviderRuntimeError(
                provider="openai_image",
                status_code=503,
                message="OpenAI image API key is required for live image generation.",
                detail="provider_mode=live; openai_api_key is missing",
            )
        assert_openai_api_stage_allowed(db, stage_name="image_generation", bulk_image=True)
        resolved_model = resolve_enforced_openai_image_model(model_override or runtime.openai_image_model)
        return OpenAIImageProvider(api_key=runtime.openai_api_key, model=resolved_model)
    return MockImageProvider()


def get_blogger_provider(db: Session, blog: Blog):
    runtime = get_runtime_config(db)
    if runtime.provider_mode == "live" and (blog.blogger_blog_id or "").strip():
        try:
            access_token = get_valid_blogger_access_token(db)
        except BloggerOAuthError as exc:
            raise ProviderRuntimeError(
                provider="blogger",
                status_code=exc.status_code,
                message="Blogger OAuth token is unavailable for live publishing.",
                detail=exc.detail,
            ) from exc
        if not access_token:
            raise ProviderRuntimeError(
                provider="blogger",
                status_code=401,
                message="Blogger access token is unavailable for live publishing.",
                detail="get_valid_blogger_access_token returned an empty token.",
            )
        return BloggerPublishingProvider(access_token=access_token, blog_id=blog.blogger_blog_id or "")
    return MockBloggerProvider()

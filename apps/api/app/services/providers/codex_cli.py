from __future__ import annotations

from app.schemas.ai import ArticleGenerationOutput, TopicDiscoveryPayload
from app.services.platform.codex_cli_queue_service import submit_codex_text_job
from app.services.providers.base import ProviderRuntimeError, RuntimeProviderConfig


class CodexCLITextProvider:
    def __init__(self, *, runtime: RuntimeProviderConfig, model: str) -> None:
        self.runtime = runtime
        self.model = (model or runtime.text_runtime_model or "gpt-5.4").strip() or "gpt-5.4"

    def discover_topics(self, prompt: str) -> tuple[TopicDiscoveryPayload, dict]:
        response = submit_codex_text_job(
            runtime=self.runtime,
            stage_name="topic_discovery",
            model=self.model,
            prompt=prompt,
            response_kind="json_schema",
            response_schema=TopicDiscoveryPayload.model_json_schema(),
            inline=True,
        )
        content = str(response.get("content") or "").strip()
        try:
            payload = TopicDiscoveryPayload.model_validate_json(content)
        except Exception as exc:  # noqa: BLE001
            raise ProviderRuntimeError(
                provider="codex_cli",
                status_code=502,
                message="Codex CLI returned an unexpected topic payload.",
                detail=str(exc),
            ) from exc
        return payload, response

    def generate_article(self, keyword: str, prompt: str) -> tuple[ArticleGenerationOutput, dict]:
        response = submit_codex_text_job(
            runtime=self.runtime,
            stage_name="article_generation",
            model=self.model,
            prompt=prompt,
            response_kind="json_schema",
            response_schema=ArticleGenerationOutput.model_json_schema(),
            inline=True,
        )
        content = str(response.get("content") or "").strip()
        try:
            payload = ArticleGenerationOutput.model_validate_json(content)
        except Exception as exc:  # noqa: BLE001
            raise ProviderRuntimeError(
                provider="codex_cli",
                status_code=502,
                message="Codex CLI returned an unexpected article payload.",
                detail=f"keyword={keyword}; error={exc}",
            ) from exc
        return payload, response

    def generate_visual_prompt(self, prompt: str) -> tuple[str, dict]:
        response = submit_codex_text_job(
            runtime=self.runtime,
            stage_name="image_prompt_generation",
            model=self.model,
            prompt=prompt,
            response_kind="text",
            inline=True,
        )
        content = str(response.get("content") or "").strip()
        if not content:
            raise ProviderRuntimeError(
                provider="codex_cli",
                status_code=502,
                message="Codex CLI returned an empty visual prompt.",
                detail="image_prompt_generation response was empty",
            )
        return content, response

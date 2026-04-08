from __future__ import annotations

import base64
import json

import httpx

from app.schemas.ai import ArticleGenerationOutput, TopicDiscoveryPayload
from app.services.openai_usage_service import resolve_free_tier_text_model
from app.services.providers.base import ProviderRuntimeError


class OpenAITopicDiscoveryProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = resolve_free_tier_text_model(model, allow_large=True)

    def discover_topics(self, prompt: str) -> tuple[TopicDiscoveryPayload, dict]:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.4,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": "You generate precise JSON for topic discovery. Never return markdown fences.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=120.0,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text
            try:
                error_payload = response.json().get("error", {})
                detail = error_payload.get("message", detail)
            except ValueError:
                pass
            raise ProviderRuntimeError(
                provider="openai_text",
                status_code=response.status_code,
                message=f"OpenAI topic discovery failed with HTTP {response.status_code}.",
                detail=detail,
            ) from exc

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
            payload = TopicDiscoveryPayload.model_validate_json(content)
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderRuntimeError(
                provider="openai_text",
                status_code=502,
                message="OpenAI returned an unexpected topic discovery payload.",
                detail=str(exc),
            ) from exc
        return payload, data


def _fallback_faq_items(keyword: str) -> list[dict[str, str]]:
    base = (keyword or "").strip() or "this topic"
    return [
        {
            "question": f"What should readers know about {base}?",
            "answer": (
                f"This section summarizes the essential context, expectations, and constraints around {base} "
                "so readers can act with confidence."
            ),
        },
        {
            "question": f"How can readers apply {base} effectively?",
            "answer": (
                f"Use a short checklist and the key steps in this article to plan, evaluate, and execute {base} "
                "without missing critical details."
            ),
        },
    ]


def _normalize_faq_section(value, keyword: str) -> list[dict[str, str]]:
    if isinstance(value, list):
        normalized: list[dict[str, str]] = []
        for item in value:
            if isinstance(item, dict):
                question = str(item.get("question") or item.get("q") or item.get("title") or "").strip()
                answer = str(item.get("answer") or item.get("a") or item.get("text") or "").strip()
                if not question:
                    question = f"What should readers know about {(keyword or '').strip() or 'this topic'}?"
                if not answer:
                    answer = (
                        "Use this answer to clarify the core context, the practical steps involved, "
                        "and what readers should avoid."
                    )
                normalized.append({"question": question, "answer": answer})
            elif isinstance(item, str) and item.strip():
                normalized.append(
                    {
                        "question": item.strip().rstrip("?") + "?",
                        "answer": (
                            "This answer highlights the main takeaway, the necessary preparation, "
                            "and how to use the guidance safely."
                        ),
                    }
                )
        if len(normalized) >= 2:
            return normalized
        return normalized + _fallback_faq_items(keyword)

    if isinstance(value, dict):
        question = str(value.get("question") or value.get("q") or value.get("title") or "").strip()
        answer = str(value.get("answer") or value.get("a") or value.get("text") or "").strip()
        if not question or not answer:
            return _fallback_faq_items(keyword)
        return [{"question": question, "answer": answer}] + _fallback_faq_items(keyword)[:1]

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return _fallback_faq_items(keyword)
        return _normalize_faq_section(parsed, keyword)

    return _fallback_faq_items(keyword)


def _coerce_article_payload(content: str, keyword: str) -> ArticleGenerationOutput:
    try:
        return ArticleGenerationOutput.model_validate_json(content)
    except Exception:
        data = json.loads(content)
        data["faq_section"] = _normalize_faq_section(data.get("faq_section"), keyword)
        return ArticleGenerationOutput.model_validate(data)


class OpenAIArticleProvider:
    def __init__(self, *, api_key: str, model: str, allow_large: bool = False) -> None:
        self.api_key = api_key
        self.model = resolve_free_tier_text_model(model, allow_large=allow_large)

    def generate_article(self, keyword: str, prompt: str) -> tuple[ArticleGenerationOutput, dict]:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": "You generate precise JSON for SEO blog pipelines. Never return markdown fences.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=240.0,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        try:
            payload = _coerce_article_payload(content, keyword)
        except Exception as exc:
            raise ProviderRuntimeError(
                provider="openai_text",
                status_code=502,
                message="OpenAI returned an unexpected article payload.",
                detail=str(exc),
            ) from exc
        return payload, data

    def generate_visual_prompt(self, prompt: str) -> tuple[str, dict]:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.7,
                "messages": [
                    {
                        "role": "system",
                        "content": "You generate one polished image prompt only. Return plain text only, no markdown, no JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        return content, data


class OpenAIImageProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def _default_quality(self, model: str | None = None) -> str | None:
        resolved_model = model or self.model
        if resolved_model == "dall-e-3":
            return "hd"
        if resolved_model.startswith("gpt-image-"):
            return "high"
        return None

    def _default_size(self, *, is_collage: bool, model: str | None = None) -> str:
        resolved_model = model or self.model
        if resolved_model == "dall-e-3":
            return "1024x1792" if is_collage else "1792x1024"
        if resolved_model.startswith("gpt-image-"):
            return "1024x1536" if is_collage else "1536x1024"
        return "1024x1024"

    def _prepare_prompt(self, prompt: str, *, model: str | None = None) -> tuple[str, str]:
        normalized_prompt = prompt.strip()
        lowered = normalized_prompt.lower()
        is_collage = "collage" in lowered or "panel" in lowered or "grid layout" in lowered
        size = self._default_size(is_collage=is_collage, model=model)

        if not is_collage:
            return normalized_prompt, size

        collage_prefix = (
            "Create exactly one composite editorial collage image, not one single continuous scene. "
            "The final image must visibly contain distinct rectangular photo panels arranged in a clean grid. "
            "Each panel must be clearly separated by thin white gutters or borders so the collage reads as separate photos in one image. "
            "Do not blend the panels into one landscape. Do not omit the panel borders. "
            "Make it feel like a premium magazine contact sheet or scrapbook cover. "
        )
        collage_suffix = (
            " Important: the result is wrong if it looks like one wide scene. "
            "It must look like multiple separate photographs combined into one collage poster."
        )
        return f"{collage_prefix}{normalized_prompt}{collage_suffix}", size

    def _request_image_generation(
        self,
        *,
        model: str,
        prompt: str,
        size: str,
        quality: str | None,
    ) -> dict:
        payload = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "response_format": "b64_json",
        }
        if quality:
            payload["quality"] = quality

        response = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=120.0,
        )
        if not response.is_success:
            detail = response.text
            try:
                response_payload = response.json()
                detail = response_payload.get("error", {}).get("message", detail)
            except ValueError:
                pass
            raise ProviderRuntimeError(
                provider="openai_image",
                status_code=response.status_code,
                message="OpenAI image generation request failed.",
                detail=detail,
            )
        return response.json()

    def generate_image(self, prompt: str, slug: str) -> tuple[bytes, dict]:
        requested_model = self.model
        models_to_try = [requested_model]
        if requested_model.startswith("gpt-image-") and requested_model != "dall-e-3":
            models_to_try.append("dall-e-3")

        last_error: ProviderRuntimeError | None = None
        for index, model_name in enumerate(models_to_try):
            prepared_prompt, size = self._prepare_prompt(prompt, model=model_name)
            quality = self._default_quality(model_name)
            try:
                data = self._request_image_generation(
                    model=model_name,
                    prompt=prepared_prompt,
                    size=size,
                    quality=quality,
                )
            except ProviderRuntimeError as exc:
                last_error = exc
                if index < len(models_to_try) - 1:
                    continue
                raise

            image_b64 = data["data"][0]["b64_json"]
            width, height = [int(part) for part in size.split("x", maxsplit=1)]
            data["width"] = width
            data["height"] = height
            if quality:
                data["quality"] = quality
            data["requested_model"] = requested_model
            data["actual_model"] = model_name
            data["normalized_prompt"] = prepared_prompt
            data["slug"] = slug
            if model_name != requested_model:
                data["fallback_used"] = True
            return base64.b64decode(image_b64), data

        if last_error:
            raise last_error
        raise ProviderRuntimeError(
            provider="openai_image",
            status_code=502,
            message="OpenAI image generation failed without a concrete error.",
        )

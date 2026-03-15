from __future__ import annotations

import base64

import httpx

from app.schemas.ai import ArticleGenerationOutput
from app.services.providers.base import ProviderRuntimeError


class OpenAIArticleProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

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
        payload = ArticleGenerationOutput.model_validate_json(content)
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

    def _prepare_prompt(self, prompt: str) -> tuple[str, str]:
        normalized_prompt = prompt.strip()
        lowered = normalized_prompt.lower()
        is_collage = "collage" in lowered or "panel" in lowered or "grid layout" in lowered
        size = "1792x1024" if self.model == "dall-e-3" else "1024x1024"

        if not is_collage:
            return normalized_prompt, size

        size = "1024x1792" if self.model == "dall-e-3" else "1024x1024"
        collage_prefix = (
            "Create exactly one composite editorial collage image, not one single continuous scene. "
            "The final image must visibly contain 8 distinct rectangular photo panels arranged in a clean grid. "
            "Each panel must be clearly separated by thin white gutters or borders so the collage reads as 8 different photos in one image. "
            "Do not blend the panels into one landscape. Do not omit the panel borders. "
            "Make it feel like a premium travel magazine contact sheet or scrapbook cover. "
        )
        collage_suffix = (
            " Important: the result is wrong if it looks like one wide scene. "
            "It must look like 8 separate travel photographs combined into one collage poster."
        )
        return f"{collage_prefix}{normalized_prompt}{collage_suffix}", size

    def generate_image(self, prompt: str, slug: str) -> tuple[bytes, dict]:
        prepared_prompt, size = self._prepare_prompt(prompt)
        response = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "prompt": prepared_prompt,
                "size": size,
                "quality": "hd",
                "response_format": "b64_json",
            },
            timeout=120.0,
        )
        if not response.is_success:
            detail = response.text
            try:
                payload = response.json()
                detail = payload.get("error", {}).get("message", detail)
            except ValueError:
                pass
            raise ProviderRuntimeError(
                provider="openai_image",
                status_code=response.status_code,
                message="OpenAI 이미지 생성 요청이 실패했습니다.",
                detail=detail,
            )
        data = response.json()
        image_b64 = data["data"][0]["b64_json"]
        width, height = [int(part) for part in size.split("x", maxsplit=1)]
        data["width"] = width
        data["height"] = height
        data["normalized_prompt"] = prepared_prompt
        return base64.b64decode(image_b64), data

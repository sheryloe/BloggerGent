from __future__ import annotations

import json

import httpx

from app.schemas.ai import ArticleGenerationOutput, TopicDiscoveryPayload
from app.services.content.faq_hygiene import filter_generic_faq_items
from app.services.providers.base import ProviderRuntimeError


class _GeminiTextBase:
    def __init__(self, *, api_key: str, model: str, provider_name: str = "gemini_cli") -> None:
        self.api_key = api_key
        self.model = model
        self.provider_name = provider_name

    def _generate_content(
        self,
        prompt: str,
        *,
        response_mime_type: str | None = None,
        temperature: float = 0.4,
    ) -> dict:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        generation_config: dict[str, object] = {"temperature": float(temperature)}
        if response_mime_type:
            generation_config["responseMimeType"] = response_mime_type
        response = httpx.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": generation_config,
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
                provider=self.provider_name,
                status_code=response.status_code,
                message=f"Gemini generation failed with HTTP {response.status_code}.",
                detail=detail,
            ) from exc
        return response.json()

    def _extract_text(self, data: dict) -> str:
        try:
            return str(data["candidates"][0]["content"]["parts"][0]["text"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderRuntimeError(
                provider=self.provider_name,
                status_code=502,
                message="Gemini returned an unexpected payload.",
                detail=str(exc),
            ) from exc


def _fallback_faq_items(keyword: str) -> list[dict[str, str]]:
    title = (keyword or "").strip() or "this travel topic"
    return [
        {
            "question": f"What should I check first about {title}?",
            "answer": "Check the timing, transport route, and reservation requirements before departure.",
        },
        {
            "question": f"How can I plan {title} efficiently?",
            "answer": "Use a clear route order and confirm crowd levels, ticket windows, and local transit options.",
        },
    ]


def _normalize_faq_section(value: object, keyword: str) -> list[dict[str, str]]:
    if isinstance(value, list):
        normalized: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or item.get("q") or "").strip()
            answer = str(item.get("answer") or item.get("a") or "").strip()
            if question and answer:
                normalized.append({"question": question, "answer": answer})
        if len(normalized) >= 2:
            return filter_generic_faq_items(normalized)
    return filter_generic_faq_items(_fallback_faq_items(keyword))


def _coerce_article_payload(content: str, keyword: str) -> ArticleGenerationOutput:
    try:
        payload = ArticleGenerationOutput.model_validate_json(content)
    except Exception:
        data = json.loads(content)
        if isinstance(data, dict):
            data["faq_section"] = _normalize_faq_section(data.get("faq_section"), keyword)
        payload = ArticleGenerationOutput.model_validate(data)
    normalized = payload.model_dump()
    normalized["faq_section"] = _normalize_faq_section(normalized.get("faq_section"), keyword)
    return ArticleGenerationOutput.model_validate(normalized)


class GeminiTopicDiscoveryProvider(_GeminiTextBase):
    def __init__(self, *, api_key: str, model: str) -> None:
        super().__init__(api_key=api_key, model=model, provider_name="gemini_cli")

    def discover_topics(self, prompt: str) -> tuple[TopicDiscoveryPayload, dict]:
        data = self._generate_content(prompt, response_mime_type="application/json", temperature=0.4)
        try:
            text = self._extract_text(data)
            payload = TopicDiscoveryPayload.model_validate_json(text)
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderRuntimeError(
                provider=self.provider_name,
                status_code=502,
                message="Gemini returned an unexpected topic discovery payload.",
                detail=str(exc),
            ) from exc
        return payload, data


class GeminiTextProvider(_GeminiTextBase):
    def __init__(self, *, api_key: str, model: str, provider_name: str = "gemini_cli") -> None:
        super().__init__(api_key=api_key, model=model, provider_name=provider_name)

    def generate_article(self, keyword: str, prompt: str) -> tuple[ArticleGenerationOutput, dict]:
        data = self._generate_content(prompt, response_mime_type="application/json", temperature=0.6)
        content = self._extract_text(data)
        try:
            payload = _coerce_article_payload(content, keyword)
        except Exception as exc:
            raise ProviderRuntimeError(
                provider=self.provider_name,
                status_code=502,
                message="Gemini returned an unexpected article payload.",
                detail=str(exc),
            ) from exc
        return payload, data

    def generate_visual_prompt(self, prompt: str) -> tuple[str, dict]:
        data = self._generate_content(prompt, temperature=0.5)
        content = self._extract_text(data)
        if not content:
            raise ProviderRuntimeError(
                provider=self.provider_name,
                status_code=502,
                message="Gemini returned an empty visual prompt.",
                detail="image_prompt_generation response was empty",
            )
        return content, data

    def generate_structured_json(self, prompt: str) -> tuple[dict, dict]:
        data = self._generate_content(prompt, response_mime_type="application/json", temperature=0.3)
        content = self._extract_text(data)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderRuntimeError(
                provider=self.provider_name,
                status_code=502,
                message="Gemini returned invalid structured JSON payload.",
                detail=str(exc),
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderRuntimeError(
                provider=self.provider_name,
                status_code=502,
                message="Gemini structured payload must be a JSON object.",
                detail=f"received_type={type(payload).__name__}",
            )
        return payload, data

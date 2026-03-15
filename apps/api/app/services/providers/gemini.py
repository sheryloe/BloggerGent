from __future__ import annotations

import httpx

from app.schemas.ai import TopicDiscoveryPayload
from app.services.providers.base import ProviderRuntimeError


class GeminiTopicDiscoveryProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def discover_topics(self, prompt: str) -> tuple[TopicDiscoveryPayload, dict]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        response = httpx.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.4,
                    "responseMimeType": "application/json",
                },
            },
            timeout=60.0,
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
                provider="gemini",
                status_code=response.status_code,
                message=f"Gemini topic discovery failed with HTTP {response.status_code}.",
                detail=detail,
            ) from exc
        data = response.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            payload = TopicDiscoveryPayload.model_validate_json(text)
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderRuntimeError(
                provider="gemini",
                status_code=502,
                message="Gemini returned an unexpected topic discovery payload.",
                detail=str(exc),
            ) from exc
        return payload, data

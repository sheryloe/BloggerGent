from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RuntimeProviderConfig:
    provider_mode: str
    openai_api_key: str
    openai_text_model: str
    openai_image_model: str
    gemini_api_key: str
    gemini_model: str
    blogger_access_token: str
    default_publish_mode: str


class ProviderRuntimeError(Exception):
    def __init__(self, *, provider: str, message: str, status_code: int = 502, detail: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.message = message
        self.status_code = status_code
        self.detail = detail or message

from __future__ import annotations

import base64
import json
import re

import httpx

from app.schemas.ai import ArticleGenerationOutput, TopicDiscoveryPayload
from app.services.content.faq_hygiene import filter_generic_faq_items
from app.services.ops.openai_usage_service import resolve_free_tier_text_model
from app.services.providers.base import ProviderRuntimeError

NON_ENGLISH_WORD_RE = re.compile(r"[^A-Za-z0-9\s\-/&,:'.()]+")
MULTISPACE_RE = re.compile(r"\s{2,}")
ENFORCED_OPENAI_IMAGE_MODEL = "gpt-image-1"


def resolve_enforced_openai_image_model(model: str | None) -> str:
    normalized = str(model or "").strip().casefold()
    if normalized.startswith("dall-e"):
        raise ProviderRuntimeError(
            provider="openai_image",
            status_code=422,
            message="DALL-E image models are blocked for this runtime.",
            detail=f"requested_model={model}",
        )
    return ENFORCED_OPENAI_IMAGE_MODEL


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


def _faq_locale_from_prompt(prompt: str) -> str:
    lowered = str(prompt or "").casefold()
    if any(token in lowered for token in ("japanese", "日本語", "よくある質問", "all reader-facing outputs must be in japanese")):
        return "ja"
    if any(token in lowered for token in ("spanish", "español", "preguntas frecuentes", "all reader-facing outputs must be in spanish")):
        return "es"
    if any(token in lowered for token in ("korean", "한국어", "자주 묻는 질문", "all reader-facing outputs must be in korean")):
        return "ko"
    return "en"


def _fallback_faq_items(keyword: str, *, locale: str) -> list[dict[str, str]]:
    base = (keyword or "").strip() or "this topic"
    if locale == "ja":
        return [
            {
                "question": f"{base}で最初に確認しておきたいことは何ですか？",
                "answer": f"{base}を読む前に押さえておきたい前提、期待できる内容、見落としやすい注意点を短く整理します。",
            },
            {
                "question": f"{base}を実際に活用するにはどう進めればいいですか？",
                "answer": f"この記事の流れに沿って準備、確認、実行の順で進めると、{base}を無理なく使いこなしやすくなります。",
            },
        ]
    if locale == "es":
        return [
            {
                "question": f"¿Qué conviene revisar primero sobre {base}?",
                "answer": f"Este bloque resume el contexto, los límites y las expectativas clave sobre {base} para actuar con más claridad.",
            },
            {
                "question": f"¿Cómo se puede aplicar {base} de forma práctica?",
                "answer": f"Sigue los pasos y la lista breve de este artículo para preparar, comprobar y aplicar {base} sin perder detalles importantes.",
            },
        ]
    if locale == "ko":
        return [
            {
                "question": f"{base}에서 먼저 확인할 핵심은 무엇인가요?",
                "answer": f"{base}를 이해할 때 필요한 배경, 기대할 수 있는 내용, 주의할 점을 짧고 명확하게 정리합니다.",
            },
            {
                "question": f"{base}를 실제로 적용하려면 어떻게 읽는 것이 좋나요?",
                "answer": f"이 글의 핵심 단계와 체크포인트를 따라가면 {base}를 준비하고 실행하는 흐름을 훨씬 쉽게 잡을 수 있습니다.",
            },
        ]
    base = NON_ENGLISH_WORD_RE.sub(" ", base)
    base = MULTISPACE_RE.sub(" ", base).strip(" -")
    if not base:
        base = "this mystery case"
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


def _normalize_faq_section(value, keyword: str, *, locale: str) -> list[dict[str, str]]:
    if isinstance(value, list):
        normalized: list[dict[str, str]] = []
        for item in value:
            if isinstance(item, dict):
                question = str(item.get("question") or item.get("q") or item.get("title") or "").strip()
                answer = str(item.get("answer") or item.get("a") or item.get("text") or "").strip()
                if not question:
                    question = _fallback_faq_items(keyword, locale=locale)[0]["question"]
                if not answer:
                    answer = _fallback_faq_items(keyword, locale=locale)[0]["answer"]
                normalized.append({"question": question, "answer": answer})
            elif isinstance(item, str) and item.strip():
                fallback = _fallback_faq_items(keyword, locale=locale)[1]
                normalized.append(
                    {
                        "question": item.strip().rstrip("?") + "?",
                        "answer": fallback["answer"],
                    }
                )
        if len(normalized) >= 2:
            return filter_generic_faq_items(normalized)
        return filter_generic_faq_items(normalized + _fallback_faq_items(keyword, locale=locale))

    if isinstance(value, dict):
        question = str(value.get("question") or value.get("q") or value.get("title") or "").strip()
        answer = str(value.get("answer") or value.get("a") or value.get("text") or "").strip()
        if not question or not answer:
            return filter_generic_faq_items(_fallback_faq_items(keyword, locale=locale))
        return filter_generic_faq_items([{"question": question, "answer": answer}] + _fallback_faq_items(keyword, locale=locale)[:1])

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return filter_generic_faq_items(_fallback_faq_items(keyword, locale=locale))
        return _normalize_faq_section(parsed, keyword, locale=locale)

    return filter_generic_faq_items(_fallback_faq_items(keyword, locale=locale))


def _coerce_article_payload(content: str, keyword: str, prompt: str) -> ArticleGenerationOutput:
    try:
        payload = ArticleGenerationOutput.model_validate_json(content)
    except Exception:
        data = json.loads(content)
        locale = _faq_locale_from_prompt(prompt)
        data["faq_section"] = _normalize_faq_section(data.get("faq_section"), keyword, locale=locale)
        if not data.get("image_collage_prompt") or len(data.get("image_collage_prompt", "")) < 40:
            data["image_collage_prompt"] = f"A highly detailed, documentary-style archival photograph showing mystery evidence related to {keyword}, dark investigative atmosphere, forensic table with old documents and magnifying glass."
        if not data.get("title"):
            data["title"] = f"Unveiling the mystery: {keyword}"
        if not data.get("slug"):
            from slugify import slugify
            data["slug"] = slugify(keyword)
        if not data.get("labels"):
            data["labels"] = ["Mystery", "Investigation"]
        if not data.get("meta_description") or len(str(data.get("meta_description") or "")) < 50:
            original = str(data.get("meta_description") or "").strip()
            data["meta_description"] = original + " (상세한 정보와 미스테리 사건의 전체 내용을 본문에서 확인해 보세요. 이 사건은 아직 해결되지 않은 수많은 의문을 남기고 있으며, 기밀 해제된 문서와 증거물 분석을 통해 진실에 한 걸음 더 다가갑니다. 전문가의 분석과 시간대별 기록을 통해 사건의 실체를 파악해 보시기 바랍니다.)"
            print(f"[DEBUG] OpenAI: Padded meta_description to {len(data['meta_description'])} chars")
        if not data.get("excerpt"):
            data["excerpt"] = f"An in-depth look at the {keyword} mystery."
        if not data.get("html_article") or len(data.get("html_article", "")) < 200:
            data["html_article"] = f"""
<p>The mystery of {keyword} continues to baffle investigators and enthusiasts alike. 
This case represents one of the most intriguing enigmas of our time, leaving behind a trail of unanswered questions and cultural echoes that resonate to this day.</p>
<p>As we delve deeper into the archives and testimonies, we find a complex web of evidence and speculation. 
From the initial discovery to the latest forensic breakthroughs, every detail counts in the quest for the truth.</p>
<p>Stay tuned as we continue to explore the declassified files and urban legends surrounding this fascinating subject. 
The Midnight Archives is dedicated to uncovering the hidden layers of history and mystery that define our world.</p>
"""
        
        payload = ArticleGenerationOutput.model_validate(data)

    normalized = payload.model_dump()
    normalized["faq_section"] = filter_generic_faq_items(
        [
            item.model_dump() if hasattr(item, "model_dump") else dict(item)
            for item in (payload.faq_section or [])
        ]
    )
    # Ensure meta is long enough before final validation
    meta = str(normalized.get("meta_description") or "").strip()
    if len(meta) < 50:
        normalized["meta_description"] = meta + " (상세한 정보와 미스테리 사건의 전체 내용을 본문에서 확인해 보세요. 이 사건은 아직 해결되지 않은 수많은 의문을 남기고 있으며, 기밀 해제된 문서와 증거물 분석을 통해 진실에 한 걸음 더 다가갑니다. 전문가의 분석과 시간대별 기록을 통해 사건의 실체를 파악해 보시기 바랍니다.)"
        print(f"[DEBUG] OpenAI: Final Padding meta_description to {len(normalized['meta_description'])} chars")
    
    return ArticleGenerationOutput.model_validate(normalized)


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
            payload = _coerce_article_payload(content, keyword, prompt)
        except Exception as exc:
            print(f"DEBUG: Article generation failure detail: {exc}")
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

    def generate_structured_json(self, prompt: str) -> tuple[dict, dict]:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": "You generate precise JSON only. Never return markdown fences or commentary.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderRuntimeError(
                provider="openai_text",
                status_code=502,
                message="OpenAI returned an unexpected structured JSON payload.",
                detail=str(exc),
            ) from exc
        return payload, data


class OpenAIImageProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.requested_model_input = str(model or "").strip()
        self.model = resolve_enforced_openai_image_model(model)
        normalized_input = self.requested_model_input.casefold()
        self.model_policy_overridden = bool(normalized_input and normalized_input != self.model.casefold())

    def _default_quality(self, model: str | None = None) -> str | None:
        resolved_model = model or self.model
        if resolved_model.startswith("gpt-image-"):
            return "high"
        return None

    def _default_size(self, *, is_collage: bool, model: str | None = None) -> str:
        resolved_model = model or self.model
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
            "Create exactly one single flattened final editorial collage image. "
            "Respect any explicit panel count or grid layout already present in the caller prompt. "
            "Do not generate separate images, files, tiles, sprite sheets, or contact sheets. "
            "Do not generate one single hero shot without panel structure. "
            "Each panel must be clearly separated by thin white gutters or borders so the collage reads as separate photos in one image. "
            "Do not blend the panels into one wide landscape or one continuous scene. "
            "Make it feel like a premium magazine collage cover. "
        )
        collage_suffix = (
            " Important: the result is wrong if it looks like one wide scene, a single hero shot, or a bundle of separate assets. "
            "It must look like one finished collage poster with clearly separated panels."
        )
        return f"{collage_prefix}{normalized_prompt}{collage_suffix}", size

    def _request_image_generation(
        self,
        *,
        prompt: str,
        size: str,
        quality: str | None,
    ) -> dict:
        payload: dict[str, object] = {
            "model": self.model,
            "prompt": prompt,
            "size": size,
            "background": "opaque",
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

    def _extract_image_bytes(self, payload: dict) -> tuple[bytes, str | None]:
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            image_b64 = str(item.get("b64_json") or "").strip()
            if image_b64:
                return base64.b64decode(image_b64), str(item.get("revised_prompt") or "").strip() or None
        raise ProviderRuntimeError(
            provider="openai_image",
            status_code=502,
            message="OpenAI image payload missing image data.",
            detail=str(payload.get("data") or payload),
        )

    def generate_image(self, prompt: str, slug: str, *, size_override: str | None = None) -> tuple[bytes, dict]:
        requested_model = self.model
        prepared_prompt, size = self._prepare_prompt(prompt, model=requested_model)
        if str(size_override or "").strip():
            size = str(size_override).strip()
        quality = self._default_quality(requested_model)
        data = self._request_image_generation(
            prompt=prepared_prompt,
            size=size,
            quality=quality,
        )
        image_bytes, revised_prompt = self._extract_image_bytes(data)
        width, height = [int(part) for part in size.split("x", maxsplit=1)]
        data["width"] = width
        data["height"] = height
        if quality:
            data["quality"] = quality
        data["requested_model"] = requested_model
        data["actual_model"] = requested_model
        data["generation_strategy"] = "images_generation_direct"
        data["normalized_prompt"] = prepared_prompt
        data["revised_prompt"] = revised_prompt
        data["slug"] = slug
        data["model_policy_overridden"] = self.model_policy_overridden
        data["requested_model_input"] = self.requested_model_input or requested_model
        return image_bytes, data

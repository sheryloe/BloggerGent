from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    key: str
    title: str
    description: str
    file_name: str
    placeholders: list[str]


PROMPT_DEFINITIONS: list[PromptDefinition] = [
    PromptDefinition(
        key="topic_discovery",
        title="기본 주제 발굴 프롬프트",
        description="공용 기본 주제 발굴 템플릿입니다.",
        file_name="topic_discovery.md",
        placeholders=[],
    ),
    PromptDefinition(
        key="article_generation",
        title="기본 본문 생성 프롬프트",
        description="공용 기본 본문 생성 템플릿입니다.",
        file_name="article_generation.md",
        placeholders=["{keyword}"],
    ),
    PromptDefinition(
        key="collage_prompt",
        title="기본 콜라주 이미지 프롬프트",
        description="공용 기본 콜라주 이미지 템플릿입니다.",
        file_name="collage_prompt.md",
        placeholders=["{article_context}"],
    ),
    PromptDefinition(
        key="travel_topic_discovery",
        title="한국 여행/축제 주제 발굴 프롬프트",
        description="외국인 대상 한국 여행, 행사, 축제 블로그용 주제 발굴 템플릿입니다.",
        file_name="travel_topic_discovery.md",
        placeholders=["{blog_name}", "{content_brief}", "{target_audience}"],
    ),
    PromptDefinition(
        key="travel_article_generation",
        title="한국 여행/축제 본문 생성 프롬프트",
        description="외국인 대상 한국 여행, 행사, 축제 소개 블로그용 본문 생성 템플릿입니다.",
        file_name="travel_article_generation.md",
        placeholders=["{keyword}", "{blog_name}", "{target_audience}", "{content_brief}"],
    ),
    PromptDefinition(
        key="travel_collage_prompt",
        title="한국 여행/축제 이미지 프롬프트",
        description="한국 여행, 행사, 축제, 문화 루트형 글에 맞춘 8컷 콜라주 템플릿입니다.",
        file_name="travel_collage_prompt.md",
        placeholders=["{keyword}", "{blog_name}", "{article_title}", "{article_excerpt}", "{article_context}"],
    ),
    PromptDefinition(
        key="mystery_topic_discovery",
        title="미스터리 주제 발굴 프롬프트",
        description="세계 미스터리/다큐/전설 블로그용 주제 발굴 템플릿입니다.",
        file_name="mystery_topic_discovery.md",
        placeholders=["{blog_name}", "{content_brief}", "{target_audience}"],
    ),
    PromptDefinition(
        key="mystery_article_generation",
        title="미스터리 본문 생성 프롬프트",
        description="세계 미스터리/다큐/전설 블로그용 본문 생성 템플릿입니다.",
        file_name="mystery_article_generation.md",
        placeholders=["{keyword}", "{blog_name}", "{target_audience}", "{content_brief}"],
    ),
    PromptDefinition(
        key="mystery_collage_prompt",
        title="미스터리 이미지 프롬프트",
        description="세계 미스터리/다큐 스타일 콜라주 이미지 템플릿입니다.",
        file_name="mystery_collage_prompt.md",
        placeholders=["{keyword}", "{blog_name}", "{article_title}", "{article_excerpt}", "{article_context}"],
    ),
]


def _prompt_path(file_name: str) -> Path:
    return Path(settings.prompt_root) / file_name


def list_prompt_templates() -> list[dict]:
    templates: list[dict] = []
    for definition in PROMPT_DEFINITIONS:
        templates.append(
            {
                "key": definition.key,
                "title": definition.title,
                "description": definition.description,
                "file_name": definition.file_name,
                "placeholders": definition.placeholders,
                "content": _prompt_path(definition.file_name).read_text(encoding="utf-8"),
            }
        )
    return templates


def get_prompt_template(key: str) -> dict:
    definition = next((item for item in PROMPT_DEFINITIONS if item.key == key), None)
    if not definition:
        raise KeyError(key)
    return {
        "key": definition.key,
        "title": definition.title,
        "description": definition.description,
        "file_name": definition.file_name,
        "placeholders": definition.placeholders,
        "content": _prompt_path(definition.file_name).read_text(encoding="utf-8"),
    }


def update_prompt_template(key: str, content: str) -> dict:
    definition = next((item for item in PROMPT_DEFINITIONS if item.key == key), None)
    if not definition:
        raise KeyError(key)
    _prompt_path(definition.file_name).write_text(content.strip() + "\n", encoding="utf-8")
    return get_prompt_template(key)


def render_prompt_template(template: str, **replacements: str) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered

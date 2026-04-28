from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TopicDiscoveryItem(BaseModel):
    keyword: str = Field(min_length=3, max_length=255)
    reason: str = Field(default="")
    trend_score: float = Field(default=0.0, ge=0.0, le=100.0)


class TopicDiscoveryPayload(BaseModel):
    topics: list[TopicDiscoveryItem]


class TopicClassificationOutput(BaseModel):
    topic_cluster_label: str = Field(min_length=2, max_length=255)
    topic_cluster_key: str = Field(min_length=2, max_length=255)
    topic_angle_label: str = Field(min_length=2, max_length=255)
    topic_angle_key: str = Field(min_length=2, max_length=255)
    entity_names: list[str] = Field(default_factory=list, max_length=10)
    distinct_reason: str = Field(default="")


class FAQItem(BaseModel):
    question: str = Field(min_length=5, max_length=255)
    answer: str = Field(min_length=10)


class SlideSectionItem(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    summary: str = Field(min_length=10, max_length=500)
    speaker: str | None = Field(default=None, max_length=40)
    key_points: list[str] = Field(default_factory=list, max_length=6)


class ArticleGenerationOutput(BaseModel):
    title: str = Field(min_length=10, max_length=255)
    meta_description: str = Field(min_length=50, max_length=320)
    labels: list[str] = Field(min_length=2, max_length=8)
    slug: str = Field(min_length=3, max_length=255)
    excerpt: str = Field(min_length=40)
    html_article: str = Field(min_length=200)
    faq_section: list[FAQItem] = Field(default_factory=list, max_length=6)
    image_collage_prompt: str = Field(min_length=40)
    image_asset_plan: dict[str, Any] | None = Field(default=None)
    article_pattern_id: str | None = Field(default=None, min_length=2, max_length=100)
    article_pattern_version: int | str | None = Field(default=None)
    article_pattern_key: str | None = Field(default=None, min_length=2, max_length=100)
    article_pattern_version_key: str | None = Field(default=None, min_length=2, max_length=100)
    series_variant: str | None = Field(default=None, min_length=2, max_length=80)
    company_name: str | None = Field(default=None, min_length=2, max_length=120)
    ticker: str | None = Field(default=None, min_length=1, max_length=20)
    exchange: str | None = Field(default=None, min_length=2, max_length=30)
    chart_provider: str | None = Field(default=None, min_length=2, max_length=40)
    chart_symbol: str | None = Field(default=None, min_length=2, max_length=80)
    chart_interval: str | None = Field(default=None, min_length=1, max_length=20)
    slide_sections: list[SlideSectionItem] = Field(default_factory=list, max_length=10)
    inline_collage_prompt: str | None = None
    infographic_prompt: str | None = None
    trading_chart_prompt: str | None = None
    market_chart_prompt: str | None = None
    crypto_chart_prompt: str | None = None

    @field_validator("article_pattern_version", mode="before")
    @classmethod
    def _normalize_article_pattern_version(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if stripped.lower().startswith("travel-pattern-"):
                return stripped.lower()
            if stripped.isdigit():
                return int(stripped)
            match = re.search(r"(\d+)", stripped)
            if match:
                return int(match.group(1))
        return value

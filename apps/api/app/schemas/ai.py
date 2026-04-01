from __future__ import annotations

from pydantic import BaseModel, Field


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


class ArticleGenerationOutput(BaseModel):
    title: str = Field(min_length=10, max_length=255)
    meta_description: str = Field(min_length=50, max_length=320)
    labels: list[str] = Field(min_length=2, max_length=8)
    slug: str = Field(min_length=3, max_length=255)
    excerpt: str = Field(min_length=40)
    html_article: str = Field(min_length=200)
    faq_section: list[FAQItem] = Field(min_length=2, max_length=6)
    image_collage_prompt: str = Field(min_length=40)
    inline_collage_prompt: str | None = None
    infographic_prompt: str | None = None
    trading_chart_prompt: str | None = None
    market_chart_prompt: str | None = None
    crypto_chart_prompt: str | None = None

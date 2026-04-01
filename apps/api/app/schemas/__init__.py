from app.schemas.ai import ArticleGenerationOutput, FAQItem, TopicDiscoveryItem, TopicDiscoveryPayload
from app.schemas.api import (
    ArticleDetailRead,
    DashboardMetrics,
    DiscoveryRunResponse,
    JobCreate,
    JobDetailRead,
    JobRetryResponse,
    PromptTemplateRead,
    PromptTemplateUpdate,
    SettingItem,
    SettingUpdate,
    TopicRead,
)

ArticleRead = ArticleDetailRead
JobRead = JobDetailRead

__all__ = [
    "ArticleGenerationOutput",
    "ArticleRead",
    "DashboardMetrics",
    "DiscoveryRunResponse",
    "FAQItem",
    "JobCreate",
    "JobRead",
    "JobRetryResponse",
    "PromptTemplateRead",
    "PromptTemplateUpdate",
    "SettingItem",
    "SettingUpdate",
    "TopicDiscoveryItem",
    "TopicDiscoveryPayload",
    "TopicRead",
]

"""Service layer for Bloggent.

Folder policy:
- ``app.services.blogger``: Blogger-specific services
- ``app.services.cloudflare``: Cloudflare-specific services
- ``app.services.content``: Content-generation and editorial services
- ``app.services.ops``: Analytics/metrics/operations services
- ``app.services.integrations``: External integration services
- ``app.services.platform``: Platform/workspace orchestration services

Backward compatibility:
- Legacy imports (for example ``app.services.blogger_sync_service`` or
  ``app.services.article_service``) are exposed through module aliases.
"""

from __future__ import annotations

from importlib import import_module
import sys
from types import ModuleType

_LEGACY_MODULE_ALIASES = {
    "app.services.analytics_service": "app.services.ops.analytics_service",
    "app.services.archive_service": "app.services.integrations.archive_service",
    "app.services.article_pattern_service": "app.services.content.article_pattern_service",
    "app.services.article_service": "app.services.content.article_service",
    "app.services.audit_service": "app.services.ops.audit_service",
    "app.services.blog_seo_meta_service": "app.services.content.blog_seo_meta_service",
    "app.services.blog_service": "app.services.platform.blog_service",
    "app.services.blogger_editor_service": "app.services.blogger.blogger_editor_service",
    "app.services.blogger_label_backfill_service": "app.services.blogger.blogger_label_backfill_service",
    "app.services.blogger_live_audit_service": "app.services.blogger.blogger_live_audit_service",
    "app.services.blogger_oauth_service": "app.services.blogger.blogger_oauth_service",
    "app.services.blogger_refactor_service": "app.services.blogger.blogger_refactor_service",
    "app.services.blogger_sync_service": "app.services.blogger.blogger_sync_service",
    "app.services.codex_cli_queue_service": "app.services.platform.codex_cli_queue_service",
    "app.services.cloudflare_channel_service": "app.services.cloudflare.cloudflare_channel_service",
    "app.services.cloudflare_performance_service": "app.services.cloudflare.cloudflare_performance_service",
    "app.services.cloudflare_r2_migration_service": "app.services.cloudflare.cloudflare_r2_migration_service",
    "app.services.cloudflare_refactor_service": "app.services.cloudflare.cloudflare_refactor_service",
    "app.services.cloudflare_sync_service": "app.services.cloudflare.cloudflare_sync_service",
    "app.services.channel_prompt_service": "app.services.content.channel_prompt_service",
    "app.services.content_guard_service": "app.services.content.content_guard_service",
    "app.services.content_ops_service": "app.services.content.content_ops_service",
    "app.services.dashboard_service": "app.services.ops.dashboard_service",
    "app.services.dedupe_utils": "app.services.ops.dedupe_utils",
    "app.services.faq_hygiene": "app.services.content.faq_hygiene",
    "app.services.google_indexing_service": "app.services.integrations.google_indexing_service",
    "app.services.google_reporting_service": "app.services.integrations.google_reporting_service",
    "app.services.google_sheet_service": "app.services.integrations.google_sheet_service",
    "app.services.help_service": "app.services.integrations.help_service",
    "app.services.html_assembler": "app.services.content.html_assembler",
    "app.services.job_service": "app.services.ops.job_service",
    "app.services.lighthouse_service": "app.services.ops.lighthouse_service",
    "app.services.metric_ingestion_service": "app.services.ops.metric_ingestion_service",
    "app.services.model_policy_service": "app.services.ops.model_policy_service",
    "app.services.multilingual_bundle_service": "app.services.content.multilingual_bundle_service",
    "app.services.openai_usage_service": "app.services.ops.openai_usage_service",
    "app.services.ops_health_service": "app.services.ops.ops_health_service",
    "app.services.planner_service": "app.services.ops.planner_service",
    "app.services.platform_oauth_service": "app.services.platform.platform_oauth_service",
    "app.services.platform_publish_service": "app.services.platform.platform_publish_service",
    "app.services.platform_service": "app.services.platform.platform_service",
    "app.services.prompt_service": "app.services.content.prompt_service",
    "app.services.publishing_service": "app.services.platform.publishing_service",
    "app.services.publish_trust_gate_service": "app.services.content.publish_trust_gate_service",
    "app.services.related_posts": "app.services.content.related_posts",
    "app.services.search_console_playwright_service": "app.services.ops.search_console_playwright_service",
    "app.services.secret_service": "app.services.integrations.secret_service",
    "app.services.settings_service": "app.services.integrations.settings_service",
    "app.services.storage_service": "app.services.integrations.storage_service",
    "app.services.telegram_service": "app.services.integrations.telegram_service",
    "app.services.topic_discovery_run_service": "app.services.content.topic_discovery_run_service",
    "app.services.topic_guard_service": "app.services.content.topic_guard_service",
    "app.services.topic_service": "app.services.content.topic_service",
    "app.services.training_service": "app.services.content.training_service",
    "app.services.usage_service": "app.services.ops.usage_service",
    "app.services.wikimedia_service": "app.services.content.wikimedia_service",
    "app.services.workspace_service": "app.services.platform.workspace_service",
}


class _LazyAliasModule(ModuleType):
    def __init__(self, alias_name: str, target_name: str) -> None:
        super().__init__(alias_name)
        self.__dict__["_alias_name"] = alias_name
        self.__dict__["_target_name"] = target_name
        self.__dict__["_loaded_module"] = None

    def _load(self) -> ModuleType:
        loaded = self.__dict__.get("_loaded_module")
        if loaded is None:
            loaded = import_module(self.__dict__["_target_name"])
            self.__dict__["_loaded_module"] = loaded
            sys.modules[self.__dict__["_alias_name"]] = loaded
        return loaded

    def __getattr__(self, item: str):  # type: ignore[override]
        return getattr(self._load(), item)

    def __setattr__(self, key: str, value) -> None:  # type: ignore[override]
        if key in {"_alias_name", "_target_name", "_loaded_module"}:
            super().__setattr__(key, value)
            return
        setattr(self._load(), key, value)

    def __delattr__(self, item: str) -> None:  # type: ignore[override]
        if item in {"_alias_name", "_target_name", "_loaded_module"}:
            super().__delattr__(item)
            return
        delattr(self._load(), item)

    def __dir__(self) -> list[str]:  # type: ignore[override]
        return sorted(set(super().__dir__()) | set(dir(self._load())))


def _register_legacy_aliases() -> None:
    for legacy_name, target_name in _LEGACY_MODULE_ALIASES.items():
        alias_module = sys.modules.get(legacy_name)
        if not isinstance(alias_module, _LazyAliasModule):
            alias_module = _LazyAliasModule(legacy_name, target_name)
            sys.modules[legacy_name] = alias_module
        short_name = legacy_name.rsplit(".", 1)[-1]
        globals()[short_name] = alias_module


_register_legacy_aliases()

__all__ = [
    "blogger",
    "cloudflare",
    "content",
    "ops",
    "integrations",
    "platform",
    *sorted(name.rsplit(".", 1)[-1] for name in _LEGACY_MODULE_ALIASES),
]

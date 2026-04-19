from __future__ import annotations

from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "동그리 자동 블로그전트"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg2://bloggent:bloggent@postgres:5432/bloggent"
    redis_url: str = "redis://redis:6379/0"
    public_api_base_url: str = "http://localhost:8000"
    public_web_base_url: str = "http://localhost:3000"
    storage_root: str = "/app/storage"
    strict_storage_root: bool = True
    strict_r2_key_schema: bool = True
    mystery_single_main_image_only: bool = True
    mystery_storage_subdir: str = "images/mystery"
    mystery_storage_root_windows: str = r"D:\Donggri_Runtime\BloggerGent\storage"
    public_image_provider: str = "cloudflare_r2"
    public_asset_base_url: str = ""
    cloudflare_account_id: str = ""
    cloudflare_r2_bucket: str = ""
    cloudflare_r2_access_key_id: str = ""
    cloudflare_r2_secret_access_key: str = ""
    cloudflare_r2_public_base_url: str = ""
    cloudflare_r2_direct_public_base_url: str = ""
    cloudflare_r2_prefix: str = "assets/images"
    cloudflare_storage_root_windows: str = r"D:\Donggri_Runtime\BloggerGent\storage"
    travel_cloudflare_account_id: str = ""
    travel_cloudflare_r2_bucket: str = ""
    travel_cloudflare_r2_access_key_id: str = ""
    travel_cloudflare_r2_secret_access_key: str = ""
    travel_cloudflare_r2_public_base_url: str = ""
    shared_channel_cloudflare_account_id: str = ""
    shared_channel_cloudflare_r2_bucket: str = ""
    shared_channel_cloudflare_r2_access_key_id: str = ""
    shared_channel_cloudflare_r2_secret_access_key: str = ""
    shared_channel_cloudflare_r2_public_base_url: str = ""
    mystery_cloudflare_account_id: str = ""
    mystery_cloudflare_r2_bucket: str = ""
    mystery_cloudflare_r2_access_key_id: str = ""
    mystery_cloudflare_r2_secret_access_key: str = ""
    mystery_cloudflare_r2_public_base_url: str = ""
    mystery_cloudflare_r2_prefix: str = "assets/the-midnight-archives"
    cloudflare_cdn_transform_enabled: bool = False
    github_pages_owner: str = ""
    github_pages_repo: str = ""
    github_pages_branch: str = "main"
    github_pages_token: str = ""
    github_pages_base_url: str = ""
    github_pages_assets_dir: str = "assets/images"
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    cloudinary_folder: str = "bloggent"
    schedule_time: str = "09:00"
    schedule_timezone: str = "Asia/Seoul"
    schedule_enabled: bool = True
    travel_schedule_time: str = "00:00"
    travel_schedule_interval_hours: int = 2
    travel_topics_per_run: int = 1
    travel_inline_collage_enabled: bool = False
    mystery_inline_collage_enabled: bool = False
    mystery_schedule_time: str = "01:00"
    mystery_schedule_interval_hours: int = 2
    mystery_topics_per_run: int = 1
    quality_gate_enabled: bool = True
    quality_gate_similarity_threshold: float = 65.0
    quality_gate_min_seo_score: int = 70
    quality_gate_min_geo_score: int = 60
    quality_gate_min_ctr_score: int = 60
    travel_blossom_cap_ratio: float = 0.2
    cloudflare_blossom_cap_ratio: float = 0.2
    travel_daily_topic_mix_counts: str = "{}"
    cloudflare_daily_topic_mix_counts: str = "{}"
    cloudflare_inline_images_enabled: bool = True
    cloudflare_require_cover_image: bool = True
    default_publish_mode: str = "draft"
    provider_mode: str = "mock"
    topic_discovery_max_topics_per_run: int = 3
    publish_min_interval_seconds: int = 300
    openai_api_key: str = ""
    openai_admin_api_key: str = ""
    openai_text_model: str = "gpt-5.4-2026-03-05"
    article_generation_model: str = "gpt-5.4-mini-2026-03-17"
    image_prompt_generation_model: str = "gpt-5.4-mini-2026-03-17"
    openai_image_model: str = "gpt-image-1"
    text_runtime_kind: str = "openai"
    text_runtime_model: str = "gpt-5.4"
    image_runtime_kind: str = "openai_image"
    codex_job_timeout_seconds: int = 900
    openai_usage_hard_cap_enabled: bool = True
    openai_request_saver_mode: bool = True
    topic_discovery_provider: str = "openai"
    topic_discovery_model: str = "gpt-5.4-2026-03-05"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_daily_request_limit: int = 6
    gemini_requests_per_minute_limit: int = 2
    pipeline_stop_after: str = "none"
    blogger_client_name: str = ""
    blogger_client_id: str = ""
    blogger_client_secret: str = ""
    blogger_refresh_token: str = ""
    blogger_redirect_uri: str = ""
    blogger_access_token_expires_at: str = ""
    blogger_token_scope: str = ""
    blogger_token_type: str = "Bearer"
    blogger_oauth_state: str = ""
    blogger_access_token: str = ""
    blogger_blog_id: str = ""
    youtube_default_privacy_status: str = "private"
    meta_graph_api_version: str = "v23.0"
    instagram_client_id: str = ""
    instagram_client_secret: str = ""
    instagram_redirect_uri: str = ""
    instagram_publish_api_enabled: bool = False
    blogger_playwright_enabled: bool = False
    blogger_playwright_auto_sync: bool = False
    blogger_playwright_cdp_url: str = "http://host.docker.internal:9223"
    blogger_playwright_account_index: int = 0
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    cloudflare_channel_enabled: bool = False
    cloudflare_blog_api_base_url: str = ""
    cloudflare_blog_m2m_token: str = ""
    google_sheet_url: str = ""
    google_sheet_id: str = ""
    google_sheet_travel_tab: str = "Travel"
    google_sheet_mystery_tab: str = "Mystery"
    google_sheet_cloudflare_tab: str = "Cloudflare"
    sheet_sync_enabled: bool = False
    sheet_sync_day: str = "SUNDAY"
    sheet_sync_time: str = "10:00"
    last_sheet_sync_on: str = ""
    travel_research_mode: str = "hybrid"
    seed_demo_data: bool = True
    auto_trigger_on_discovery: bool = True
    related_post_count: int = 3
    settings_encryption_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @computed_field
    @property
    def prompt_root(self) -> Path:
        return Path("/app/prompts")

    @computed_field
    @property
    def storage_images_dir(self) -> Path:
        return Path(self.storage_root) / "images"

    @computed_field
    @property
    def storage_html_dir(self) -> Path:
        return Path(self.storage_root) / "html"

    @computed_field
    @property
    def storage_common_analysis_dir(self) -> Path:
        return Path(self.storage_root) / "_common" / "analysis"

    @computed_field
    @property
    def storage_lighthouse_dir(self) -> Path:
        return self.storage_common_analysis_dir / "lighthouse"

    @computed_field
    @property
    def storage_travel_dir(self) -> Path:
        return Path(self.storage_root) / "travel"

    @computed_field
    @property
    def storage_mystery_dir(self) -> Path:
        return Path(self.storage_root) / "mystery"

    @computed_field
    @property
    def storage_cloudflare_dir(self) -> Path:
        return Path(self.storage_root) / "cloudflare"


settings = Settings()

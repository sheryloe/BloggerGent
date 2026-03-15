from __future__ import annotations

from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "Bloggent"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg2://bloggent:bloggent@postgres:5432/bloggent"
    redis_url: str = "redis://redis:6379/0"
    public_api_base_url: str = "http://localhost:8000"
    public_web_base_url: str = "http://localhost:3000"
    storage_root: str = "/app/storage"
    public_image_provider: str = "local"
    public_asset_base_url: str = ""
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
    default_publish_mode: str = "draft"
    provider_mode: str = "mock"
    openai_api_key: str = ""
    openai_text_model: str = "gpt-4.1-mini"
    openai_image_model: str = "dall-e-3"
    openai_request_saver_mode: bool = True
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
    seed_demo_data: bool = True
    auto_trigger_on_discovery: bool = True
    related_post_count: int = 3

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


settings = Settings()

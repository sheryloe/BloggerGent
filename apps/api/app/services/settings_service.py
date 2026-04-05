from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Setting
from app.services.secret_service import decrypt_secret_value, encrypt_secret_value, is_encrypted_secret


@dataclass(slots=True)
class DefaultSetting:
    value: str
    description: str
    is_secret: bool = False


DEFAULT_SETTINGS: dict[str, DefaultSetting] = {
    "app_name": DefaultSetting("Donggr AutoBloggent", "Workspace display name"),
    "default_blog_timezone": DefaultSetting("Asia/Seoul", "Default planner and publishing timezone"),
    "default_publish_mode": DefaultSetting("draft", "Default publishing mode for newly created jobs"),
    "default_writer_tone": DefaultSetting("system-operator", "Default writing tone label"),
    "planner_default_daily_posts": DefaultSetting("3", "Default daily slot count when building a month plan"),
    "planner_day_start_time": DefaultSetting("09:00", "Planner day start time in HH:MM"),
    "planner_day_end_time": DefaultSetting("21:00", "Planner day end time in HH:MM"),
    "automation_master_enabled": DefaultSetting("false", "Master gate for every automation path"),
    "automation_scheduler_enabled": DefaultSetting("false", "Enable scheduler tick automation"),
    "automation_publish_queue_enabled": DefaultSetting("false", "Enable publish queue automation"),
    "automation_content_review_enabled": DefaultSetting("false", "Enable content review automation"),
    "automation_telegram_enabled": DefaultSetting("false", "Enable Telegram polling automation"),
    "automation_sheet_enabled": DefaultSetting("false", "Deprecated Google Sheet automation flag"),
    "automation_cloudflare_enabled": DefaultSetting("false", "Enable Cloudflare automation"),
    "automation_google_indexing_enabled": DefaultSetting("false", "Enable Google indexing automation"),
    "automation_training_enabled": DefaultSetting("false", "Enable training automation"),
    "workspace_metrics_sync_enabled": DefaultSetting(
        "true",
        "Enable periodic Search Console / GA4 metric ingestion for managed Blogger channels.",
    ),
    "workspace_metrics_sync_interval_hours": DefaultSetting(
        "6",
        "Hours between automatic workspace metric ingestion runs.",
    ),
    "workspace_metrics_lookback_days": DefaultSetting(
        "28",
        "Lookback window in days for Search Console / GA4 metric ingestion.",
    ),
    "provider_mode": DefaultSetting(settings.provider_mode, "mock or live provider mode"),
    "public_image_provider": DefaultSetting(
        settings.public_image_provider,
        "대표 이미지 공개 전달 방식. 현재 운영 권장값은 cloudflare_r2 입니다.",
    ),
    "public_asset_base_url": DefaultSetting(
        settings.public_asset_base_url,
        "Public base URL used only when provider is local. Example: https://your-domain.com",
    ),
    "cloudflare_account_id": DefaultSetting(settings.cloudflare_account_id, "Cloudflare account ID"),
    "cloudflare_r2_bucket": DefaultSetting(settings.cloudflare_r2_bucket, "Cloudflare R2 bucket name"),
    "cloudflare_r2_access_key_id": DefaultSetting(
        settings.cloudflare_r2_access_key_id,
        "Cloudflare R2 access key ID",
        True,
    ),
    "cloudflare_r2_secret_access_key": DefaultSetting(
        settings.cloudflare_r2_secret_access_key,
        "Cloudflare R2 secret access key",
        True,
    ),
    "cloudflare_r2_public_base_url": DefaultSetting(
        settings.cloudflare_r2_public_base_url,
        "Cloudflare 공개 이미지 기준 URL. integration 업로드를 쓰면 비워둘 때 cloudflare_blog_api_base_url + /assets 가 자동 적용됩니다.",
    ),
    "cloudflare_r2_prefix": DefaultSetting(
        settings.cloudflare_r2_prefix,
        "Object key prefix inside the R2 bucket. Files are stored as <prefix>/<slug>.png",
    ),
    "cloudflare_cdn_transform_enabled": DefaultSetting(
        str(settings.cloudflare_cdn_transform_enabled).lower(),
        "Enable Cloudflare /cdn-cgi/image transform URLs. Keep false when transform is unavailable.",
    ),
    "github_pages_owner": DefaultSetting(settings.github_pages_owner, "GitHub Pages owner or organization"),
    "github_pages_repo": DefaultSetting(settings.github_pages_repo, "GitHub Pages repository name"),
    "github_pages_branch": DefaultSetting(settings.github_pages_branch, "GitHub Pages upload branch"),
    "github_pages_token": DefaultSetting(settings.github_pages_token, "GitHub personal access token", True),
    "github_pages_base_url": DefaultSetting(
        settings.github_pages_base_url,
        "GitHub Pages base URL. If empty, it is derived from owner/repo.",
    ),
    "github_pages_assets_dir": DefaultSetting(
        settings.github_pages_assets_dir,
        "Directory inside the GitHub Pages repository where public images are uploaded.",
    ),
    "cloudinary_cloud_name": DefaultSetting(settings.cloudinary_cloud_name, "Cloudinary cloud name"),
    "cloudinary_api_key": DefaultSetting(settings.cloudinary_api_key, "Cloudinary API key", True),
    "cloudinary_api_secret": DefaultSetting(settings.cloudinary_api_secret, "Cloudinary API secret", True),
    "cloudinary_folder": DefaultSetting(settings.cloudinary_folder, "Cloudinary upload folder"),
    "openai_api_key": DefaultSetting(settings.openai_api_key, "OpenAI API key", True),
    "openai_admin_api_key": DefaultSetting(
        settings.openai_admin_api_key,
        "OpenAI Admin API key used for free-tier usage reporting",
        True,
    ),
    "openai_text_model": DefaultSetting(settings.openai_text_model, "기본 OpenAI 보조 텍스트 모델"),
    "article_generation_model": DefaultSetting(
        settings.article_generation_model,
        "장문 본문 생성과 리라이트에 쓰는 주력 OpenAI 모델",
    ),
    "openai_image_model": DefaultSetting(settings.openai_image_model, "Default OpenAI image model"),
    "openai_request_saver_mode": DefaultSetting(
        str(settings.openai_request_saver_mode).lower(),
        "Skip the extra image prompt refinement request when possible",
    ),
    "topic_discovery_provider": DefaultSetting(
        settings.topic_discovery_provider,
        "Topic discovery provider: openai or gemini",
    ),
    "topic_discovery_model": DefaultSetting(
        settings.topic_discovery_model,
        "Default topic discovery model when provider is OpenAI",
    ),
    "topic_discovery_max_topics_per_run": DefaultSetting(
        str(settings.topic_discovery_max_topics_per_run),
        "Maximum number of topics queued per discovery run. 0 means unlimited.",
    ),
    "topic_history_lookback_days": DefaultSetting(
        "180",
        "Lookback window in days for topic history matching (sheet first, DB fallback).",
    ),
    "topic_novelty_cluster_threshold": DefaultSetting(
        "0.85",
        "Cluster similarity threshold for strict same-cluster duplicate risk.",
    ),
    "topic_novelty_angle_threshold": DefaultSetting(
        "0.75",
        "Angle similarity threshold for strict same-angle duplicate risk.",
    ),
    "topic_soft_penalty_threshold": DefaultSetting(
        "2",
        "Soft-penalty cutoff. Candidates at or above this value are regenerated.",
    ),
    "gemini_api_key": DefaultSetting(settings.gemini_api_key, "Gemini API key", True),
    "gemini_model": DefaultSetting(settings.gemini_model, "Gemini model for topic discovery"),
    "gemini_daily_request_limit": DefaultSetting(
        str(settings.gemini_daily_request_limit),
        "Gemini daily request limit. 0 means unlimited.",
    ),
    "gemini_requests_per_minute_limit": DefaultSetting(
        str(settings.gemini_requests_per_minute_limit),
        "Gemini per-minute request limit. 0 means unlimited.",
    ),
    "pipeline_stop_after": DefaultSetting(settings.pipeline_stop_after, "Stop the pipeline after a given stage"),
    "blogger_client_name": DefaultSetting(settings.blogger_client_name, "Google OAuth client display name"),
    "blogger_client_id": DefaultSetting(settings.blogger_client_id, "Google OAuth client ID"),
    "blogger_client_secret": DefaultSetting(settings.blogger_client_secret, "Google OAuth client secret", True),
    "blogger_redirect_uri": DefaultSetting(settings.blogger_redirect_uri, "Google OAuth redirect URI"),
    "blogger_refresh_token": DefaultSetting(settings.blogger_refresh_token, "Google OAuth refresh token", True),
    "blogger_oauth_state": DefaultSetting(settings.blogger_oauth_state, "Google OAuth state", True),
    "blogger_access_token": DefaultSetting(settings.blogger_access_token, "Google OAuth access token", True),
    "blogger_access_token_expires_at": DefaultSetting(
        settings.blogger_access_token_expires_at,
        "Google OAuth access token expiry timestamp",
    ),
    "blogger_token_scope": DefaultSetting(settings.blogger_token_scope, "Granted Google OAuth scope"),
    "blogger_token_type": DefaultSetting(settings.blogger_token_type, "Google OAuth token type"),
    "youtube_default_privacy_status": DefaultSetting(
        settings.youtube_default_privacy_status,
        "Default YouTube privacy status. Recommended value is private.",
    ),
    "meta_graph_api_version": DefaultSetting(
        settings.meta_graph_api_version,
        "Meta Graph API version used for Instagram OAuth and publish flows.",
    ),
    "instagram_client_id": DefaultSetting(settings.instagram_client_id, "Instagram / Meta app client ID"),
    "instagram_client_secret": DefaultSetting(settings.instagram_client_secret, "Instagram / Meta app client secret", True),
    "instagram_redirect_uri": DefaultSetting(settings.instagram_redirect_uri, "Instagram / Meta OAuth redirect URI"),
    "instagram_publish_api_enabled": DefaultSetting(
        str(settings.instagram_publish_api_enabled).lower(),
        "Enable the live Instagram publish adapter after app review and permission verification.",
    ),
    "blogger_playwright_enabled": DefaultSetting(
        str(settings.blogger_playwright_enabled).lower(),
        "Enable Playwright automation for Blogger search description sync",
    ),
    "blogger_playwright_auto_sync": DefaultSetting(
        str(settings.blogger_playwright_auto_sync).lower(),
        "Automatically sync Blogger search description after publish",
    ),
    "blogger_playwright_cdp_url": DefaultSetting(
        settings.blogger_playwright_cdp_url,
        "Remote debugging URL used by Playwright",
    ),
    "blogger_playwright_account_index": DefaultSetting(
        str(settings.blogger_playwright_account_index),
        "Account index used in the Blogger editor URL. Usually 0.",
    ),
    "telegram_bot_token": DefaultSetting(settings.telegram_bot_token, "Telegram bot token", True),
    "telegram_chat_id": DefaultSetting(settings.telegram_chat_id, "Telegram chat ID", True),
    "cloudflare_channel_enabled": DefaultSetting(
        str(settings.cloudflare_channel_enabled).lower(),
        "Cloudflare 채널 연동 사용 여부",
    ),
    "cloudflare_blog_api_base_url": DefaultSetting(
        settings.cloudflare_blog_api_base_url,
        "Cloudflare 연동 API 기본 주소. 예: https://api.dongriarchive.com",
    ),
    "cloudflare_blog_m2m_token": DefaultSetting(
        settings.cloudflare_blog_m2m_token,
        "Cloudflare integration Bearer 토큰",
        True,
    ),
    "google_sheet_url": DefaultSetting(
        settings.google_sheet_url,
        "Google Sheets URL used for weekly blog snapshot sync.",
    ),
    "google_sheet_id": DefaultSetting(
        settings.google_sheet_id,
        "Derived Google Sheets document id. Usually filled automatically from google_sheet_url.",
    ),
    "google_sheet_travel_tab": DefaultSetting(
        settings.google_sheet_travel_tab,
        "Tab name used for Korea travel snapshot rows.",
    ),
    "google_sheet_mystery_tab": DefaultSetting(
        settings.google_sheet_mystery_tab,
        "Tab name used for mystery snapshot rows.",
    ),
    "google_sheet_cloudflare_tab": DefaultSetting(
        settings.google_sheet_cloudflare_tab,
        "Tab name used for Cloudflare channel snapshot rows.",
    ),
    "sheet_sync_enabled": DefaultSetting(
        str(settings.sheet_sync_enabled).lower(),
        "Enable weekly Google Sheets snapshot sync.",
    ),
    "sheet_sync_day": DefaultSetting(
        settings.sheet_sync_day,
        "Weekly Google Sheets sync day. Example: SUNDAY.",
    ),
    "sheet_sync_time": DefaultSetting(
        settings.sheet_sync_time,
        "Weekly Google Sheets sync time in HH:MM format.",
    ),
    "last_sheet_sync_on": DefaultSetting(
        settings.last_sheet_sync_on,
        "Last successful Google Sheets sync date (YYYY-MM-DD).",
    ),
    "default_publish_mode": DefaultSetting(settings.default_publish_mode, "Default publish mode"),
    "schedule_enabled": DefaultSetting(str(settings.schedule_enabled).lower(), "Enable the automatic scheduler"),
    "schedule_time": DefaultSetting(settings.schedule_time, "Scheduler run time in HH:MM format"),
    "schedule_timezone": DefaultSetting(settings.schedule_timezone, "Scheduler timezone"),
    "last_schedule_run_on": DefaultSetting("", "Last successful scheduler run date"),
    "travel_schedule_time": DefaultSetting(
        settings.travel_schedule_time,
        "Travel profile recurring schedule start time in HH:MM format.",
    ),
    "travel_schedule_interval_hours": DefaultSetting(
        str(settings.travel_schedule_interval_hours),
        "Hours between recurring travel profile runs.",
    ),
    "travel_topics_per_run": DefaultSetting(
        str(settings.travel_topics_per_run),
        "Number of travel topics queued on each recurring run.",
    ),
    "travel_inline_collage_enabled": DefaultSetting(
        str(settings.travel_inline_collage_enabled).lower(),
        "Enable travel inline body collage image generation.",
    ),
    "mystery_inline_collage_enabled": DefaultSetting(
        str(settings.mystery_inline_collage_enabled).lower(),
        "Enable mystery inline body collage image generation.",
    ),
    "last_schedule_run_on_travel": DefaultSetting(
        "",
        "Last successful recurring travel scheduler slot marker.",
    ),
    "mystery_schedule_time": DefaultSetting(
        settings.mystery_schedule_time,
        "Mystery profile recurring schedule start time in HH:MM format.",
    ),
    "mystery_schedule_interval_hours": DefaultSetting(
        str(settings.mystery_schedule_interval_hours),
        "Hours between recurring mystery profile runs.",
    ),
    "mystery_topics_per_run": DefaultSetting(
        str(settings.mystery_topics_per_run),
        "Number of mystery topics queued on each recurring run.",
    ),
    "quality_gate_enabled": DefaultSetting(
        str(settings.quality_gate_enabled).lower(),
        "Enable pre-publish quality gate for Blogger and Cloudflare generation.",
    ),
    "quality_gate_similarity_threshold": DefaultSetting(
        str(settings.quality_gate_similarity_threshold),
        "Similarity threshold (0-100) for pre-publish quality gate.",
    ),
    "quality_gate_min_seo_score": DefaultSetting(
        str(settings.quality_gate_min_seo_score),
        "Minimum SEO score (0-100) required by pre-publish quality gate.",
    ),
    "quality_gate_min_geo_score": DefaultSetting(
        str(settings.quality_gate_min_geo_score),
        "Minimum GEO score (0-100) required by pre-publish quality gate.",
    ),
    "quality_gate_min_ctr_score": DefaultSetting(
        str(settings.quality_gate_min_ctr_score),
        "Minimum CTR score (0-100) required by pre-publish quality gate.",
    ),
    "last_schedule_run_on_mystery": DefaultSetting(
        "",
        "Last successful recurring mystery scheduler slot marker.",
    ),
    "travel_editorial_weights": DefaultSetting(
        "Travel:45,Culture:30,Food:25",
        "Weighted rotation config for travel editorial categories.",
    ),
    "mystery_editorial_weights": DefaultSetting(
        "Case Files:45,Mystery Archives:30,Legends & Lore:25",
        "Weighted rotation config for mystery editorial categories.",
    ),
    "travel_editorial_last_category": DefaultSetting(
        "",
        "Last selected travel editorial category for weighted rotation.",
    ),
    "travel_editorial_last_streak": DefaultSetting(
        "0",
        "Consecutive streak count for last selected travel editorial category.",
    ),
    "mystery_editorial_last_category": DefaultSetting(
        "",
        "Last selected mystery editorial category for weighted rotation.",
    ),
    "mystery_editorial_last_streak": DefaultSetting(
        "0",
        "Consecutive streak count for last selected mystery editorial category.",
    ),
    "travel_editorial_daily_counts": DefaultSetting(
        "{}",
        "JSON object for travel editorial daily category counts.",
    ),
    "mystery_editorial_daily_counts": DefaultSetting(
        "{}",
        "JSON object for mystery editorial daily category counts.",
    ),
    "cloudflare_daily_publish_enabled": DefaultSetting(
        "true",
        "Enable daily Cloudflare auto publishing.",
    ),
    "cloudflare_daily_publish_time": DefaultSetting(
        "00:00",
        "Cloudflare auto publishing start time in HH:MM.",
    ),
    "cloudflare_daily_publish_interval_hours": DefaultSetting(
        "2",
        "Cloudflare auto publishing interval in hours.",
    ),
    "cloudflare_daily_last_run_slot": DefaultSetting(
        "",
        "Last Cloudflare auto publishing slot marker in ISO local time.",
    ),
    "cloudflare_daily_last_attempted_slot": DefaultSetting(
        "",
        "Last attempted Cloudflare auto publishing slot marker in ISO local time.",
    ),
    "cloudflare_daily_publish_timezone": DefaultSetting(
        "Asia/Seoul",
        "Timezone for daily Cloudflare auto publishing.",
    ),
    "cloudflare_daily_publish_weekday_quota": DefaultSetting(
        "9",
        "Daily Cloudflare post quota for Monday-Saturday.",
    ),
    "cloudflare_daily_publish_sunday_quota": DefaultSetting(
        "7",
        "Daily Cloudflare post quota for Sunday.",
    ),
    "cloudflare_daily_last_run_on": DefaultSetting(
        "",
        "Last date when Cloudflare daily auto publishing completed.",
    ),
    "cloudflare_daily_category_counts": DefaultSetting(
        "{}",
        "JSON object for Cloudflare daily weighted category counts.",
    ),
    "google_indexing_policy_mode": DefaultSetting(
        "mixed",
        "Google indexing policy mode. mixed keeps publish requests for eligible URLs only.",
    ),
    "google_indexing_daily_quota": DefaultSetting(
        "200",
        "Google Indexing API daily publish request quota (project-level, LA day boundary).",
    ),
    "google_indexing_cooldown_days": DefaultSetting(
        "7",
        "Cooldown days before auto publish request can repeat for the same URL.",
    ),
    "google_indexing_blog_quota_map": DefaultSetting(
        "{}",
        "Per-blog integer daily publish allocation map as JSON. Example: {\"1\": 20, \"2\": 10}",
    ),
    "cloudflare_inline_images_enabled": DefaultSetting(
        str(settings.cloudflare_inline_images_enabled).lower(),
        "Enable inline markdown collage images for Cloudflare posts.",
    ),
    "cloudflare_require_cover_image": DefaultSetting(
        str(settings.cloudflare_require_cover_image).lower(),
        "Require cover image before Cloudflare post publish; fail generation when missing.",
    ),
    "travel_blossom_cap_ratio": DefaultSetting(
        str(settings.travel_blossom_cap_ratio),
        "Daily cherry-blossom topic cap ratio for Korea travel channel.",
    ),
    "cloudflare_blossom_cap_ratio": DefaultSetting(
        str(settings.cloudflare_blossom_cap_ratio),
        "Daily cherry-blossom topic cap ratio for Cloudflare channel.",
    ),
    "travel_daily_topic_mix_counts": DefaultSetting(
        settings.travel_daily_topic_mix_counts,
        "JSON counter for travel daily total/blossom topic generation counts.",
    ),
    "cloudflare_daily_topic_mix_counts": DefaultSetting(
        settings.cloudflare_daily_topic_mix_counts,
        "JSON counter for Cloudflare daily total/blossom topic generation counts.",
    ),
    "training_schedule_enabled": DefaultSetting("false", "Enable daily scheduled training session"),
    "training_schedule_time": DefaultSetting("03:00", "Daily training schedule time in HH:MM format"),
    "training_schedule_timezone": DefaultSetting("Asia/Seoul", "Timezone for daily training schedule"),
    "training_schedule_last_run_on": DefaultSetting("", "Last date when scheduled training attempted"),
    "training_use_real_engine": DefaultSetting("false", "Enable real training engine execution (simulation remains default)"),
    "content_ops_scan_enabled": DefaultSetting("true", "Enable the 5-minute live content review scan."),
    "content_ops_auto_fix_drafts": DefaultSetting("true", "Automatically apply safe low-risk draft fixes."),
    "content_ops_auto_fix_published_meta": DefaultSetting(
        "true",
        "Automatically apply safe published meta/search-description fixes.",
    ),
    "content_ops_learning_paused": DefaultSetting("false", "Pause scheduled learning snapshot/training activity."),
    "content_ops_learning_snapshot_path": DefaultSetting("", "Latest curated learning JSONL snapshot path."),
    "content_ops_prompt_memory_path": DefaultSetting("", "Latest prompt memory snapshot path."),
    "content_ops_learning_snapshot_updated_at": DefaultSetting("", "Last curated learning snapshot build timestamp."),
    "content_ops_telegram_update_offset": DefaultSetting("0", "Telegram getUpdates offset for ops polling."),
    "content_ops_sync_failure_streak": DefaultSetting("0", "Consecutive live sync failure counter."),
    "publish_daily_limit_per_blog": DefaultSetting("3", "Daily publish limit per blog"),
    "publish_min_interval_seconds": DefaultSetting(
        str(settings.publish_min_interval_seconds),
        "Minimum interval between Blogger publish requests for the same blog",
    ),
    "same_cluster_cooldown_hours": DefaultSetting("24", "Cooldown for repeating the same topic cluster"),
    "same_angle_cooldown_days": DefaultSetting("7", "Cooldown for repeating the same topic angle"),
    "topic_guard_enabled": DefaultSetting("true", "Enable topic memory based publish guard"),
    "travel_research_mode": DefaultSetting(
        settings.travel_research_mode,
        "Travel fact-check mode: hybrid, prompt_only, validate, or off.",
    ),
}

SETTING_DESCRIPTION_OVERRIDES_KO: dict[str, str] = {
    "app_name": "워크스페이스 표시 이름",
    "default_blog_timezone": "플래너와 발행에 쓰는 기본 시간대",
    "default_publish_mode": "새 작업에 적용할 기본 발행 모드",
    "default_writer_tone": "기본 작성 톤 라벨",
    "admin_auth_enabled": "API와 대시보드에 관리자 인증을 적용할지 결정",
    "admin_auth_username": "관리자 인증이 켜져 있을 때 사용할 기본 사용자명",
    "planner_default_daily_posts": "월간 계획 생성 시 기본 일일 슬롯 수",
    "planner_day_start_time": "플래너 자동 배치 시작 시각(HH:MM)",
    "planner_day_end_time": "플래너 자동 배치 종료 시각(HH:MM)",
    "automation_master_enabled": "모든 자동화 경로의 최상위 마스터 스위치",
    "automation_scheduler_enabled": "스케줄러 자동 실행 사용",
    "automation_publish_queue_enabled": "발행 큐 자동 처리 사용",
    "automation_content_review_enabled": "콘텐츠 검토 자동화 사용",
    "automation_telegram_enabled": "텔레그램 운영 자동화 사용",
    "automation_sheet_enabled": "시트 자동화 사용(구형)",
    "automation_cloudflare_enabled": "Cloudflare 자동화 사용",
    "automation_google_indexing_enabled": "Google 색인 자동화 사용",
    "automation_training_enabled": "학습 자동화 사용",
    "provider_mode": "공급자 실행 모드(mock/live)",
    "public_image_provider": "대표 이미지 공개 전달 방식",
    "public_asset_base_url": "로컬 자산 공개 시 사용할 기준 URL",
    "cloudflare_account_id": "Cloudflare 계정 ID",
    "cloudflare_r2_bucket": "Cloudflare R2 버킷 이름",
    "cloudflare_r2_access_key_id": "Cloudflare R2 액세스 키 ID",
    "cloudflare_r2_secret_access_key": "Cloudflare R2 시크릿 액세스 키",
    "cloudflare_r2_public_base_url": "Cloudflare R2 공개 자산 기본 URL",
    "cloudflare_r2_prefix": "Cloudflare R2 내부 경로 접두사",
    "cloudflare_cdn_transform_enabled": "Cloudflare 이미지 변환 URL 사용 여부",
    "cloudinary_cloud_name": "Cloudinary 클라우드 이름",
    "cloudinary_api_key": "Cloudinary API 키",
    "cloudinary_api_secret": "Cloudinary API 시크릿",
    "cloudinary_folder": "Cloudinary 업로드 폴더",
    "github_pages_owner": "GitHub Pages 소유자 또는 조직명",
    "github_pages_repo": "GitHub Pages 저장소 이름",
    "github_pages_branch": "GitHub Pages 업로드 브랜치",
    "github_pages_token": "GitHub Pages 업로드 토큰",
    "github_pages_base_url": "GitHub Pages 기준 URL",
    "github_pages_assets_dir": "GitHub Pages 자산 업로드 디렉터리",
    "openai_text_model": "기본 OpenAI 텍스트 모델",
    "openai_large_text_model": "장문 생성에 쓰는 주력 OpenAI 텍스트 모델",
    "openai_small_text_model": "검토·분석·보정에 쓰는 OpenAI 소형 텍스트 모델",
    "article_generation_model": "본문 생성에 사용할 기본 OpenAI 모델",
    "image_prompt_generation_model": "이미지 프롬프트 정제에 쓰는 텍스트 모델",
    "revision_pass_model": "최종 수정 패스 모델",
    "post_review_model": "게시 검토 모델",
    "openai_image_model": "기본 OpenAI 이미지 모델",
    "openai_request_saver_mode": "추가 요청을 줄이는 절약 모드 사용 여부",
    "openai_api_key": "OpenAI API 키",
    "openai_admin_api_key": "OpenAI Admin API 키",
    "gemini_api_key": "Gemini API 키",
    "gemini_model": "Gemini 기본 모델",
    "topic_discovery_provider": "토픽 발굴 공급자",
    "topic_discovery_model": "OpenAI 토픽 발굴 모델",
    "topic_discovery_max_topics_per_run": "토픽 발굴 1회 최대 생성 수",
    "cloudflare_channel_enabled": "Cloudflare 채널 연동 사용 여부",
    "cloudflare_blog_api_base_url": "Cloudflare 연동 API 기준 주소",
    "cloudflare_blog_m2m_token": "Cloudflare 연동용 Bearer 토큰",
    "blogger_client_name": "Blogger OAuth 앱 이름",
    "blogger_client_id": "Blogger OAuth 클라이언트 ID",
    "blogger_client_secret": "Blogger OAuth 클라이언트 시크릿",
    "blogger_redirect_uri": "Blogger OAuth 리디렉션 URI",
    "youtube_default_privacy_status": "YouTube 기본 업로드 공개 상태",
    "meta_graph_api_version": "Instagram/Meta Graph API 버전",
    "instagram_client_id": "Instagram/Meta 앱 클라이언트 ID",
    "instagram_client_secret": "Instagram/Meta 앱 클라이언트 시크릿",
    "instagram_redirect_uri": "Instagram/Meta OAuth 리디렉션 URI",
    "instagram_publish_api_enabled": "Instagram 실게시 어댑터 활성화 여부",
    "blogger_playwright_enabled": "Blogger Playwright 자동화 사용 여부",
    "blogger_playwright_auto_sync": "발행 후 Blogger 메타 자동 동기화 사용 여부",
    "blogger_playwright_cdp_url": "Blogger Playwright 원격 디버깅 URL",
    "blogger_playwright_account_index": "Blogger 편집기 계정 인덱스",
    "google_sheet_url": "운영 스냅샷 동기화용 Google Sheets URL",
    "google_sheet_id": "Google Sheets URL에서 추출한 문서 ID",
    "google_sheet_travel_tab": "여행 채널 스냅샷 탭 이름",
    "google_sheet_mystery_tab": "미스터리 채널 스냅샷 탭 이름",
    "google_sheet_cloudflare_tab": "Cloudflare 채널 스냅샷 탭 이름",
    "schedule_enabled": "전역 자동 스케줄러 사용",
    "schedule_time": "전역 스케줄러 실행 시각(HH:MM)",
    "schedule_timezone": "전역 스케줄러 시간대",
    "travel_schedule_time": "여행 채널 반복 시작 시각(HH:MM)",
    "travel_schedule_interval_hours": "여행 채널 반복 간격(시간)",
    "travel_topics_per_run": "여행 채널 회차당 생성 주제 수",
    "mystery_schedule_time": "미스터리 채널 반복 시작 시각(HH:MM)",
    "mystery_schedule_interval_hours": "미스터리 채널 반복 간격(시간)",
    "mystery_topics_per_run": "미스터리 채널 회차당 생성 주제 수",
    "topics_per_run": "기본 반복 실행당 생성 주제 수",
    "sheet_sync_enabled": "주간 Google Sheets 동기화 사용 여부",
    "sheet_sync_day": "주간 Google Sheets 동기화 요일",
    "sheet_sync_time": "주간 Google Sheets 동기화 시각(HH:MM)",
    "quality_gate_enabled": "발행 전 품질 게이트 사용",
    "quality_gate_similarity_threshold": "품질 게이트 유사도 기준(0-100)",
    "quality_gate_min_seo_score": "품질 게이트 최소 SEO 점수(0-100)",
    "quality_gate_min_geo_score": "품질 게이트 최소 GEO 점수(0-100)",
    "quality_gate_min_ctr_score": "품질 게이트 최소 CTR 점수(0-100)",
    "similarity_threshold": "기본 유사도 임계치",
    "topic_history_lookback_days": "토픽 히스토리 조회 기간(일)",
    "topic_novelty_cluster_threshold": "클러스터 신규성 임계치",
    "topic_novelty_angle_threshold": "앵글 신규성 임계치",
    "topic_soft_penalty_threshold": "소프트 패널티 임계치",
    "travel_editorial_weights": "여행 카테고리 가중치 회전 설정",
    "mystery_editorial_weights": "미스터리 카테고리 가중치 회전 설정",
    "cloudflare_daily_publish_enabled": "Cloudflare 일간 자동 발행 사용",
    "cloudflare_daily_publish_time": "Cloudflare 자동 발행 시작 시각(HH:MM)",
    "cloudflare_daily_publish_interval_hours": "Cloudflare 자동 발행 간격(시간)",
    "cloudflare_daily_publish_timezone": "Cloudflare 자동 발행 시간대",
    "cloudflare_daily_publish_weekday_quota": "월~토 Cloudflare 하루 발행 수",
    "cloudflare_daily_publish_sunday_quota": "일요일 Cloudflare 하루 발행 수",
    "google_indexing_policy_mode": "Google 색인 정책 모드(mixed 고정)",
    "google_indexing_daily_quota": "Google 색인 API 하루 요청 상한(프로젝트 기준)",
    "google_indexing_cooldown_days": "같은 URL 자동 색인 재요청 쿨다운(일)",
    "google_indexing_blog_quota_map": "블로그별 하루 색인 요청 배분(JSON)",
    "travel_blossom_cap_ratio": "여행 채널 벚꽃 주제 상한 비율",
    "cloudflare_blossom_cap_ratio": "Cloudflare 채널 벚꽃 주제 상한 비율",
    "cloudflare_inline_images_enabled": "Cloudflare 본문 인라인 이미지 사용",
    "cloudflare_require_cover_image": "Cloudflare 발행 시 대표 이미지 필수",
    "travel_inline_collage_enabled": "여행 본문 인라인 콜라주 사용",
    "mystery_inline_collage_enabled": "미스터리 본문 인라인 콜라주 사용",
    "wikimedia_image_count": "Wikimedia 이미지 최대 수",
    "training_schedule_enabled": "일간 학습 스케줄 사용",
    "training_schedule_time": "학습 스케줄 실행 시각(HH:MM)",
    "training_schedule_timezone": "학습 스케줄 시간대",
    "training_use_real_engine": "시뮬레이션 대신 실제 학습 엔진을 실행할지 결정",
    "content_ops_scan_enabled": "5분 주기 라이브 콘텐츠 검토 스캔 사용",
    "content_ops_auto_fix_drafts": "안전한 초안 자동 수정 사용",
    "content_ops_auto_fix_published_meta": "안전한 발행 글 메타 자동 수정 사용",
    "content_ops_learning_paused": "학습/스냅샷 자동화를 일시 중지",
    "publish_daily_limit_per_blog": "블로그별 하루 발행 제한 수",
    "publish_min_interval_seconds": "같은 블로그 발행 최소 간격(초)",
    "publish_interval_minutes": "기존 발행 간격 별칭(분)",
    "backlog_publish_interval_minutes": "백로그 발행 간격 별칭(분)",
    "first_publish_delay_minutes": "첫 발행 지연 시간(분)",
    "scheduled_batch_interval_minutes": "배치 슬롯 간격(분)",
    "same_cluster_cooldown_hours": "동일 클러스터 반복 쿨다운(시간)",
    "same_angle_cooldown_days": "동일 앵글 반복 쿨다운(일)",
    "topic_guard_enabled": "토픽 메모리 기반 중복 방지 사용",
    "travel_research_mode": "여행 채널 사실 확인 모드",
}

for key, description in SETTING_DESCRIPTION_OVERRIDES_KO.items():
    if key in DEFAULT_SETTINGS:
        DEFAULT_SETTINGS[key].description = description

GOOGLE_SHEET_ID_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def _extract_google_sheet_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = GOOGLE_SHEET_ID_PATTERN.search(raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", raw):
        return raw
    return ""


def ensure_default_settings(db: Session) -> None:
    existing = {item.key: item for item in db.execute(select(Setting)).scalars().all()}
    changed = False
    for key, default in DEFAULT_SETTINGS.items():
        item = existing.get(key)
        if item:
            if item.description != default.description:
                item.description = default.description
                changed = True
            if item.is_secret != default.is_secret:
                item.is_secret = default.is_secret
                changed = True
            if item.is_secret and item.value and not is_encrypted_secret(item.value):
                item.value = encrypt_secret_value(item.value)
                changed = True
            continue
        db.add(
            Setting(
                key=key,
                value=encrypt_secret_value(default.value) if default.is_secret and default.value else default.value,
                description=default.description,
                is_secret=default.is_secret,
            )
        )
        changed = True
    for key, description in SETTING_DESCRIPTION_OVERRIDES_KO.items():
        item = existing.get(key)
        if item and item.description != description:
            item.description = description
            changed = True
    if changed:
        db.commit()


def get_settings_map(db: Session) -> dict[str, str]:
    ensure_default_settings(db)
    items = db.execute(select(Setting).order_by(Setting.key.asc())).scalars().all()
    return {item.key: decrypt_secret_value(item.value) if item.is_secret else item.value for item in items}


def list_settings(db: Session) -> list[Setting]:
    ensure_default_settings(db)
    return db.execute(select(Setting).order_by(Setting.key.asc())).scalars().all()


def upsert_settings(db: Session, values: dict[str, str]) -> list[Setting]:
    ensure_default_settings(db)
    normalized_values = dict(values)
    if "google_sheet_url" in normalized_values:
        normalized_values["google_sheet_id"] = _extract_google_sheet_id(normalized_values.get("google_sheet_url", ""))
    existing = {item.key: item for item in db.execute(select(Setting)).scalars().all()}
    for key, value in normalized_values.items():
        if key in existing:
            if existing[key].is_secret and not str(value).strip():
                continue
            existing[key].value = encrypt_secret_value(value) if existing[key].is_secret else value
            continue
        meta = DEFAULT_SETTINGS.get(key, DefaultSetting("", SETTING_DESCRIPTION_OVERRIDES_KO.get(key, "User-defined setting")))
        db.add(
            Setting(
                key=key,
                value=encrypt_secret_value(value) if meta.is_secret else value,
                description=SETTING_DESCRIPTION_OVERRIDES_KO.get(key, meta.description),
                is_secret=meta.is_secret,
            )
        )
    db.commit()
    return list_settings(db)


def get_blogger_config(db: Session) -> dict:
    from app.services.blog_service import list_blog_profiles, list_blogs

    values = get_settings_map(db)
    blogs = list_blogs(db)
    return {
        "client_name": values.get("blogger_client_name", ""),
        "client_id_configured": bool(values.get("blogger_client_id", "").strip()),
        "client_secret_configured": bool(values.get("blogger_client_secret", "").strip()),
        "access_token_configured": bool(values.get("blogger_access_token", "").strip()),
        "refresh_token_configured": bool(values.get("blogger_refresh_token", "").strip()),
        "redirect_uri": values.get("blogger_redirect_uri", ""),
        "default_publish_mode": values.get("default_publish_mode", settings.default_publish_mode),
        "profiles": list_blog_profiles(),
        "imported_blogger_blog_ids": [blog.blogger_blog_id for blog in blogs if (blog.blogger_blog_id or "").strip()],
        "blogs": [
            {
                "id": blog.id,
                "name": blog.name,
                "blogger_blog_id": blog.blogger_blog_id or "",
                "blogger_url": blog.blogger_url or "",
                "search_console_site_url": blog.search_console_site_url or "",
                "ga4_property_id": blog.ga4_property_id or "",
                "publish_mode": blog.publish_mode.value,
                "is_active": blog.is_active,
            }
            for blog in blogs
        ],
    }

"use client";

import { type ReactNode, useEffect, useMemo, useRef, useState, useTransition } from "react";

import {
  createChannelPromptFlowStep,
  deleteChannelPromptFlowStep,
  getBlogArchive,
  getBloggerConfig,
  getBlogs,
  getChannelPromptFlow,
  getChannels,
  getCloudflarePosts,
  getModelPolicy,
  reorderChannelPromptFlow,
  updateChannelPromptFlowStep,
  updateSettings,
} from "@/lib/api";
import type {
  Blog,
  BloggerConfigRead,
  ManagedChannelRead,
  ModelPolicyRead,
  PromptFlowRead,
  PromptFlowStepRead,
  SettingRead,
  WorkflowStageType,
} from "@/lib/types";

type SettingsConsoleProps = {
  settings: SettingRead[];
  config: BloggerConfigRead;
};

type SettingsTab = "workspace" | "channels" | "pipeline" | "models" | "planner" | "automation" | "publishing" | "integrations";

type PreviewItem = {
  id: string;
  title: string;
  url: string | null;
  publishedAt: string | null;
};

type StepDraft = {
  id: string;
  name: string;
  objective: string;
  promptTemplate: string;
  providerModel: string;
  isEnabled: boolean;
};

type SettingControlKind = "text" | "textarea" | "password" | "number" | "boolean" | "select" | "time" | "url";

type SettingOption = {
  value: string;
  label: string;
};

type SettingSection = {
  id: string;
  key: SettingsTab;
  title: string;
  description: string;
  keys: string[];
};

const GOOGLE_INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing";

const TABS: Array<{ key: SettingsTab; label: string }> = [
  { key: "workspace", label: "개요" },
  { key: "channels", label: "채널 관리" },
  { key: "pipeline", label: "프롬프트 플로우" },
  { key: "models", label: "모델" },
  { key: "planner", label: "일정 / 플래너" },
  { key: "automation", label: "자동화" },
  { key: "publishing", label: "품질 / 발행" },
  { key: "integrations", label: "연동" },
];

const STAGE_LABELS: Record<string, string> = {
  topic_discovery: "주제 발굴",
  article_generation: "글 작성",
  image_prompt_generation: "이미지 프롬프트",
  related_posts: "관련 글",
  image_generation: "이미지 생성",
  html_assembly: "HTML 조립",
  publishing: "발행",
};

const STAGE_ORDER: WorkflowStageType[] = [
  "topic_discovery",
  "article_generation",
  "image_prompt_generation",
  "related_posts",
  "image_generation",
  "html_assembly",
  "publishing",
];

const SECTION_DEFS: SettingSection[] = [
  {
    id: "workspace-core",
    key: "workspace",
    title: "운영 기본값",
    description: "서비스 이름, 실행 모드, 관리자 접근 같은 전역 기본값입니다.",
    keys: ["app_name", "provider_mode", "default_publish_mode", "default_writer_tone", "admin_auth_enabled", "admin_auth_username"],
  },
  {
    id: "models-core",
    key: "models",
    title: "생성 모델 라우팅",
    description: "토픽 발굴과 글·이미지 생성에 쓰는 모델을 관리합니다.",
    keys: [
      "topic_discovery_provider",
      "topic_discovery_model",
      "gemini_topic_model",
      "gemini_model",
      "openai_text_model",
      "openai_large_text_model",
      "openai_small_text_model",
      "openai_image_model",
      "article_generation_model",
      "image_prompt_generation_model",
      "revision_pass_model",
      "post_review_model",
      "openai_request_saver_mode",
    ],
  },
  {
    id: "planner-core",
    key: "planner",
    title: "플래너 기준값",
    description: "일간 계획 화면의 기본 슬롯과 전역 스케줄 기준입니다.",
    keys: [
      "planner_default_daily_posts",
      "planner_day_start_time",
      "planner_day_end_time",
      "schedule_enabled",
      "schedule_time",
      "schedule_timezone",
      "topics_per_run",
      "topic_discovery_max_topics_per_run",
    ],
  },
  {
    id: "planner-channel",
    key: "planner",
    title: "채널 일정",
    description: "여행, 미스테리, Cloudflare 채널의 반복 일정과 시트/학습 스케줄입니다.",
    keys: [
      "travel_schedule_time",
      "travel_schedule_interval_hours",
      "travel_topics_per_run",
      "travel_research_mode",
      "travel_blossom_cap_ratio",
      "mystery_schedule_time",
      "mystery_schedule_interval_hours",
      "mystery_topics_per_run",
      "cloudflare_daily_publish_enabled",
      "cloudflare_daily_publish_time",
      "cloudflare_daily_publish_timezone",
      "cloudflare_daily_publish_interval_hours",
      "cloudflare_daily_publish_weekday_quota",
      "cloudflare_daily_publish_sunday_quota",
      "cloudflare_blossom_cap_ratio",
      "sheet_sync_enabled",
      "sheet_sync_day",
      "sheet_sync_time",
      "training_schedule_enabled",
      "training_schedule_time",
      "training_schedule_timezone",
    ],
  },
  {
    id: "automation-core",
    key: "automation",
    title: "자동화 게이트",
    description: "전역 자동화 허용과 도메인별 자동화 토글입니다.",
    keys: [
      "automation_master_enabled",
      "automation_scheduler_enabled",
      "automation_publish_queue_enabled",
      "automation_cloudflare_enabled",
      "automation_content_review_enabled",
      "automation_sheet_enabled",
      "automation_telegram_enabled",
      "automation_training_enabled",
      "content_ops_scan_enabled",
      "content_ops_auto_fix_drafts",
      "content_ops_auto_fix_published_meta",
      "content_ops_learning_paused",
      "training_use_real_engine",
    ],
  },
  {
    id: "publishing-gate",
    key: "publishing",
    title: "품질·발행 게이트",
    description: "발행 전 품질 기준과 실제 발행 간격을 수치로 관리합니다.",
    keys: [
      "quality_gate_enabled",
      "quality_gate_min_seo_score",
      "quality_gate_min_geo_score",
      "quality_gate_similarity_threshold",
      "similarity_threshold",
      "topic_guard_enabled",
      "topic_history_lookback_days",
      "topic_novelty_cluster_threshold",
      "topic_novelty_angle_threshold",
      "topic_soft_penalty_threshold",
      "same_cluster_cooldown_hours",
      "same_angle_cooldown_days",
      "publish_daily_limit_per_blog",
      "publish_min_interval_seconds",
      "publish_interval_minutes",
      "backlog_publish_interval_minutes",
      "first_publish_delay_minutes",
      "scheduled_batch_interval_minutes",
    ],
  },
  {
    id: "integrations-blogger",
    key: "integrations",
    title: "Blogger / Google",
    description: "Blogger OAuth와 시트 기반 연동 정보입니다.",
    keys: [
      "blogger_client_name",
      "blogger_client_id",
      "blogger_client_secret",
      "blogger_redirect_uri",
      "google_sheet_url",
      "google_sheet_id",
      "google_sheet_travel_tab",
      "google_sheet_mystery_tab",
      "google_sheet_cloudflare_tab",
    ],
  },
  {
    id: "integrations-media",
    key: "integrations",
    title: "공개 이미지 전달",
    description: "R2, Cloudinary, GitHub Pages, 로컬 자산 전달 구성을 관리합니다.",
    keys: [
      "public_image_provider",
      "public_asset_base_url",
      "cloudflare_account_id",
      "cloudflare_r2_bucket",
      "cloudflare_r2_access_key_id",
      "cloudflare_r2_secret_access_key",
      "cloudflare_r2_public_base_url",
      "cloudflare_r2_prefix",
      "cloudinary_cloud_name",
      "cloudinary_api_key",
      "cloudinary_api_secret",
      "cloudinary_folder",
      "github_pages_owner",
      "github_pages_repo",
      "github_pages_branch",
      "github_pages_token",
      "github_pages_base_url",
      "github_pages_assets_dir",
      "cloudflare_inline_images_enabled",
      "cloudflare_cdn_transform_enabled",
      "travel_inline_collage_enabled",
      "mystery_inline_collage_enabled",
      "wikimedia_image_count",
    ],
  },
  {
    id: "integrations-runtime",
    key: "integrations",
    title: "런타임 연동",
    description: "Cloudflare API, AI 공급자 키, Telegram, Playwright 연결입니다.",
    keys: [
      "cloudflare_channel_enabled",
      "cloudflare_blog_api_base_url",
      "cloudflare_blog_m2m_token",
      "openai_api_key",
      "openai_admin_api_key",
      "gemini_api_key",
      "telegram_bot_token",
      "telegram_chat_id",
      "blogger_playwright_enabled",
      "blogger_playwright_auto_sync",
      "blogger_playwright_cdp_url",
      "blogger_playwright_account_index",
    ],
  },
];

const FIELD_LABELS: Record<string, string> = {
  app_name: "서비스 이름",
  provider_mode: "실행 모드",
  default_publish_mode: "기본 발행 모드",
  default_writer_tone: "기본 작성 톤",
  admin_auth_enabled: "관리자 인증 사용",
  admin_auth_username: "관리자 사용자명",
  topics_per_run: "전역 회차당 주제 수",
  planner_default_daily_posts: "일일 기본 슬롯 수",
  planner_day_start_time: "운영 시작 시각",
  planner_day_end_time: "운영 종료 시각",
  topic_discovery_provider: "토픽 발굴 공급자",
  topic_discovery_model: "OpenAI 토픽 모델",
  topic_discovery_max_topics_per_run: "최대 토픽 생성 수",
  gemini_topic_model: "Gemini 토픽 모델",
  gemini_model: "Gemini 기본 모델",
  openai_text_model: "기본 텍스트 모델",
  openai_large_text_model: "대형 텍스트 모델",
  openai_small_text_model: "소형 텍스트 모델",
  openai_image_model: "이미지 생성 모델",
  article_generation_model: "글 작성 모델",
  image_prompt_generation_model: "이미지 프롬프트 모델",
  revision_pass_model: "수정 패스 모델",
  post_review_model: "게시 검토 모델",
  openai_request_saver_mode: "요청 절약 모드",
  quality_gate_enabled: "품질 게이트 사용",
  quality_gate_min_seo_score: "최소 SEO 점수",
  quality_gate_min_geo_score: "최소 GEO 점수",
  quality_gate_similarity_threshold: "품질 게이트 유사도",
  similarity_threshold: "기본 유사도 임계치",
  topic_guard_enabled: "토픽 중복 방지",
  topic_history_lookback_days: "토픽 히스토리 조회 일수",
  topic_novelty_cluster_threshold: "클러스터 신규성 임계치",
  topic_novelty_angle_threshold: "앵글 신규성 임계치",
  topic_soft_penalty_threshold: "소프트 패널티 임계치",
  same_cluster_cooldown_hours: "동일 클러스터 쿨다운(시간)",
  same_angle_cooldown_days: "동일 앵글 쿨다운(일)",
  public_image_provider: "공개 이미지 공급자",
  public_asset_base_url: "로컬 공개 기준 URL",
  blogger_client_name: "OAuth 앱 이름",
  blogger_client_id: "OAuth 클라이언트 ID",
  blogger_client_secret: "OAuth 클라이언트 시크릿",
  blogger_redirect_uri: "리디렉션 URI",
  cloudflare_blog_api_base_url: "Cloudflare API 기준 URL",
  cloudflare_blog_m2m_token: "Cloudflare M2M 토큰",
  telegram_bot_token: "Telegram Bot 토큰",
  telegram_chat_id: "Telegram Chat ID",
  blogger_playwright_enabled: "Blogger Playwright 사용",
  blogger_playwright_auto_sync: "발행 후 자동 동기화",
  blogger_playwright_cdp_url: "CDP URL",
  blogger_playwright_account_index: "계정 인덱스",
  automation_master_enabled: "자동화 전체 마스터 스위치",
  automation_scheduler_enabled: "스케줄러 자동화 사용",
  automation_publish_queue_enabled: "발행 큐 자동화 사용",
  automation_cloudflare_enabled: "Cloudflare 자동화 사용",
  automation_content_review_enabled: "콘텐츠 검토 자동화 사용",
  automation_sheet_enabled: "시트 자동화 사용(구형)",
  automation_telegram_enabled: "텔레그램 자동화 사용",
  automation_training_enabled: "학습 자동화 사용",
  content_ops_scan_enabled: "실시간 콘텐츠 검토 스캔",
  content_ops_auto_fix_drafts: "초안 자동 수정",
  content_ops_auto_fix_published_meta: "발행 글 메타 자동 수정",
  content_ops_learning_paused: "학습 자동화 일시 중지",
  training_use_real_engine: "실제 학습 엔진 사용",
  schedule_enabled: "전역 스케줄러 사용",
  schedule_time: "전역 스케줄 실행 시각",
  schedule_timezone: "전역 스케줄 시간대",
  travel_schedule_time: "여행 채널 시작 시각",
  travel_schedule_interval_hours: "여행 채널 반복 간격(시간)",
  travel_topics_per_run: "여행 채널 회차당 주제 수",
  travel_research_mode: "여행 리서치 모드",
  travel_blossom_cap_ratio: "여행 Blossom 상한 비율",
  mystery_schedule_time: "미스터리 채널 시작 시각",
  mystery_schedule_interval_hours: "미스터리 채널 반복 간격(시간)",
  mystery_topics_per_run: "미스터리 채널 회차당 주제 수",
  cloudflare_daily_publish_enabled: "Cloudflare 일간 발행 사용",
  cloudflare_daily_publish_time: "Cloudflare 시작 시각",
  cloudflare_daily_publish_timezone: "Cloudflare 시간대",
  cloudflare_daily_publish_interval_hours: "Cloudflare 반복 간격(시간)",
  cloudflare_daily_publish_weekday_quota: "Cloudflare 평일 발행 수",
  cloudflare_daily_publish_sunday_quota: "Cloudflare 일요일 발행 수",
  cloudflare_blossom_cap_ratio: "Cloudflare Blossom 상한 비율",
  cloudflare_channel_enabled: "Cloudflare 채널 연동 사용",
  openai_api_key: "OpenAI API 키",
  openai_admin_api_key: "OpenAI Admin API 키",
  gemini_api_key: "Gemini API 키",
  google_sheet_url: "Google Sheets URL",
  google_sheet_id: "Google Sheets 문서 ID",
  google_sheet_travel_tab: "여행 시트 탭 이름",
  google_sheet_mystery_tab: "미스터리 시트 탭 이름",
  google_sheet_cloudflare_tab: "Cloudflare 시트 탭 이름",
  sheet_sync_enabled: "시트 동기화 사용",
  sheet_sync_day: "시트 동기화 요일",
  sheet_sync_time: "시트 동기화 시각",
  publish_daily_limit_per_blog: "채널별 일일 발행 한도",
  publish_min_interval_seconds: "최소 발행 간격(초)",
  publish_interval_minutes: "기본 발행 간격(분)",
  backlog_publish_interval_minutes: "백로그 발행 간격(분)",
  first_publish_delay_minutes: "첫 발행 대기(분)",
  scheduled_batch_interval_minutes: "예약 배치 간격(분)",
  cloudflare_account_id: "Cloudflare 계정 ID",
  cloudflare_r2_bucket: "R2 버킷 이름",
  cloudflare_r2_access_key_id: "R2 Access Key ID",
  cloudflare_r2_secret_access_key: "R2 Secret Access Key",
  cloudflare_r2_public_base_url: "R2 공개 기준 URL",
  cloudflare_r2_prefix: "R2 저장 경로 접두사",
  cloudflare_cdn_transform_enabled: "Cloudflare 이미지 변환 URL 사용",
  cloudflare_inline_images_enabled: "Cloudflare 인라인 이미지 사용",
  travel_inline_collage_enabled: "여행 인라인 콜라주 사용",
  mystery_inline_collage_enabled: "미스터리 인라인 콜라주 사용",
  training_schedule_enabled: "학습 스케줄 사용",
  training_schedule_time: "학습 실행 시각",
  training_schedule_timezone: "학습 시간대",
  wikimedia_image_count: "Wikimedia 이미지 수",
  cloudinary_cloud_name: "Cloudinary 클라우드 이름",
  cloudinary_api_key: "Cloudinary API 키",
  cloudinary_api_secret: "Cloudinary API 시크릿",
  cloudinary_folder: "Cloudinary 폴더",
  github_pages_owner: "GitHub Pages 소유자",
  github_pages_repo: "GitHub Pages 저장소",
  github_pages_branch: "GitHub Pages 브랜치",
  github_pages_token: "GitHub Pages 토큰",
  github_pages_base_url: "GitHub Pages 기준 URL",
  github_pages_assets_dir: "GitHub Pages 자산 경로",
};

const FIELD_DESCRIPTIONS: Record<string, string> = {
  app_name: "관리 콘솔과 화면 상단에 표시되는 워크스페이스 이름입니다.",
  provider_mode: "실제 공급자를 호출할지, 목업 모드로 실행할지 결정합니다.",
  default_publish_mode: "새 작업과 플래너 실행이 기본으로 저장할 발행 상태입니다.",
  default_writer_tone: "글 생성 프롬프트에 기본 톤으로 전달하는 운영 라벨입니다.",
  admin_auth_enabled: "관리 콘솔 접근에 로그인 인증을 요구합니다.",
  admin_auth_username: "관리자 로그인 시 사용할 기본 계정 이름입니다.",
  topics_per_run: "전역 스케줄 한 번에 처리할 기본 주제 수입니다.",
  planner_default_daily_posts: "월간 계획을 만들 때 날짜별 기본 슬롯 수로 사용합니다.",
  planner_day_start_time: "플래너 자동 배치가 시작되는 기본 시각입니다.",
  planner_day_end_time: "플래너 자동 배치가 끝나는 기본 시각입니다.",
  topic_discovery_provider: "토픽 발굴을 OpenAI와 Gemini 중 어디로 보낼지 결정합니다.",
  topic_discovery_model: "OpenAI 기반 토픽 발굴에 사용할 기본 모델입니다.",
  topic_discovery_max_topics_per_run: "한 번의 토픽 발굴에서 큐에 올릴 최대 주제 수입니다.",
  gemini_topic_model: "Gemini 기반 토픽 발굴에 사용할 모델 이름입니다.",
  gemini_model: "Gemini 일반 생성 작업에 사용할 기본 모델입니다.",
  openai_text_model: "일반 텍스트 보조 작업에 쓰는 기본 OpenAI 모델입니다.",
  openai_large_text_model: "긴 글이나 복잡한 생성 작업에 쓰는 대형 OpenAI 모델입니다.",
  openai_small_text_model: "가벼운 보조 작업에 쓰는 소형 OpenAI 모델입니다.",
  openai_image_model: "대표 이미지 생성에 사용할 OpenAI 이미지 모델입니다.",
  article_generation_model: "본문 생성과 리라이트에 쓰는 주력 모델입니다.",
  image_prompt_generation_model: "이미지 프롬프트를 다듬는 데 쓰는 모델입니다.",
  revision_pass_model: "초안 수정 패스에서 사용하는 모델입니다.",
  post_review_model: "발행 전 검토와 평가 단계에서 사용하는 모델입니다.",
  openai_request_saver_mode: "가능하면 추가 요청을 줄여 비용과 호출량을 아낍니다.",
  automation_master_enabled: "모든 자동화 경로를 한 번에 허용하거나 차단하는 최상위 스위치입니다.",
  automation_scheduler_enabled: "정시 스케줄러 자동 실행을 허용합니다.",
  automation_publish_queue_enabled: "발행 큐 자동 처리를 허용합니다.",
  automation_cloudflare_enabled: "Cloudflare 채널 자동화를 허용합니다.",
  automation_content_review_enabled: "콘텐츠 품질 검토 자동화를 허용합니다.",
  automation_sheet_enabled: "기존 Google Sheets 자동화 플래그입니다.",
  automation_telegram_enabled: "텔레그램 운영 명령 폴링 자동화를 허용합니다.",
  automation_training_enabled: "학습 세션 자동 실행을 허용합니다.",
  content_ops_scan_enabled: "5분 주기 라이브 콘텐츠 검토 스캔을 켭니다.",
  content_ops_auto_fix_drafts: "위험도가 낮은 초안 수정은 자동 반영합니다.",
  content_ops_auto_fix_published_meta: "발행 글의 안전한 메타와 검색설명 수정은 자동 반영합니다.",
  content_ops_learning_paused: "예약된 학습 스냅샷과 학습 작업을 일시 중지합니다.",
  schedule_enabled: "전역 스케줄러 자체를 켜거나 끕니다.",
  schedule_time: "전역 스케줄러 실행 시각입니다.",
  schedule_timezone: "전역 스케줄러 기준 시간대입니다.",
  travel_schedule_time: "여행 채널 자동 생성이 시작되는 시각입니다.",
  travel_schedule_interval_hours: "여행 채널 자동 생성 반복 간격입니다.",
  travel_topics_per_run: "여행 채널 한 번 실행 시 생성할 주제 수입니다.",
  mystery_schedule_time: "미스터리 채널 자동 생성이 시작되는 시각입니다.",
  mystery_schedule_interval_hours: "미스터리 채널 자동 생성 반복 간격입니다.",
  mystery_topics_per_run: "미스터리 채널 한 번 실행 시 생성할 주제 수입니다.",
  training_schedule_enabled: "정해진 시각에 학습과 리포트 작업을 자동 실행합니다.",
  training_schedule_time: "학습 자동화가 시작되는 시각입니다.",
  training_schedule_timezone: "학습 자동화 기준 시간대입니다.",
  cloudflare_daily_publish_enabled: "Cloudflare 채널의 일간 자동 발행 스케줄을 사용합니다.",
  cloudflare_daily_publish_time: "Cloudflare 채널 자동 발행 시작 시각입니다.",
  cloudflare_daily_publish_timezone: "Cloudflare 채널 자동 발행 시간대입니다.",
  cloudflare_daily_publish_interval_hours: "Cloudflare 채널 자동 발행 반복 간격입니다.",
  cloudflare_daily_publish_weekday_quota: "월요일부터 토요일까지 하루 발행 개수입니다.",
  cloudflare_daily_publish_sunday_quota: "일요일 하루 발행 개수입니다.",
  travel_blossom_cap_ratio: "여행 채널에서 Blossom 계열 주제 비중 상한입니다.",
  cloudflare_blossom_cap_ratio: "Cloudflare 채널에서 Blossom 계열 주제 비중 상한입니다.",
  travel_research_mode: "여행 채널 리서치 방식을 운영 모드에 맞게 조정합니다.",
  sheet_sync_enabled: "정해진 요일과 시각에 Google Sheets 동기화를 실행합니다.",
  sheet_sync_day: "시트 동기화를 수행할 요일입니다.",
  sheet_sync_time: "시트 동기화를 수행할 시각입니다.",
  quality_gate_enabled: "발행 전 중복도·SEO·GEO 기준을 검사합니다.",
  quality_gate_min_seo_score: "품질 게이트에서 요구하는 최소 SEO 점수입니다.",
  quality_gate_min_geo_score: "품질 게이트에서 요구하는 최소 GEO 점수입니다.",
  quality_gate_similarity_threshold: "중복 위험으로 간주하는 최대 유사도 기준입니다.",
  similarity_threshold: "전역 기본 중복 판단 임계치입니다.",
  topic_guard_enabled: "과거 주제 기록을 기준으로 중복 발행을 막습니다.",
  topic_history_lookback_days: "과거 토픽 이력을 되돌아보는 조회 기간입니다.",
  topic_novelty_cluster_threshold: "같은 클러스터로 판단하는 유사도 기준입니다.",
  topic_novelty_angle_threshold: "같은 앵글로 판단하는 유사도 기준입니다.",
  topic_soft_penalty_threshold: "완전 차단 대신 감점 처리할 중복 위험 기준입니다.",
  same_cluster_cooldown_hours: "같은 클러스터 재사용을 막는 최소 시간입니다.",
  same_angle_cooldown_days: "같은 앵글 재사용을 막는 최소 일수입니다.",
  publish_daily_limit_per_blog: "채널별 하루 최대 발행 수입니다.",
  publish_min_interval_seconds: "연속 발행 사이에 반드시 확보할 최소 초 단위 간격입니다.",
  publish_interval_minutes: "기본 발행 큐 처리 간격입니다.",
  backlog_publish_interval_minutes: "백로그를 밀어낼 때 사용하는 발행 간격입니다.",
  first_publish_delay_minutes: "큐에 올린 뒤 첫 발행까지 기다리는 시간입니다.",
  scheduled_batch_interval_minutes: "예약 발행 배치를 묶어 처리하는 간격입니다.",
  public_image_provider: "대표 이미지와 인라인 이미지를 공개하는 저장소입니다.",
  public_asset_base_url: "로컬 공개 서버를 쓸 때 자산 URL의 기준 주소입니다.",
  cloudflare_account_id: "Cloudflare API와 R2에 연결할 계정 ID입니다.",
  cloudflare_r2_bucket: "이미지를 업로드할 Cloudflare R2 버킷 이름입니다.",
  cloudflare_r2_access_key_id: "Cloudflare R2 업로드용 액세스 키 ID입니다.",
  cloudflare_r2_secret_access_key: "Cloudflare R2 업로드용 비밀 키입니다.",
  cloudflare_r2_public_base_url: "R2 자산을 공개할 때 사용할 기준 URL입니다.",
  cloudflare_r2_prefix: "버킷 내부에서 파일을 저장할 접두 경로입니다.",
  cloudflare_cdn_transform_enabled: "Cloudflare 이미지 변환 URL(/cdn-cgi/image) 사용 여부를 결정합니다.",
  cloudflare_inline_images_enabled: "본문 중간 이미지도 Cloudflare 공개 경로를 사용합니다.",
  cloudflare_blog_api_base_url: "Cloudflare 통합 API의 기준 주소입니다.",
  cloudflare_blog_m2m_token: "Cloudflare 통합 API 호출용 M2M 토큰입니다.",
  cloudflare_channel_enabled: "Cloudflare 채널 연동 자체를 사용합니다.",
  openai_api_key: "OpenAI 호출에 사용할 기본 API 키입니다.",
  openai_admin_api_key: "사용량과 관리 API 조회에 사용할 OpenAI Admin 키입니다.",
  gemini_api_key: "Gemini API 호출에 사용할 키입니다.",
  google_sheet_url: "운영 스냅샷과 품질 시트 동기화에 쓰는 Google Sheets 주소입니다.",
  google_sheet_id: "Google Sheets URL에서 추출된 문서 ID입니다.",
  google_sheet_travel_tab: "여행 채널 데이터를 쓰는 시트 탭 이름입니다.",
  google_sheet_mystery_tab: "미스터리 채널 데이터를 쓰는 시트 탭 이름입니다.",
  google_sheet_cloudflare_tab: "Cloudflare 채널 데이터를 쓰는 시트 탭 이름입니다.",
  blogger_client_name: "Blogger OAuth 앱을 구분하는 표시 이름입니다.",
  blogger_client_id: "Blogger와 Google OAuth 클라이언트 ID입니다.",
  blogger_client_secret: "Blogger와 Google OAuth 클라이언트 시크릿입니다.",
  blogger_redirect_uri: "OAuth 인증 후 되돌아올 리디렉션 주소입니다.",
  blogger_playwright_enabled: "Blogger 편집기 자동화를 허용합니다.",
  blogger_playwright_auto_sync: "발행 후 검색 설명 동기화를 자동 실행합니다.",
  blogger_playwright_cdp_url: "Playwright가 붙을 원격 디버깅 주소입니다.",
  blogger_playwright_account_index: "Blogger 편집기에 사용할 계정 인덱스입니다.",
  telegram_bot_token: "운영 알림과 명령을 받을 Telegram Bot 토큰입니다.",
  telegram_chat_id: "알림을 보낼 Telegram 채팅 ID입니다.",
  training_use_real_engine: "학습 자동화에서 실제 엔진을 호출할지 결정합니다.",
  travel_inline_collage_enabled: "여행 채널 본문에 인라인 콜라주를 삽입합니다.",
  mystery_inline_collage_enabled: "미스터리 채널 본문에 인라인 콜라주를 삽입합니다.",
  wikimedia_image_count: "Wikimedia에서 보조 이미지를 가져올 최대 개수입니다.",
  cloudinary_cloud_name: "Cloudinary 계정의 cloud name 값입니다.",
  cloudinary_api_key: "Cloudinary 업로드용 API 키입니다.",
  cloudinary_api_secret: "Cloudinary 업로드용 API 시크릿입니다.",
  cloudinary_folder: "Cloudinary에 저장할 기본 폴더입니다.",
  github_pages_owner: "GitHub Pages 저장소를 소유한 사용자 또는 조직입니다.",
  github_pages_repo: "공개 이미지를 올릴 GitHub Pages 저장소 이름입니다.",
  github_pages_branch: "배포 자산을 업로드할 GitHub Pages 브랜치입니다.",
  github_pages_token: "GitHub Pages 저장소 업로드에 사용할 토큰입니다.",
  github_pages_base_url: "GitHub Pages 공개 기준 URL입니다.",
  github_pages_assets_dir: "저장소 안에서 자산을 저장할 디렉터리입니다.",
};

function sortSteps(steps: PromptFlowStepRead[]) {
  return [...steps].sort((a, b) => {
    const stageGap = STAGE_ORDER.indexOf(a.stageType as WorkflowStageType) - STAGE_ORDER.indexOf(b.stageType as WorkflowStageType);
    if (stageGap !== 0) {
      return stageGap;
    }
    return a.sortOrder - b.sortOrder;
  });
}

function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "미기록";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function prettifyKey(key: string) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase())
    .replace(/Openai/g, "OpenAI");
}

function resolveFieldLabel(key: string) {
  if (FIELD_LABELS[key]) {
    return FIELD_LABELS[key];
  }
  if (key.startsWith("cloudflare_prompt__")) {
    return "Cloudflare 프롬프트 설정";
  }
  return prettifyKey(key);
}

function resolveFieldDescription(item: SettingRead) {
  if (item.description === "User-defined setting") {
    return "사용자 정의 설정입니다.";
  }
  return FIELD_DESCRIPTIONS[item.key] || item.description || item.key;
}

function isSecretKey(item: SettingRead) {
  return item.is_secret || /(secret|token|password|key)/i.test(item.key);
}

function inferControlKind(item: SettingRead): SettingControlKind {
  const normalizedValue = (item.value ?? "").trim().toLowerCase();
  if (item.is_secret) {
    return "password";
  }
  if (/_time$/.test(item.key)) {
    return "time";
  }
  if (/_url$/.test(item.key) || /_uri$/.test(item.key) || /base_url/.test(item.key)) {
    return "url";
  }
  if (normalizedValue === "true" || normalizedValue === "false") {
    return "boolean";
  }
  if (/(^|_)(enabled|paused|auto_sync|request_saver_mode|inline_images_enabled|cdn_transform_enabled|inline_collage_enabled)$/.test(item.key)) {
    return "boolean";
  }
  if (/(_hours|_days|_minutes|_seconds|_limit|_quota|_count|_ratio|_threshold|_score|_index)$/.test(item.key)) {
    return "number";
  }
  if (/_weights$|_counts$|_path$/.test(item.key)) {
    return "textarea";
  }
  return "text";
}

function resolveOptions(key: string, availableModels: string[]): SettingOption[] | null {
  if (key === "provider_mode") {
    return [
      { value: "mock", label: "모의 실행" },
      { value: "live", label: "실제 실행" },
    ];
  }
  if (key === "default_publish_mode") {
    return [
      { value: "draft", label: "초안" },
      { value: "publish", label: "즉시 발행" },
    ];
  }
  if (key === "topic_discovery_provider") {
    return [
      { value: "openai", label: "OpenAI" },
      { value: "gemini", label: "Gemini" },
    ];
  }
  if (key === "public_image_provider") {
    return [
      { value: "cloudflare_r2", label: "Cloudflare R2" },
      { value: "cloudinary", label: "Cloudinary" },
      { value: "github_pages", label: "GitHub Pages" },
      { value: "local", label: "로컬 URL" },
    ];
  }
  if (key.includes("model") && availableModels.length) {
    return availableModels.map((value) => ({ value, label: value }));
  }
  return null;
}

function shouldHideField(item: SettingRead) {
  return item.key.startsWith("cloudflare_prompt__") || item.key === "admin_auth_password_hash";
}

function shouldShowField(key: string, values: Record<string, string>) {
  if (key === "admin_auth_username") {
    return values.admin_auth_enabled === "true";
  }
  if (key.startsWith("cloudflare_r2_") || key === "cloudflare_account_id") {
    return values.public_image_provider === "cloudflare_r2";
  }
  if (key.startsWith("cloudinary_")) {
    return values.public_image_provider === "cloudinary";
  }
  if (key.startsWith("github_pages_")) {
    return values.public_image_provider === "github_pages";
  }
  if (key === "public_asset_base_url") {
    return values.public_image_provider === "local";
  }
  if (key.startsWith("blogger_playwright_") && key !== "blogger_playwright_enabled") {
    return values.blogger_playwright_enabled === "true";
  }
  if (key === "gemini_api_key" || key === "gemini_topic_model" || key === "gemini_model") {
    return values.topic_discovery_provider === "gemini";
  }
  if (key === "topic_discovery_model") {
    return (values.topic_discovery_provider || "openai") === "openai";
  }
  if (key.startsWith("cloudflare_daily_publish_") && key !== "cloudflare_daily_publish_enabled") {
    return values.cloudflare_daily_publish_enabled === "true";
  }
  if (key.startsWith("schedule_") && key !== "schedule_enabled") {
    return values.schedule_enabled === "true";
  }
  if (key.startsWith("training_schedule_") && key !== "training_schedule_enabled") {
    return values.training_schedule_enabled === "true";
  }
  if (key === "sheet_sync_day" || key === "sheet_sync_time") {
    return values.sheet_sync_enabled === "true";
  }
  return true;
}

function isDiagnosticField(item: SettingRead) {
  return (
    item.key.includes("_last_") ||
    item.key.endsWith("_updated_at") ||
    item.key.endsWith("_created_at") ||
    item.key.endsWith("_counts") ||
    item.key.endsWith("_path") ||
    item.key.endsWith("_weights") ||
    item.key.endsWith("_streak") ||
    item.key.endsWith("_scope") ||
    item.key.endsWith("_type") ||
    item.key.endsWith("_expires_at") ||
    item.key === "content_overview_tab"
  );
}

function normalizeOptions(value: string, options: SettingOption[] | null) {
  if (!options) {
    return [];
  }
  if (value && !options.some((option) => option.value === value)) {
    return [{ value, label: `현재값: ${value}` }, ...options];
  }
  return options;
}

function buildDraft(step: PromptFlowStepRead): StepDraft {
  return {
    id: step.id,
    name: step.name,
    objective: step.objective ?? "",
    promptTemplate: step.promptTemplate,
    providerModel: step.providerModel ?? "",
    isEnabled: step.isEnabled,
  };
}

async function loadChannelPreviews(channelList: ManagedChannelRead[], blogList: Blog[]) {
  const previewMap: Record<string, PreviewItem[]> = {};

  const cloudflareChannel = channelList.find((item) => item.provider === "cloudflare");
  if (cloudflareChannel) {
    try {
      const items = await getCloudflarePosts();
      previewMap[cloudflareChannel.channelId] = items.slice(0, 3).map((item) => ({
        id: String(item.remote_id),
        title: item.title,
        url: item.published_url ?? null,
        publishedAt: item.published_at ?? null,
      }));
    } catch {
      previewMap[cloudflareChannel.channelId] = [];
    }
  }

  await Promise.all(
    channelList
      .filter((item) => item.provider === "blogger")
      .map(async (channel) => {
        const matchedBlog = blogList.find((blog) => channel.channelId === `blogger:${blog.id}`);
        if (!matchedBlog) {
          previewMap[channel.channelId] = [];
          return;
        }
        try {
          const page = await getBlogArchive(matchedBlog.id, 1, 3);
          previewMap[channel.channelId] = page.items.slice(0, 3).map((item) => ({
            id: String(item.id),
            title: item.title,
            url: item.published_url ?? null,
            publishedAt: item.published_at ?? null,
          }));
        } catch {
          previewMap[channel.channelId] = [];
        }
      }),
  );

  return previewMap;
}

export function SettingsConsole({ settings, config }: SettingsConsoleProps) {
  const settingsByKey = useMemo(() => new Map(settings.map((item) => [item.key, item])), [settings]);
  const [runtimeConfig, setRuntimeConfig] = useState<BloggerConfigRead>(config);
  const [activeTab, setActiveTab] = useState<SettingsTab>("workspace");
  const [savedSettings, setSavedSettings] = useState<Record<string, string>>(() => Object.fromEntries(settings.map((item) => [item.key, item.value])));
  const [localSettings, setLocalSettings] = useState<Record<string, string>>(() => Object.fromEntries(settings.map((item) => [item.key, item.value])));
  const [saveMessage, setSaveMessage] = useState("");
  const [saveError, setSaveError] = useState("");
  const [channels, setChannels] = useState<ManagedChannelRead[]>([]);
  const [channelPreviews, setChannelPreviews] = useState<Record<string, PreviewItem[]>>({});
  const [bootstrapError, setBootstrapError] = useState("");
  const [flowError, setFlowError] = useState("");
  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [selectedCloudflareCategory, setSelectedCloudflareCategory] = useState("");
  const [flow, setFlow] = useState<PromptFlowRead | null>(null);
  const [selectedStepId, setSelectedStepId] = useState("");
  const [draft, setDraft] = useState<StepDraft | null>(null);
  const [flowSaveState, setFlowSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [modelPolicy, setModelPolicy] = useState<ModelPolicyRead | null>(null);
  const [selectedStageType, setSelectedStageType] = useState<string>(STAGE_ORDER[0]);
  const [channelPreviewsLoaded, setChannelPreviewsLoaded] = useState(false);
  const [channelPreviewsLoading, setChannelPreviewsLoading] = useState(false);
  const [remoteConfigLoading, setRemoteConfigLoading] = useState(false);
  const [remoteConfigError, setRemoteConfigError] = useState("");
  const [isPending, startTransition] = useTransition();
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flowDraftVersion = useRef(0);

  useEffect(() => {
    setRuntimeConfig(config);
  }, [config]);

  useEffect(() => {
    let mounted = true;
    startTransition(() => {
      void Promise.all([getChannels(), getModelPolicy()])
        .then(([channelList, policy]) => {
          if (!mounted) {
            return;
          }
          setBootstrapError("");
          setChannels(channelList);
          setModelPolicy(policy);
          const defaultChannel = channelList.find((item) => item.promptFlowSupported) ?? channelList[0] ?? null;
          if (defaultChannel) {
            setSelectedChannelId((current) => current || defaultChannel.channelId);
          }
        })
        .catch(() => {
          if (mounted) {
            setBootstrapError("채널 또는 모델 정책을 불러오지 못했습니다.");
          }
        });
    });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (activeTab !== "channels" || channelPreviewsLoaded || channelPreviewsLoading || channels.length === 0) {
      return;
    }
    let mounted = true;
    const timer = window.setTimeout(() => {
      setChannelPreviewsLoading(true);
      void getBlogs()
        .then((blogList) => loadChannelPreviews(channels, blogList))
        .then((previews) => {
          if (!mounted) return;
          setChannelPreviews(previews);
          setChannelPreviewsLoaded(true);
        })
        .catch(() => {
          if (!mounted) return;
          setBootstrapError("채널 미리보기를 불러오지 못했습니다.");
        })
        .finally(() => {
          if (!mounted) return;
          setChannelPreviewsLoading(false);
        });
    }, 200);
    return () => {
      mounted = false;
      window.clearTimeout(timer);
    };
  }, [activeTab, channels, channelPreviewsLoaded, channelPreviewsLoading]);

  useEffect(() => {
    if (!selectedChannelId) {
      return;
    }
    let mounted = true;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void getChannelPromptFlow(selectedChannelId, controller.signal)
        .then((payload) => {
          if (!mounted) {
            return;
          }
          setFlowError("");
          const ordered = sortSteps(payload.steps);
          setFlow({ ...payload, steps: ordered });
          setSelectedStageType(payload.availableStageTypes[0] ?? STAGE_ORDER[0]);
          if (payload.provider === "cloudflare") {
            const categories = Array.from(new Set(ordered.map((step) => step.id.split("::")[0]).filter(Boolean)));
            setSelectedCloudflareCategory((current) => (current && categories.includes(current) ? current : categories[0] ?? ""));
          } else {
            setSelectedCloudflareCategory("");
          }
        })
        .catch((error) => {
          if (!mounted) return;
          if (error instanceof DOMException && error.name === "AbortError") return;
          setFlow(null);
          setFlowError("프롬프트 플로우를 불러오지 못했습니다.");
        });
    });
    return () => {
      mounted = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [selectedChannelId]);

  const selectedChannel = useMemo(
    () => channels.find((item) => item.channelId === selectedChannelId) ?? channels[0] ?? null,
    [channels, selectedChannelId],
  );

  const availableModels = useMemo(() => {
    const values = new Set<string>();
    (modelPolicy?.large ?? []).forEach((item) => values.add(item));
    (modelPolicy?.small ?? []).forEach((item) => values.add(item));
    return Array.from(values);
  }, [modelPolicy]);

  const cloudflareCategories = useMemo(() => {
    if (!flow || flow.provider !== "cloudflare") {
      return [] as string[];
    }
    return Array.from(new Set(flow.steps.map((step) => step.id.split("::")[0]).filter(Boolean)));
  }, [flow]);

  const visibleSteps = useMemo(() => {
    if (!flow) {
      return [];
    }
    if (flow.provider !== "cloudflare") {
      return sortSteps(flow.steps);
    }
    return sortSteps(flow.steps).filter((step) => step.id.split("::")[0] === selectedCloudflareCategory);
  }, [flow, selectedCloudflareCategory]);

  useEffect(() => {
    if (!visibleSteps.length) {
      setSelectedStepId("");
      setDraft(null);
      return;
    }
    setSelectedStepId((current) => (current && visibleSteps.some((step) => step.id === current) ? current : visibleSteps[0].id));
  }, [visibleSteps]);

  const selectedStep = useMemo(() => visibleSteps.find((item) => item.id === selectedStepId) ?? null, [selectedStepId, visibleSteps]);

  useEffect(() => {
    if (!selectedStep) {
      setDraft(null);
      return;
    }
    setDraft(buildDraft(selectedStep));
  }, [selectedStep]);

  useEffect(() => {
    return () => {
      if (saveTimer.current) {
        clearTimeout(saveTimer.current);
      }
    };
  }, []);

  const groupedSettings = useMemo(
    () =>
      SECTION_DEFS.map((section) => ({
        ...section,
        items: section.keys
          .map((key) => settingsByKey.get(key))
          .filter((item): item is SettingRead => item !== undefined)
          .filter((item) => !shouldHideField(item))
          .filter((item) => shouldShowField(item.key, localSettings)),
      })).filter((section) => section.items.length > 0),
    [localSettings, settingsByKey],
  );

  const diagnosticItems = useMemo(
    () => settings.filter((item) => !shouldHideField(item) && !isSecretKey(item) && isDiagnosticField(item)),
    [settings],
  );

  function handleSettingChange(key: string, value: string) {
    setSaveMessage("");
    setSaveError("");
    setLocalSettings((current) => ({ ...current, [key]: value }));
  }

  function isDirtyField(key: string) {
    const currentValue = localSettings[key] ?? "";
    const item = settingsByKey.get(key);
    if (item && isSecretKey(item)) {
      return currentValue.trim().length > 0;
    }
    return currentValue !== (savedSettings[key] ?? "");
  }

  async function handleSaveSettings(keys: string[]) {
    const payload = Object.fromEntries(
      keys
        .filter((key) => {
          const item = settingsByKey.get(key);
          if (item && isSecretKey(item)) {
            return (localSettings[key] ?? "").trim().length > 0;
          }
          return (localSettings[key] ?? "") !== (savedSettings[key] ?? "");
        })
        .map((key) => [key, localSettings[key] ?? ""]),
    );

    if (!Object.keys(payload).length) {
      setSaveError("");
      setSaveMessage("변경된 항목이 없습니다.");
      return;
    }

    try {
      await updateSettings(payload);
      setSavedSettings((current) => {
        const next = { ...current };
        Object.entries(payload).forEach(([key, value]) => {
          const item = settingsByKey.get(key);
          if (!item || !isSecretKey(item)) {
            next[key] = value;
          }
        });
        return next;
      });
      setLocalSettings((current) => {
        const next = { ...current };
        Object.keys(payload).forEach((key) => {
          const item = settingsByKey.get(key);
          if (item && isSecretKey(item)) {
            next[key] = "";
          }
        });
        return next;
      });
      setSaveError("");
      setSaveMessage("설정이 저장되었습니다.");
      window.setTimeout(() => setSaveMessage(""), 1600);
    } catch {
      setSaveMessage("");
      setSaveError("설정을 저장하지 못했습니다.");
    }
  }

  async function handleLoadRemoteConfig() {
    try {
      setRemoteConfigLoading(true);
      setRemoteConfigError("");
      const next = await getBloggerConfig(true);
      setRuntimeConfig(next);
    } catch {
      setRemoteConfigError("연동 데이터를 불러오지 못했습니다.");
    } finally {
      setRemoteConfigLoading(false);
    }
  }

  async function applyFlowUpdate(patch: Partial<StepDraft>, immediate = false) {
    if (!selectedStep || !draft || !selectedChannel) {
      return;
    }
    const nextDraft = { ...draft, ...patch };
    const version = ++flowDraftVersion.current;
    setDraft(nextDraft);
    setFlowError("");
    setFlow((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        steps: current.steps.map((step) =>
          step.id === selectedStep.id
            ? {
                ...step,
                name: nextDraft.name,
                objective: nextDraft.objective,
                promptTemplate: nextDraft.promptTemplate,
                providerModel: nextDraft.providerModel || null,
                isEnabled: nextDraft.isEnabled,
              }
            : step,
        ),
      };
    });

    const submit = async () => {
      setFlowSaveState("saving");
      try {
        const updated = await updateChannelPromptFlowStep(selectedChannel.channelId, selectedStep.id, {
          name: nextDraft.name,
          objective: nextDraft.objective,
          prompt_template: nextDraft.promptTemplate,
          provider_model: nextDraft.providerModel || null,
          is_enabled: nextDraft.isEnabled,
        });
        if (version !== flowDraftVersion.current) {
          return;
        }
        setFlow({ ...updated, steps: sortSteps(updated.steps) });
        setFlowSaveState("saved");
        window.setTimeout(() => setFlowSaveState("idle"), 1200);
      } catch {
        if (version !== flowDraftVersion.current) {
          return;
        }
        setFlowSaveState("error");
        setFlowError("프롬프트 플로우 저장에 실패했습니다.");
      }
    };

    if (saveTimer.current) {
      clearTimeout(saveTimer.current);
    }
    if (immediate) {
      await submit();
      return;
    }
    saveTimer.current = setTimeout(() => {
      void submit();
    }, 700);
  }

  async function handleMoveStep(stepId: string, direction: "left" | "right") {
    if (!flow?.structureEditable || !selectedChannel) {
      return;
    }
    try {
      const ordered = sortSteps(flow.steps);
      const index = ordered.findIndex((step) => step.id === stepId);
      if (index < 0) {
        return;
      }
      const targetIndex = direction === "left" ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= ordered.length) {
        return;
      }
      const next = [...ordered];
      const [moved] = next.splice(index, 1);
      next.splice(targetIndex, 0, moved);
      const updated = await reorderChannelPromptFlow(selectedChannel.channelId, next.map((step) => step.id));
      setFlowError("");
      setFlow({ ...updated, steps: sortSteps(updated.steps) });
    } catch {
      setFlowError("프롬프트 단계 순서를 바꾸지 못했습니다.");
    }
  }

  async function handleAddStep() {
    if (!flow?.structureEditable || !selectedChannel || !selectedStageType) {
      return;
    }
    try {
      const updated = await createChannelPromptFlowStep(selectedChannel.channelId, selectedStageType);
      setFlowError("");
      setFlow({ ...updated, steps: sortSteps(updated.steps) });
    } catch {
      setFlowError("새 단계를 추가하지 못했습니다.");
    }
  }

  async function handleRemoveStep(step: PromptFlowStepRead) {
    if (!step.removable || !selectedChannel) {
      return;
    }
    try {
      const updated = await deleteChannelPromptFlowStep(selectedChannel.channelId, step.id);
      setFlowError("");
      setFlow({ ...updated, steps: sortSteps(updated.steps) });
    } catch {
      setFlowError("단계를 삭제하지 못했습니다.");
    }
  }

  const currentSections = groupedSettings.filter((section) => section.key === activeTab);
  const currentSectionKeys = currentSections.flatMap((section) => section.items.map((item) => item.key));
  const currentDirtyCount = currentSectionKeys.filter(isDirtyField).length;
  const oauthClientConfigured = Boolean(runtimeConfig.client_id_configured && runtimeConfig.client_secret_configured);
  const oauthStartUrl = runtimeConfig.authorization_url || `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"}/blogger/oauth/start`;
  const grantedScopeSet = useMemo(
    () => new Set((runtimeConfig.granted_scopes ?? []).map((item) => item.trim()).filter(Boolean)),
    [runtimeConfig.granted_scopes],
  );
  const missingScopes = useMemo(
    () => (runtimeConfig.oauth_scopes ?? []).filter((scope) => !grantedScopeSet.has(scope)),
    [runtimeConfig.oauth_scopes, grantedScopeSet],
  );
  const indexingScopeGranted = grantedScopeSet.has(GOOGLE_INDEXING_SCOPE);
  const overviewStats = [
    { label: "자동화 게이트", value: localSettings.automation_master_enabled === "true" ? "활성" : "중지" },
    { label: "품질 게이트", value: localSettings.quality_gate_enabled === "true" ? "사용" : "중지" },
    { label: "공개 이미지", value: FIELD_LABELS.public_image_provider ? prettifyKey(localSettings.public_image_provider || "local") : "미설정" },
    { label: "플래너 슬롯", value: `${localSettings.planner_default_daily_posts || "0"}개` },
  ];

  return (
    <div className="space-y-5">
      <section className="rounded-[28px] border border-slate-200 bg-white px-5 py-5 shadow-sm lg:px-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">설정 워크스페이스</p>
            <h2 className="text-[28px] font-semibold tracking-tight text-slate-950">설정 콘솔</h2>
            <p className="max-w-3xl text-sm leading-6 text-slate-600">채널·플로우는 작업 화면으로 유지하고, 나머지 설정은 운영 과업 기준의 섹션 카드로 재구성했습니다. 비밀값은 직접 입력한 경우에만 저장합니다.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <GuideStep number="01" title="일간 기준 운영" description="기준값은 일간 운영 데이터로 저장합니다." />
            <GuideStep number="02" title="채널별 파이프라인" description="블로그·Cloudflare별 단계를 따로 관리합니다." />
            <GuideStep number="03" title="월간 공유 반영" description="설정 변경은 계획·분석 화면에 바로 공유됩니다." />
          </div>
        </div>
      </section>

      <div className="flex flex-wrap gap-2">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={[
              "rounded-full px-4 py-2 text-sm font-medium transition",
              activeTab === tab.key ? "bg-slate-950 text-white shadow-sm" : "bg-white text-slate-600 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50 hover:text-slate-900",
            ].join(" ")}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {bootstrapError ? <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{bootstrapError}</div> : null}

      {activeTab === "channels" ? (
        <section className="grid gap-4 xl:grid-cols-3">
          {channels.map((channel) => {
            const previews = channelPreviews[channel.channelId] ?? [];
            const capabilityPills = [
              channel.plannerSupported ? "플래너 지원" : null,
              channel.analyticsSupported ? "분석 지원" : null,
              channel.promptFlowSupported ? "플로우 편집" : null,
            ].filter(Boolean) as string[];
            return (
              <article key={channel.channelId} className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <FlagPill tone="slate">{channel.provider === "cloudflare" ? "Cloudflare" : "Blogger"}</FlagPill>
                      <FlagPill tone={channel.status === "connected" ? "emerald" : "amber"}>
                        {channel.status === "connected" ? "연결됨" : channel.status || "확인 필요"}
                      </FlagPill>
                      {capabilityPills.map((label) => (
                        <FlagPill key={label} tone="indigo">
                          {label}
                        </FlagPill>
                      ))}
                    </div>
                    <h3 className="line-clamp-2 text-lg font-semibold text-slate-950">{channel.name}</h3>
                    <p className="truncate text-sm text-slate-500">{channel.baseUrl || "기본 URL 미설정"}</p>
                  </div>
                  <div className="grid shrink-0 grid-cols-3 gap-2 text-center">
                    <StatTile label="게시글" value={String(channel.postsCount)} />
                    <StatTile label="카테고리" value={String(channel.categoriesCount)} />
                    <StatTile label="프롬프트" value={String(channel.promptsCount)} />
                  </div>
                </div>
                <div className="mt-4 grid gap-2 text-sm text-slate-600">
                  <InfoRow label="대표 카테고리" value={channel.primaryCategory || "미설정"} />
                  <InfoRow label="운영 목적" value={channel.purpose || "설명 없음"} />
                  <InfoRow label="채널 ID" value={channel.channelId} />
                </div>
                <div className="mt-5 border-t border-slate-200 pt-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-slate-900">최근 게시글</h4>
                    <span className="text-xs text-slate-400">최대 3건</span>
                  </div>
                  <div className="space-y-2">
                    {previews.length ? (
                      previews.map((item) => (
                        <div key={item.id} className="rounded-2xl bg-slate-50 px-3 py-3">
                          <p className="line-clamp-2 text-sm font-medium text-slate-900">{item.title}</p>
                          <div className="mt-2 flex items-center justify-between gap-2">
                            <span className="text-xs text-slate-500">{formatDateTime(item.publishedAt)}</span>
                            {item.url ? (
                              <a
                                href={item.url}
                                target="_blank"
                                rel="noreferrer"
                                className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-950"
                              >
                                사이트가기
                              </a>
                            ) : (
                              <span className="text-xs text-slate-400">URL 없음</span>
                            )}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-5 text-sm text-slate-500">게시글 미리보기가 아직 없습니다.</div>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </section>
      ) : null}

      {activeTab === "pipeline" && selectedChannel ? (
        <section className="space-y-4 rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm lg:p-6">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="grid gap-3 lg:grid-cols-[minmax(240px,300px)_minmax(220px,260px)_minmax(0,1fr)]">
              <SelectField label="관리 채널" value={selectedChannel.channelId} onChange={setSelectedChannelId}>
                {channels.filter((item) => item.promptFlowSupported).map((item) => (
                  <option key={item.channelId} value={item.channelId}>
                    {item.name}
                  </option>
                ))}
              </SelectField>
              {flow?.provider === "cloudflare" ? (
                <SelectField label="카테고리" value={selectedCloudflareCategory} onChange={setSelectedCloudflareCategory}>
                  {cloudflareCategories.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </SelectField>
              ) : (
                <ReadonlyField label="편집 범위" value="전체 블로그 파이프라인" />
              )}
              <div className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
                <p className="font-semibold text-slate-900">가로형 파이프라인</p>
                <p className="mt-1 leading-6">블록 안에는 단계 요약만 표시합니다. 본문과 세부 설정은 아래 편집기에서 수정됩니다.</p>
              </div>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              {flow?.structureEditable ? (
                <>
                  <SelectField label="단계 추가" value={selectedStageType} onChange={setSelectedStageType}>
                    {(flow.availableStageTypes.length ? flow.availableStageTypes : STAGE_ORDER).map((stage) => (
                      <option key={stage} value={stage}>
                        {STAGE_LABELS[stage] ?? stage}
                      </option>
                    ))}
                  </SelectField>
                  <button
                    type="button"
                    onClick={() => void handleAddStep()}
                    className="rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
                  >
                    단계 추가
                  </button>
                </>
              ) : (
                <FlagPill tone="slate">구조 고정 채널</FlagPill>
              )}
            </div>
          </div>

          {flowError ? <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{flowError}</div> : null}

          <div className="overflow-x-auto pb-2">
            <div className="flex min-w-max items-stretch gap-4 pr-4">
              {visibleSteps.map((step, index) => {
                const active = step.id === selectedStepId;
                return (
                  <div key={step.id} className="flex items-center gap-4">
                    <button
                      type="button"
                      onClick={() => setSelectedStepId(step.id)}
                      className={[
                        "w-[248px] rounded-[24px] border p-4 text-left shadow-sm transition",
                        active ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white text-slate-900 hover:border-slate-300",
                      ].join(" ")}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 space-y-2">
                          <div className="flex flex-wrap items-center gap-2 text-[11px] font-medium">
                            <span className={active ? "text-slate-300" : "text-slate-500"}>{String(index + 1).padStart(2, "0")}</span>
                            <FlagPill tone={step.isRequired ? (active ? "dark" : "indigo") : active ? "dark" : "slate"}>{step.isRequired ? "필수" : "선택"}</FlagPill>
                            <FlagPill tone={step.isEnabled ? (active ? "dark" : "emerald") : active ? "dark" : "amber"}>{step.isEnabled ? "사용" : "중지"}</FlagPill>
                          </div>
                          <p className={active ? "text-xs text-slate-300" : "text-xs text-slate-500"}>{STAGE_LABELS[step.stageType] ?? step.stageLabel}</p>
                          <h3 className="line-clamp-2 text-sm font-semibold leading-6">{step.name}</h3>
                          <p className={active ? "line-clamp-1 text-xs text-slate-300" : "line-clamp-1 text-xs text-slate-500"}>{step.providerModel || "기본값 상속"}</p>
                          <p className={active ? "line-clamp-2 text-xs text-slate-300" : "line-clamp-2 text-xs text-slate-500"}>{step.objective || "목적 미설정"}</p>
                        </div>
                        {flow?.structureEditable ? (
                          <div className="flex shrink-0 flex-col gap-2">
                            <button type="button" className={blockActionClass(active)} onClick={(event) => { event.stopPropagation(); void handleMoveStep(step.id, "left"); }}>←</button>
                            <button type="button" className={blockActionClass(active)} onClick={(event) => { event.stopPropagation(); void handleMoveStep(step.id, "right"); }}>→</button>
                            {step.removable ? (
                              <button type="button" className={blockActionClass(active)} onClick={(event) => { event.stopPropagation(); void handleRemoveStep(step); }}>삭제</button>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    </button>
                    {index < visibleSteps.length - 1 ? <div className="text-slate-300">→</div> : null}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4 lg:p-5">
            {selectedStep && draft ? (
              <div className="space-y-5">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">선택 단계 편집기</p>
                    <h3 className="mt-1 text-xl font-semibold text-slate-950">{STAGE_LABELS[selectedStep.stageType] ?? selectedStep.stageLabel}</h3>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <FlagPill tone="slate">{selectedChannel.name}</FlagPill>
                    <FlagPill tone={flowSaveState === "error" ? "amber" : flowSaveState === "saved" ? "emerald" : "slate"}>
                      {flowSaveState === "saving" ? "저장 중" : flowSaveState === "saved" ? "저장 완료" : flowSaveState === "error" ? "저장 실패" : "자동 저장"}
                    </FlagPill>
                  </div>
                </div>

                <div className="grid gap-4 xl:grid-cols-2">
                  <FieldGroup label="단계 제목">
                    <input value={draft.name} onChange={(event) => void applyFlowUpdate({ name: event.target.value })} className={inputClass()} />
                  </FieldGroup>
                  <FieldGroup label="모델 선택">
                    <select value={draft.providerModel} onChange={(event) => void applyFlowUpdate({ providerModel: event.target.value }, true)} className={inputClass()}>
                      <option value="">기본값 상속</option>
                      {availableModels.map((model) => (
                        <option key={model} value={model}>
                          {model}
                        </option>
                      ))}
                    </select>
                  </FieldGroup>
                  <FieldGroup label="목적 / 설명" className="xl:col-span-2">
                    <textarea value={draft.objective} onChange={(event) => void applyFlowUpdate({ objective: event.target.value })} rows={2} className={textareaClass("min-h-[92px]")} />
                  </FieldGroup>
                  <FieldGroup label="사용 상태">
                    <label className="flex h-[44px] items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-700">
                      <input type="checkbox" checked={draft.isEnabled} onChange={(event) => void applyFlowUpdate({ isEnabled: event.target.checked }, true)} />
                      현재 단계 사용
                    </label>
                  </FieldGroup>
                  <ReadonlyField label="구조 변경 가능" value={selectedStep.structureEditable ? "예" : "아니오"} />
                  <FieldGroup label="프롬프트 본문" className="xl:col-span-2">
                    <textarea value={draft.promptTemplate} onChange={(event) => void applyFlowUpdate({ promptTemplate: event.target.value })} rows={14} className={textareaClass("min-h-[320px]")} />
                  </FieldGroup>
                </div>
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-12 text-center text-sm text-slate-500">편집할 단계를 선택하세요.</div>
            )}
          </div>
        </section>
      ) : null}

      {activeTab !== "channels" && activeTab !== "pipeline" ? (
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-4">
            {activeTab === "workspace" ? (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                {overviewStats.map((item) => (
                  <div key={item.label} className="rounded-[24px] border border-slate-200 bg-white p-4 shadow-sm">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">{item.label}</p>
                    <p className="mt-2 text-xl font-semibold text-slate-950">{item.value}</p>
                  </div>
                ))}
              </div>
            ) : null}

            {activeTab === "integrations" ? (
              <article className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm lg:p-6">
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div>
                    <h3 className="text-xl font-semibold text-slate-950">Google OAuth2 연동</h3>
                    <p className="mt-1 text-sm text-slate-500">Blogger, Search Console, GA4, Indexing API 동작은 이 OAuth 인증 상태를 기준으로 결정됩니다.</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {oauthClientConfigured ? (
                      <a
                        href={oauthStartUrl}
                        className="rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
                      >
                        OAuth2 연결/재인증
                      </a>
                    ) : (
                      <button
                        type="button"
                        disabled
                        className="rounded-full bg-slate-200 px-4 py-2 text-sm font-medium text-slate-500"
                      >
                        먼저 Client ID/Secret 저장
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => void handleLoadRemoteConfig()}
                      disabled={remoteConfigLoading}
                      className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
                    >
                      {remoteConfigLoading ? "연동 데이터 조회 중..." : "연동 데이터 불러오기"}
                    </button>
                    <a
                      href="/google"
                      className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                    >
                      연동 상태 확인
                    </a>
                    <a
                      href="/guide"
                      className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                    >
                      문제 해결 가이드
                    </a>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <StatTile label="OAuth 연결" value={runtimeConfig.connected ? "연결됨" : "미연결"} />
                  <StatTile label="승인 Scope" value={String(runtimeConfig.granted_scopes.length)} />
                  <StatTile label="누락 Scope" value={String(missingScopes.length)} />
                  <StatTile label="Indexing Scope" value={indexingScopeGranted ? "승인됨" : "누락"} />
                </div>

                <div className="mt-3 text-xs text-slate-500">
                  원격 연동 데이터 조회 상태: {runtimeConfig.remote_loaded ? "불러옴" : "미조회(초기 경량 모드)"}
                </div>
                {remoteConfigError ? (
                  <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                    {remoteConfigError}
                  </div>
                ) : null}

                {!indexingScopeGranted ? (
                  <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-7 text-amber-900">
                    `https://www.googleapis.com/auth/indexing` 권한이 누락되어 자동 색인 요청이 실행되지 않습니다. 위의 `OAuth2 연결/재인증`을 실행해 권한을 다시 승인하세요.
                  </div>
                ) : null}

                {missingScopes.length ? (
                  <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-700">
                    <p className="font-semibold text-slate-900">누락 Scope</p>
                    <p className="mt-2 break-all">{missingScopes.join(", ")}</p>
                  </div>
                ) : null}

                <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-700">
                  <p className="font-semibold text-slate-900">동작하지 않을 때 확인 순서</p>
                  <p className="mt-2">1. `blogger_client_id`, `blogger_client_secret`, `blogger_redirect_uri` 저장 후 현재 탭 저장을 눌러 반영합니다.</p>
                  <p>2. Google OAuth 동의화면이 Testing이면 실제 로그인 계정을 Test users에 추가합니다.</p>
                  <p>3. `OAuth2 연결/재인증` 버튼으로 다시 인증하고, `/google` 화면에서 승인 Scope에 indexing이 포함됐는지 확인합니다.</p>
                  <p>4. 여전히 실패하면 Redirect URI가 Google Cloud 설정과 완전히 동일한지(프로토콜/포트/경로) 확인합니다.</p>
                </div>
              </article>
            ) : null}

            {currentSections.map((section) => (
              <article key={section.id} className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm lg:p-6">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-xl font-semibold text-slate-950">{section.title}</h3>
                    <p className="mt-1 text-sm text-slate-500">{section.description}</p>
                  </div>
                  <FlagPill tone={section.items.some((item) => isDirtyField(item.key)) ? "indigo" : "slate"}>
                    {section.items.filter((item) => isDirtyField(item.key)).length || section.items.length}개 {section.items.some((item) => isDirtyField(item.key)) ? "변경" : "설정"}
                  </FlagPill>
                </div>
                <div className="mt-5 grid gap-4 xl:grid-cols-2">
                  {section.items.map((item) => {
                    const resolvedOptions = resolveOptions(item.key, availableModels);
                    const kind = resolvedOptions ? "select" : inferControlKind(item);
                    const options = normalizeOptions(localSettings[item.key] ?? "", resolvedOptions);
                    const wide = kind === "textarea" || /_(url|uri)$/.test(item.key) || item.key.includes("base_url") || item.key.includes("prompt");
                    const title = resolveFieldLabel(item.key);
                    return (
                      <div key={item.key} className={wide ? "xl:col-span-2" : ""}>
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                          <div className="mb-3 flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <p className="line-clamp-2 text-sm font-semibold text-slate-900">{title}</p>
                                {isSecretKey(item) ? <FlagPill tone="amber">보호됨</FlagPill> : null}
                                {isDirtyField(item.key) ? <FlagPill tone="indigo">변경됨</FlagPill> : null}
                              </div>
                              <p className="mt-1 text-xs text-slate-500">{resolveFieldDescription(item)}</p>
                            </div>
                          </div>

                          {kind === "boolean" ? (
                            <label className="flex h-[44px] items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-700">
                              <input
                                type="checkbox"
                                checked={localSettings[item.key] === "true"}
                                onChange={(event) => handleSettingChange(item.key, event.target.checked ? "true" : "false")}
                              />
                              현재 값: {localSettings[item.key] === "true" ? "사용" : "사용 안 함"}
                            </label>
                          ) : null}

                          {kind === "select" ? (
                            <select value={localSettings[item.key] ?? ""} onChange={(event) => handleSettingChange(item.key, event.target.value)} className={inputClass()}>
                              {item.key.includes("model") ? <option value="">기본값 상속</option> : null}
                              {options.map((option) => (
                                <option key={option.value} value={option.value}>
                                  {option.label}
                                </option>
                              ))}
                            </select>
                          ) : null}

                          {kind === "textarea" ? (
                            <textarea
                              value={localSettings[item.key] ?? ""}
                              onChange={(event) => handleSettingChange(item.key, event.target.value)}
                              rows={4}
                              className={textareaClass("min-h-[112px]")}
                            />
                          ) : null}

                          {kind === "password" ? (
                            <div className="space-y-2">
                              <input
                                type="password"
                                value={localSettings[item.key] ?? ""}
                                onChange={(event) => handleSettingChange(item.key, event.target.value)}
                                placeholder="변경할 때만 입력"
                                className={inputClass()}
                              />
                              <p className="text-xs text-slate-500">비워 두면 기존 비밀값을 유지합니다.</p>
                            </div>
                          ) : null}

                          {kind !== "boolean" && kind !== "select" && kind !== "textarea" && kind !== "password" ? (
                            <input
                              type={kind}
                              value={localSettings[item.key] ?? ""}
                              onChange={(event) => handleSettingChange(item.key, event.target.value)}
                              className={inputClass()}
                            />
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </article>
            ))}

            {activeTab === "workspace" && diagnosticItems.length ? (
              <article className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm lg:p-6">
                <div>
                  <h3 className="text-xl font-semibold text-slate-950">운영 진단 값</h3>
                  <p className="mt-1 text-sm text-slate-500">마지막 실행 시간, 경로, 카운트 같은 읽기 전용 운영 값입니다.</p>
                </div>
                <div className="mt-5 overflow-hidden rounded-2xl border border-slate-200">
                  <div className="grid grid-cols-[minmax(220px,280px)_minmax(0,1fr)] bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                    <span>키</span>
                    <span>값</span>
                  </div>
                  <div className="divide-y divide-slate-100">
                    {diagnosticItems.map((item) => (
                      <div key={item.key} className="grid grid-cols-[minmax(220px,280px)_minmax(0,1fr)] gap-4 px-4 py-3 text-sm">
                        <span className="break-all font-medium text-slate-900">{item.key}</span>
                        <span className="break-all text-slate-600">{localSettings[item.key] || "미기록"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </article>
            ) : null}
          </div>
          <aside className="space-y-4 rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">현재 탭 요약</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">키 덤프 대신 실제 운영 과업 기준으로 섹션을 재구성했습니다.</p>
            </div>
            <InfoRow label="Blogger 연결 블로그" value={String(runtimeConfig.blogs.length)} />
            <InfoRow label="OAuth 연결 상태" value={runtimeConfig.connected ? "연결됨" : "확인 필요"} />
            <InfoRow label="변경 항목" value={String(currentDirtyCount)} />
            <InfoRow label="저장 상태" value={saveError || saveMessage || "대기"} />
            <button
              type="button"
              onClick={() => void handleSaveSettings(currentSectionKeys)}
              className="w-full rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
            >
              현재 탭 저장
            </button>
            {saveError ? <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{saveError}</div> : null}
          </aside>
        </section>
      ) : null}

      {isPending ? <div className="text-xs text-slate-400">데이터를 불러오는 중입니다.</div> : null}
    </div>
  );
}

function GuideStep({ number, title, description }: { number: string; title: string; description: string }) {
  return (
    <div className="rounded-[22px] bg-slate-50 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">{number}</p>
      <p className="mt-1 text-sm font-semibold text-slate-900">{title}</p>
      <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-slate-50 px-3 py-2">
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-slate-900">{value}</p>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-dashed border-slate-200 pb-2 text-sm last:border-none last:pb-0">
      <span className="shrink-0 text-slate-500">{label}</span>
      <span className="min-w-0 text-right text-slate-900">{value}</span>
    </div>
  );
}

function FieldGroup({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <div className={className}>
      <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</label>
      {children}
    </div>
  );
}

function ReadonlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</label>
      <div className="flex h-[44px] items-center rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-700">{value}</div>
    </div>
  );
}

function SelectField({ label, value, onChange, children }: { label: string; value: string; onChange: (value: string) => void; children: ReactNode }) {
  return (
    <div>
      <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</label>
      <select value={value} onChange={(event) => onChange(event.target.value)} className={inputClass()}>
        {children}
      </select>
    </div>
  );
}

function FlagPill({ children, tone }: { children: ReactNode; tone: "slate" | "emerald" | "amber" | "indigo" | "dark" }) {
  const toneClass = {
    slate: "bg-slate-100 text-slate-600",
    emerald: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100 text-amber-700",
    indigo: "bg-indigo-100 text-indigo-700",
    dark: "bg-white/15 text-white",
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold ${toneClass}`}>{children}</span>;
}

function inputClass() {
  return "h-[44px] w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200";
}

function textareaClass(extra: string) {
  return `w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 ${extra}`;
}

function blockActionClass(active: boolean) {
  return [
    "rounded-full px-2.5 py-1 text-[11px] font-medium transition",
    active ? "bg-white/15 text-white hover:bg-white/20" : "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900",
  ].join(" ");
}

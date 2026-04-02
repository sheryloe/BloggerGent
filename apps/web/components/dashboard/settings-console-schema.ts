import type { SettingRead } from "@/lib/types";

export type SettingsTab =
  | "overview"
  | "runtime"
  | "models"
  | "quality"
  | "scheduling"
  | "delivery"
  | "automation"
  | "integrations"
  | "diagnostics"
  | "channels"
  | "pipeline";

export type SettingsFieldKind = "text" | "textarea" | "number" | "boolean" | "password" | "time" | "url" | "select";

export type SettingsFieldOption = {
  value: string;
  label: string;
};

export type SettingsFieldConfig = {
  key: string;
  label: string;
  help: string;
  kind?: SettingsFieldKind;
  options?: SettingsFieldOption[];
  placeholder?: string;
  rows?: number;
};

export type SettingsSectionConfig = {
  id: string;
  tab: Exclude<SettingsTab, "overview" | "diagnostics" | "channels" | "pipeline">;
  title: string;
  description: string;
  fields: SettingsFieldConfig[];
};

export const SETTINGS_TABS: Array<{ key: SettingsTab; label: string }> = [
  { key: "overview", label: "개요" },
  { key: "runtime", label: "워크스페이스" },
  { key: "models", label: "모델" },
  { key: "quality", label: "품질" },
  { key: "scheduling", label: "일정" },
  { key: "delivery", label: "전달" },
  { key: "automation", label: "자동화" },
  { key: "integrations", label: "연동" },
  { key: "diagnostics", label: "진단" },
  { key: "channels", label: "채널" },
  { key: "pipeline", label: "파이프라인" },
];

const BOOLEAN_OPTIONS: SettingsFieldOption[] = [
  { value: "true", label: "사용" },
  { value: "false", label: "사용 안 함" },
];

const PROVIDER_MODE_OPTIONS: SettingsFieldOption[] = [
  { value: "live", label: "실운영" },
  { value: "mock", label: "테스트" },
];

const PUBLISH_MODE_OPTIONS: SettingsFieldOption[] = [
  { value: "draft", label: "초안 저장" },
  { value: "publish", label: "즉시 발행" },
];

const TOPIC_PROVIDER_OPTIONS: SettingsFieldOption[] = [
  { value: "openai", label: "OpenAI" },
  { value: "gemini", label: "Gemini" },
];

const PUBLIC_IMAGE_PROVIDER_OPTIONS: SettingsFieldOption[] = [
  { value: "cloudflare_r2", label: "Cloudflare R2" },
  { value: "cloudinary", label: "Cloudinary" },
  { value: "github_pages", label: "GitHub Pages" },
  { value: "local", label: "직접 URL" },
];

const PIPELINE_STOP_OPTIONS: SettingsFieldOption[] = [
  { value: "none", label: "끝까지 실행" },
  { value: "GENERATING_ARTICLE", label: "글 생성 후 중단" },
  { value: "GENERATING_IMAGE_PROMPT", label: "이미지 프롬프트 후 중단" },
  { value: "GENERATING_IMAGE", label: "이미지 생성 후 중단" },
  { value: "ASSEMBLING_HTML", label: "HTML 조합 후 중단" },
];

export const SETTINGS_SECTIONS: SettingsSectionConfig[] = [
  {
    id: "workspace-runtime",
    tab: "runtime",
    title: "워크스페이스 기본값",
    description: "운영 기본 모드와 기본 발행 동작을 정합니다.",
    fields: [
      { key: "app_name", label: "앱 이름", help: "대시보드와 워크스페이스에 표시되는 이름입니다." },
      { key: "provider_mode", label: "실행 모드", help: "실운영 호출과 테스트 모드를 전환합니다.", kind: "select", options: PROVIDER_MODE_OPTIONS },
      { key: "default_blog_timezone", label: "기본 시간대", help: "플래너와 예약 발행 기본 시간대입니다." },
      { key: "default_publish_mode", label: "기본 발행 모드", help: "새 채널의 기본 발행 정책입니다.", kind: "select", options: PUBLISH_MODE_OPTIONS },
      { key: "default_writer_tone", label: "기본 작성 톤", help: "프롬프트에서 기본 톤 라벨로 사용합니다." },
    ],
  },
  {
    id: "workspace-access",
    tab: "runtime",
    title: "관리자 접근 제어",
    description: "대시보드 자체 접근 정책을 조정합니다.",
    fields: [
      { key: "admin_auth_enabled", label: "관리자 인증", help: "대시보드와 API에 기본 인증을 걸지 결정합니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "admin_auth_username", label: "관리자 계정", help: "기본 인증 사용자명입니다." },
      { key: "admin_auth_password_hash", label: "관리자 비밀번호 해시", help: "변경 시에만 입력합니다. 현재 값은 표시하지 않습니다.", kind: "password" },
    ],
  },
  {
    id: "workspace-planner",
    tab: "runtime",
    title: "플래너 기본값",
    description: "월간 계획 생성 시 기준 슬롯과 운영 시간을 정합니다.",
    fields: [
      { key: "planner_default_daily_posts", label: "일 기본 슬롯 수", help: "월간 계획 생성 시 하루 기본 슬롯 수입니다.", kind: "number" },
      { key: "planner_day_start_time", label: "플래너 시작 시각", help: "일간 슬롯 기본 시작 시각입니다.", kind: "time" },
      { key: "planner_day_end_time", label: "플래너 종료 시각", help: "일간 슬롯 기본 종료 시각입니다.", kind: "time" },
    ],
  },
  {
    id: "models-primary",
    tab: "models",
    title: "핵심 모델 라우팅",
    description: "토픽 발굴과 본문 생성의 기본 모델 조합을 정합니다.",
    fields: [
      { key: "topic_discovery_provider", label: "토픽 발굴 공급자", help: "토픽 발굴에 사용하는 주 공급자입니다.", kind: "select", options: TOPIC_PROVIDER_OPTIONS },
      { key: "topic_discovery_model", label: "OpenAI 토픽 발굴 모델", help: "토픽 발굴 공급자가 OpenAI일 때 사용합니다." },
      { key: "gemini_model", label: "Gemini 모델", help: "Gemini 발굴 기본 모델입니다." },
      { key: "gemini_topic_model", label: "Gemini 토픽 전용 모델", help: "Gemini 토픽 발굴 전용 모델입니다." },
      { key: "article_generation_model", label: "본문 생성 모델", help: "장문 본문과 리라이트에 사용하는 주력 모델입니다." },
      { key: "openai_large_text_model", label: "OpenAI 대형 텍스트 모델", help: "복잡한 생성과 재작성용 기본값입니다." },
      { key: "openai_small_text_model", label: "OpenAI 소형 텍스트 모델", help: "검토, 수정, 분석용 기본값입니다." },
    ],
  },
  {
    id: "models-support",
    tab: "models",
    title: "보조 모델과 절약 정책",
    description: "리뷰, 이미지, 요청 절약 정책을 조정합니다.",
    fields: [
      { key: "post_review_model", label: "포스트 리뷰 모델", help: "글별 편집 리뷰에 사용합니다." },
      { key: "revision_pass_model", label: "최종 수정 모델", help: "최종 정리 단계 기본값입니다." },
      { key: "image_prompt_generation_model", label: "이미지 프롬프트 모델", help: "이미지 프롬프트 정제에 사용합니다." },
      { key: "openai_text_model", label: "기본 보조 텍스트 모델", help: "보조 텍스트 작업 기본값입니다." },
      { key: "openai_image_model", label: "이미지 생성 모델", help: "기본 이미지 생성 모델입니다." },
      { key: "openai_request_saver_mode", label: "요청 절약 모드", help: "가능한 경우 추가 호출을 생략합니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
    ],
  },
  {
    id: "quality-gate",
    tab: "quality",
    title: "발행 품질 게이트",
    description: "발행 전 SEO, GEO, 중복 기준을 정합니다.",
    fields: [
      { key: "quality_gate_enabled", label: "품질 게이트", help: "발행 전 품질 게이트를 강제합니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "quality_gate_min_seo_score", label: "최소 SEO 점수", help: "품질 게이트 SEO 하한값입니다.", kind: "number" },
      { key: "quality_gate_min_geo_score", label: "최소 GEO 점수", help: "품질 게이트 GEO 하한값입니다.", kind: "number" },
      { key: "quality_gate_similarity_threshold", label: "최대 유사도", help: "품질 게이트가 허용하는 최대 유사도입니다.", kind: "number" },
      { key: "pipeline_stop_after", label: "테스트 중단 단계", help: "파이프라인을 특정 단계에서 중단합니다.", kind: "select", options: PIPELINE_STOP_OPTIONS },
    ],
  },
  {
    id: "quality-topic-memory",
    tab: "quality",
    title: "중복 방지와 토픽 메모리",
    description: "같은 주제와 각도의 반복을 제어합니다.",
    fields: [
      { key: "similarity_threshold", label: "중복 차단 임계값", help: "기본 중복 차단 임계값입니다.", kind: "number" },
      { key: "topic_guard_enabled", label: "토픽 메모리 가드", help: "토픽 메모리 기반 발행 가드를 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "topic_history_lookback_days", label: "이력 조회 기간", help: "과거 발행 이력을 며칠까지 봅니다.", kind: "number" },
      { key: "same_angle_cooldown_days", label: "같은 각도 쿨다운(일)", help: "같은 주제 각도 재사용 대기 기간입니다.", kind: "number" },
      { key: "same_cluster_cooldown_hours", label: "같은 클러스터 쿨다운(시간)", help: "같은 클러스터 재사용 대기 시간입니다.", kind: "number" },
      { key: "topic_novelty_angle_threshold", label: "각도 유사도 임계값", help: "같은 각도로 판단할 기준입니다.", kind: "number" },
      { key: "topic_novelty_cluster_threshold", label: "클러스터 유사도 임계값", help: "같은 클러스터로 판단할 기준입니다.", kind: "number" },
      { key: "topic_soft_penalty_threshold", label: "소프트 패널티 기준", help: "이 값 이상이면 재생성합니다.", kind: "number" },
      { key: "topic_discovery_max_topics_per_run", label: "1회 최대 토픽 수", help: "토픽 발굴 시 한 번에 큐잉할 최대 개수입니다.", kind: "number" },
    ],
  },
  {
    id: "schedule-master",
    tab: "scheduling",
    title: "전역 스케줄러",
    description: "전체 자동 실행 시각과 발행 슬롯 간격을 정합니다.",
    fields: [
      { key: "schedule_enabled", label: "전역 스케줄러", help: "일일 자동 스케줄러를 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "schedule_time", label: "전역 실행 시각", help: "전역 스케줄러 시작 시각입니다.", kind: "time" },
      { key: "schedule_timezone", label: "전역 시간대", help: "스케줄러 시간대입니다." },
      { key: "scheduled_batch_interval_minutes", label: "배치 슬롯 간격(분)", help: "하루 예약 슬롯 간격입니다.", kind: "number" },
      { key: "first_publish_delay_minutes", label: "첫 발행 지연(분)", help: "토픽 생성 후 첫 발행까지 지연입니다.", kind: "number" },
      { key: "publish_daily_limit_per_blog", label: "블로그별 일일 발행 한도", help: "실제 발행 상한값입니다.", kind: "number" },
      { key: "publish_min_interval_seconds", label: "최소 발행 간격(초)", help: "같은 블로그 API 호출 최소 간격입니다.", kind: "number" },
    ],
  },
  {
    id: "schedule-travel",
    tab: "scheduling",
    title: "여행 채널 반복 일정",
    description: "여행 프로필 반복 발행 규칙입니다.",
    fields: [
      { key: "travel_schedule_time", label: "시작 시각", help: "여행 반복 실행 시작 시각입니다.", kind: "time" },
      { key: "travel_schedule_interval_hours", label: "반복 간격(시간)", help: "여행 반복 간격입니다.", kind: "number" },
      { key: "travel_topics_per_run", label: "1회 생성 수", help: "여행 반복 1회당 큐에 넣는 수입니다.", kind: "number" },
      { key: "travel_research_mode", label: "팩트체크 모드", help: "여행 채널 검증 모드입니다." },
      { key: "travel_inline_collage_enabled", label: "본문 콜라주", help: "여행 본문 인라인 콜라주를 사용합니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "travel_blossom_cap_ratio", label: "벚꽃 비중 상한", help: "벚꽃 주제 상한 비율입니다.", kind: "number" },
    ],
  },
  {
    id: "schedule-mystery",
    tab: "scheduling",
    title: "미스터리 채널 반복 일정",
    description: "미스터리 프로필 반복 발행 규칙입니다.",
    fields: [
      { key: "mystery_schedule_time", label: "시작 시각", help: "미스터리 반복 실행 시작 시각입니다.", kind: "time" },
      { key: "mystery_schedule_interval_hours", label: "반복 간격(시간)", help: "미스터리 반복 간격입니다.", kind: "number" },
      { key: "mystery_topics_per_run", label: "1회 생성 수", help: "미스터리 반복 1회당 큐에 넣는 수입니다.", kind: "number" },
      { key: "mystery_inline_collage_enabled", label: "본문 콜라주", help: "미스터리 본문 인라인 콜라주를 사용합니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "wikimedia_image_count", label: "Wikimedia 이미지 수", help: "미스터리 글당 최대 Wikimedia 이미지 수입니다.", kind: "number" },
    ],
  },
  {
    id: "schedule-sheet-training",
    tab: "scheduling",
    title: "시트 동기화와 학습 일정",
    description: "주간 시트 동기화와 학습 예약을 조정합니다.",
    fields: [
      { key: "sheet_sync_enabled", label: "시트 동기화", help: "주간 Google Sheet 동기화를 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "sheet_sync_day", label: "시트 동기화 요일", help: "주간 동기화 요일입니다." },
      { key: "sheet_sync_time", label: "시트 동기화 시각", help: "주간 동기화 시각입니다.", kind: "time" },
      { key: "training_schedule_enabled", label: "학습 예약", help: "일일 학습 세션을 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "training_schedule_time", label: "학습 시각", help: "학습 세션 시각입니다.", kind: "time" },
      { key: "training_schedule_timezone", label: "학습 시간대", help: "학습 세션 시간대입니다." },
      { key: "training_use_real_engine", label: "실제 학습 엔진", help: "시뮬레이션 대신 실제 학습 엔진을 사용합니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
    ],
  },
  {
    id: "delivery-public",
    tab: "delivery",
    title: "공개 이미지 전달",
    description: "대표 이미지를 어디서 서빙할지 정합니다.",
    fields: [
      { key: "public_image_provider", label: "공개 이미지 공급자", help: "공개 이미지 전달 방식입니다.", kind: "select", options: PUBLIC_IMAGE_PROVIDER_OPTIONS },
      { key: "public_asset_base_url", label: "직접 자산 URL", help: "local 공급자일 때만 사용합니다.", kind: "url" },
      { key: "cloudflare_cdn_transform_enabled", label: "Cloudflare 변환 URL", help: "Cloudflare /cdn-cgi/image 변환 URL 사용 여부입니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
    ],
  },
  {
    id: "delivery-r2",
    tab: "delivery",
    title: "Cloudflare R2 전달",
    description: "R2에 업로드하고 공개 URL을 생성할 때 사용합니다.",
    fields: [
      { key: "cloudflare_account_id", label: "계정 ID", help: "Cloudflare 계정 ID입니다." },
      { key: "cloudflare_r2_bucket", label: "버킷", help: "공개 이미지를 저장하는 R2 버킷입니다." },
      { key: "cloudflare_r2_prefix", label: "오브젝트 prefix", help: "버킷 내 저장 경로 prefix입니다." },
      { key: "cloudflare_r2_public_base_url", label: "공개 기준 URL", help: "공개 이미지 기준 URL입니다.", kind: "url" },
      { key: "cloudflare_r2_access_key_id", label: "접근 키 ID", help: "변경 시에만 입력합니다.", kind: "password" },
      { key: "cloudflare_r2_secret_access_key", label: "비밀 접근 키", help: "변경 시에만 입력합니다.", kind: "password" },
    ],
  },
  {
    id: "delivery-github",
    tab: "delivery",
    title: "GitHub Pages 전달",
    description: "GitHub Pages에 공개 이미지를 업로드할 때 사용합니다.",
    fields: [
      { key: "github_pages_owner", label: "소유자", help: "GitHub 사용자 또는 조직입니다." },
      { key: "github_pages_repo", label: "저장소", help: "이미지 업로드 대상 저장소입니다." },
      { key: "github_pages_branch", label: "브랜치", help: "업로드 브랜치입니다." },
      { key: "github_pages_base_url", label: "기준 URL", help: "GitHub Pages 공개 URL입니다.", kind: "url" },
      { key: "github_pages_assets_dir", label: "자산 디렉터리", help: "저장소 내부 업로드 경로입니다." },
      { key: "github_pages_token", label: "업로드 토큰", help: "변경 시에만 입력합니다.", kind: "password" },
    ],
  },
  {
    id: "delivery-cloudinary",
    tab: "delivery",
    title: "Cloudinary 전달",
    description: "Cloudinary 기반 전달을 사용할 때 입력합니다.",
    fields: [
      { key: "cloudinary_cloud_name", label: "클라우드 이름", help: "Cloudinary cloud name 입니다." },
      { key: "cloudinary_folder", label: "폴더", help: "기본 업로드 폴더입니다." },
      { key: "cloudinary_api_key", label: "API 키", help: "변경 시에만 입력합니다.", kind: "password" },
      { key: "cloudinary_api_secret", label: "API 비밀키", help: "변경 시에만 입력합니다.", kind: "password" },
    ],
  },
  {
    id: "automation-master",
    tab: "automation",
    title: "자동화 게이트",
    description: "작업 큐와 각 자동화 경로의 진입 게이트입니다.",
    fields: [
      { key: "automation_master_enabled", label: "마스터 게이트", help: "모든 자동화를 한 번에 허용합니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "automation_scheduler_enabled", label: "스케줄러 자동화", help: "스케줄러 tick 자동화를 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "automation_publish_queue_enabled", label: "발행 큐 자동화", help: "발행 큐 자동화를 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "automation_content_review_enabled", label: "콘텐츠 리뷰 자동화", help: "콘텐츠 리뷰 자동화를 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "automation_training_enabled", label: "학습 자동화", help: "학습 자동화를 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "automation_cloudflare_enabled", label: "Cloudflare 자동화", help: "Cloudflare 자동화 경로를 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "automation_telegram_enabled", label: "Telegram 자동화", help: "Telegram polling 자동화를 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
    ],
  },
  {
    id: "automation-content-ops",
    tab: "automation",
    title: "콘텐츠 운영 자동화",
    description: "리뷰 스캔, 안전 수정, 학습 스냅샷 정책입니다.",
    fields: [
      { key: "content_ops_scan_enabled", label: "리뷰 스캔", help: "5분 주기 라이브 스캔을 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "content_ops_auto_fix_drafts", label: "초안 자동 수정", help: "저위험 초안 수정 자동 적용 여부입니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "content_ops_auto_fix_published_meta", label: "발행본 메타 자동 수정", help: "안전한 메타 수정 자동 적용 여부입니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "content_ops_learning_paused", label: "학습 스냅샷 일시정지", help: "큐레이션 학습 작업을 멈춥니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
    ],
  },
  {
    id: "automation-cloudflare",
    tab: "automation",
    title: "Cloudflare 운영 자동화",
    description: "Cloudflare 채널 반복 발행과 카테고리 가중치를 조정합니다.",
    fields: [
      { key: "cloudflare_channel_enabled", label: "Cloudflare 채널", help: "Cloudflare 채널 자체를 활성화합니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "cloudflare_daily_publish_enabled", label: "일간 자동 발행", help: "Cloudflare 일간 자동 발행을 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "cloudflare_daily_publish_time", label: "시작 시각", help: "Cloudflare 일간 발행 시작 시각입니다.", kind: "time" },
      { key: "cloudflare_daily_publish_interval_hours", label: "반복 간격(시간)", help: "Cloudflare 자동 발행 반복 간격입니다.", kind: "number" },
      { key: "cloudflare_daily_publish_weekday_quota", label: "평일 쿼터", help: "월~토 일일 발행 수입니다.", kind: "number" },
      { key: "cloudflare_daily_publish_sunday_quota", label: "일요일 쿼터", help: "일요일 일일 발행 수입니다.", kind: "number" },
      { key: "cloudflare_inline_images_enabled", label: "본문 인라인 이미지", help: "본문 인라인 콜라주 사용 여부입니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "cloudflare_blossom_cap_ratio", label: "벚꽃 비중 상한", help: "Cloudflare 채널 벚꽃 주제 상한입니다.", kind: "number" },
    ],
  },
  {
    id: "integrations-blogger",
    tab: "integrations",
    title: "Blogger OAuth",
    description: "Blogger, Search Console, GA4 연동에 필요한 인증 정보입니다.",
    fields: [
      { key: "blogger_client_name", label: "OAuth 앱 이름", help: "Google 동의 화면에 표시되는 이름입니다." },
      { key: "blogger_client_id", label: "클라이언트 ID", help: "Google OAuth 웹 클라이언트 ID입니다." },
      { key: "blogger_client_secret", label: "클라이언트 시크릿", help: "변경 시에만 입력합니다.", kind: "password" },
      { key: "blogger_redirect_uri", label: "리디렉션 URI", help: "Google OAuth 콜백 URI입니다.", kind: "url" },
    ],
  },
  {
    id: "integrations-cloudflare",
    tab: "integrations",
    title: "Cloudflare 연동",
    description: "Cloudflare 콘텐츠 채널 API 연동 정보입니다.",
    fields: [
      { key: "cloudflare_blog_api_base_url", label: "API 기본 URL", help: "Cloudflare 블로그 API 기본 주소입니다.", kind: "url" },
      { key: "cloudflare_blog_m2m_token", label: "M2M 토큰", help: "변경 시에만 입력합니다.", kind: "password" },
    ],
  },
  {
    id: "integrations-sheet",
    tab: "integrations",
    title: "Google Sheet 연동",
    description: "채널별 시트 동기화 대상 문서와 탭 이름입니다.",
    fields: [
      { key: "google_sheet_url", label: "시트 URL", help: "동기화 대상 Google Sheet URL입니다.", kind: "url" },
      { key: "google_sheet_id", label: "시트 ID", help: "URL에서 파생되는 문서 ID입니다." },
      { key: "google_sheet_travel_tab", label: "여행 탭", help: "여행 채널 스냅샷 탭 이름입니다." },
      { key: "google_sheet_mystery_tab", label: "미스터리 탭", help: "미스터리 채널 스냅샷 탭 이름입니다." },
      { key: "google_sheet_cloudflare_tab", label: "Cloudflare 탭", help: "Cloudflare 채널 스냅샷 탭 이름입니다." },
    ],
  },
  {
    id: "integrations-bots",
    tab: "integrations",
    title: "외부 봇과 보조 연동",
    description: "LLM 키, Telegram, Blogger Playwright 동기화 값을 설정합니다.",
    fields: [
      { key: "openai_api_key", label: "OpenAI API 키", help: "변경 시에만 입력합니다.", kind: "password" },
      { key: "openai_admin_api_key", label: "OpenAI Admin API 키", help: "무료 사용량 위젯용 키입니다.", kind: "password" },
      { key: "gemini_api_key", label: "Gemini API 키", help: "변경 시에만 입력합니다.", kind: "password" },
      { key: "telegram_bot_token", label: "Telegram 봇 토큰", help: "변경 시에만 입력합니다.", kind: "password" },
      { key: "telegram_chat_id", label: "Telegram 채팅 ID", help: "알림 대상 채팅 ID입니다.", kind: "password" },
      { key: "blogger_playwright_enabled", label: "Blogger Playwright", help: "Blogger 에디터 자동 동기화를 켭니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "blogger_playwright_auto_sync", label: "발행 후 자동 동기화", help: "발행 직후 검색 설명 동기화 여부입니다.", kind: "boolean", options: BOOLEAN_OPTIONS },
      { key: "blogger_playwright_cdp_url", label: "원격 디버깅 URL", help: "Blogger Playwright가 붙을 CDP 주소입니다.", kind: "url" },
      { key: "blogger_playwright_account_index", label: "계정 인덱스", help: "Blogger 에디터 URL의 /u/{index} 값입니다.", kind: "number" },
    ],
  },
];

export const EDITABLE_SETTING_KEYS = new Set(
  SETTINGS_SECTIONS.flatMap((section) => section.fields.map((field) => field.key)),
);

export function getSectionsForTab(tab: SettingsTab) {
  return SETTINGS_SECTIONS.filter((section) => section.tab === tab);
}

export function getDiagnosticSettings(settings: SettingRead[]) {
  const diagnosticMatchers = [
    /^cloudflare_prompt__/,
    /_last_/,
    /_counts$/,
    /_path$/,
    /_updated_at$/,
    /_created_at$/,
    /_version$/,
    /_offset$/,
    /_expires_at$/,
    /token_scope$/,
    /token_type$/,
    /^content_overview_tab$/,
  ];

  return settings
    .filter((item) => !EDITABLE_SETTING_KEYS.has(item.key))
    .filter((item) => diagnosticMatchers.some((matcher) => matcher.test(item.key)))
    .sort((left, right) => left.key.localeCompare(right.key));
}

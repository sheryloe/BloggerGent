import type { SettingRead } from "@/lib/types";

export type SettingsTab = "workspace" | "channels" | "pipeline" | "models" | "planner" | "automation" | "publishing" | "integrations";

export type SettingsControlType = "boolean" | "number" | "text" | "textarea" | "password" | "time" | "select";

export type SettingsOption = {
  label: string;
  value: string;
};

export type SettingsFieldMeta = {
  control: SettingsControlType;
  label?: string;
  description?: string;
  placeholder?: string;
  options?: SettingsOption[];
  monospace?: boolean;
  highImpact?: boolean;
};

export type SettingsGroupDefinition = {
  id: string;
  title: string;
  description: string;
  match: (key: string) => boolean;
};

export const SETTINGS_TABS: Array<{ key: SettingsTab; label: string; summary: string }> = [
  { key: "workspace", label: "워크스페이스", summary: "기본 정책과 기본값" },
  { key: "channels", label: "채널", summary: "연결 상태와 지원 범위" },
  { key: "pipeline", label: "파이프라인", summary: "채널별 프롬프트 플로우" },
  { key: "models", label: "모델", summary: "모델 라우팅과 토큰 정책" },
  { key: "planner", label: "플래너", summary: "캘린더/스케줄/주제 믹스" },
  { key: "automation", label: "자동화", summary: "자동화 마스터 스위치와 학습" },
  { key: "publishing", label: "발행", summary: "발행 안전장치와 품질 게이트" },
  { key: "integrations", label: "연동", summary: "OAuth, 저장소, 비밀값" },
];

const BOOLEAN_OPTIONS: SettingsOption[] = [
  { label: "사용", value: "true" },
  { label: "중지", value: "false" },
];

const PROVIDER_MODE_OPTIONS: SettingsOption[] = [
  { label: "Mock", value: "mock" },
  { label: "Live", value: "live" },
];

const IMAGE_PROVIDER_OPTIONS: SettingsOption[] = [
  { label: "Cloudflare R2", value: "cloudflare_r2" },
  { label: "Cloudinary", value: "cloudinary" },
  { label: "GitHub Pages", value: "github_pages" },
  { label: "Local URL", value: "local" },
];

const TOPIC_PROVIDER_OPTIONS: SettingsOption[] = [
  { label: "OpenAI", value: "openai" },
  { label: "Gemini", value: "gemini" },
];

const PIPELINE_STOP_OPTIONS: SettingsOption[] = [
  { label: "전체 파이프라인 실행", value: "none" },
  { label: "글 생성 후 중단", value: "GENERATING_ARTICLE" },
  { label: "이미지 프롬프트 후 중단", value: "GENERATING_IMAGE_PROMPT" },
  { label: "이미지 생성 후 중단", value: "GENERATING_IMAGE" },
  { label: "HTML 조립 후 중단", value: "ASSEMBLING_HTML" },
];

const RESEARCH_MODE_OPTIONS: SettingsOption[] = [
  { label: "Hybrid", value: "hybrid" },
  { label: "Prompt Only", value: "prompt_only" },
  { label: "Validate", value: "validate" },
  { label: "Off", value: "off" },
];

function hasPrefix(key: string, prefixes: string[]) {
  return prefixes.some((prefix) => key.startsWith(prefix));
}

function hasFragment(key: string, fragments: string[]) {
  return fragments.some((fragment) => key.includes(fragment));
}

export const GLOBAL_TABS: SettingsTab[] = ["workspace", "models", "planner", "automation", "publishing", "integrations"];

const TAB_GROUPS: Record<Exclude<SettingsTab, "channels" | "pipeline">, SettingsGroupDefinition[]> = {
  workspace: [
    {
      id: "workspace-foundation",
      title: "기본 정책",
      description: "워크스페이스 이름, 기본 시간대, 기본 발행 정책처럼 전체 시스템의 기준점입니다.",
      match: (key) => ["app_name", "default_blog_timezone", "default_publish_mode", "default_writer_tone", "provider_mode"].includes(key),
    },
    {
      id: "workspace-topic-policy",
      title: "주제 정책",
      description: "주제 발굴 제한, 중복 가드, 리서치 모드를 조정합니다.",
      match: (key) =>
        hasPrefix(key, ["topic_"]) ||
        ["same_cluster_cooldown_hours", "same_angle_cooldown_days", "topic_guard_enabled", "travel_research_mode"].includes(key),
    },
  ],
  models: [
    {
      id: "models-defaults",
      title: "기본 모델 라우팅",
      description: "본문 생성, 이미지 생성, 요청 절약 모드를 정의합니다.",
      match: (key) =>
        ["openai_text_model", "article_generation_model", "openai_image_model", "openai_request_saver_mode"].includes(key),
    },
    {
      id: "models-topic-discovery",
      title: "토픽 발굴 모델",
      description: "토픽 발굴 공급자와 모델 선택을 관리합니다.",
      match: (key) => ["topic_discovery_provider", "topic_discovery_model", "gemini_model"].includes(key),
    },
    {
      id: "models-limits",
      title: "모델 사용 한도",
      description: "Gemini 요청 한도와 발굴량 상한을 조정합니다.",
      match: (key) =>
        ["topic_discovery_max_topics_per_run", "gemini_daily_request_limit", "gemini_requests_per_minute_limit"].includes(key),
    },
  ],
  planner: [
    {
      id: "planner-foundation",
      title: "플래너 기본값",
      description: "월간 계획 생성 시 사용하는 슬롯 수와 운영 시간을 정의합니다.",
      match: (key) => hasPrefix(key, ["planner_"]),
    },
    {
      id: "planner-schedules",
      title: "운영 스케줄",
      description: "전역 스케줄과 여행/미스터리 반복 스케줄을 관리합니다.",
      match: (key) =>
        ["schedule_enabled", "schedule_time", "schedule_timezone", "last_schedule_run_on"].includes(key) ||
        hasPrefix(key, ["travel_schedule_", "mystery_schedule_"]),
    },
    {
      id: "planner-rotation",
      title: "주제 믹스와 회전 규칙",
      description: "카테고리 회전과 계절성 캡 비율을 관리합니다.",
      match: (key) =>
        hasFragment(key, ["editorial_", "blossom_", "topic_mix_counts"]) ||
        ["travel_topics_per_run", "mystery_topics_per_run"].includes(key),
    },
  ],
  automation: [
    {
      id: "automation-gates",
      title: "자동화 마스터 스위치",
      description: "스케줄러, 발행 큐, 컨텐츠 리뷰, 텔레그램 같은 자동화 경로의 마스터 게이트입니다.",
      match: (key) => hasPrefix(key, ["automation_"]),
    },
    {
      id: "automation-training",
      title: "학습 자동화",
      description: "예약 학습과 실제 엔진 실행 여부를 관리합니다.",
      match: (key) => hasPrefix(key, ["training_"]),
    },
    {
      id: "automation-content-ops",
      title: "컨텐츠 운영 자동화",
      description: "리뷰 스캔, 자동 수정, 스냅샷 경로 같은 운영 자동화를 관리합니다.",
      match: (key) => hasPrefix(key, ["content_ops_"]),
    },
  ],
  publishing: [
    {
      id: "publishing-safety",
      title: "발행 안전장치",
      description: "블로그별 일일 한도, 최소 간격, 단계 중단 지점을 정의합니다.",
      match: (key) => hasPrefix(key, ["publish_"]) || key === "pipeline_stop_after",
    },
    {
      id: "publishing-quality",
      title: "품질 게이트",
      description: "유사도/SEO/GEO 최소 점수 기준을 제어합니다.",
      match: (key) => hasPrefix(key, ["quality_gate_"]),
    },
    {
      id: "publishing-execution",
      title: "실행 채널 동기화",
      description: "Blogger 에디터 자동화와 Cloudflare 발행 자동화를 관리합니다.",
      match: (key) =>
        hasPrefix(key, ["blogger_playwright_", "cloudflare_daily_"]) ||
        ["cloudflare_inline_images_enabled", "travel_inline_collage_enabled", "mystery_inline_collage_enabled"].includes(key),
    },
  ],
  integrations: [
    {
      id: "integrations-openai-gemini",
      title: "AI 자격 증명",
      description: "OpenAI/Gemini API 키와 관리자 키를 관리합니다.",
      match: (key) => ["openai_api_key", "openai_admin_api_key", "gemini_api_key"].includes(key),
    },
    {
      id: "integrations-google-oauth",
      title: "Google OAuth",
      description: "Blogger, Search Console, GA4 연동에 쓰는 OAuth 정보를 관리합니다.",
      match: (key) => hasPrefix(key, ["blogger_client_", "blogger_redirect_uri", "blogger_refresh_token", "blogger_access_token", "blogger_token_", "blogger_oauth_"]),
    },
    {
      id: "integrations-public-assets",
      title: "공개 이미지 전달",
      description: "Cloudflare, Cloudinary, GitHub Pages, Local URL 중 공개 이미지 전달 경로를 설정합니다.",
      match: (key) =>
        ["public_image_provider", "public_asset_base_url"].includes(key) ||
        hasPrefix(key, ["cloudflare_account_", "cloudflare_r2_", "cloudinary_", "github_pages_"]),
    },
    {
      id: "integrations-cloudflare-api",
      title: "Cloudflare 채널 API",
      description: "Cloudflare 채널 연동 API 주소와 토큰을 관리합니다.",
      match: (key) => hasPrefix(key, ["cloudflare_channel_", "cloudflare_blog_"]),
    },
    {
      id: "integrations-google-sheet",
      title: "Google Sheets",
      description: "스냅샷 시트 동기화 경로와 탭 이름을 설정합니다.",
      match: (key) => hasPrefix(key, ["google_sheet_", "sheet_sync_"]) || key === "last_sheet_sync_on",
    },
    {
      id: "integrations-telegram",
      title: "Telegram",
      description: "알림/운영 메시지 전달에 필요한 Telegram 비밀값입니다.",
      match: (key) => hasPrefix(key, ["telegram_"]),
    },
  ],
};

const FIELD_META_BY_KEY: Record<string, SettingsFieldMeta> = {
  provider_mode: { control: "select", options: PROVIDER_MODE_OPTIONS, highImpact: true },
  public_image_provider: { control: "select", options: IMAGE_PROVIDER_OPTIONS, highImpact: true },
  openai_request_saver_mode: { control: "boolean", options: BOOLEAN_OPTIONS },
  topic_discovery_provider: { control: "select", options: TOPIC_PROVIDER_OPTIONS },
  pipeline_stop_after: { control: "select", options: PIPELINE_STOP_OPTIONS, highImpact: true },
  travel_research_mode: { control: "select", options: RESEARCH_MODE_OPTIONS },
};

const TEXTAREA_HINTS = ["weights", "counts", "scope", "prompt_memory_path", "snapshot_path"];
const NUMBER_HINTS = ["limit", "count", "hours", "minutes", "seconds", "ratio", "quota", "posts", "score", "index"];

export function prettifySettingKey(key: string) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase())
    .replace(/Openai/g, "OpenAI")
    .replace(/Ga4/g, "GA4")
    .replace(/Oauth/g, "OAuth")
    .replace(/Api/g, "API")
    .replace(/Url/g, "URL")
    .replace(/R2/g, "R2");
}

export function getSettingsGroups(tab: Exclude<SettingsTab, "channels" | "pipeline">, items: SettingRead[]) {
  const groups = TAB_GROUPS[tab];
  const consumed = new Set<string>();
  const resolved = groups
    .map((group) => {
      const groupItems = items.filter((item) => group.match(item.key));
      groupItems.forEach((item) => consumed.add(item.key));
      return { ...group, items: groupItems };
    })
    .filter((group) => group.items.length > 0);

  const remaining = items.filter((item) => !consumed.has(item.key));
  if (remaining.length > 0) {
    resolved.push({
      id: `${tab}-advanced`,
      title: "기타 / 고급",
      description: "아직 별도 분류되지 않은 고급 설정입니다.",
      match: () => true,
      items: remaining,
    });
  }

  return resolved;
}

export function getSettingsTabItems(tab: Exclude<SettingsTab, "channels" | "pipeline">, settings: SettingRead[]) {
  switch (tab) {
    case "workspace":
      return settings.filter((item) => {
        if (hasPrefix(item.key, ["automation_", "planner_", "publish_", "training_", "content_ops_", "travel_schedule_", "mystery_schedule_", "cloudflare_daily_", "google_sheet_", "sheet_sync_", "telegram_", "github_pages_", "cloudinary_", "cloudflare_r2_"])) {
          return false;
        }
        if (hasFragment(item.key, ["model", "api_key"])) {
          return false;
        }
        return !hasPrefix(item.key, ["blogger_client_", "blogger_refresh_", "blogger_access_", "blogger_token_", "blogger_oauth_", "blogger_playwright_", "cloudflare_blog_", "cloudflare_account_"]);
      });
    case "models":
      return settings.filter((item) => hasFragment(item.key, ["model"]) || ["provider_mode", "openai_request_saver_mode", "topic_discovery_provider", "topic_discovery_max_topics_per_run", "gemini_daily_request_limit", "gemini_requests_per_minute_limit"].includes(item.key));
    case "planner":
      return settings.filter((item) => hasPrefix(item.key, ["planner_", "schedule_", "travel_schedule_", "mystery_schedule_"]) || hasFragment(item.key, ["editorial_", "blossom_", "topic_mix_counts"]) || ["travel_topics_per_run", "mystery_topics_per_run"].includes(item.key));
    case "automation":
      return settings.filter((item) => hasPrefix(item.key, ["automation_", "training_", "content_ops_"]));
    case "publishing":
      return settings.filter((item) => hasPrefix(item.key, ["publish_", "quality_gate_", "blogger_playwright_", "cloudflare_daily_"]) || ["pipeline_stop_after", "cloudflare_inline_images_enabled", "travel_inline_collage_enabled", "mystery_inline_collage_enabled"].includes(item.key));
    case "integrations":
      return settings.filter((item) => hasPrefix(item.key, ["openai_", "gemini_", "blogger_client_", "blogger_redirect_uri", "blogger_refresh_", "blogger_access_", "blogger_token_", "blogger_oauth_", "google_sheet_", "sheet_sync_", "telegram_", "github_pages_", "cloudinary_", "cloudflare_blog_", "cloudflare_account_", "cloudflare_r2_", "public_image_provider", "public_asset_base_url", "cloudflare_channel_"]) || item.key === "last_sheet_sync_on");
  }
}

export function getSettingFieldMeta(item: SettingRead): SettingsFieldMeta {
  if (item.is_secret) {
    return {
      control: "password",
      label: prettifySettingKey(item.key),
      description: item.description ?? item.key,
      placeholder: "새 값 입력 시 갱신됩니다.",
      monospace: true,
      highImpact: true,
    };
  }

  const mapped = FIELD_META_BY_KEY[item.key];
  if (mapped) {
    return {
      ...mapped,
      label: mapped.label ?? prettifySettingKey(item.key),
      description: mapped.description ?? item.description ?? item.key,
    };
  }

  const normalized = (item.value ?? "").trim().toLowerCase();
  if (normalized === "true" || normalized === "false") {
    return { control: "boolean", label: prettifySettingKey(item.key), description: item.description ?? item.key, options: BOOLEAN_OPTIONS };
  }

  if (item.key.endsWith("_time") && /^\d{2}:\d{2}$/.test(item.value ?? "")) {
    return { control: "time", label: prettifySettingKey(item.key), description: item.description ?? item.key };
  }

  if (/^-?\d+(\.\d+)?$/.test(item.value ?? "") || hasFragment(item.key, NUMBER_HINTS)) {
    return { control: "number", label: prettifySettingKey(item.key), description: item.description ?? item.key };
  }

  if ((item.value ?? "").length > 80 || hasFragment(item.key, TEXTAREA_HINTS)) {
    return { control: "textarea", label: prettifySettingKey(item.key), description: item.description ?? item.key, monospace: hasFragment(item.key, ["json", "path", "url"]) };
  }

  return {
    control: "text",
    label: prettifySettingKey(item.key),
    description: item.description ?? item.key,
    monospace: hasFragment(item.key, ["path", "url", "token", "id"]),
  };
}

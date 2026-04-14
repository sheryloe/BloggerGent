"use client";

import { useMemo, useState, useTransition, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  GEMINI_MODEL_SUGGESTIONS,
  OPENAI_DATA_SHARING_FREE_TIERS,
  OPENAI_IMAGE_MODEL_SUGGESTIONS,
  OPENAI_TEXT_MODEL_SUGGESTIONS,
} from "@/lib/ai-model-catalog";
import type { SettingItem } from "@/lib/types";

type FieldConfig = {
  key: string;
  label: string;
  help: string;
  required?: boolean;
  type?: "text" | "password" | "number";
  options?: Array<{ value: string; label: string }>;
  suggestions?: string[];
  showWhen?: (values: Record<string, string>) => boolean;
};

type SectionConfig = {
  title: string;
  description: string;
  fields: FieldConfig[];
};

const sections: SectionConfig[] = [
  {
    title: "AI 공급자",
    description: "BloggerGent가 토픽을 찾고, 글을 쓰고, 이미지를 생성하는 방식을 정합니다.",
    fields: [
      {
        key: "provider_mode",
        label: "공급자 모드",
        help: "테스트 PC에서는 mock을 사용하고, 실제 API 호출이 필요할 때만 live로 전환합니다.",
        required: true,
        options: [
          { value: "mock", label: "mock" },
          { value: "live", label: "live" },
        ],
      },
      {
        key: "openai_api_key",
        label: "OpenAI API 키",
        help: "기존 OpenAI live 생성 경로와 이미지 생성에 사용합니다. 리팩토링/개선 배치는 별도로 Codex CLI / GPT-5.4를 우선 사용합니다.",
        type: "password",
      },
      {
        key: "openai_admin_api_key",
        label: "OpenAI Admin API 키",
        help: "선택 항목입니다. 무료 사용량 위젯과 조직 사용량 조회에만 사용합니다.",
        type: "password",
      },
      {
        key: "text_runtime_kind",
        label: "텍스트 런타임",
        help: "표준 생성 파이프라인의 기본 텍스트 런타임입니다. 리팩토링 전용 단계는 Codex CLI / GPT-5.4를 우선 사용합니다.",
        options: [
          { value: "openai", label: "OpenAI" },
          { value: "codex_cli", label: "Codex CLI" },
          { value: "gemini_cli", label: "Gemini CLI" },
        ],
      },
      {
        key: "text_runtime_model",
        label: "텍스트 런타임 모델",
        help: "표준 생성 경로에서 사용하는 기본 텍스트 모델입니다. 리팩토링 단계는 Codex CLI / GPT-5.4를 별도로 사용합니다.",
        suggestions: OPENAI_TEXT_MODEL_SUGGESTIONS,
      },
      {
        key: "image_runtime_kind",
        label: "이미지 런타임",
        help: "이미지 생성만 OpenAI Image API를 사용합니다.",
        options: [{ value: "openai_image", label: "OpenAI Image API" }],
      },
      {
        key: "openai_image_model",
        label: "OpenAI 이미지 모델",
        help: "live 모드에서만 사용합니다. mock 모드에서는 로컬 MockImageProvider가 Pillow로 이미지를 만듭니다.",
        suggestions: OPENAI_IMAGE_MODEL_SUGGESTIONS,
      },
      {
        key: "openai_request_saver_mode",
        label: "요청 절약 모드",
        help: "가능한 경우 추가 이미지 프롬프트 정제 호출을 생략하고 기존 본문 출력을 재사용합니다.",
        options: [
          { value: "true", label: "사용" },
          { value: "false", label: "사용 안 함" },
        ],
      },
      {
        key: "openai_usage_hard_cap_enabled",
        label: "OpenAI 사용량 하드캡",
        help: "호환성 필드입니다. 실제 운영에서는 API 경로 하드캡이 항상 강제되며 100% 도달 또는 사용량 조회 실패 시 즉시 차단됩니다.",
        options: [{ value: "true", label: "항상 사용" }],
      },
      {
        key: "topic_discovery_provider",
        label: "토픽 발굴 공급자",
        help: "표준 생성 경로의 토픽 발굴 공급자입니다. 리팩토링/재작성 배치는 별도 Codex 우선 라우팅을 사용합니다.",
        options: [
          { value: "openai", label: "OpenAI" },
          { value: "codex_cli", label: "Codex CLI" },
          { value: "gemini", label: "Gemini" },
        ],
      },
      {
        key: "topic_discovery_max_topics_per_run",
        label: "1회 토픽 발굴 최대 개수",
        help: "모델이 토픽을 돌려준 직후 적용되는 상한입니다. 0은 무제한이며, 과도한 큐 적재 방지를 위해 기본값 3을 권장합니다.",
        type: "number",
      },
      {
        key: "gemini_api_key",
        label: "Gemini API 키",
        help: "토픽 발굴 공급자가 Gemini일 때만 필요합니다.",
        type: "password",
        showWhen: (values) => values.topic_discovery_provider === "gemini",
      },
      {
        key: "gemini_model",
        label: "Gemini 모델",
        help: "Gemini 토픽 발굴에 사용할 모델입니다.",
        suggestions: GEMINI_MODEL_SUGGESTIONS,
        showWhen: (values) => values.topic_discovery_provider === "gemini",
      },
    ],
  },
  {
    title: "공개 이미지 전달",
    description: "Blogger 글에서 썸네일과 대표 이미지를 안정적으로 열 수 있도록 공개 이미지 URL의 원본을 정합니다.",
    fields: [
      {
        key: "public_image_provider",
        label: "공개 이미지 공급자",
        help: "권장 순서는 img 서브도메인을 붙인 Cloudflare R2, 그다음 Cloudinary, 그다음 GitHub Pages입니다. Local은 외부 공개 URL일 때만 안전합니다.",
        required: true,
        options: [
          { value: "cloudflare_r2", label: "Cloudflare R2" },
          { value: "cloudinary", label: "Cloudinary" },
          { value: "github_pages", label: "GitHub Pages" },
          { value: "local", label: "로컬 URL" },
        ],
      },
      {
        key: "cloudflare_account_id",
        label: "Cloudflare 계정 ID",
        help: "S3 호환 API로 직접 R2 업로드할 때 사용합니다.",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudflare_r2_bucket",
        label: "Cloudflare R2 버킷",
        help: "글마다 업로드되는 원본 이미지를 저장하는 버킷입니다.",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudflare_r2_access_key_id",
        label: "R2 접근 키 ID",
        help: "R2 버킷에 발급된 접근 키입니다.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudflare_r2_secret_access_key",
        label: "R2 비밀 접근 키",
        help: "R2 접근 키 ID와 짝을 이루는 비밀 키입니다.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudflare_r2_public_base_url",
        label: "Cloudflare 공개 기준 URL",
        help: "권장값은 https://img.example.com 입니다. 렌더링된 페이지는 이 호스트에서 /cdn-cgi/image 변환 URL로 hero/card/thumb 변형을 만듭니다.",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudflare_r2_prefix",
        label: "R2 오브젝트 prefix",
        help: "버킷 내부 경로 prefix입니다. 파일은 <prefix>/<slug>.png 형태로 저장됩니다.",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudinary_cloud_name",
        label: "Cloudinary 클라우드 이름",
        help: "BloggerGent가 Cloudinary에 직접 업로드합니다. 원본 secure URL을 기준으로 저장하고, 렌더링된 페이지에서는 변환 URL을 써야 최적화 전달이 됩니다.",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_api_key",
        label: "Cloudinary API 키",
        help: "Cloudinary 직접 업로드에 필요합니다.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_api_secret",
        label: "Cloudinary API 비밀키",
        help: "Cloudinary 직접 업로드에 필요합니다.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_folder",
        label: "Cloudinary 폴더",
        help: "업로드 이미지용 선택 폴더 prefix입니다. Cloudinary 마이그레이션 검증이 끝날 때까지 기존 자산은 삭제하지 마세요.",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "github_pages_owner",
        label: "GitHub 소유자",
        help: "GitHub Pages 전달에 쓰는 저장소 소유자입니다. 나중에 원격 파일을 지우면 예전 Blogger 글의 이미지가 깨질 수 있습니다.",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_repo",
        label: "GitHub 저장소",
        help: "공개 이미지를 저장하는 저장소입니다.",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_branch",
        label: "GitHub 브랜치",
        help: "보통 main 입니다.",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_token",
        label: "GitHub 토큰",
        help: "업로드를 위해 Contents 읽기/쓰기 권한이 필요합니다.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_base_url",
        label: "GitHub Pages 기준 URL",
        help: "예: https://username.github.io/repository",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_assets_dir",
        label: "GitHub 자산 디렉터리",
        help: "저장소 내부의 선택 폴더 경로입니다. Cloudinary 마이그레이션 검증이 끝날 때까지 GitHub 자산을 삭제하지 마세요.",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "public_asset_base_url",
        label: "로컬 공개 자산 기준 URL",
        help: "API 또는 정적 저장소가 외부 인터넷에서 직접 접근 가능할 때만 사용하세요.",
        showWhen: (values) => values.public_image_provider === "local",
      },
    ],
  },
  {
    title: "Google OAuth",
    description: "Blogger, Search Console, GA4 연동에 사용하는 인증 정보입니다.",
    fields: [
      { key: "blogger_client_name", label: "OAuth 앱 이름", help: "Google 동의 화면에 표시되는 앱 이름입니다." },
      { key: "blogger_client_id", label: "클라이언트 ID", help: "Google Cloud OAuth 웹 클라이언트 ID입니다.", required: true },
      { key: "blogger_client_secret", label: "클라이언트 시크릿", help: "Google Cloud OAuth 클라이언트 비밀값입니다.", type: "password", required: true },
      { key: "blogger_redirect_uri", label: "리디렉션 URI", help: "기본값: http://localhost:8000/api/v1/blogger/oauth/callback", required: true },
    ],
  },
  {
    title: "운영 설정",
    description: "토픽 발굴 주기와 발행 안전장치를 조정합니다.",
    fields: [
      {
        key: "schedule_enabled",
        label: "자동 스케줄",
        help: "일일 토픽 발굴 스케줄러를 켭니다.",
        options: [
          { value: "true", label: "사용" },
          { value: "false", label: "사용 안 함" },
        ],
      },
      { key: "schedule_time", label: "일일 스케줄 시간", help: "형식: HH:MM" },
      { key: "schedule_timezone", label: "스케줄 시간대", help: "예: Asia/Seoul" },
      {
        key: "travel_schedule_time",
        label: "여행 시작 시각",
        help: "여행 자동 발행 슬롯의 첫 시작 시각입니다. 예: 00:00",
      },
      {
        key: "travel_schedule_interval_hours",
        label: "여행 반복 간격(시간)",
        help: "여행 글을 몇 시간 간격으로 1개씩 올릴지 정합니다.",
        type: "number",
      },
      {
        key: "travel_topics_per_run",
        label: "여행 슬롯당 글 수",
        help: "현재 권장값은 1입니다.",
        type: "number",
      },
      {
        key: "mystery_schedule_time",
        label: "미스테리 시작 시각",
        help: "미스테리 자동 발행 슬롯의 첫 시작 시각입니다. 예: 01:00",
      },
      {
        key: "mystery_schedule_interval_hours",
        label: "미스테리 반복 간격(시간)",
        help: "미스테리 글을 몇 시간 간격으로 1개씩 올릴지 정합니다.",
        type: "number",
      },
      {
        key: "mystery_topics_per_run",
        label: "미스테리 슬롯당 글 수",
        help: "현재 권장값은 1입니다.",
        type: "number",
      },
      {
        key: "publish_daily_limit_per_blog",
        label: "블로그별 일일 공개 발행 한도",
        help: "실제 발행과 예약 작업만 제한합니다. 주제 발굴이나 초안 생성 개수는 제한하지 않습니다.",
        type: "number",
      },
      {
        key: "publish_min_interval_seconds",
        label: "최소 발행 간격(초)",
        help: "같은 블로그에서 Blogger 발행 API 호출 사이의 최소 간격입니다. 권장값은 60초 이상입니다.",
        type: "number",
      },
      {
        key: "gemini_daily_request_limit",
        label: "Gemini 일일 요청 한도",
        help: "Gemini 무료 티어 보호용 제한입니다. 0이면 무제한입니다.",
        type: "number",
        showWhen: (values) => values.topic_discovery_provider === "gemini",
      },
      {
        key: "gemini_requests_per_minute_limit",
        label: "Gemini 분당 요청 한도",
        help: "Gemini 토픽 발굴 속도 제한입니다. 0이면 무제한입니다.",
        type: "number",
        showWhen: (values) => values.topic_discovery_provider === "gemini",
      },
      {
        key: "pipeline_stop_after",
        label: "파이프라인 중단 단계",
        help: "전체 결과물을 만들기 전에 멈추고 싶을 때 테스트 PC에서만 사용하세요.",
        options: [
          { value: "none", label: "전체 파이프라인 실행" },
          { value: "GENERATING_ARTICLE", label: "글 생성 후 중단" },
          { value: "GENERATING_IMAGE_PROMPT", label: "이미지 프롬프트 단계 후 중단" },
          { value: "GENERATING_IMAGE", label: "이미지 생성 후 중단" },
          { value: "ASSEMBLING_HTML", label: "HTML 조립 후 중단" },
        ],
      },
    ],
  },
  {
    title: "Blogger 에디터 자동화",
    description: "발행 후 Blogger 검색 설명을 갱신하는 선택형 Playwright 자동화입니다.",
    fields: [
      {
        key: "blogger_playwright_enabled",
        label: "Playwright 동기화 사용",
        help: "원격 디버그 브라우저 세션이 이미 Blogger에 로그인된 경우에만 켜세요.",
        options: [
          { value: "true", label: "사용" },
          { value: "false", label: "사용 안 함" },
        ],
      },
      {
        key: "blogger_playwright_auto_sync",
        label: "발행 후 자동 동기화",
        help: "켜면 공개 발행 성공 후 워커가 검색 설명 동기화를 시도합니다.",
        options: [
          { value: "true", label: "사용" },
          { value: "false", label: "사용 안 함" },
        ],
        showWhen: (values) => values.blogger_playwright_enabled === "true",
      },
      {
        key: "blogger_playwright_cdp_url",
        label: "원격 디버깅 URL",
        help: "기본값: http://host.docker.internal:9223",
        showWhen: (values) => values.blogger_playwright_enabled === "true",
      },
      {
        key: "blogger_playwright_account_index",
        label: "Blogger 계정 인덱스",
        help: "보통 0입니다. Blogger 에디터 URL이 다른 /u/{index} 값을 쓸 때만 바꾸세요.",
        type: "number",
        showWhen: (values) => values.blogger_playwright_enabled === "true",
      },
    ],
  },
];

function getInputType(field: FieldConfig): "password" | "number" | "text" {
  if (field.options) return "text";
  return field.type ?? "text";
}

function sharingGroupLabel(groupId: string) {
  if (groupId === "shared-1m") return "일일 공유 무료 풀: 100만 토큰";
  if (groupId === "shared-10m") return "일일 공유 무료 풀: 1,000만 토큰";
  return "공유 무료 풀";
}

function resolveApiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
}

export function SettingsForm({ settings }: { settings: SettingItem[] }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [status, setStatus] = useState("");
  const [values, setValues] = useState<Record<string, string>>(Object.fromEntries(settings.map((item) => [item.key, item.value])));
  const settingsByKey = useMemo(() => new Map(settings.map((item) => [item.key, item])), [settings]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("");

    const response = await fetch(`${resolveApiBaseUrl()}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setStatus(typeof payload?.detail === "string" ? payload.detail : "설정을 저장하지 못했습니다.");
      return;
    }

    setStatus("설정을 저장했습니다.");
    startTransition(() => router.refresh());
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <Card>
        <CardHeader>
          <CardDescription>빠른 안내</CardDescription>
          <CardTitle>먼저 볼 핵심</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm leading-7 text-slate-700 lg:grid-cols-3">
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">안전한 테스트 모드</p>
            <p className="mt-1"><code>provider_mode=mock</code>이면 글 생성, 이미지 생성, 발행 작업이 테스트 PC 안에서만 동작합니다.</p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">과도한 토픽 적재 방지</p>
            <p className="mt-1"><code>topic_discovery_max_topics_per_run</code>은 발굴된 토픽이 실제 작업 큐로 넘어가는 개수를 강제로 제한합니다.</p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">Blogger API 보호</p>
            <p className="mt-1"><code>publish_min_interval_seconds</code>는 Blogger 발행 요청 사이의 안전 간격을 유지합니다.</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription>OpenAI 공유 무료 풀</CardDescription>
          <CardTitle>무료 사용량 참고</CardTitle>
          <p className="text-sm leading-6 text-slate-600">이 수치는 OpenAI API 감시용 참고값입니다. 기본 텍스트 생성은 Codex CLI가 담당하고, 여기서는 이미지 API와 예외적인 OpenAI 텍스트 호출만 추적합니다.</p>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2">
          {OPENAI_DATA_SHARING_FREE_TIERS.map((group) => (
            <div key={group.id} className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
              <p className="font-semibold text-ink">{sharingGroupLabel(group.id)}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {group.models.map((model) => (
                  <Badge key={model} className="rounded-full px-3 py-1 text-[11px]">{model}</Badge>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {sections.map((section) => {
        const fields = section.fields.filter((field) => !field.showWhen || field.showWhen(values));
        return (
          <Card key={section.title}>
            <CardHeader>
              <CardDescription>전역 설정</CardDescription>
              <CardTitle>{section.title}</CardTitle>
              <p className="text-sm leading-6 text-slate-600">{section.description}</p>
            </CardHeader>
            <CardContent className="grid gap-5 md:grid-cols-2">
              {fields.map((field) => {
                const item = settingsByKey.get(field.key);
                const isSecret = item?.is_secret || field.type === "password";
                const placeholder = isSecret ? "비워 두면 기존 비밀값을 유지합니다." : "";
                return (
                  <div key={field.key} className="space-y-2">
                    <div className="flex items-center gap-2">
                      <Label htmlFor={field.key}>{field.label}</Label>
                      {field.required ? <Badge className="px-2 py-0 text-[10px]">필수</Badge> : null}
                    </div>
                    {field.options ? (
                      <select
                        id={field.key}
                        className="flex h-11 w-full rounded-full border border-ink/10 bg-white px-4 text-sm text-ink outline-none"
                        value={values[field.key] ?? ""}
                        onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
                      >
                        {field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                    ) : (
                      <>
                        <Input
                          id={field.key}
                          type={getInputType(field)}
                          list={field.suggestions?.length ? `${field.key}-suggestions` : undefined}
                          min={field.type === "number" ? 0 : undefined}
                          value={values[field.key] ?? ""}
                          placeholder={placeholder}
                          onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
                        />
                        {field.suggestions?.length ? <datalist id={`${field.key}-suggestions`}>{field.suggestions.map((suggestion) => <option key={suggestion} value={suggestion} />)}</datalist> : null}
                      </>
                    )}
                    <p className="text-xs leading-5 text-slate-500">{field.help}</p>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        );
      })}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={isPending}>{isPending ? "저장 중..." : "설정 저장"}</Button>
        {status ? <p className="text-sm text-slate-600">{status}</p> : null}
      </div>
    </form>
  );
}

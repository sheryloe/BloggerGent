"use client";

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SettingItem } from "@/lib/types";

type FieldConfig = {
  key: string;
  label: string;
  help: string;
  required?: boolean;
  type?: "text" | "password" | "number";
  options?: Array<{ value: string; label: string }>;
  showWhen?: (values: Record<string, string>) => boolean;
};

type SectionConfig = {
  title: string;
  description: string;
  fields: FieldConfig[];
};

const sections: SectionConfig[] = [
  {
    title: "AI 연결",
    description: "글 생성과 주제 발굴에 필요한 모델/API를 관리합니다.",
    fields: [
      {
        key: "provider_mode",
        label: "실행 모드",
        help: "`mock`은 테스트용, `live`는 실제 API 호출입니다.",
        required: true,
        options: [
          { value: "mock", label: "mock" },
          { value: "live", label: "live" },
        ],
      },
      {
        key: "openai_api_key",
        label: "OpenAI API Key",
        help: "본문 생성과 이미지 생성에 사용합니다.",
        required: true,
        type: "password",
      },
      {
        key: "openai_text_model",
        label: "OpenAI 텍스트 모델",
        help: "글 생성에 사용할 모델입니다.",
      },
      {
        key: "openai_image_model",
        label: "OpenAI 이미지 모델",
        help: "콜라주 이미지 생성에 사용할 모델입니다.",
      },
      {
        key: "openai_request_saver_mode",
        label: "OpenAI 요청 절약 모드",
        help: "이미지 프롬프트 전용 호출을 줄여 요청 수를 아낍니다.",
        options: [
          { value: "true", label: "사용" },
          { value: "false", label: "사용 안 함" },
        ],
      },
      {
        key: "gemini_api_key",
        label: "Gemini API Key",
        help: "자동 주제 발굴에만 사용합니다. 수동 키워드만 쓸 거면 비워도 됩니다.",
        type: "password",
      },
      {
        key: "gemini_model",
        label: "Gemini 모델",
        help: "주제 발굴용 Gemini 모델명입니다.",
      },
    ],
  },
  {
    title: "공개 이미지",
    description: "Blogger 글에서 대표 이미지가 깨지지 않도록 공개 URL이 가능한 저장소를 설정합니다.",
    fields: [
      {
        key: "public_image_provider",
        label: "이미지 호스팅 방식",
        help: "현재는 GitHub Pages를 기본 권장값으로 사용합니다.",
        required: true,
        options: [
          { value: "github_pages", label: "GitHub Pages" },
          { value: "cloudinary", label: "Cloudinary" },
          { value: "local", label: "Local URL" },
        ],
      },
      {
        key: "github_pages_owner",
        label: "GitHub Owner",
        help: "예: sheryloe",
        required: true,
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_repo",
        label: "GitHub Repository",
        help: "예: BloManagent",
        required: true,
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_branch",
        label: "GitHub Branch",
        help: "보통 `main`입니다.",
        required: true,
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_token",
        label: "GitHub Token",
        help: "Fine-grained token + `Contents: Read and write` 권한이 필요합니다.",
        required: true,
        type: "password",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_base_url",
        label: "GitHub Pages URL",
        help: "예: https://username.github.io/repo",
        required: true,
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_assets_dir",
        label: "기본 업로드 폴더",
        help: "비워두면 날짜 기준 폴더를 자동으로 생성합니다.",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "cloudinary_cloud_name",
        label: "Cloudinary Cloud Name",
        help: "Cloudinary를 사용할 때만 입력합니다.",
        type: "text",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_api_key",
        label: "Cloudinary API Key",
        help: "Cloudinary를 사용할 때만 입력합니다.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_api_secret",
        label: "Cloudinary API Secret",
        help: "Cloudinary를 사용할 때만 입력합니다.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_folder",
        label: "Cloudinary 폴더",
        help: "업로드할 기본 폴더명입니다.",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "public_asset_base_url",
        label: "공개 베이스 URL",
        help: "Local URL 방식을 쓸 때만 필요합니다.",
        showWhen: (values) => values.public_image_provider === "local",
      },
    ],
  },
  {
    title: "Google OAuth",
    description: "Blogger, Search Console, GA4 연결에 필요한 OAuth 정보를 입력합니다.",
    fields: [
      {
        key: "blogger_client_name",
        label: "OAuth 표시 이름",
        help: "Google 동의 화면에 보이는 앱 이름입니다.",
      },
      {
        key: "blogger_client_id",
        label: "Client ID",
        help: "Google Cloud에서 만든 Web application Client ID입니다.",
        required: true,
      },
      {
        key: "blogger_client_secret",
        label: "Client Secret",
        help: "Google Cloud에서 발급한 Client Secret입니다.",
        required: true,
        type: "password",
      },
      {
        key: "blogger_redirect_uri",
        label: "Redirect URI",
        help: "보통 `http://localhost:8000/api/v1/blogger/oauth/callback` 입니다.",
        required: true,
      },
    ],
  },
  {
    title: "운영 옵션",
    description: "자동 주제 발굴 시간과 무료 티어 보호 제한만 최소한으로 관리합니다. 공개 게시 여부는 글 목록에서 직접 결정합니다.",
    fields: [
      {
        key: "schedule_enabled",
        label: "자동 스케줄 사용",
        help: "매일 자동 주제 발굴을 돌릴지 결정합니다.",
        options: [
          { value: "true", label: "사용" },
          { value: "false", label: "사용 안 함" },
        ],
      },
      {
        key: "schedule_time",
        label: "스케줄 시간",
        help: "형식: HH:MM",
      },
      {
        key: "schedule_timezone",
        label: "시간대",
        help: "예: Asia/Seoul",
      },
      {
        key: "gemini_daily_request_limit",
        label: "Gemini 일일 최대 요청 수",
        help: "무료 티어 보호용입니다. 0이면 제한 없음입니다.",
        type: "number",
      },
      {
        key: "gemini_requests_per_minute_limit",
        label: "Gemini 분당 최대 요청 수",
        help: "무료 티어 보호용입니다. 0이면 제한 없음입니다.",
        type: "number",
      },
      {
        key: "pipeline_stop_after",
        label: "테스트용 중간 종료 단계",
        help: "운영 중에는 `전체 실행`을 권장합니다.",
        options: [
          { value: "none", label: "전체 실행" },
          { value: "GENERATING_ARTICLE", label: "본문 생성까지만" },
          { value: "GENERATING_IMAGE_PROMPT", label: "이미지 프롬프트까지만" },
          { value: "GENERATING_IMAGE", label: "이미지 생성까지만" },
          { value: "ASSEMBLING_HTML", label: "HTML 조립까지만" },
        ],
      },
    ],
  },
  {
    title: "Blogger editor automation",
    description:
      "Connect Playwright to a logged-in Chrome or Edge session and fill the Blogger search description after publish.",
    fields: [
      {
        key: "blogger_playwright_enabled",
        label: "Enable Playwright sync",
        help: "Turn this on only after Chrome or Edge is running with remote debugging and Blogger is already signed in.",
        options: [
          { value: "true", label: "enabled" },
          { value: "false", label: "disabled" },
        ],
      },
      {
        key: "blogger_playwright_auto_sync",
        label: "Auto sync after publish",
        help: "If enabled, Bloggent will attempt to update the Blogger search description right after public publish.",
        options: [
          { value: "true", label: "enabled" },
          { value: "false", label: "disabled" },
        ],
        showWhen: (values) => values.blogger_playwright_enabled === "true",
      },
      {
        key: "blogger_playwright_cdp_url",
        label: "Remote debugging URL",
        help: "Default: http://host.docker.internal:9223",
        showWhen: (values) => values.blogger_playwright_enabled === "true",
      },
      {
        key: "blogger_playwright_account_index",
        label: "Blogger account index",
        help: "Usually 0. Change only if your Blogger editor URL uses another /u/{index} value.",
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

export function SettingsForm({ settings }: { settings: SettingItem[] }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [status, setStatus] = useState("");
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(settings.map((item) => [item.key, item.value])),
  );
  const settingsByKey = useMemo(() => new Map(settings.map((item) => [item.key, item])), [settings]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("");

    const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    });

    if (!response.ok) {
      setStatus("전역 설정 저장에 실패했습니다. API 로그를 확인해 주세요.");
      return;
    }

    setStatus("전역 설정을 저장했습니다.");
    startTransition(() => router.refresh());
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <Card>
        <CardHeader>
          <CardDescription>빠른 안내</CardDescription>
          <CardTitle>먼저 이것만 입력하면 됩니다</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm leading-7 text-slate-700 lg:grid-cols-3">
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">필수</p>
            <p className="mt-1">
              OpenAI API Key, Google OAuth Client ID/Secret, Redirect URI, 공개 이미지 저장소
            </p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">선택</p>
            <p className="mt-1">Gemini API Key는 자동 주제 발굴까지 쓸 때만 필요합니다.</p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">게시 방식</p>
            <p className="mt-1">글은 생성 후 초안으로 두고, 공개 게시 버튼을 눌러 직접 올리는 흐름을 권장합니다.</p>
          </div>
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
                const placeholder = isSecret ? "비워두면 기존 저장값을 유지합니다." : "";

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
                        onChange={(event) =>
                          setValues((current) => ({
                            ...current,
                            [field.key]: event.target.value,
                          }))
                        }
                      >
                        {field.options.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Input
                        id={field.key}
                        type={getInputType(field)}
                        min={field.type === "number" ? 0 : undefined}
                        value={values[field.key] ?? ""}
                        placeholder={placeholder}
                        onChange={(event) =>
                          setValues((current) => ({
                            ...current,
                            [field.key]: event.target.value,
                          }))
                        }
                      />
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
        <Button type="submit" disabled={isPending}>
          {isPending ? "저장 중..." : "전역 설정 저장"}
        </Button>
        {status ? <p className="text-sm text-slate-600">{status}</p> : null}
      </div>
    </form>
  );
}

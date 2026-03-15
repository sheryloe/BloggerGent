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
    title: "기본 운영",
    description: "실제 API를 쓸지, 기본 발행 모드를 무엇으로 할지 먼저 정합니다.",
    fields: [
      {
        key: "provider_mode",
        label: "실행 모드",
        help: "mock은 테스트용, live는 실제 API와 Blogger를 호출합니다.",
        required: true,
        options: [
          { value: "mock", label: "mock" },
          { value: "live", label: "live" },
        ],
      },
      {
        key: "default_publish_mode",
        label: "기본 발행 모드",
        help: "새 작업을 만들 때 기본으로 draft로 둘지, 바로 publish로 갈지 정합니다.",
        required: true,
        options: [
          { value: "draft", label: "draft" },
          { value: "publish", label: "publish" },
        ],
      },
    ],
  },
  {
    title: "AI 연결",
    description: "OpenAI는 글과 이미지를 만들고, Gemini는 자동 주제 발굴에 사용합니다.",
    fields: [
      {
        key: "openai_api_key",
        label: "OpenAI API Key",
        help: "본문 생성과 대표 이미지 생성에 사용합니다.",
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
        help: "대표 이미지 생성에 사용할 모델입니다.",
      },
      {
        key: "openai_request_saver_mode",
        label: "요청 절약 모드",
        help: "이미지 프롬프트 전용 LLM 호출을 줄여 OpenAI 요청 수를 아낍니다.",
        options: [
          { value: "true", label: "사용" },
          { value: "false", label: "사용 안 함" },
        ],
      },
      {
        key: "gemini_api_key",
        label: "Gemini API Key",
        help: "자동 주제 발굴을 쓸 때만 필요합니다. 수동 키워드만 쓰면 비워둬도 됩니다.",
        type: "password",
      },
      {
        key: "gemini_model",
        label: "Gemini 모델",
        help: "주제 발굴에 사용할 Gemini 모델입니다.",
      },
    ],
  },
  {
    title: "이미지 공개 호스팅",
    description: "공개 글 썸네일이 깨지지 않도록 외부에서 접근 가능한 이미지 호스팅을 설정합니다.",
    fields: [
      {
        key: "public_image_provider",
        label: "공개 이미지 방식",
        help: "현재는 GitHub Pages 사용을 권장합니다.",
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
        label: "GitHub Repo",
        help: "예: BloManagent",
        required: true,
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_branch",
        label: "GitHub Branch",
        help: "보통 main",
        required: true,
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_token",
        label: "GitHub Token",
        help: "Fine-grained token, Contents: Read and write 권한이 필요합니다.",
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
        help: "비워두면 날짜별 하위 폴더를 자동으로 붙여 저장합니다.",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "cloudinary_cloud_name",
        label: "Cloudinary Cloud Name",
        help: "Cloudinary를 쓸 때만 입력합니다.",
        required: true,
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_api_key",
        label: "Cloudinary API Key",
        help: "Cloudinary를 쓸 때만 입력합니다.",
        required: true,
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_api_secret",
        label: "Cloudinary API Secret",
        help: "Cloudinary를 쓸 때만 입력합니다.",
        required: true,
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_folder",
        label: "Cloudinary 폴더",
        help: "업로드할 기본 폴더 이름입니다.",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "public_asset_base_url",
        label: "공개 베이스 URL",
        help: "local 방식일 때만 필요합니다. 외부에서 접근 가능한 실제 주소여야 합니다.",
        showWhen: (values) => values.public_image_provider === "local",
      },
    ],
  },
  {
    title: "Google OAuth 앱",
    description: "Blogger 게시와 Blogger / Search Console / GA4 목록 조회에 필요한 Google OAuth 앱 정보입니다.",
    fields: [
      {
        key: "blogger_client_name",
        label: "앱 표시 이름",
        help: "Google 동의 화면에 보이는 이름입니다.",
      },
      {
        key: "blogger_client_id",
        label: "Client ID",
        help: "Google Cloud에서 발급한 Web application Client ID",
        required: true,
      },
      {
        key: "blogger_client_secret",
        label: "Client Secret",
        help: "Google Cloud에서 발급한 Client Secret",
        required: true,
        type: "password",
      },
      {
        key: "blogger_redirect_uri",
        label: "Redirect URI",
        help: "Google Cloud에 등록한 값과 정확히 같아야 합니다. 기본값은 http://localhost:8000/api/v1/blogger/oauth/callback",
        required: true,
      },
    ],
  },
  {
    title: "스케줄과 운영 최적화",
    description: "자동 주제 발굴 시간과 무료 API 보호용 제한을 관리합니다.",
    fields: [
      {
        key: "schedule_enabled",
        label: "자동 스케줄 사용",
        help: "매일 자동 주제 발굴을 실행할지 결정합니다.",
        options: [
          { value: "true", label: "사용" },
          { value: "false", label: "사용 안 함" },
        ],
      },
      {
        key: "schedule_time",
        label: "실행 시간",
        help: "HH:MM 형식, 예: 09:00",
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
        label: "파이프라인 중간 종료 단계",
        help: "테스트용 옵션입니다. 운영 중에는 none을 권장합니다.",
        options: [
          { value: "none", label: "전체 실행" },
          { value: "GENERATING_ARTICLE", label: "본문 생성 후 중지" },
          { value: "GENERATING_IMAGE_PROMPT", label: "이미지 프롬프트 후 중지" },
          { value: "GENERATING_IMAGE", label: "이미지 생성 후 중지" },
          { value: "ASSEMBLING_HTML", label: "HTML 조립 후 중지" },
        ],
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
          <CardDescription>빠른 체크</CardDescription>
          <CardTitle>이 화면에서 꼭 필요한 것만 먼저 입력하세요</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm leading-7 text-slate-700 lg:grid-cols-2">
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">필수</p>
            <p className="mt-1">OpenAI API Key, Google OAuth Client ID / Secret, Redirect URI, 공개 이미지 방식</p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">선택</p>
            <p className="mt-1">Gemini API Key는 자동 주제 발굴을 쓸 때만 필요합니다.</p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4 lg:col-span-2">
            <p className="font-semibold text-ink">주의</p>
            <p className="mt-1">
              비밀 입력칸을 비워두고 저장하면 기존 DB 값은 유지됩니다. 값을 바꾸고 싶을 때만 다시 입력해 주세요.
            </p>
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

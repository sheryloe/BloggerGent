import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getBloggerConfig, getBlogs, getWorkspaceIntegrations } from "@/lib/api";
import type { BloggerConfig, ManagedChannelRead, WorkspaceIntegrationOverviewRead } from "@/lib/types";

const fallbackBloggerConfig: BloggerConfig = {
  client_name: "",
  client_id_configured: false,
  client_secret_configured: false,
  access_token_configured: false,
  refresh_token_configured: false,
  redirect_uri: "",
  default_publish_mode: "draft",
  connected: false,
  remote_loaded: false,
  authorization_url: null,
  authorization_error: null,
  connection_error: null,
  oauth_scopes: [],
  granted_scopes: [],
  available_blogs: [],
  profiles: [],
  imported_blogger_blog_ids: [],
  search_console_sites: [],
  analytics_properties: [],
  warnings: ["정적 프리뷰 모드에서는 실제 OAuth 검증을 실행하지 않습니다."],
  blogs: [],
};

const fallbackIntegrations: WorkspaceIntegrationOverviewRead = {
  channels: [],
  integrations: [],
  credentials: [],
};

type GuideSection = {
  title: string;
  bullets: string[];
};

type PlatformGuide = {
  id: "blogger" | "youtube" | "instagram";
  name: string;
  description: string;
  sections: GuideSection[];
};

const PLATFORM_GUIDES: PlatformGuide[] = [
  {
    id: "blogger",
    name: "Blogger",
    description: "글 게시 자동화 + Search Console/GA4 분석 루프",
    sections: [
      {
        title: "사전 준비",
        bullets: [
          "Google OAuth Client ID/Secret, Redirect URI 저장",
          "운영 블로그 URL, Search Console 사이트, GA4 Property 확인",
          "공개 이미지 전달(R2 또는 고정 공개 URL) 경로 준비",
        ],
      },
      {
        title: "OAuth 연결",
        bullets: [
          "Settings > Integrations에서 Blogger 채널 카드의 OAuth 시작 클릭",
          "권한 승인 후 oauth_state=connected, scope 수 확인",
          "만료/오류 시 토큰 갱신으로 access token 재발급",
        ],
      },
      {
        title: "첫 게시",
        bullets: [
          "Content Lab에서 blog_article 초안 생성",
          "필요 이미지/본문 보강 후 게시 큐 등록",
          "Publishing에서 처리 결과와 최종 URL 확인",
        ],
      },
      {
        title: "실패 복구",
        bullets: [
          "AUTH_EXPIRED면 채널 토큰 갱신 후 재큐잉",
          "MISSING_ASSET이면 누락 자산 보강 후 ready_to_publish 전환",
          "SEO/Indexing 데스크에서 sitemap/inspection 기반 재검증",
        ],
      },
    ],
  },
  {
    id: "youtube",
    name: "YouTube",
    description: "영상 파일 업로드 + 메타/썸네일 + private 기본 게시",
    sections: [
      {
        title: "사전 준비",
        bullets: [
          "YouTube 채널 연결 가능한 Google 계정 준비",
          "업로드할 video_file_path와 thumbnail_file_path 확보",
          "기본 privacyStatus는 private로 운영",
        ],
      },
      {
        title: "OAuth 연결",
        bullets: [
          "Settings > Integrations에서 YouTube 채널 OAuth 시작",
          "연결 후 channel status, oauth_state, scope 확인",
          "권한/쿼터 이슈가 있으면 토큰 갱신 후 재시도",
        ],
      },
      {
        title: "첫 게시",
        bullets: [
          "youtube_video 생성 시 video_file_path 필수",
          "에셋 누락 시 blocked_asset으로 유지",
          "에셋 보강 후 ready_to_publish -> 게시 대기 등록 -> 큐 처리",
        ],
      },
      {
        title: "실패 복구",
        bullets: [
          "AUTH_EXPIRED, RATE_LIMITED, PROVIDER_ERROR 코드 기준 조치",
          "썸네일/메타만 수정해도 idempotency 키 유지로 중복 방지",
          "업로드 성공 후 review 상태(private)에서 운영자 검토",
        ],
      },
    ],
  },
  {
    id: "instagram",
    name: "Instagram",
    description: "Image/Reel 분리 운영 + capability-gated publish",
    sections: [
      {
        title: "사전 준비",
        bullets: [
          "Professional 계정 + business account id(remote_resource_id) 확인",
          "image는 image_url, reel은 video_url/cover_url 준비",
          "게시 권한은 기본 차단 정책 유지",
        ],
      },
      {
        title: "OAuth 연결",
        bullets: [
          "Settings > Integrations에서 Instagram 채널 OAuth 시작",
          "토큰 만료 시 refresh로 즉시 갱신",
          "필수 스코프 미충족이면 capability blocked 유지",
        ],
      },
      {
        title: "첫 게시",
        bullets: [
          "콘텐츠 타입별 필수 에셋 충족 시 ready_to_publish",
          "릴스는 컨테이너 완료 폴링 후 publish 실행",
          "큐 처리 결과는 PublicationRecord로 추적",
        ],
      },
      {
        title: "실패 복구",
        bullets: [
          "CAPABILITY_BLOCKED면 설정/권한/capabilities 3축 확인",
          "MISSING_ASSET이면 URL 자산 보강 후 재큐잉",
          "PROVIDER_ERROR는 응답 payload detail로 원인 분리",
        ],
      },
    ],
  },
];

function providerStatusLabel(channelId: string, integrations: WorkspaceIntegrationOverviewRead) {
  const integration = integrations.integrations.find((item) => item.channelId === channelId);
  if (!integration) {
    return "unknown";
  }
  return `${integration.oauthState}/${integration.status}`;
}

export default async function GuidePage() {
  const [blogsResult, bloggerConfigResult, integrationsResult] = await Promise.allSettled([
    getBlogs(),
    getBloggerConfig(true),
    getWorkspaceIntegrations(),
  ]);
  const blogs = blogsResult.status === "fulfilled" ? blogsResult.value : [];
  const bloggerConfig = bloggerConfigResult.status === "fulfilled" ? bloggerConfigResult.value : fallbackBloggerConfig;
  const integrations = integrationsResult.status === "fulfilled" ? integrationsResult.value : fallbackIntegrations;

  const channelMap = new Map<string, ManagedChannelRead>(integrations.channels.map((channel: ManagedChannelRead) => [channel.provider, channel]));

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-ink">연결 가이드 허브</h1>
          <p className="mt-2 max-w-3xl text-base leading-7 text-slate-600">
            신규 운영자가 바로 시작할 수 있도록 Blogger/YouTube/Instagram 설정 절차를 동일한 구조로 정리했습니다.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>{blogs.length}개 블로그 관리 중</Badge>
          <Badge className="bg-transparent">{bloggerConfig.connected ? "Google 연결됨" : "Google 미연결"}</Badge>
          <Badge className="bg-transparent">{integrations.channels.length}개 채널 감지</Badge>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardDescription>빠른 이동</CardDescription>
          <CardTitle>플랫폼 탭</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button asChild>
            <Link href="#blogger">Blogger</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="#youtube">YouTube</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="#instagram">Instagram</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/settings">Integrations 열기</Link>
          </Button>
        </CardContent>
      </Card>

      {PLATFORM_GUIDES.map((guide) => {
        const channel = channelMap.get(guide.id);
        return (
          <section key={guide.id} id={guide.id} className="space-y-4 scroll-mt-24">
            <Card>
              <CardHeader>
                <CardDescription>{guide.name}</CardDescription>
                <CardTitle>{guide.description}</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <MiniInfo label="channel_id" value={channel?.channelId ?? `${guide.id}:main`} />
                <MiniInfo label="oauth/status" value={channel ? providerStatusLabel(channel.channelId, integrations) : "not_connected"} />
                <MiniInfo label="pending_items" value={String(channel?.pendingItems ?? 0)} />
                <MiniInfo label="failed_items" value={String(channel?.failedItems ?? 0)} />
              </CardContent>
            </Card>

            <div className="grid gap-4 xl:grid-cols-2">
              {guide.sections.map((section) => (
                <Card key={`${guide.id}-${section.title}`}>
                  <CardHeader>
                    <CardDescription>{guide.name}</CardDescription>
                    <CardTitle>{section.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm leading-7 text-slate-700">
                    {section.bullets.map((line, index) => (
                      <p key={`${guide.id}-${section.title}-${index}`}>{index + 1}. {line}</p>
                    ))}
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function MiniInfo({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] border border-slate-200 bg-slate-50 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</p>
      <p className="mt-1 break-all text-sm font-semibold text-slate-900">{value}</p>
    </div>
  );
}

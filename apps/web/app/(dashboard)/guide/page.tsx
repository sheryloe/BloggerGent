import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getBloggerConfig, getBlogs } from "@/lib/api";
import type { BloggerConfig } from "@/lib/types";

const requiredInputs = [
  { title: "OpenAI API 키", level: "필수", description: "실제 본문 생성과 이미지 생성에 필요합니다.", example: "sk-..." },
  { title: "Google OAuth Client ID / Secret", level: "필수", description: "Blogger 연결, 블로그 가져오기, Search Console, GA4 연동에 사용합니다.", example: "1234567890-xxxx.apps.googleusercontent.com" },
  { title: "공개 이미지 전달 설정", level: "필수", description: "권장 조합은 Cloudflare R2 버킷과 img.<domain> 전용 호스트입니다. Blogger와 자체 허브에서 같은 원본과 변환 URL을 재사용할 수 있습니다.", example: "cloudflare_r2 + https://img.example.com" },
  { title: "Gemini API 키", level: "선택", description: "토픽 발굴 공급자를 Gemini로 쓸 때만 필요합니다.", example: "AIza..." },
];

const oauthSteps = [
  "Google Cloud Console에서 OAuth 웹 클라이언트를 생성합니다.",
  "Blogger 콜백 URL을 승인된 리디렉션 URI에 추가합니다.",
  "앱이 테스트 상태라면 실제 운영 Google 계정을 테스트 사용자에 넣습니다.",
  "설정 화면에 Client ID, Client Secret, Redirect URI를 저장합니다.",
  "설정 화면에서 Google 계정을 연결합니다.",
  "실제로 운영할 Blogger 블로그만 가져옵니다.",
];

const imageSteps = [
  "원본 이미지를 Blogger와 자체 채널에서 함께 재사용하려면 Cloudflare R2를 기본 원본으로 사용합니다.",
  "Cloudflare에서 img.<domain> 커스텀 호스트를 만들고 cloudflare_r2_public_base_url에 연결합니다.",
  "이미지 최적화는 원본 URL이 아니라 /cdn-cgi/image 변환 URL을 실제 HTML에서 쓸 때만 적용됩니다.",
  "Cloudflare 마이그레이션 검증이 끝나기 전까지 기존 GitHub Pages 또는 Cloudinary 자산은 삭제하지 않습니다.",
  "Local delivery를 쓸 경우 공개 인터넷에서 열리는 기준 URL인지 먼저 확인합니다.",
  "앱은 로컬 원본을 먼저 저장한 뒤, 설정된 공개 전달 공급자 URL을 추가로 만듭니다.",
];

const publishSteps = [
  "글과 이미지를 먼저 생성합니다.",
  "발행 전에 본문 미리보기, 사용량 요약, 공개 이미지 URL을 검토합니다.",
  "Blogger API를 한꺼번에 직접 호출하지 말고 예약 큐를 사용합니다.",
  "publish_min_interval_seconds로 Blogger 발행 호출 간격을 안전하게 유지합니다.",
  "시간 지정 발행은 예약 큐에 넣고 worker가 순차 처리하게 둡니다.",
];

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
  warnings: ["GitHub Pages/정적 빌드에서는 Google API를 연결하지 않고 가이드 화면을 렌더링합니다."],
  blogs: [],
};

export default async function GuidePage() {
  const [blogsResult, bloggerConfigResult] = await Promise.allSettled([getBlogs(), getBloggerConfig(true)]);
  const blogs = blogsResult.status === "fulfilled" ? blogsResult.value : [];
  const bloggerConfig = bloggerConfigResult.status === "fulfilled" ? bloggerConfigResult.value : fallbackBloggerConfig;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-ink">사용 가이드</h1>
          <p className="mt-2 max-w-3xl text-base leading-7 text-slate-600">BloggerGent를 실제 운영 기준으로 설정하는 순서와, 토픽 발굴·이미지 전달·발행을 안전하게 돌리는 방법을 정리했습니다.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>{blogs.length}개 블로그 관리 중</Badge>
          <Badge className="bg-transparent">{bloggerConfig.connected ? "Google 연결됨" : "Google 미연결"}</Badge>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader><CardDescription>연결 상태</CardDescription><CardTitle>OAuth 필수 항목</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm leading-7 text-slate-700">
            <p>Client ID: {bloggerConfig.client_id_configured ? "설정됨" : "누락"}</p>
            <p>Client Secret: {bloggerConfig.client_secret_configured ? "설정됨" : "누락"}</p>
            <p>Refresh Token: {bloggerConfig.refresh_token_configured ? "설정됨" : "누락"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardDescription>가져온 범위</CardDescription><CardTitle>Blogger 계정 상태</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm leading-7 text-slate-700">
            <p>연결 가능한 Blogger 블로그: {bloggerConfig.available_blogs.length}</p>
            <p>앱에 가져온 서비스 블로그: {blogs.length}</p>
            <p>Search Console 속성: {bloggerConfig.search_console_sites.length}</p>
            <p>GA4 속성: {bloggerConfig.analytics_properties.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardDescription>바로가기</CardDescription><CardTitle>다음 작업</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            <Button asChild><Link href="/settings">설정 열기</Link></Button>
            <Button asChild variant="outline"><Link href="/articles">글 목록 열기</Link></Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardDescription>최소 입력 체크리스트</CardDescription><CardTitle>실운영 전에 필요한 항목</CardTitle></CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2">
          {requiredInputs.map((item) => (
            <div key={item.title} className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <div className="flex items-center gap-2"><p className="font-semibold text-ink">{item.title}</p><Badge className={item.level === "필수" ? "" : "bg-transparent"}>{item.level}</Badge></div>
              <p className="mt-3 text-sm leading-7 text-slate-600">{item.description}</p>
              <p className="mt-3 rounded-2xl bg-slate-50 px-3 py-2 font-mono text-xs text-slate-600">{item.example}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader><CardDescription>설정 순서</CardDescription><CardTitle>Google OAuth 연결 흐름</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm leading-7 text-slate-700">
            {oauthSteps.map((step, index) => <div key={step} className="rounded-[20px] border border-ink/10 px-4 py-3"><p className="font-semibold text-ink">단계 {index + 1}</p><p className="mt-1">{step}</p></div>)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardDescription>이미지 전달 전략</CardDescription><CardTitle>공개 이미지가 동작하는 방식</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm leading-7 text-slate-700">
            {imageSteps.map((step, index) => <div key={step} className="rounded-[20px] border border-ink/10 px-4 py-3"><p className="font-semibold text-ink">단계 {index + 1}</p><p className="mt-1">{step}</p></div>)}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardDescription>안전 운영</CardDescription><CardTitle>권장 발행 흐름</CardTitle></CardHeader>
        <CardContent className="grid gap-3 text-sm leading-7 text-slate-700 lg:grid-cols-2">
          {publishSteps.map((step, index) => <div key={step} className="rounded-[20px] border border-ink/10 px-4 py-3"><p className="font-semibold text-ink">단계 {index + 1}</p><p className="mt-1">{step}</p></div>)}
        </CardContent>
      </Card>
    </div>
  );
}

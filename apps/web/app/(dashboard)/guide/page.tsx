import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getBloggerConfig, getBlogs } from "@/lib/api";

const requiredInputs = [
  {
    title: "OpenAI API Key",
    level: "필수",
    description: "본문 생성과 대표 이미지 생성을 위해 사용합니다.",
    example: "sk-...",
  },
  {
    title: "Gemini API Key",
    level: "선택",
    description: "자동 주제 발굴을 쓸 때만 필요합니다. 수동 키워드 입력만 하면 생략할 수 있습니다.",
    example: "AIza...",
  },
  {
    title: "Google OAuth Client ID / Secret",
    level: "필수",
    description: "Blogger 게시, 블로그 목록 가져오기, Search Console, GA4 연결에 사용합니다.",
    example: "1234567890-xxxx.apps.googleusercontent.com",
  },
  {
    title: "GitHub Pages 업로드 정보",
    level: "필수",
    description: "공개 글에서 이미지가 깨지지 않도록 GitHub Pages에 대표 이미지를 업로드합니다.",
    example: "owner / repo / branch / token / base URL",
  },
];

const oauthSteps = [
  "Google Cloud Console에서 OAuth Client를 Web application으로 생성합니다.",
  "Authorized redirect URI에 http://localhost:8000/api/v1/blogger/oauth/callback 을 등록합니다.",
  "앱이 Testing 상태라면 실제 로그인할 Google 계정을 Test users에 추가합니다.",
  "Bloggent 설정 화면에서 Client ID, Client Secret, Redirect URI를 저장합니다.",
  "설정 화면의 'Google 계정 연결하기' 버튼을 눌러 Blogger 권한을 승인합니다.",
  "연결 후 Blogger 블로그 목록이 조회되면 필요한 블로그를 서비스용 블로그로 가져옵니다.",
  "여러 사람이 쓰는 서비스라면 Testing 대신 Production 전환을 권장합니다.",
];

const usageSteps = [
  "전역 설정에서 AI 키, 이미지 공개 방식, Google OAuth 앱 정보를 입력합니다.",
  "Google 계정을 연결하고 Blogger 블로그 목록을 불러옵니다.",
  "가져온 블로그를 서비스용 블로그로 import 한 뒤 Search Console / GA4를 매핑합니다.",
  "블로그별 워크플로 단계와 프롬프트를 확인하고, 필요하면 프리셋 라이브러리를 초기값으로 다시 적용합니다.",
  "주제를 수동 입력하거나 Gemini로 자동 발굴합니다.",
  "글 생성 후 HTML 미리보기와 대표 이미지를 확인합니다.",
  "문제가 없으면 생성 글 목록의 공개 게시 버튼을 눌러 Blogger에 반영합니다.",
];

const seoPatchSteps = [
  "설정 > 블로그별 워크플로 > 연결 탭에서 Blogger SEO 메타 패치 카드를 엽니다.",
  "제공된 스니펫을 Blogger 테마 HTML의 <head> 영역에 추가합니다.",
  "적용 후 공개 글 URL을 기준으로 head meta description / og:description / twitter:description을 검증합니다.",
  "앱 저장값과 실제 공개 페이지 값이 모두 일치하면 검증 완료 상태가 됩니다.",
];

const githubPagesSteps = [
  "이미지 전용 public 저장소를 하나 만듭니다.",
  "Settings > Pages에서 main 브랜치를 GitHub Pages 소스로 설정합니다.",
  "Fine-grained token을 만들고 Contents: Read and write 권한을 저장소에 부여합니다.",
  "Bloggent 설정에 owner, repo, branch, token, base URL을 입력합니다.",
  "이후 대표 이미지는 날짜별 폴더로 자동 업로드되고 Blogger 글에는 공개 URL이 들어갑니다.",
];

export default async function GuidePage() {
  const [blogs, bloggerConfig] = await Promise.all([getBlogs(), getBloggerConfig()]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-ink">사용 가이드</h1>
          <p className="mt-2 max-w-3xl text-base leading-7 text-slate-600">
            Bloggent를 다른 사람도 바로 실행할 수 있도록 필요한 입력값, Google OAuth 연결, 이미지 공개,
            Blogger 가져오기 순서를 한 페이지에 정리했습니다.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>{blogs.length}개 서비스 블로그</Badge>
          <Badge className="bg-transparent">{bloggerConfig.connected ? "Google 연결됨" : "Google 미연결"}</Badge>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription>현재 상태</CardDescription>
            <CardTitle>전역 연결</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm leading-7 text-slate-700">
            <p>Client ID: {bloggerConfig.client_id_configured ? "설정됨" : "미설정"}</p>
            <p>Client Secret: {bloggerConfig.client_secret_configured ? "설정됨" : "미설정"}</p>
            <p>Refresh Token: {bloggerConfig.refresh_token_configured ? "설정됨" : "미설정"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>블로그 가져오기</CardDescription>
            <CardTitle>Blogger 계정 상태</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm leading-7 text-slate-700">
            <p>가져온 Blogger 블로그: {bloggerConfig.available_blogs.length}개</p>
            <p>서비스 블로그 등록 수: {blogs.length}개</p>
            <p>Search Console 속성: {bloggerConfig.search_console_sites.length}개</p>
            <p>GA4 속성: {bloggerConfig.analytics_properties.length}개</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>빠른 이동</CardDescription>
            <CardTitle>다음 작업</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            <Button asChild>
              <Link href="/settings">설정으로 이동</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/articles">생성 글 보기</Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardDescription>누가 써도 같은 방식으로 시작할 수 있게</CardDescription>
          <CardTitle>필수 입력값 정리</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2">
          {requiredInputs.map((item) => (
            <div key={item.title} className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <div className="flex items-center gap-2">
                <p className="font-semibold text-ink">{item.title}</p>
                <Badge className={item.level === "필수" ? "" : "bg-transparent"}>{item.level}</Badge>
              </div>
              <p className="mt-3 text-sm leading-7 text-slate-600">{item.description}</p>
              <p className="mt-3 rounded-2xl bg-slate-50 px-3 py-2 font-mono text-xs text-slate-600">{item.example}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardDescription>다른 사람도 바로 연결할 수 있게</CardDescription>
            <CardTitle>Google OAuth 설정 순서</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-7 text-slate-700">
            {oauthSteps.map((step, index) => (
              <div key={step} className="rounded-[20px] border border-ink/10 px-4 py-3">
                <p className="font-semibold text-ink">Step {index + 1}</p>
                <p className="mt-1">{step}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardDescription>썸네일이 안 깨지는 방식</CardDescription>
            <CardTitle>GitHub Pages 이미지 공개 설정</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-7 text-slate-700">
            {githubPagesSteps.map((step, index) => (
              <div key={step} className="rounded-[20px] border border-ink/10 px-4 py-3">
                <p className="font-semibold text-ink">Step {index + 1}</p>
                <p className="mt-1">{step}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardDescription>앱 저장값과 실제 공개 페이지 head 반영을 함께 맞춰야 합니다.</CardDescription>
          <CardTitle>Blogger SEO 메타 패치</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm leading-7 text-slate-700 lg:grid-cols-2">
          {seoPatchSteps.map((step, index) => (
            <div key={step} className="rounded-[20px] border border-ink/10 px-4 py-3">
              <p className="font-semibold text-ink">Step {index + 1}</p>
              <p className="mt-1">{step}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription>실제 운영 흐름</CardDescription>
          <CardTitle>처음 실행하는 순서</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm leading-7 text-slate-700 lg:grid-cols-2">
          {usageSteps.map((step, index) => (
            <div key={step} className="rounded-[20px] border border-ink/10 px-4 py-3">
              <p className="font-semibold text-ink">Step {index + 1}</p>
              <p className="mt-1">{step}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription>중요 메모</CardDescription>
          <CardTitle>운영 팁</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-7 text-slate-700">
          <p>Google OAuth 앱이 Testing 상태면 로그인할 계정을 Test users에 반드시 추가해야 합니다.</p>
          <p>장기 운영용이면 Google OAuth 앱을 Production으로 전환하는 편이 더 안정적입니다.</p>
          <p>OpenAI 요청 수를 줄이고 싶다면 요청 절약 모드를 켜서 이미지 프롬프트 전용 호출을 줄이세요.</p>
          <p>대표 이미지는 외부에서 접근 가능한 URL이어야 하므로 localhost 경로로는 게시하면 안 됩니다.</p>
        </CardContent>
      </Card>
    </div>
  );
}

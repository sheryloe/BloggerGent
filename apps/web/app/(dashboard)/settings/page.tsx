import Link from "next/link";

import { BlogSettingsManager } from "@/components/dashboard/blog-settings-manager";
import { BloggerConnectionCard } from "@/components/dashboard/blogger-connection-card";
import { PromptTemplatesForm } from "@/components/dashboard/prompt-templates-form";
import { SettingsForm } from "@/components/dashboard/settings-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getBloggerConfig, getBlogs, getPrompts, getSettings } from "@/lib/api";

export default async function SettingsPage({
  searchParams,
}: {
  searchParams?: { blogger_oauth?: string; message?: string };
}) {
  const [settings, blogs, bloggerConfig, prompts] = await Promise.all([
    getSettings(),
    getBlogs(),
    getBloggerConfig(),
    getPrompts(),
  ]);

  const importedBlogIds = new Set(bloggerConfig.imported_blogger_blog_ids);
  const importOptions = {
    available_blogs: bloggerConfig.available_blogs.filter((blog) => !importedBlogIds.has(blog.id)),
    profiles: bloggerConfig.profiles,
    imported_blogger_blog_ids: bloggerConfig.imported_blogger_blog_ids,
    warnings: bloggerConfig.warnings,
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-ink">설정</h1>
          <p className="mt-2 max-w-3xl text-base leading-7 text-slate-600">
            전역 API 입력, Google OAuth 연결, Blogger 가져오기, 블로그별 워크플로와 프롬프트까지 한 곳에서 관리합니다.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/guide">사용 가이드 보기</Link>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>설정 순서</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm leading-7 text-slate-700 lg:grid-cols-4">
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">1. 전역 API 입력</p>
            <p className="mt-1">OpenAI, Gemini, 이미지 호스팅부터 먼저 저장합니다.</p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">2. Google 연결</p>
            <p className="mt-1">OAuth Client를 저장하고 실제 Google 계정을 연결합니다.</p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">3. Blogger 가져오기</p>
            <p className="mt-1">같은 계정 안의 Blogger 블로그를 서비스용 블로그로 가져옵니다.</p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">4. 블로그별 워크플로</p>
            <p className="mt-1">Search Console, GA4, 프롬프트, 단계 순서를 블로그별로 정리합니다.</p>
          </div>
        </CardContent>
      </Card>

      <SettingsForm settings={settings} />

      <BloggerConnectionCard
        config={bloggerConfig}
        oauthStatus={searchParams?.blogger_oauth}
        oauthMessage={searchParams?.message}
      />

      <BlogSettingsManager blogs={blogs} bloggerConfig={bloggerConfig} importOptions={importOptions} />

      <section className="space-y-4">
        <div>
          <h2 className="text-2xl font-semibold text-ink">공용 프롬프트 템플릿</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            블로그 프로필별 기본 프롬프트입니다. 새 블로그를 가져오거나 커스텀 블로그를 만들 때 기준 템플릿으로 사용됩니다.
          </p>
        </div>
        <PromptTemplatesForm prompts={prompts} />
      </section>
    </div>
  );
}

import Link from "next/link";

import { BlogSettingsManager } from "@/components/dashboard/blog-settings-manager";
import { BloggerConnectionCard } from "@/components/dashboard/blogger-connection-card";
import { OpenAIFreeUsageWidget } from "@/components/dashboard/openai-free-usage-widget";
import { PromptTemplatesForm } from "@/components/dashboard/prompt-templates-form";
import { SettingsForm } from "@/components/dashboard/settings-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getBloggerConfig, getBlogs, getPrompts, getSettings } from "@/lib/api";

export default async function SettingsPage({ searchParams }: { searchParams?: { blogger_oauth?: string; message?: string } }) {
  const [settings, blogs, bloggerConfig, prompts] = await Promise.all([getSettings(), getBlogs(), getBloggerConfig(), getPrompts()]);

  const importedBlogIds = new Set(bloggerConfig.imported_blogger_blog_ids);
  const importOptions = {
    available_blogs: bloggerConfig.available_blogs.filter((blog) => !importedBlogIds.has(blog.id)),
    profiles: bloggerConfig.profiles,
    imported_blogger_blog_ids: bloggerConfig.imported_blogger_blog_ids,
    warnings: bloggerConfig.warnings,
  };

  return (
    <div className="space-y-6">
      <OpenAIFreeUsageWidget />

      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-ink">Settings</h1>
          <p className="mt-2 max-w-3xl text-base leading-7 text-slate-600">
            Manage global providers, Google OAuth, public image delivery, blog workflow, and reusable prompt templates from one place.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/guide">Open usage guide</Link>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recommended setup order</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm leading-7 text-slate-700 lg:grid-cols-5">
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4"><p className="font-semibold text-ink">1. Global providers</p><p className="mt-1">Set provider mode, OpenAI keys, topic discovery provider, and image delivery strategy.</p></div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4"><p className="font-semibold text-ink">2. Google OAuth</p><p className="mt-1">Connect Blogger, Search Console, and GA4 using the real account you will operate with.</p></div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4"><p className="font-semibold text-ink">3. Import blogs</p><p className="mt-1">Bring Blogger blogs into the app and map the correct reporting properties.</p></div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4"><p className="font-semibold text-ink">4. Tune workflow</p><p className="mt-1">Adjust prompts, models, reading-time targets, and visible workflow steps per blog.</p></div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4"><p className="font-semibold text-ink">5. Verify publishing</p><p className="mt-1">Check the safe publish queue, meta verification, and image URL stability before going live.</p></div>
        </CardContent>
      </Card>

      <SettingsForm settings={settings} />

      <BloggerConnectionCard config={bloggerConfig} oauthStatus={searchParams?.blogger_oauth} oauthMessage={searchParams?.message} />

      <BlogSettingsManager blogs={blogs} bloggerConfig={bloggerConfig} importOptions={importOptions} />

      <section className="space-y-4">
        <div>
          <h2 className="text-2xl font-semibold text-ink">Prompt library</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">These prompt templates seed imported blog workflows. After import, each blog can still override its own prompts and models.</p>
        </div>
        <PromptTemplatesForm prompts={prompts} />
      </section>
    </div>
  );
}

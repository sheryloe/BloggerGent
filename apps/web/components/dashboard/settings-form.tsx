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
    title: "AI Providers",
    description: "Choose how BloggerGent discovers topics, writes articles, and generates images.",
    fields: [
      {
        key: "provider_mode",
        label: "Provider mode",
        help: "Use mock on the test PC. Use live only when you want real API calls.",
        required: true,
        options: [
          { value: "mock", label: "mock" },
          { value: "live", label: "live" },
        ],
      },
      {
        key: "openai_api_key",
        label: "OpenAI API key",
        help: "Required for live article and image generation.",
        type: "password",
      },
      {
        key: "openai_admin_api_key",
        label: "OpenAI admin API key",
        help: "Optional. Used only for the free usage dashboard and shared usage reporting.",
        type: "password",
      },
      {
        key: "openai_text_model",
        label: "OpenAI text model",
        help: "Main model used for article writing when a blog stage does not override it.",
        suggestions: OPENAI_TEXT_MODEL_SUGGESTIONS,
      },
      {
        key: "openai_image_model",
        label: "OpenAI image model",
        help: "Only used in live mode. In mock mode, images are created locally by MockImageProvider using Pillow.",
        suggestions: OPENAI_IMAGE_MODEL_SUGGESTIONS,
      },
      {
        key: "openai_request_saver_mode",
        label: "Request saver mode",
        help: "Skips the extra image prompt refinement call and reuses article output when possible.",
        options: [
          { value: "true", label: "enabled" },
          { value: "false", label: "disabled" },
        ],
      },
      {
        key: "topic_discovery_provider",
        label: "Topic discovery provider",
        help: "Choose which provider discovers daily topics before jobs are queued.",
        options: [
          { value: "openai", label: "OpenAI" },
          { value: "gemini", label: "Gemini" },
        ],
      },
      {
        key: "topic_discovery_max_topics_per_run",
        label: "Topic discovery max topics per run",
        help: "Hard cap applied right after the model returns topics. 0 means unlimited. Recommended default is 3 to prevent over-queuing.",
        type: "number",
      },
      {
        key: "topic_discovery_model",
        label: "Topic discovery model",
        help: "Default OpenAI model for topic discovery when provider is OpenAI.",
        suggestions: OPENAI_TEXT_MODEL_SUGGESTIONS,
        showWhen: (values) => (values.topic_discovery_provider || "openai") === "openai",
      },
      {
        key: "gemini_api_key",
        label: "Gemini API key",
        help: "Only needed when topic discovery provider is Gemini.",
        type: "password",
        showWhen: (values) => values.topic_discovery_provider === "gemini",
      },
      {
        key: "gemini_model",
        label: "Gemini model",
        help: "Model used for topic discovery when Gemini is enabled.",
        suggestions: GEMINI_MODEL_SUGGESTIONS,
        showWhen: (values) => values.topic_discovery_provider === "gemini",
      },
    ],
  },
  {
    title: "Public Image Delivery",
    description: "Pick where public image URLs come from so Blogger posts can safely render thumbnails and hero images.",
    fields: [
      {
        key: "public_image_provider",
        label: "Public image provider",
        help: "Recommended order: Cloudflare R2 on an img subdomain, then Cloudinary, then GitHub Pages. Local works only if the URL is publicly reachable.",
        required: true,
        options: [
          { value: "cloudflare_r2", label: "Cloudflare R2" },
          { value: "cloudinary", label: "Cloudinary" },
          { value: "github_pages", label: "GitHub Pages" },
          { value: "local", label: "Local URL" },
        ],
      },
      {
        key: "cloudflare_account_id",
        label: "Cloudflare account ID",
        help: "Used for authenticated R2 uploads through the S3-compatible API.",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudflare_r2_bucket",
        label: "Cloudflare R2 bucket",
        help: "Bucket that stores the original uploaded image for each article.",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudflare_r2_access_key_id",
        label: "R2 access key ID",
        help: "Access key issued for the R2 bucket.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudflare_r2_secret_access_key",
        label: "R2 secret access key",
        help: "Secret access key paired with the R2 access key ID.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudflare_r2_public_base_url",
        label: "Cloudflare public base URL",
        help: "Recommended: https://img.example.com. Rendered pages use /cdn-cgi/image transforms on this host for hero/card/thumb variants.",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudflare_r2_prefix",
        label: "R2 object prefix",
        help: "Optional prefix inside the bucket. Files are stored as <prefix>/<slug>.png.",
        showWhen: (values) => values.public_image_provider === "cloudflare_r2",
      },
      {
        key: "cloudinary_cloud_name",
        label: "Cloudinary cloud name",
        help: "BloggerGent uploads directly to Cloudinary. The original secure URL is stored as a reference, and rendered pages should use transformation URLs for optimized delivery.",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_api_key",
        label: "Cloudinary API key",
        help: "Required for direct Cloudinary upload.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_api_secret",
        label: "Cloudinary API secret",
        help: "Required for direct Cloudinary upload.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "cloudinary_folder",
        label: "Cloudinary folder",
        help: "Optional folder prefix for uploaded images. Keep old assets until Cloudinary migration verification is complete.",
        showWhen: (values) => values.public_image_provider === "cloudinary",
      },
      {
        key: "github_pages_owner",
        label: "GitHub owner",
        help: "Repository owner for GitHub Pages delivery. Deleting remote files later can break images inside older Blogger posts.",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_repo",
        label: "GitHub repository",
        help: "Repository that stores public images.",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_branch",
        label: "GitHub branch",
        help: "Usually main.",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_token",
        label: "GitHub token",
        help: "Needs Contents read/write permission for uploads.",
        type: "password",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_base_url",
        label: "GitHub Pages base URL",
        help: "Example: https://username.github.io/repository",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "github_pages_assets_dir",
        label: "GitHub assets directory",
        help: "Optional folder path inside the repository. Do not delete GitHub assets until Cloudinary migration verification is complete.",
        showWhen: (values) => values.public_image_provider === "github_pages",
      },
      {
        key: "public_asset_base_url",
        label: "Local public asset base URL",
        help: "Use only when your API or static storage is reachable from the public internet.",
        showWhen: (values) => values.public_image_provider === "local",
      },
    ],
  },
  {
    title: "Google OAuth",
    description: "Credentials used for Blogger, Search Console, and GA4 integration.",
    fields: [
      { key: "blogger_client_name", label: "OAuth app name", help: "Name shown on the Google consent screen." },
      { key: "blogger_client_id", label: "Client ID", help: "Google Cloud OAuth web client ID.", required: true },
      { key: "blogger_client_secret", label: "Client secret", help: "Google Cloud OAuth client secret.", type: "password", required: true },
      { key: "blogger_redirect_uri", label: "Redirect URI", help: "Default: http://localhost:8000/api/v1/blogger/oauth/callback", required: true },
    ],
  },
  {
    title: "Operations",
    description: "These settings control how often the system discovers topics and how safely it publishes posts.",
    fields: [
      {
        key: "schedule_enabled",
        label: "Automatic schedule",
        help: "Turns on the daily discovery scheduler.",
        options: [
          { value: "true", label: "enabled" },
          { value: "false", label: "disabled" },
        ],
      },
      { key: "schedule_time", label: "Daily schedule time", help: "Format: HH:MM" },
      { key: "schedule_timezone", label: "Schedule timezone", help: "Example: Asia/Seoul" },
      {
        key: "publish_daily_limit_per_blog",
        label: "Daily public publish limit per blog",
        help: "This limits real publish or schedule actions. It does not cap topic discovery or draft creation.",
        type: "number",
      },
      {
        key: "publish_min_interval_seconds",
        label: "Minimum publish interval seconds",
        help: "Minimum gap between Blogger publish API calls for the same blog. Recommended: 60 seconds or more.",
        type: "number",
      },
      {
        key: "gemini_daily_request_limit",
        label: "Gemini daily request limit",
        help: "Safety guard for free-tier Gemini usage. 0 means unlimited.",
        type: "number",
        showWhen: (values) => values.topic_discovery_provider === "gemini",
      },
      {
        key: "gemini_requests_per_minute_limit",
        label: "Gemini requests per minute",
        help: "Rate guard for Gemini topic discovery. 0 means unlimited.",
        type: "number",
        showWhen: (values) => values.topic_discovery_provider === "gemini",
      },
      {
        key: "pipeline_stop_after",
        label: "Pipeline stop after",
        help: "Use this only on the test PC when you want to stop before full output generation.",
        options: [
          { value: "none", label: "Run full pipeline" },
          { value: "GENERATING_ARTICLE", label: "Stop after article generation" },
          { value: "GENERATING_IMAGE_PROMPT", label: "Stop after image prompt stage" },
          { value: "GENERATING_IMAGE", label: "Stop after image generation" },
          { value: "ASSEMBLING_HTML", label: "Stop after HTML assembly" },
        ],
      },
    ],
  },
  {
    title: "Blogger Editor Automation",
    description: "Optional Playwright automation that updates Blogger search description after publish.",
    fields: [
      {
        key: "blogger_playwright_enabled",
        label: "Enable Playwright sync",
        help: "Turn this on only when a remote-debug browser session is already logged in to Blogger.",
        options: [
          { value: "true", label: "enabled" },
          { value: "false", label: "disabled" },
        ],
      },
      {
        key: "blogger_playwright_auto_sync",
        label: "Auto sync after publish",
        help: "If enabled, the worker attempts search description sync after a successful public publish.",
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
        help: "Usually 0. Change only when the Blogger editor URL uses another /u/{index} value.",
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
  if (groupId === "shared-1m") return "Shared daily free pool: 1M tokens";
  if (groupId === "shared-10m") return "Shared daily free pool: 10M tokens";
  return "Shared free pool";
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

    const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setStatus(typeof payload?.detail === "string" ? payload.detail : "Failed to save settings.");
      return;
    }

    setStatus("Settings saved.");
    startTransition(() => router.refresh());
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <Card>
        <CardHeader>
          <CardDescription>Quick orientation</CardDescription>
          <CardTitle>What matters most</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm leading-7 text-slate-700 lg:grid-cols-3">
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">Safe test mode</p>
            <p className="mt-1"><code>provider_mode=mock</code> keeps article, image, and publish work local on the test PC.</p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">Prevent topic explosions</p>
            <p className="mt-1"><code>topic_discovery_max_topics_per_run</code> hard-caps how many discovered topics become queued jobs.</p>
          </div>
          <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-4">
            <p className="font-semibold text-ink">Protect Blogger API</p>
            <p className="mt-1"><code>publish_min_interval_seconds</code> keeps a safe gap between Blogger publish requests.</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription>OpenAI traffic sharing free pools</CardDescription>
          <CardTitle>Free usage strategy reference</CardTitle>
          <p className="text-sm leading-6 text-slate-600">These are shared daily token pools. Text usage is the main thing to watch here; image billing is tracked separately.</p>
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
              <CardDescription>Global settings</CardDescription>
              <CardTitle>{section.title}</CardTitle>
              <p className="text-sm leading-6 text-slate-600">{section.description}</p>
            </CardHeader>
            <CardContent className="grid gap-5 md:grid-cols-2">
              {fields.map((field) => {
                const item = settingsByKey.get(field.key);
                const isSecret = item?.is_secret || field.type === "password";
                const placeholder = isSecret ? "Leave blank to keep the current secret." : "";
                return (
                  <div key={field.key} className="space-y-2">
                    <div className="flex items-center gap-2">
                      <Label htmlFor={field.key}>{field.label}</Label>
                      {field.required ? <Badge className="px-2 py-0 text-[10px]">required</Badge> : null}
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
        <Button type="submit" disabled={isPending}>{isPending ? "Saving..." : "Save settings"}</Button>
        {status ? <p className="text-sm text-slate-600">{status}</p> : null}
      </div>
    </form>
  );
}

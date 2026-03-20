import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getBloggerConfig, getBlogs } from "@/lib/api";

const requiredInputs = [
  { title: "OpenAI API key", level: "Required", description: "Needed for live article and live image generation.", example: "sk-..." },
  { title: "Google OAuth client ID and secret", level: "Required", description: "Used for Blogger access, blog import, Search Console, and GA4.", example: "1234567890-xxxx.apps.googleusercontent.com" },
  { title: "Public image delivery", level: "Required", description: "Recommended: Cloudflare R2 bucket plus an img.<domain> custom hostname so Blogger and your custom blog can reuse the same original and transformed image URLs.", example: "cloudflare_r2 + https://img.example.com" },
  { title: "Gemini API key", level: "Optional", description: "Only needed when Gemini is selected for topic discovery.", example: "AIza..." },
];

const oauthSteps = [
  "Create a Google OAuth web client in Google Cloud Console.",
  "Add the Blogger callback URL as an authorized redirect URI.",
  "If the app is still in testing, add the real Google account to test users.",
  "Save the client ID, client secret, and redirect URI in Settings.",
  "Connect the Google account from the Settings screen.",
  "Import the Blogger blogs you actually want the service to manage.",
];

const imageSteps = [
  "Use Cloudflare R2 as the default image origin when you want the same originals reused across Blogger and your custom hub/card pages.",
  "Set an img.<domain> custom hostname in Cloudflare and point the app at that host with cloudflare_r2_public_base_url.",
  "Image optimization only becomes real when rendered HTML uses /cdn-cgi/image transformation URLs, not the raw original object URL.",
  "Keep old GitHub Pages or Cloudinary assets until Cloudflare migration verification is complete.",
  "If you use local delivery, make sure the base URL is reachable from the public internet.",
  "The app stores a local copy first, then creates a public delivery URL using the configured provider.",
];

const publishSteps = [
  "Generate articles and images first.",
  "Review the article preview, usage summary, and public image URLs.",
  "Queue publish requests instead of sending many direct Blogger calls at once.",
  "Use publish_min_interval_seconds to keep a safe gap between Blogger publish calls.",
  "For timed launches, queue scheduled publishes and let the worker process them one at a time.",
];

export default async function GuidePage() {
  const [blogs, bloggerConfig] = await Promise.all([getBlogs(), getBloggerConfig()]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-ink">Usage guide</h1>
          <p className="mt-2 max-w-3xl text-base leading-7 text-slate-600">This guide explains the practical setup order for BloggerGent and the safest way to run topic discovery, image delivery, and publishing.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>{blogs.length} managed blogs</Badge>
          <Badge className="bg-transparent">{bloggerConfig.connected ? "Google connected" : "Google not connected"}</Badge>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader><CardDescription>Connection status</CardDescription><CardTitle>OAuth essentials</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm leading-7 text-slate-700">
            <p>Client ID: {bloggerConfig.client_id_configured ? "configured" : "missing"}</p>
            <p>Client Secret: {bloggerConfig.client_secret_configured ? "configured" : "missing"}</p>
            <p>Refresh Token: {bloggerConfig.refresh_token_configured ? "configured" : "missing"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardDescription>Imported coverage</CardDescription><CardTitle>Blogger account status</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm leading-7 text-slate-700">
            <p>Available Blogger blogs: {bloggerConfig.available_blogs.length}</p>
            <p>Imported service blogs: {blogs.length}</p>
            <p>Search Console properties: {bloggerConfig.search_console_sites.length}</p>
            <p>GA4 properties: {bloggerConfig.analytics_properties.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardDescription>Quick links</CardDescription><CardTitle>Next action</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            <Button asChild><Link href="/settings">Open settings</Link></Button>
            <Button asChild variant="outline"><Link href="/articles">Open articles</Link></Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardDescription>Minimum input checklist</CardDescription><CardTitle>What you need before going live</CardTitle></CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2">
          {requiredInputs.map((item) => (
            <div key={item.title} className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
              <div className="flex items-center gap-2"><p className="font-semibold text-ink">{item.title}</p><Badge className={item.level === "Required" ? "" : "bg-transparent"}>{item.level}</Badge></div>
              <p className="mt-3 text-sm leading-7 text-slate-600">{item.description}</p>
              <p className="mt-3 rounded-2xl bg-slate-50 px-3 py-2 font-mono text-xs text-slate-600">{item.example}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader><CardDescription>Setup order</CardDescription><CardTitle>Google OAuth flow</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm leading-7 text-slate-700">
            {oauthSteps.map((step, index) => <div key={step} className="rounded-[20px] border border-ink/10 px-4 py-3"><p className="font-semibold text-ink">Step {index + 1}</p><p className="mt-1">{step}</p></div>)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardDescription>Image delivery strategy</CardDescription><CardTitle>How public images should work</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm leading-7 text-slate-700">
            {imageSteps.map((step, index) => <div key={step} className="rounded-[20px] border border-ink/10 px-4 py-3"><p className="font-semibold text-ink">Step {index + 1}</p><p className="mt-1">{step}</p></div>)}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardDescription>Safe operations</CardDescription><CardTitle>Publish flow recommendation</CardTitle></CardHeader>
        <CardContent className="grid gap-3 text-sm leading-7 text-slate-700 lg:grid-cols-2">
          {publishSteps.map((step, index) => <div key={step} className="rounded-[20px] border border-ink/10 px-4 py-3"><p className="font-semibold text-ink">Step {index + 1}</p><p className="mt-1">{step}</p></div>)}
        </CardContent>
      </Card>
    </div>
  );
}

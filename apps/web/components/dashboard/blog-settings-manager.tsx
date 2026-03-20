"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Blog, BlogImportOptions, BloggerConfig, WorkflowStageType } from "@/lib/types";

type TabKey = "connections" | "basic" | "workflow" | "monitoring";

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "connections", label: "Connections" },
  { key: "basic", label: "Basic Info" },
  { key: "workflow", label: "Blog Workflow" },
  { key: "monitoring", label: "Monitoring" },
];

const stageLabels: Record<WorkflowStageType, string> = {
  topic_discovery: "Topic Discovery",
  article_generation: "Writing Package",
  image_prompt_generation: "Image Prompt Refinement",
  related_posts: "Related Posts",
  image_generation: "Image Generation",
  html_assembly: "HTML Assembly",
  publishing: "Publish Queue",
};

const optionalStages: WorkflowStageType[] = ["topic_discovery", "image_prompt_generation"];

function workflowPath(blog: Blog) {
  return blog.execution_path_labels.length > 0
    ? blog.execution_path_labels
    : blog.workflow_steps.map((step) => stageLabels[step.stage_type]);
}

export function BlogSettingsManager({
  blogs,
  bloggerConfig,
  importOptions,
}: {
  blogs: Blog[];
  bloggerConfig: BloggerConfig;
  importOptions: BlogImportOptions;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [selectedBlogId, setSelectedBlogId] = useState<number | null>(blogs[0]?.id ?? null);
  const [tab, setTab] = useState<TabKey>("workflow");
  const [readingTimeMin, setReadingTimeMin] = useState<number>(blogs[0]?.target_reading_time_min_minutes ?? 6);
  const [readingTimeMax, setReadingTimeMax] = useState<number>(blogs[0]?.target_reading_time_max_minutes ?? 8);
  const [saveStatus, setSaveStatus] = useState("");

  const selectedBlog = useMemo(
    () => blogs.find((blog) => blog.id === selectedBlogId) ?? null,
    [blogs, selectedBlogId],
  );

  useEffect(() => {
    if (!selectedBlog) return;
    setReadingTimeMin(selectedBlog.target_reading_time_min_minutes);
    setReadingTimeMax(selectedBlog.target_reading_time_max_minutes);
    setSaveStatus("");
  }, [selectedBlog]);

  async function saveReadingTargets() {
    if (!selectedBlog) return;
    setSaveStatus("");
    const min = Math.max(1, Math.min(60, Math.floor(readingTimeMin || 1)));
    const max = Math.max(min, Math.min(60, Math.floor(readingTimeMax || min)));

    const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/blogs/${selectedBlog.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: selectedBlog.name,
        description: selectedBlog.description ?? null,
        content_category: selectedBlog.content_category,
        primary_language: selectedBlog.primary_language,
        target_audience: selectedBlog.target_audience ?? null,
        content_brief: selectedBlog.content_brief ?? null,
        target_reading_time_min_minutes: min,
        target_reading_time_max_minutes: max,
        publish_mode: selectedBlog.publish_mode,
        is_active: selectedBlog.is_active,
      }),
    });

    if (!response.ok) {
      setSaveStatus("읽기 시간 목표 저장에 실패했습니다.");
      return;
    }

    setSaveStatus(`읽기 목표를 ${min}-${max}분으로 저장했습니다.`);
    startTransition(() => router.refresh());
  }

  if (!selectedBlog) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Blog Workflow</CardTitle>
          <CardDescription>
            No imported blog yet. Import a Blogger blog first to see workflow settings here.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-slate-600">
          <p>Available Blogger blogs: {importOptions.available_blogs.length}</p>
          <p>Profiles: {importOptions.profiles.map((profile) => profile.label).join(", ") || "-"}</p>
          {bloggerConfig.warnings.map((warning) => (
            <p key={warning}>- {warning}</p>
          ))}
        </CardContent>
      </Card>
    );
  }

  return (
    <section className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[280px_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Service Blogs</CardTitle>
            <CardDescription>Select one blog to inspect its settings and workflow.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {blogs.map((blog) => {
              const active = blog.id === selectedBlog.id;
              return (
                <button
                  key={blog.id}
                  type="button"
                  onClick={() => setSelectedBlogId(blog.id)}
                  className={`w-full rounded-[24px] border px-4 py-4 text-left ${
                    active
                      ? "border-ink bg-ink text-white"
                      : "border-ink/10 bg-white/80 text-ink"
                  }`}
                >
                  <p className={`text-xs uppercase tracking-[0.16em] ${active ? "text-white/65" : "text-slate-500"}`}>
                    {blog.profile_key}
                  </p>
                  <p className="mt-1 font-semibold">{blog.name}</p>
                  <p className={`mt-2 text-sm leading-6 ${active ? "text-white/80" : "text-slate-600"}`}>
                    {workflowPath(blog).join(" -> ")}
                  </p>
                </button>
              );
            })}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{selectedBlog.name}</CardTitle>
              <CardDescription>This panel shows the imported blog configuration and workflow.</CardDescription>
              <div className="flex flex-wrap gap-2">
                {tabs.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => setTab(item.key)}
                    className={
                      tab === item.key
                        ? "rounded-full bg-ink px-4 py-2 text-sm font-medium text-white"
                        : "rounded-full border border-ink/10 bg-white px-4 py-2 text-sm font-medium text-slate-700"
                    }
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </CardHeader>
          </Card>

          {tab === "connections" ? (
            <Card>
              <CardHeader>
                <CardTitle>Connections</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 lg:grid-cols-3">
                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Blogger</p>
                  <p className="mt-2 font-semibold text-ink">{selectedBlog.selected_connections.blogger?.name ?? selectedBlog.name}</p>
                  <p className="mt-2 break-all text-sm text-slate-600">{selectedBlog.blogger_url ?? "-"}</p>
                </div>
                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Search Console</p>
                  <p className="mt-2 break-all text-sm text-ink">
                    {selectedBlog.selected_connections.search_console?.site_url ?? "Not selected"}
                  </p>
                </div>
                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">GA4</p>
                  <p className="mt-2 break-all text-sm text-ink">
                    {selectedBlog.selected_connections.analytics
                      ? `${selectedBlog.selected_connections.analytics.display_name} (${selectedBlog.selected_connections.analytics.property_id})`
                      : "Not selected"}
                  </p>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {tab === "basic" ? (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Basic Info</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 lg:grid-cols-2">
                  <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Language</p>
                    <p className="mt-2 text-sm text-ink">{selectedBlog.primary_language}</p>
                  </div>
                  <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Category</p>
                    <p className="mt-2 text-sm text-ink">{selectedBlog.content_category}</p>
                  </div>
                  <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4 lg:col-span-2">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Description</p>
                    <p className="mt-2 text-sm leading-6 text-slate-700">{selectedBlog.description || "-"}</p>
                  </div>
                  <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4 lg:col-span-2">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Target Audience</p>
                    <p className="mt-2 text-sm leading-6 text-slate-700">{selectedBlog.target_audience || "-"}</p>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Reading Time Target</CardTitle>
                  <CardDescription>
                    Control how long each generated article should feel to read for this blog.
                  </CardDescription>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-[1fr_1fr_auto]">
                  <div className="space-y-2">
                    <Label htmlFor={`reading-min-${selectedBlog.id}`}>Minimum Minutes</Label>
                    <Input
                      id={`reading-min-${selectedBlog.id}`}
                      type="number"
                      min={1}
                      max={60}
                      value={readingTimeMin}
                      onChange={(event) => setReadingTimeMin(Number(event.target.value))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor={`reading-max-${selectedBlog.id}`}>Maximum Minutes</Label>
                    <Input
                      id={`reading-max-${selectedBlog.id}`}
                      type="number"
                      min={1}
                      max={60}
                      value={readingTimeMax}
                      onChange={(event) => setReadingTimeMax(Number(event.target.value))}
                    />
                  </div>
                  <div className="flex items-end">
                    <Button type="button" onClick={() => void saveReadingTargets()} disabled={isPending}>
                      {isPending ? "Saving..." : "Save Target"}
                    </Button>
                  </div>
                  <div className="rounded-[24px] border border-dashed border-ink/15 bg-slate-50 p-4 text-sm leading-6 text-slate-600 md:col-span-3">
                    This value is injected into the writing prompt. Recommended starting point is 6 to 8 minutes.
                    {saveStatus ? <p className="mt-2 text-ink">{saveStatus}</p> : null}
                  </div>
                </CardContent>
              </Card>
            </div>
          ) : null}

          {tab === "workflow" ? (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Current Execution Path</CardTitle>
                  <CardDescription>Manual publish flow: generate first, publish later from the article list.</CardDescription>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-2">
                  {workflowPath(selectedBlog).map((label) => (
                    <Badge key={label} className="bg-ink text-white">
                      {label}
                    </Badge>
                  ))}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>User Editable Stages</CardTitle>
                  <CardDescription>
                    These are the stages where prompt text and model choice matter per blog.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {selectedBlog.user_visible_steps.map((step) => (
                    <div key={step.id} className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge className="border border-ink/15 bg-white text-ink">{stageLabels[step.stage_type]}</Badge>
                        {step.provider_model ? (
                          <Badge className="border border-ink/15 bg-white text-ink">{step.provider_model}</Badge>
                        ) : null}
                        <Badge className="border border-ink/15 bg-white text-ink">
                          {step.is_enabled ? "Enabled" : "Disabled"}
                        </Badge>
                      </div>
                      <p className="mt-3 text-sm font-semibold text-ink">{step.name}</p>
                      <p className="mt-2 text-sm leading-6 text-slate-600">{step.objective || "-"}</p>
                      <div className="mt-4 space-y-2">
                        <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Prompt</p>
                        <Textarea
                          value={step.prompt_template}
                          readOnly
                          className="min-h-[220px] font-mono text-[13px] leading-6"
                        />
                      </div>
                    </div>
                  ))}

                  <div className="rounded-[24px] border border-dashed border-ink/15 bg-slate-50 p-4 text-sm leading-6 text-slate-600">
                    Optional stages available to add later:{" "}
                    {optionalStages
                      .filter((stage) => !selectedBlog.user_visible_steps.some((step) => step.stage_type === stage))
                      .map((stage) => stageLabels[stage])
                      .join(", ") || "None"}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>System Stages</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 lg:grid-cols-3">
                  {selectedBlog.system_steps.map((step) => (
                    <div key={step.id} className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                      <p className="font-semibold text-ink">{stageLabels[step.stage_type]}</p>
                      <p className="mt-2 text-sm leading-6 text-slate-600">{step.objective || "-"}</p>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          ) : null}

          {tab === "monitoring" ? (
            <Card>
              <CardHeader>
                <CardTitle>Monitoring</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-4">
                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Jobs</p>
                  <p className="mt-2 text-3xl font-semibold text-ink">{selectedBlog.job_count}</p>
                </div>
                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Completed</p>
                  <p className="mt-2 text-3xl font-semibold text-ink">{selectedBlog.completed_jobs}</p>
                </div>
                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Failed</p>
                  <p className="mt-2 text-3xl font-semibold text-ink">{selectedBlog.failed_jobs}</p>
                </div>
                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Published</p>
                  <p className="mt-2 text-3xl font-semibold text-ink">{selectedBlog.published_posts}</p>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </section>
  );
}

"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Blog, BlogImportOptions, BlogSeoMeta, BloggerConfig, GoogleBlogOverview, WorkflowStageType, WorkflowStep } from "@/lib/types";

type TabKey = "connections" | "basic" | "pipeline" | "monitoring";
type BasicDraft = { name: string; description: string; content_category: string; primary_language: string; target_audience: string; content_brief: string; is_active: boolean };
type ConnectionDraft = { search_console_site_url: string; ga4_property_id: string };

const apiBase = () => process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "connections", label: "연결" },
  { key: "basic", label: "기본 정보" },
  { key: "pipeline", label: "블로그별 워크플로" },
  { key: "monitoring", label: "모니터링" },
];
const stageLabels: Record<WorkflowStageType, string> = {
  topic_discovery: "주제 발굴",
  article_generation: "글쓰기 패키지",
  image_prompt_generation: "이미지 프롬프트 정교화",
  related_posts: "관련 글 연결",
  image_generation: "이미지 생성",
  html_assembly: "HTML 조립",
  publishing: "게시 대기",
};
const userVisibleStageOrder: WorkflowStageType[] = ["topic_discovery", "article_generation", "image_prompt_generation"];
const optionalStages: WorkflowStageType[] = ["topic_discovery", "image_prompt_generation"];
const modelOptions: Record<string, string[]> = {
  gemini: ["gemini-2.5-flash", "gemini-1.5-pro"],
  openai_text: ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
  openai_image: ["dall-e-3"],
  blogger: ["blogger-v3"],
};

const toBasicDraft = (blog: Blog): BasicDraft => ({
  name: blog.name,
  description: blog.description ?? "",
  content_category: blog.content_category,
  primary_language: blog.primary_language,
  target_audience: blog.target_audience ?? "",
  content_brief: blog.content_brief ?? "",
  is_active: blog.is_active,
});
const toConnectionDraft = (blog: Blog): ConnectionDraft => ({
  search_console_site_url: blog.search_console_site_url ?? "",
  ga4_property_id: blog.ga4_property_id ?? "",
});
const fmtDate = (value?: string | null) => {
  if (!value) return "-";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(d);
};
const fmtNum = (value?: number | null) => new Intl.NumberFormat("ko-KR").format(value ?? 0);
const deriveExecution = (steps: WorkflowStep[]) => {
  const enabled = new Map(steps.map((step) => [step.stage_type, step.is_enabled]));
  let idx = 1;
  const labels: string[] = [];
  if (enabled.get("topic_discovery")) labels.push(`${idx++}. 주제 발굴`);
  labels.push(`${idx++}. 글쓰기 패키지`);
  if (enabled.get("image_prompt_generation")) labels.push(`${idx++}. 이미지 프롬프트 정교화`);
  labels.push(`${idx++}. 이미지 생성`);
  labels.push(`${idx++}. HTML 조립`);
  labels.push(`${idx}. 게시 대기`);
  return labels;
};
const deriveUserSteps = (steps: WorkflowStep[]) => userVisibleStageOrder.map((type) => steps.find((step) => step.stage_type === type)).filter(Boolean) as WorkflowStep[];
const deriveSystemSteps = (steps: WorkflowStep[]) => ["image_generation", "html_assembly", "publishing"].map((type) => steps.find((step) => step.stage_type === type)).filter(Boolean) as WorkflowStep[];
const normalizeBlog = (blog: Blog): Blog => ({
  ...blog,
  user_visible_steps: deriveUserSteps(blog.workflow_steps),
  system_steps: deriveSystemSteps(blog.workflow_steps),
  execution_path_labels: deriveExecution(blog.workflow_steps),
});

function Detail({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[140px_minmax(0,1fr)]">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <div className={`min-w-0 rounded-2xl bg-slate-50 px-3 py-2 text-sm text-slate-700 ${mono ? "break-all font-mono text-xs" : "break-all"}`}>{value || "-"}</div>
    </div>
  );
}

function MetaStatus({ title, item }: { title: string; item: BlogSeoMeta["head_meta_description_status"] }) {
  const badge = item.status === "ok" ? "bg-emerald-700" : item.status === "warning" ? "bg-amber-700" : "bg-ink";
  return (
    <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="font-semibold text-ink">{title}</p>
        <Badge className={`${badge} text-white`}>{item.status === "ok" ? "정상" : item.status === "warning" ? "주의" : "검증 전"}</Badge>
      </div>
      <p className="mt-3 text-sm leading-7 text-slate-700">{item.message}</p>
      {item.expected ? <p className="mt-3 text-xs leading-6 text-slate-500">예상값: {item.expected}</p> : null}
      {item.actual ? <p className="mt-1 text-xs leading-6 text-slate-500">실제값: {item.actual}</p> : null}
    </div>
  );
}

export function BlogSettingsManager({ blogs, bloggerConfig, importOptions }: { blogs: Blog[]; bloggerConfig: BloggerConfig; importOptions: BlogImportOptions }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [status, setStatus] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("connections");
  const [blogsState, setBlogsState] = useState<Blog[]>(blogs.map(normalizeBlog));
  const [selectedBlogId, setSelectedBlogId] = useState<number | null>(blogs[0]?.id ?? null);
  const [importState, setImportState] = useState(importOptions);
  const [importDraft, setImportDraft] = useState({ blogger_blog_id: importOptions.available_blogs[0]?.id ?? "", profile_key: importOptions.profiles[0]?.key ?? "custom" });
  const [basicDrafts, setBasicDrafts] = useState<Record<number, BasicDraft>>(Object.fromEntries(blogs.map((blog) => [blog.id, toBasicDraft(blog)])));
  const [connectionDrafts, setConnectionDrafts] = useState<Record<number, ConnectionDraft>>(Object.fromEntries(blogs.map((blog) => [blog.id, toConnectionDraft(blog)])));
  const [workflowDrafts, setWorkflowDrafts] = useState<Record<number, WorkflowStep[]>>(Object.fromEntries(blogs.map((blog) => [blog.id, blog.workflow_steps])));
  const [newStageByBlog, setNewStageByBlog] = useState<Record<number, WorkflowStageType | "">>({});
  const [overviewByBlog, setOverviewByBlog] = useState<Record<number, GoogleBlogOverview | null>>({});
  const [seoByBlog, setSeoByBlog] = useState<Record<number, BlogSeoMeta | null>>({});
  const [loadingOverview, setLoadingOverview] = useState<Record<number, boolean>>({});
  const [loadingSeo, setLoadingSeo] = useState<Record<number, boolean>>({});

  const selectedBlog = useMemo(() => blogsState.find((blog) => blog.id === selectedBlogId) ?? null, [blogsState, selectedBlogId]);
  const selectedWorkflow = selectedBlog ? workflowDrafts[selectedBlog.id] ?? selectedBlog.workflow_steps : [];
  const missingStages = selectedBlog ? optionalStages.filter((stage) => !selectedWorkflow.some((step) => step.stage_type === stage)) : [];

  async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${apiBase()}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
    if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
    return res.json() as Promise<T>;
  }

  function refresh(message: string) {
    setStatus(message);
    startTransition(() => router.refresh());
  }

  function syncBlog(next: Blog) {
    const normalized = normalizeBlog(next);
    setBlogsState((current) => current.some((blog) => blog.id === normalized.id) ? current.map((blog) => (blog.id === normalized.id ? normalized : blog)) : [...current, normalized]);
    setBasicDrafts((current) => ({ ...current, [normalized.id]: toBasicDraft(normalized) }));
    setConnectionDrafts((current) => ({ ...current, [normalized.id]: toConnectionDraft(normalized) }));
    setWorkflowDrafts((current) => ({ ...current, [normalized.id]: normalized.workflow_steps }));
  }

  function syncWorkflow(blogId: number, steps: WorkflowStep[]) {
    setWorkflowDrafts((current) => ({ ...current, [blogId]: steps }));
    setBlogsState((current) => current.map((blog) => (blog.id === blogId ? normalizeBlog({ ...blog, workflow_steps: steps }) : blog)));
  }

  useEffect(() => {
    if (!selectedBlog) return;
    if (!overviewByBlog[selectedBlog.id]) {
      setLoadingOverview((current) => ({ ...current, [selectedBlog.id]: true }));
      requestJson<GoogleBlogOverview>(`/google/blogs/${selectedBlog.id}/overview`).then((payload) => {
        setOverviewByBlog((current) => ({ ...current, [selectedBlog.id]: payload }));
      }).catch((error) => setStatus(error instanceof Error ? error.message : "Google 개요를 불러오지 못했습니다.")).finally(() => {
        setLoadingOverview((current) => ({ ...current, [selectedBlog.id]: false }));
      });
    }
    if (!seoByBlog[selectedBlog.id]) {
      setLoadingSeo((current) => ({ ...current, [selectedBlog.id]: true }));
      requestJson<BlogSeoMeta>(`/blogs/${selectedBlog.id}/seo-meta`).then((payload) => {
        setSeoByBlog((current) => ({ ...current, [selectedBlog.id]: payload }));
      }).catch((error) => setStatus(error instanceof Error ? error.message : "SEO 메타 상태를 불러오지 못했습니다.")).finally(() => {
        setLoadingSeo((current) => ({ ...current, [selectedBlog.id]: false }));
      });
    }
  }, [selectedBlog, overviewByBlog, seoByBlog]);

  async function handleImport() {
    if (!importDraft.blogger_blog_id) return;
    try {
      const blog = normalizeBlog(await requestJson<Blog>("/blogs/import", { method: "POST", body: JSON.stringify(importDraft) }));
      const remaining = importState.available_blogs.filter((item) => item.id !== importDraft.blogger_blog_id);
      syncBlog(blog);
      setSelectedBlogId(blog.id);
      setImportState((current) => ({ ...current, available_blogs: remaining, imported_blogger_blog_ids: [...current.imported_blogger_blog_ids, importDraft.blogger_blog_id] }));
      setImportDraft((current) => ({ ...current, blogger_blog_id: remaining[0]?.id ?? "" }));
      refresh("Blogger 블로그를 서비스용 블로그로 가져왔습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Blogger 블로그 가져오기에 실패했습니다.");
    }
  }

  if (!selectedBlog && blogsState.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>블로그별 워크플로</CardTitle>
          <CardDescription>먼저 Blogger 블로그를 가져와 서비스형 워크플로를 붙이세요.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>가져올 Blogger 블로그</Label>
            <select className="h-11 w-full rounded-xl border border-ink/15 bg-white px-3 text-sm" value={importDraft.blogger_blog_id} onChange={(event) => setImportDraft((current) => ({ ...current, blogger_blog_id: event.target.value }))}>
              <option value="">선택하세요</option>
              {importState.available_blogs.map((blog) => <option key={blog.id} value={blog.id}>{blog.name}</option>)}
            </select>
          </div>
          <div className="space-y-2">
            <Label>초기 프로필</Label>
            <select className="h-11 w-full rounded-xl border border-ink/15 bg-white px-3 text-sm" value={importDraft.profile_key} onChange={(event) => setImportDraft((current) => ({ ...current, profile_key: event.target.value }))}>
              {importState.profiles.map((profile) => <option key={profile.key} value={profile.key}>{profile.label}</option>)}
            </select>
          </div>
          <Button type="button" onClick={handleImport} disabled={!importDraft.blogger_blog_id || isPending}>Blogger 블로그 가져오기</Button>
          {status ? <p className="text-sm text-slate-600">{status}</p> : null}
        </CardContent>
      </Card>
    );
  }

  if (!selectedBlog) {
    return null;
  }

  return (
    <section className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardDescription>Blogger에서 가져온 실제 블로그를 기준으로 서비스별 설정을 관리합니다.</CardDescription>
            <CardTitle>서비스 블로그 목록</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3 rounded-[24px] border border-ink/10 bg-slate-50 p-4">
              <p className="font-semibold text-ink">Blogger에서 가져오기</p>
              <div className="space-y-2">
                <Label>가져올 Blogger 블로그</Label>
                <select className="h-11 w-full rounded-xl border border-ink/15 bg-white px-3 text-sm" value={importDraft.blogger_blog_id} onChange={(event) => setImportDraft((current) => ({ ...current, blogger_blog_id: event.target.value }))}>
                  <option value="">선택하세요</option>
                  {importState.available_blogs.map((blog) => <option key={blog.id} value={blog.id}>{blog.name}</option>)}
                </select>
              </div>
              <div className="space-y-2">
                <Label>초기 프로필</Label>
                <select className="h-11 w-full rounded-xl border border-ink/15 bg-white px-3 text-sm" value={importDraft.profile_key} onChange={(event) => setImportDraft((current) => ({ ...current, profile_key: event.target.value }))}>
                  {importState.profiles.map((profile) => <option key={profile.key} value={profile.key}>{profile.label}</option>)}
                </select>
              </div>
              <Button type="button" className="w-full" onClick={handleImport} disabled={!importDraft.blogger_blog_id || isPending}>Blogger 블로그 가져오기</Button>
            </div>

            <div className="space-y-2">
              {blogsState.map((blog) => (
                <button
                  key={blog.id}
                  type="button"
                  onClick={() => setSelectedBlogId(blog.id)}
                  className={`w-full rounded-[24px] border px-4 py-4 text-left transition ${
                    selectedBlogId === blog.id ? "border-ink bg-ink text-white" : "border-ink/10 bg-white/70 text-ink hover:bg-white"
                  }`}
                >
                  <p className={`text-xs uppercase tracking-[0.16em] ${selectedBlogId === blog.id ? "text-white/60" : "text-slate-500"}`}>{blog.profile_key}</p>
                  <p className="mt-1 break-words font-semibold">{blog.name}</p>
                  <p className={`mt-2 text-sm ${selectedBlogId === blog.id ? "text-white/80" : "text-slate-600"}`}>{blog.execution_path_labels.join(" -> ")}</p>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <CardDescription>이 블로그에서 실제로 쓰는 프롬프트와 실행 순서를 관리합니다.</CardDescription>
                  <CardTitle className="mt-1 text-2xl">{selectedBlog.name}</CardTitle>
                  <p className="mt-2 text-sm leading-7 text-slate-600">기본 운영은 항상 초안 생성 후 수동 공개 게시입니다. 실제 공개는 생성 글 목록에서만 진행합니다.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge>{selectedBlog.content_category}</Badge>
                  <Badge className="bg-transparent">{selectedBlog.primary_language}</Badge>
                  <Badge className="bg-transparent">{selectedBlog.publish_mode === "draft" ? "초안 생성" : "게시 모드"}</Badge>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {tabs.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setActiveTab(tab.key)}
                    className={activeTab === tab.key ? "rounded-full bg-ink px-4 py-2 text-sm font-medium text-white" : "rounded-full border border-ink/10 bg-white px-4 py-2 text-sm font-medium text-slate-700"}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </CardHeader>
          </Card>

          {activeTab === "connections" ? (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardDescription>가져온 Blogger/Google 연결을 이 블로그에 매핑합니다.</CardDescription>
                  <CardTitle>연결</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Detail label="Blogger 블로그" value={selectedBlog.selected_connections.blogger?.name ?? selectedBlog.name} />
                  <Detail label="Blogger 주소" value={selectedBlog.selected_connections.blogger?.url ?? selectedBlog.blogger_url ?? "-"} mono />
                  <div className="space-y-2">
                    <Label>Search Console 속성</Label>
                    <select className="h-11 w-full rounded-xl border border-ink/15 bg-white px-3 text-sm" value={connectionDrafts[selectedBlog.id]?.search_console_site_url ?? ""} onChange={(event) => setConnectionDrafts((current) => ({ ...current, [selectedBlog.id]: { ...current[selectedBlog.id], search_console_site_url: event.target.value } }))}>
                      <option value="">선택 안 함</option>
                      {bloggerConfig.search_console_sites.map((site) => <option key={site.site_url} value={site.site_url}>{site.site_url}</option>)}
                    </select>
                  </div>
                  <div className="space-y-2">
                    <Label>GA4 속성</Label>
                    <select className="h-11 w-full rounded-xl border border-ink/15 bg-white px-3 text-sm" value={connectionDrafts[selectedBlog.id]?.ga4_property_id ?? ""} onChange={(event) => setConnectionDrafts((current) => ({ ...current, [selectedBlog.id]: { ...current[selectedBlog.id], ga4_property_id: event.target.value } }))}>
                      <option value="">선택 안 함</option>
                      {bloggerConfig.analytics_properties.map((property) => <option key={property.property_id} value={property.property_id}>{property.display_name} ({property.property_id})</option>)}
                    </select>
                  </div>
                  <Button
                    type="button"
                    onClick={async () => {
                      try {
                        const next = await requestJson<Blog>(`/blogs/${selectedBlog.id}/connections`, { method: "PUT", body: JSON.stringify(connectionDrafts[selectedBlog.id]) });
                        syncBlog(next);
                        refresh("연결 정보를 저장했습니다.");
                      } catch (error) {
                        setStatus(error instanceof Error ? error.message : "연결 정보 저장에 실패했습니다.");
                      }
                    }}
                  >
                    연결 저장
                  </Button>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardDescription>앱 저장값과 실제 공개 페이지 head 반영 결과를 분리해서 보여줍니다.</CardDescription>
                  <CardTitle>Blogger SEO 메타 패치</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {!seoByBlog[selectedBlog.id] ? (
                    <p className="text-sm text-slate-600">{loadingSeo[selectedBlog.id] ? "SEO 메타 상태를 불러오는 중입니다..." : "SEO 메타 상태가 없습니다."}</p>
                  ) : (
                    <>
                      <label className="flex items-center gap-2 text-sm text-slate-700">
                        <input
                          type="checkbox"
                          checked={seoByBlog[selectedBlog.id]?.seo_theme_patch_installed ?? false}
                          onChange={async (event) => {
                            try {
                              const payload = await requestJson<BlogSeoMeta>(`/blogs/${selectedBlog.id}/seo-meta`, { method: "PUT", body: JSON.stringify({ seo_theme_patch_installed: event.target.checked }) });
                              setSeoByBlog((current) => ({ ...current, [selectedBlog.id]: payload }));
                              refresh("SEO 메타 패치 상태를 저장했습니다.");
                            } catch (error) {
                              setStatus(error instanceof Error ? error.message : "SEO 패치 상태 저장에 실패했습니다.");
                            }
                          }}
                        />
                        Blogger 테마에 SEO 메타 패치를 적용했습니다
                      </label>
                      <Detail label="검증 대상 URL" value={seoByBlog[selectedBlog.id]?.verification_target_url ?? "-"} mono />
                      <Detail label="예상 검색 설명" value={seoByBlog[selectedBlog.id]?.expected_meta_description ?? "-"} />
                      <div className="grid gap-4 lg:grid-cols-3">
                        <MetaStatus title="head meta description" item={seoByBlog[selectedBlog.id]!.head_meta_description_status} />
                        <MetaStatus title="og:description" item={seoByBlog[selectedBlog.id]!.og_description_status} />
                        <MetaStatus title="twitter:description" item={seoByBlog[selectedBlog.id]!.twitter_description_status} />
                      </div>
                      <div className="flex flex-wrap gap-3">
                        <Button
                          type="button"
                          onClick={async () => {
                            try {
                              setLoadingSeo((current) => ({ ...current, [selectedBlog.id]: true }));
                              const payload = await requestJson<BlogSeoMeta>(`/blogs/${selectedBlog.id}/seo-meta/verify`, { method: "POST" });
                              setSeoByBlog((current) => ({ ...current, [selectedBlog.id]: payload }));
                              refresh("공개 페이지 메타 검증을 완료했습니다.");
                            } catch (error) {
                              setStatus(error instanceof Error ? error.message : "SEO 메타 검증에 실패했습니다.");
                            } finally {
                              setLoadingSeo((current) => ({ ...current, [selectedBlog.id]: false }));
                            }
                          }}
                          disabled={loadingSeo[selectedBlog.id]}
                        >
                          {loadingSeo[selectedBlog.id] ? "검증 중..." : "공개 페이지 메타 검증"}
                        </Button>
                        <Badge className={seoByBlog[selectedBlog.id]?.seo_theme_patch_verified ? "bg-emerald-700 text-white" : "bg-transparent"}>
                          {seoByBlog[selectedBlog.id]?.seo_theme_patch_verified ? `검증 완료 (${fmtDate(seoByBlog[selectedBlog.id]?.seo_theme_patch_verified_at)})` : "검증 필요"}
                        </Badge>
                      </div>
                      {seoByBlog[selectedBlog.id]!.warnings.length ? (
                        <div className="rounded-[24px] border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-900">
                          {seoByBlog[selectedBlog.id]!.warnings.map((warning) => <p key={warning}>{warning}</p>)}
                        </div>
                      ) : null}
                      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
                        <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                          <p className="font-semibold text-ink">테마에 넣을 스니펫</p>
                          <Textarea value={seoByBlog[selectedBlog.id]!.patch_snippet} readOnly className="mt-3 min-h-[220px] font-mono text-[12px] leading-6" />
                        </div>
                        <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                          <p className="font-semibold text-ink">적용 체크리스트</p>
                          <div className="mt-3 space-y-3 text-sm leading-7 text-slate-700">
                            {seoByBlog[selectedBlog.id]!.patch_steps.map((step, index) => (
                              <div key={step} className="rounded-2xl border border-ink/10 px-3 py-2">
                                <p className="font-medium text-ink">Step {index + 1}</p>
                                <p className="mt-1">{step}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            </div>
          ) : null}

          {activeTab === "basic" ? (
            <Card>
              <CardHeader>
                <CardDescription>이 블로그의 소개 문구와 운영 브리프를 정리합니다.</CardDescription>
                <CardTitle>기본 정보</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 lg:grid-cols-2">
                <div className="space-y-2"><Label>블로그 이름</Label><Input value={basicDrafts[selectedBlog.id]?.name ?? ""} onChange={(event) => setBasicDrafts((current) => ({ ...current, [selectedBlog.id]: { ...current[selectedBlog.id], name: event.target.value } }))} /></div>
                <div className="space-y-2"><Label>주 언어</Label><Input value={basicDrafts[selectedBlog.id]?.primary_language ?? ""} onChange={(event) => setBasicDrafts((current) => ({ ...current, [selectedBlog.id]: { ...current[selectedBlog.id], primary_language: event.target.value } }))} /></div>
                <div className="space-y-2 lg:col-span-2"><Label>블로그 설명</Label><Textarea className="min-h-[120px]" value={basicDrafts[selectedBlog.id]?.description ?? ""} onChange={(event) => setBasicDrafts((current) => ({ ...current, [selectedBlog.id]: { ...current[selectedBlog.id], description: event.target.value } }))} /></div>
                <div className="space-y-2 lg:col-span-2"><Label>타깃 독자</Label><Input value={basicDrafts[selectedBlog.id]?.target_audience ?? ""} onChange={(event) => setBasicDrafts((current) => ({ ...current, [selectedBlog.id]: { ...current[selectedBlog.id], target_audience: event.target.value } }))} /></div>
                <div className="space-y-2 lg:col-span-2"><Label>운영 브리프</Label><Textarea className="min-h-[160px]" value={basicDrafts[selectedBlog.id]?.content_brief ?? ""} onChange={(event) => setBasicDrafts((current) => ({ ...current, [selectedBlog.id]: { ...current[selectedBlog.id], content_brief: event.target.value } }))} /></div>
                <label className="flex items-center gap-2 text-sm text-slate-700 lg:col-span-2"><input type="checkbox" checked={basicDrafts[selectedBlog.id]?.is_active ?? true} onChange={(event) => setBasicDrafts((current) => ({ ...current, [selectedBlog.id]: { ...current[selectedBlog.id], is_active: event.target.checked } }))} />이 블로그를 활성 상태로 유지</label>
                <div className="lg:col-span-2">
                  <Button
                    type="button"
                    onClick={async () => {
                      try {
                        const next = await requestJson<Blog>(`/blogs/${selectedBlog.id}`, { method: "PUT", body: JSON.stringify({ ...basicDrafts[selectedBlog.id], publish_mode: selectedBlog.publish_mode }) });
                        syncBlog(next);
                        refresh("기본 정보를 저장했습니다.");
                      } catch (error) {
                        setStatus(error instanceof Error ? error.message : "기본 정보 저장에 실패했습니다.");
                      }
                    }}
                  >
                    기본 정보 저장
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {activeTab === "pipeline" ? (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardDescription>현재 이 블로그가 실제로 실행하는 순서입니다.</CardDescription>
                  <CardTitle>현재 실행 순서</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-2">
                  {normalizeBlog({ ...selectedBlog, workflow_steps: selectedWorkflow }).execution_path_labels.map((label) => <Badge key={label} className="bg-ink text-white">{label}</Badge>)}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <CardDescription>실제 운영용 프롬프트와 모델은 여기서 수정합니다.</CardDescription>
                      <CardTitle>사용자 설정 단계</CardTitle>
                    </div>
                    <div className="flex flex-wrap gap-3">
                      <select className="h-11 rounded-xl border border-ink/15 bg-white px-3 text-sm" value={newStageByBlog[selectedBlog.id] ?? ""} onChange={(event) => setNewStageByBlog((current) => ({ ...current, [selectedBlog.id]: event.target.value as WorkflowStageType | "" }))}>
                        <option value="">추가할 선택 단계</option>
                        {missingStages.map((stage) => <option key={stage} value={stage}>{stageLabels[stage]}</option>)}
                      </select>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={async () => {
                          const stageType = newStageByBlog[selectedBlog.id];
                          if (!stageType) return;
                          try {
                            const steps = await requestJson<WorkflowStep[]>(`/blogs/${selectedBlog.id}/workflow`, { method: "POST", body: JSON.stringify({ stage_type: stageType }) });
                            syncWorkflow(selectedBlog.id, steps);
                            setNewStageByBlog((current) => ({ ...current, [selectedBlog.id]: "" }));
                            refresh("선택 단계를 추가했습니다.");
                          } catch (error) {
                            setStatus(error instanceof Error ? error.message : "단계 추가에 실패했습니다.");
                          }
                        }}
                        disabled={!newStageByBlog[selectedBlog.id]}
                      >
                        단계 추가
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={async () => {
                          if (!window.confirm("현재 블로그의 단계 설정과 프롬프트를 프로필 프리셋 기준으로 다시 적용할까요?")) return;
                          try {
                            const steps = await requestJson<WorkflowStep[]>(`/blogs/${selectedBlog.id}/workflow/apply-preset`, { method: "POST", body: JSON.stringify({ overwrite_prompts: true }) });
                            syncWorkflow(selectedBlog.id, steps);
                            refresh("프로필 프리셋을 다시 적용했습니다.");
                          } catch (error) {
                            setStatus(error instanceof Error ? error.message : "프리셋 다시 적용에 실패했습니다.");
                          }
                        }}
                      >
                        프리셋 다시 적용
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {deriveUserSteps(selectedWorkflow).map((step) => (
                    <div key={step.id} className="rounded-[28px] border border-ink/10 bg-white/70 p-5">
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div>
                          <div className="flex flex-wrap gap-2">
                            <Badge>{stageLabels[step.stage_type]}</Badge>
                            {step.is_required ? <Badge className="bg-transparent">필수</Badge> : <Badge className="bg-transparent">선택</Badge>}
                            {!step.is_enabled ? <Badge className="bg-transparent">비활성</Badge> : null}
                          </div>
                          <p className="mt-3 text-lg font-semibold text-ink">{step.name}</p>
                        </div>
                        {!step.is_required ? (
                          <Button
                            type="button"
                            variant="outline"
                            onClick={async () => {
                              try {
                                const steps = await requestJson<WorkflowStep[]>(`/blogs/${selectedBlog.id}/workflow/${step.id}`, { method: "DELETE" });
                                syncWorkflow(selectedBlog.id, steps);
                                refresh(`${step.name} 단계를 제거했습니다.`);
                              } catch (error) {
                                setStatus(error instanceof Error ? error.message : "단계 제거에 실패했습니다.");
                              }
                            }}
                          >
                            제거
                          </Button>
                        ) : null}
                      </div>
                      <div className="mt-4 grid gap-4 lg:grid-cols-2">
                        <div className="space-y-2"><Label>단계 이름</Label><Input value={step.name} onChange={(event) => setWorkflowDrafts((current) => ({ ...current, [selectedBlog.id]: current[selectedBlog.id].map((item) => item.id === step.id ? { ...item, name: event.target.value } : item) }))} /></div>
                        <div className="space-y-2"><Label>역할명</Label><Input value={step.role_name} onChange={(event) => setWorkflowDrafts((current) => ({ ...current, [selectedBlog.id]: current[selectedBlog.id].map((item) => item.id === step.id ? { ...item, role_name: event.target.value } : item) }))} /></div>
                        <div className="space-y-2"><Label>모델</Label><select className="h-11 w-full rounded-xl border border-ink/15 bg-white px-3 text-sm" value={step.provider_model ?? ""} onChange={(event) => setWorkflowDrafts((current) => ({ ...current, [selectedBlog.id]: current[selectedBlog.id].map((item) => item.id === step.id ? { ...item, provider_model: event.target.value } : item) }))}>{(step.provider_hint ? modelOptions[step.provider_hint] ?? [] : []).map((model) => <option key={model} value={model}>{model}</option>)}</select></div>
                        <div className="space-y-2"><Label>사용 여부</Label><label className="flex h-11 items-center gap-2 rounded-xl border border-ink/15 bg-white px-3 text-sm text-slate-700"><input type="checkbox" checked={step.is_enabled} disabled={step.is_required} onChange={(event) => setWorkflowDrafts((current) => ({ ...current, [selectedBlog.id]: current[selectedBlog.id].map((item) => item.id === step.id ? { ...item, is_enabled: event.target.checked } : item) }))} />이 단계를 사용합니다</label></div>
                        <div className="space-y-2 lg:col-span-2"><Label>목적</Label><Textarea className="min-h-[90px]" value={step.objective ?? ""} onChange={(event) => setWorkflowDrafts((current) => ({ ...current, [selectedBlog.id]: current[selectedBlog.id].map((item) => item.id === step.id ? { ...item, objective: event.target.value } : item) }))} /></div>
                        <div className="space-y-2 lg:col-span-2"><Label>프롬프트 본문</Label><Textarea className="min-h-[300px] font-mono text-[13px] leading-6" value={step.prompt_template} onChange={(event) => setWorkflowDrafts((current) => ({ ...current, [selectedBlog.id]: current[selectedBlog.id].map((item) => item.id === step.id ? { ...item, prompt_template: event.target.value } : item) }))} /></div>
                      </div>
                      <div className="mt-4">
                        <Button
                          type="button"
                          onClick={async () => {
                            const draft = (workflowDrafts[selectedBlog.id] ?? []).find((item) => item.id === step.id) ?? step;
                            try {
                              const steps = await requestJson<WorkflowStep[]>(`/blogs/${selectedBlog.id}/workflow/${step.id}`, { method: "PUT", body: JSON.stringify({ name: draft.name, role_name: draft.role_name, objective: draft.objective ?? "", prompt_template: draft.prompt_template ?? "", provider_hint: draft.provider_hint ?? null, provider_model: draft.provider_model ?? null, is_enabled: draft.is_enabled }) });
                              syncWorkflow(selectedBlog.id, steps);
                              refresh(`${draft.name} 단계를 저장했습니다.`);
                            } catch (error) {
                              setStatus(error instanceof Error ? error.message : "단계 저장에 실패했습니다.");
                            }
                          }}
                        >
                          이 단계 저장
                        </Button>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardDescription>항상 자동으로 이어지는 시스템 단계입니다.</CardDescription>
                  <CardTitle>자동 실행 시스템 단계</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 lg:grid-cols-3">
                  {deriveSystemSteps(selectedWorkflow).map((step) => (
                    <div key={step.id} className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="font-semibold text-ink">{stageLabels[step.stage_type]}</p>
                        <Badge className="bg-transparent">{step.provider_model ?? "system"}</Badge>
                      </div>
                      <p className="mt-3 text-sm leading-7 text-slate-600">{step.objective}</p>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          ) : null}

          {activeTab === "monitoring" ? (
            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-4">
                <Card><CardContent className="p-5"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">총 작업</p><p className="mt-2 text-3xl font-semibold text-ink">{fmtNum(selectedBlog.job_count)}</p></CardContent></Card>
                <Card><CardContent className="p-5"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">완료</p><p className="mt-2 text-3xl font-semibold text-ink">{fmtNum(selectedBlog.completed_jobs)}</p></CardContent></Card>
                <Card><CardContent className="p-5"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">실패</p><p className="mt-2 text-3xl font-semibold text-ink">{fmtNum(selectedBlog.failed_jobs)}</p></CardContent></Card>
                <Card><CardContent className="p-5"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">게시 글</p><p className="mt-2 text-3xl font-semibold text-ink">{fmtNum(selectedBlog.published_posts)}</p></CardContent></Card>
              </div>
              <Card>
                <CardHeader>
                  <CardDescription>선택된 연결값 기준 Blogger, Search Console, GA4 요약입니다.</CardDescription>
                  <CardTitle>실시간 개요</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {!overviewByBlog[selectedBlog.id] ? (
                    <p className="text-sm text-slate-600">{loadingOverview[selectedBlog.id] ? "개요를 불러오는 중입니다..." : "연결된 개요 데이터가 없습니다."}</p>
                  ) : (
                    <>
                      {overviewByBlog[selectedBlog.id]!.warnings.length ? <div className="rounded-[24px] border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-900">{overviewByBlog[selectedBlog.id]!.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div> : null}
                      <div className="grid gap-4 xl:grid-cols-3">
                        <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">최근 게시글</p><div className="mt-3 space-y-3">{overviewByBlog[selectedBlog.id]!.recent_posts.slice(0, 5).map((post) => <div key={post.id} className="rounded-2xl border border-ink/10 px-3 py-3"><p className="font-medium text-ink">{post.title}</p>{post.url ? <a href={post.url} target="_blank" rel="noreferrer" className="mt-2 block break-all text-xs text-ember underline-offset-4 hover:underline">{post.url}</a> : null}</div>)}</div></div>
                        <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">Search Console</p><div className="mt-3 space-y-2 text-sm leading-7 text-slate-700"><p>클릭: {fmtNum(overviewByBlog[selectedBlog.id]!.search_console?.totals.clicks)}</p><p>노출: {fmtNum(overviewByBlog[selectedBlog.id]!.search_console?.totals.impressions)}</p><p>CTR: {overviewByBlog[selectedBlog.id]!.search_console?.totals.ctr?.toFixed?.(2) ?? "0"}%</p><p>평균 순위: {overviewByBlog[selectedBlog.id]!.search_console?.totals.position?.toFixed?.(2) ?? "0"}</p></div></div>
                        <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4"><p className="text-xs uppercase tracking-[0.16em] text-slate-500">GA4</p><div className="mt-3 space-y-2 text-sm leading-7 text-slate-700"><p>페이지뷰: {fmtNum(overviewByBlog[selectedBlog.id]!.analytics?.totals.screenPageViews)}</p><p>세션: {fmtNum(overviewByBlog[selectedBlog.id]!.analytics?.totals.sessions)}</p><p>최근 28일 기준 요약입니다.</p></div></div>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            </div>
          ) : null}
        </div>
      </div>

      {status ? <p className="text-sm text-slate-600">{status}</p> : null}
    </section>
  );
}

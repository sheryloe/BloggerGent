"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Blog,
  BlogImportOptions,
  BloggerConfig,
  GoogleBlogOverview,
  WorkflowStageType,
  WorkflowStep,
} from "@/lib/types";

type TabKey = "connections" | "basic" | "pipeline" | "monitoring";
type BasicDraft = {
  name: string;
  description: string;
  content_category: string;
  primary_language: string;
  target_audience: string;
  content_brief: string;
  is_active: boolean;
};
type ConnectionDraft = {
  search_console_site_url: string;
  ga4_property_id: string;
};

const apiBase = () => process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const optionalStages: WorkflowStageType[] = ["topic_discovery", "image_prompt_generation", "related_posts"];
const tabLabels: Record<TabKey, string> = {
  connections: "연결",
  basic: "기본 정보",
  pipeline: "파이프라인",
  monitoring: "모니터링",
};
const stageLabels: Record<WorkflowStageType, string> = {
  topic_discovery: "주제 발굴",
  article_generation: "본문 생성",
  image_prompt_generation: "이미지 프롬프트",
  related_posts: "관련 글 연결",
  image_generation: "이미지 생성",
  html_assembly: "HTML 조립",
  publishing: "Blogger 게시",
};
const profileLabels: Record<string, string> = {
  korea_travel: "Korea Travel",
  world_mystery: "World Mystery",
  custom: "Custom",
};
const stageDescriptions: Partial<Record<WorkflowStageType, string>> = {
  related_posts: "라벨과 유사도를 기준으로 관련 글 카드 섹션을 구성합니다.",
  image_generation: "저장된 이미지 프롬프트를 이용해 대표 이미지를 생성합니다.",
  html_assembly: "대표 이미지, 본문, FAQ, 관련 글을 합쳐 최종 HTML을 조립합니다.",
  publishing: "공개 게시 버튼을 누르면 Blogger로 최종 전송합니다.",
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

const formatNumber = (value?: number | null) => new Intl.NumberFormat("ko-KR").format(value ?? 0);
const formatDate = (value?: string | null) => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", { month: "short", day: "numeric" }).format(date);
};

function DetailRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="grid gap-1 text-sm leading-6 text-slate-700 sm:grid-cols-[120px_minmax(0,1fr)] sm:gap-3">
      <p className="font-medium text-slate-500">{label}</p>
      <div className={`min-w-0 rounded-2xl bg-slate-50 px-3 py-2 ${mono ? "break-all font-mono text-xs" : "break-all"}`}>
        {value || "-"}
      </div>
    </div>
  );
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
      <p className="text-xs uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-ink">{value}</p>
    </div>
  );
}

function tabClass(active: boolean) {
  return active
    ? "rounded-full bg-ink px-4 py-2 text-sm font-medium text-white"
    : "rounded-full border border-ink/10 bg-white px-4 py-2 text-sm font-medium text-slate-700";
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
  const [status, setStatus] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("connections");
  const [blogsState, setBlogsState] = useState<Blog[]>(blogs);
  const [importState, setImportState] = useState(importOptions);
  const [selectedBlogId, setSelectedBlogId] = useState<number | null>(blogs[0]?.id ?? null);
  const [basicDrafts, setBasicDrafts] = useState<Record<number, BasicDraft>>(
    Object.fromEntries(blogs.map((blog) => [blog.id, toBasicDraft(blog)])),
  );
  const [connectionDrafts, setConnectionDrafts] = useState<Record<number, ConnectionDraft>>(
    Object.fromEntries(blogs.map((blog) => [blog.id, toConnectionDraft(blog)])),
  );
  const [workflowDrafts, setWorkflowDrafts] = useState<Record<number, WorkflowStep[]>>(
    Object.fromEntries(blogs.map((blog) => [blog.id, blog.workflow_steps])),
  );
  const [importDraft, setImportDraft] = useState({
    blogger_blog_id: importOptions.available_blogs[0]?.id ?? "",
    profile_key: importOptions.profiles[0]?.key ?? "custom",
  });
  const [newStageByBlog, setNewStageByBlog] = useState<Record<number, WorkflowStageType | "">>({});
  const [overviewByBlog, setOverviewByBlog] = useState<Record<number, GoogleBlogOverview | null>>({});
  const [overviewLoading, setOverviewLoading] = useState<Record<number, boolean>>({});
  const [overviewError, setOverviewError] = useState<Record<number, string>>({});

  const selectedBlog = useMemo(
    () => blogsState.find((blog) => blog.id === selectedBlogId) ?? null,
    [blogsState, selectedBlogId],
  );
  const selectedOverview = selectedBlog ? overviewByBlog[selectedBlog.id] : null;
  const missingStageOptions = selectedBlog
    ? optionalStages.filter(
        (stage) => !(workflowDrafts[selectedBlog.id] ?? []).some((step) => step.stage_type === stage),
      )
    : [];

  function syncBlog(nextBlog: Blog) {
    setBlogsState((current) =>
      current.some((blog) => blog.id === nextBlog.id)
        ? current.map((blog) => (blog.id === nextBlog.id ? nextBlog : blog))
        : [...current, nextBlog],
    );
    setBasicDrafts((current) => ({ ...current, [nextBlog.id]: toBasicDraft(nextBlog) }));
    setConnectionDrafts((current) => ({ ...current, [nextBlog.id]: toConnectionDraft(nextBlog) }));
    setWorkflowDrafts((current) => ({ ...current, [nextBlog.id]: nextBlog.workflow_steps }));
  }

  function updateWorkflow(blogId: number, steps: WorkflowStep[]) {
    setWorkflowDrafts((current) => ({ ...current, [blogId]: steps }));
    setBlogsState((current) =>
      current.map((blog) => (blog.id === blogId ? { ...blog, workflow_steps: steps } : blog)),
    );
  }

  async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${apiBase()}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
    if (!response.ok) {
      throw new Error((await response.text()) || `HTTP ${response.status}`);
    }
    return response.json() as Promise<T>;
  }

  function refreshWithStatus(message: string) {
    setStatus(message);
    startTransition(() => router.refresh());
  }

  function patchStep(blogId: number, stepId: number, patch: Partial<WorkflowStep>) {
    setWorkflowDrafts((current) => ({
      ...current,
      [blogId]: (current[blogId] ?? []).map((item) => (item.id === stepId ? { ...item, ...patch } : item)),
    }));
  }

  async function handleImport() {
    if (!importDraft.blogger_blog_id) return;
    try {
      const blog = await requestJson<Blog>("/blogs/import", {
        method: "POST",
        body: JSON.stringify(importDraft),
      });
      const remaining = importState.available_blogs.filter((item) => item.id !== importDraft.blogger_blog_id);
      syncBlog(blog);
      setSelectedBlogId(blog.id);
      setActiveTab("connections");
      setImportState((current) => ({
        ...current,
        available_blogs: remaining,
        imported_blogger_blog_ids: [...current.imported_blogger_blog_ids, importDraft.blogger_blog_id],
      }));
      setImportDraft((current) => ({
        ...current,
        blogger_blog_id: remaining[0]?.id ?? "",
      }));
      refreshWithStatus("Blogger 블로그를 서비스용 블로그로 가져왔습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Blogger 블로그 가져오기에 실패했습니다.");
    }
  }

  async function saveBasic(blog: Blog) {
    try {
      const payload = {
        ...basicDrafts[blog.id],
        publish_mode: blog.publish_mode,
      };
      syncBlog(
        await requestJson<Blog>(`/blogs/${blog.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        }),
      );
      refreshWithStatus("기본 정보를 저장했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "기본 정보 저장에 실패했습니다.");
    }
  }

  async function saveConnections(blog: Blog) {
    try {
      syncBlog(
        await requestJson<Blog>(`/blogs/${blog.id}/connections`, {
          method: "PUT",
          body: JSON.stringify(connectionDrafts[blog.id]),
        }),
      );
      refreshWithStatus("연결 정보를 저장했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "연결 정보 저장에 실패했습니다.");
    }
  }

  async function saveStep(blogId: number, step: WorkflowStep) {
    try {
      updateWorkflow(
        blogId,
        await requestJson<WorkflowStep[]>(`/blogs/${blogId}/workflow/${step.id}`, {
          method: "PUT",
          body: JSON.stringify({
            name: step.name,
            role_name: step.role_name,
            objective: step.objective ?? "",
            prompt_template: step.prompt_template,
            provider_hint: step.provider_hint ?? "",
            is_enabled: step.is_enabled,
          }),
        }),
      );
      setStatus(`'${stageLabels[step.stage_type]}' 단계를 저장했습니다.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "단계 저장에 실패했습니다.");
    }
  }

  async function addStep(blogId: number) {
    const stageType = newStageByBlog[blogId];
    if (!stageType) return;
    try {
      updateWorkflow(
        blogId,
        await requestJson<WorkflowStep[]>(`/blogs/${blogId}/workflow`, {
          method: "POST",
          body: JSON.stringify({ stage_type: stageType }),
        }),
      );
      setNewStageByBlog((current) => ({ ...current, [blogId]: "" }));
      setStatus("선택한 단계를 추가했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "단계 추가에 실패했습니다.");
    }
  }

  async function removeStep(blogId: number, stepId: number) {
    try {
      updateWorkflow(
        blogId,
        await requestJson<WorkflowStep[]>(`/blogs/${blogId}/workflow/${stepId}`, {
          method: "DELETE",
        }),
      );
      setStatus("선택한 단계를 제거했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "단계 제거에 실패했습니다.");
    }
  }

  async function moveStep(blogId: number, stepId: number, direction: -1 | 1) {
    const currentSteps = workflowDrafts[blogId] ?? [];
    const index = currentSteps.findIndex((step) => step.id === stepId);
    const nextIndex = index + direction;
    if (index < 0 || nextIndex < 0 || nextIndex >= currentSteps.length) return;

    const ordered = [...currentSteps];
    const [moved] = ordered.splice(index, 1);
    ordered.splice(nextIndex, 0, moved);

    try {
      updateWorkflow(
        blogId,
        await requestJson<WorkflowStep[]>(`/blogs/${blogId}/workflow/reorder`, {
          method: "POST",
          body: JSON.stringify({ ordered_ids: ordered.map((step) => step.id) }),
        }),
      );
      setStatus("단계 순서를 저장했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "단계 순서 저장에 실패했습니다.");
    }
  }

  useEffect(() => {
    if (!selectedBlog || activeTab !== "monitoring" || overviewByBlog[selectedBlog.id] || overviewLoading[selectedBlog.id]) {
      return;
    }

    let ignore = false;
    setOverviewLoading((current) => ({ ...current, [selectedBlog.id]: true }));

    fetch(`${apiBase()}/google/blogs/${selectedBlog.id}/overview`)
      .then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        return response.json() as Promise<GoogleBlogOverview>;
      })
      .then((overview) => {
        if (!ignore) {
          setOverviewByBlog((current) => ({ ...current, [selectedBlog.id]: overview }));
        }
      })
      .catch((error) => {
        if (!ignore) {
          setOverviewError((current) => ({
            ...current,
            [selectedBlog.id]: error instanceof Error ? error.message : "모니터링 정보를 불러오지 못했습니다.",
          }));
        }
      })
      .finally(() => {
        if (!ignore) {
          setOverviewLoading((current) => ({ ...current, [selectedBlog.id]: false }));
        }
      });

    return () => {
      ignore = true;
    };
  }, [activeTab, overviewByBlog, overviewLoading, selectedBlog]);

  return (
    <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
      <Card className="h-fit">
        <CardHeader>
          <CardDescription>서비스 블로그</CardDescription>
          <CardTitle>Blogger에서 가져오기</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
            <p className="text-sm font-semibold text-ink">새 블로그 가져오기</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              실제 Blogger 블로그를 선택하면 초기 프로필과 워크플로가 자동으로 붙습니다.
            </p>
            <div className="mt-4 space-y-3">
              <div className="space-y-2">
                <Label htmlFor="import-blogger-blog">Blogger 블로그</Label>
                <select
                  id="import-blogger-blog"
                  className="flex h-11 w-full rounded-full border border-ink/10 bg-white px-4 text-sm text-ink outline-none"
                  value={importDraft.blogger_blog_id}
                  onChange={(event) => setImportDraft((current) => ({ ...current, blogger_blog_id: event.target.value }))}
                >
                  <option value="">가져올 Blogger 블로그 선택</option>
                  {importState.available_blogs.map((blog) => (
                    <option key={blog.id} value={blog.id}>
                      {blog.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="import-profile">초기 프로필</Label>
                <select
                  id="import-profile"
                  className="flex h-11 w-full rounded-full border border-ink/10 bg-white px-4 text-sm text-ink outline-none"
                  value={importDraft.profile_key}
                  onChange={(event) => setImportDraft((current) => ({ ...current, profile_key: event.target.value }))}
                >
                  {importState.profiles.map((profile) => (
                    <option key={profile.key} value={profile.key}>
                      {profile.label}
                    </option>
                  ))}
                </select>
              </div>

              <Button type="button" className="w-full" onClick={handleImport} disabled={!importDraft.blogger_blog_id || isPending}>
                Blogger 블로그 가져오기
              </Button>
            </div>

            {importState.warnings.length ? (
              <div className="mt-4 rounded-[20px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
                {importState.warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            ) : null}
          </div>

          <div className="space-y-2">
            {blogsState.length === 0 ? (
              <div className="rounded-[24px] border border-dashed border-ink/15 bg-white/50 px-4 py-5 text-sm text-slate-600">
                아직 가져온 서비스 블로그가 없습니다.
              </div>
            ) : (
              blogsState.map((blog) => {
                const selected = blog.id === selectedBlogId;
                return (
                  <button
                    key={blog.id}
                    type="button"
                    onClick={() => setSelectedBlogId(blog.id)}
                    className={`w-full rounded-[24px] border px-4 py-4 text-left transition ${
                      selected ? "border-ink bg-ink text-white" : "border-ink/10 bg-white/70 text-ink"
                    }`}
                  >
                    <p className="break-words font-semibold">{blog.name}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Badge className={selected ? "border-white/30 bg-white/10 text-white" : ""}>
                        {profileLabels[blog.profile_key] ?? blog.profile_key}
                      </Badge>
                      <Badge className={selected ? "border-white/30 bg-white/10 text-white" : "bg-transparent"}>
                        {blog.content_category}
                      </Badge>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="min-w-0">
        <CardHeader className="border-b border-ink/10 bg-white/70">
          {selectedBlog ? (
            <div className="space-y-3">
              <CardDescription>블로그 상세 설정</CardDescription>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                <div className="min-w-0">
                  <CardTitle className="break-words">{selectedBlog.name}</CardTitle>
                  <p className="mt-2 break-words text-sm leading-6 text-slate-600">
                    {selectedBlog.description || "설명을 적어두면 새 글 주제와 프롬프트 방향을 더 안정적으로 잡을 수 있습니다."}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge>{profileLabels[selectedBlog.profile_key] ?? selectedBlog.profile_key}</Badge>
                  <Badge className="bg-transparent">{selectedBlog.primary_language}</Badge>
                  <Badge className="bg-transparent">{selectedBlog.is_active ? "활성" : "비활성"}</Badge>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                {(Object.keys(tabLabels) as TabKey[]).map((tab) => (
                  <button key={tab} type="button" className={tabClass(activeTab === tab)} onClick={() => setActiveTab(tab)}>
                    {tabLabels[tab]}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              <CardDescription>블로그 상세 설정</CardDescription>
              <CardTitle>먼저 Blogger 블로그를 가져와 주세요</CardTitle>
            </>
          )}
        </CardHeader>

        <CardContent className="p-6">
          {!selectedBlog ? (
            <div className="rounded-[24px] border border-dashed border-ink/15 bg-white/50 px-4 py-8 text-sm text-slate-600">
              왼쪽에서 블로그를 가져오면 연결, 기본 정보, 파이프라인, 모니터링을 여기서 관리할 수 있습니다.
            </div>
          ) : null}

          {selectedBlog && activeTab === "connections" ? (
            <div className="space-y-6">
              <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
                  <p className="text-sm font-semibold text-ink">Blogger 원본 블로그</p>
                  <p className="mt-2 text-sm leading-6 text-slate-600">Blogger에서 가져온 실제 블로그 정보입니다.</p>
                  <div className="mt-4 space-y-3">
                    <DetailRow label="이름" value={selectedBlog.selected_connections.blogger?.name ?? selectedBlog.name} />
                    <DetailRow label="Blogger ID" value={selectedBlog.blogger_blog_id || "-"} mono />
                    <DetailRow label="주소" value={selectedBlog.blogger_url || selectedBlog.selected_connections.blogger?.url || "-"} mono />
                  </div>
                </div>

                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
                  <div className="space-y-2">
                    <Label htmlFor={`search-console-${selectedBlog.id}`}>Search Console 속성</Label>
                    <select
                      id={`search-console-${selectedBlog.id}`}
                      className="flex h-11 w-full rounded-full border border-ink/10 bg-white px-4 text-sm text-ink outline-none"
                      value={connectionDrafts[selectedBlog.id]?.search_console_site_url ?? ""}
                      onChange={(event) =>
                        setConnectionDrafts((current) => ({
                          ...current,
                          [selectedBlog.id]: {
                            ...current[selectedBlog.id],
                            search_console_site_url: event.target.value,
                          },
                        }))
                      }
                    >
                      <option value="">연결 안 함</option>
                      {bloggerConfig.search_console_sites.map((site) => (
                        <option key={site.site_url} value={site.site_url}>
                          {site.site_url}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="mt-4">
                    <DetailRow label="현재 선택" value={connectionDrafts[selectedBlog.id]?.search_console_site_url || "-"} mono />
                  </div>
                </div>

                <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
                  <div className="space-y-2">
                    <Label htmlFor={`ga4-${selectedBlog.id}`}>GA4 속성</Label>
                    <select
                      id={`ga4-${selectedBlog.id}`}
                      className="flex h-11 w-full rounded-full border border-ink/10 bg-white px-4 text-sm text-ink outline-none"
                      value={connectionDrafts[selectedBlog.id]?.ga4_property_id ?? ""}
                      onChange={(event) =>
                        setConnectionDrafts((current) => ({
                          ...current,
                          [selectedBlog.id]: {
                            ...current[selectedBlog.id],
                            ga4_property_id: event.target.value,
                          },
                        }))
                      }
                    >
                      <option value="">연결 안 함</option>
                      {bloggerConfig.analytics_properties.map((property) => (
                        <option key={property.property_id} value={property.property_id}>
                          {property.display_name} ({property.property_id})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="mt-4">
                    <DetailRow label="현재 선택" value={connectionDrafts[selectedBlog.id]?.ga4_property_id || "-"} mono />
                  </div>
                </div>
              </div>

              <Button type="button" onClick={() => saveConnections(selectedBlog)} disabled={isPending}>
                연결 정보 저장
              </Button>
            </div>
          ) : null}

          {selectedBlog && activeTab === "basic" ? (
            <div className="space-y-6">
              <div className="grid gap-5 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor={`blog-name-${selectedBlog.id}`}>블로그 이름</Label>
                  <Input
                    id={`blog-name-${selectedBlog.id}`}
                    value={basicDrafts[selectedBlog.id]?.name ?? ""}
                    onChange={(event) =>
                      setBasicDrafts((current) => ({
                        ...current,
                        [selectedBlog.id]: { ...current[selectedBlog.id], name: event.target.value },
                      }))
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={`category-${selectedBlog.id}`}>콘텐츠 카테고리</Label>
                  <Input
                    id={`category-${selectedBlog.id}`}
                    value={basicDrafts[selectedBlog.id]?.content_category ?? ""}
                    onChange={(event) =>
                      setBasicDrafts((current) => ({
                        ...current,
                        [selectedBlog.id]: { ...current[selectedBlog.id], content_category: event.target.value },
                      }))
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={`language-${selectedBlog.id}`}>주 언어</Label>
                  <Input
                    id={`language-${selectedBlog.id}`}
                    value={basicDrafts[selectedBlog.id]?.primary_language ?? ""}
                    onChange={(event) =>
                      setBasicDrafts((current) => ({
                        ...current,
                        [selectedBlog.id]: { ...current[selectedBlog.id], primary_language: event.target.value },
                      }))
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={`audience-${selectedBlog.id}`}>타깃 독자</Label>
                  <Input
                    id={`audience-${selectedBlog.id}`}
                    value={basicDrafts[selectedBlog.id]?.target_audience ?? ""}
                    onChange={(event) =>
                      setBasicDrafts((current) => ({
                        ...current,
                        [selectedBlog.id]: { ...current[selectedBlog.id], target_audience: event.target.value },
                      }))
                    }
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor={`description-${selectedBlog.id}`}>블로그 설명</Label>
                  <Textarea
                    id={`description-${selectedBlog.id}`}
                    className="min-h-[90px]"
                    value={basicDrafts[selectedBlog.id]?.description ?? ""}
                    onChange={(event) =>
                      setBasicDrafts((current) => ({
                        ...current,
                        [selectedBlog.id]: { ...current[selectedBlog.id], description: event.target.value },
                      }))
                    }
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor={`brief-${selectedBlog.id}`}>운영 브리프</Label>
                  <Textarea
                    id={`brief-${selectedBlog.id}`}
                    className="min-h-[180px]"
                    value={basicDrafts[selectedBlog.id]?.content_brief ?? ""}
                    onChange={(event) =>
                      setBasicDrafts((current) => ({
                        ...current,
                        [selectedBlog.id]: { ...current[selectedBlog.id], content_brief: event.target.value },
                      }))
                    }
                  />
                </div>
              </div>

              <label className="flex items-center gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={basicDrafts[selectedBlog.id]?.is_active ?? false}
                  onChange={(event) =>
                    setBasicDrafts((current) => ({
                      ...current,
                      [selectedBlog.id]: { ...current[selectedBlog.id], is_active: event.target.checked },
                    }))
                  }
                />
                자동 스케줄 대상에 포함
              </label>

              <Button type="button" onClick={() => saveBasic(selectedBlog)} disabled={isPending}>
                기본 정보 저장
              </Button>
            </div>
          ) : null}

          {selectedBlog && activeTab === "pipeline" ? (
            <div className="space-y-6">
              <div className="rounded-[24px] border border-ink/10 bg-mist px-4 py-4 text-sm leading-7 text-slate-700">
                번호가 붙은 순서대로 실제 파이프라인이 실행됩니다. 공개 게시 여부는 이 화면이 아니라{" "}
                <strong>생성 글 목록의 게시 버튼</strong>에서 직접 결정하는 방식으로 운영합니다.
              </div>

              <div className="space-y-4">
                {(workflowDrafts[selectedBlog.id] ?? []).map((step, index, steps) => (
                  <div key={step.id} className="rounded-[28px] border border-ink/10 bg-white/70 p-5">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                      <div className="space-y-2">
                        <p className="text-sm font-semibold text-ink">
                          {index + 1}. {stageLabels[step.stage_type]}
                        </p>
                        <div className="flex flex-wrap gap-2">
                          <Badge>{step.stage_type}</Badge>
                          <Badge className="bg-transparent">{step.provider_hint || "system"}</Badge>
                          {step.is_required ? <Badge className="bg-transparent">필수</Badge> : null}
                        </div>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        <Button type="button" variant="outline" onClick={() => moveStep(selectedBlog.id, step.id, -1)} disabled={index === 0}>
                          위로
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => moveStep(selectedBlog.id, step.id, 1)}
                          disabled={index === steps.length - 1}
                        >
                          아래로
                        </Button>
                        {step.removable ? (
                          <Button type="button" variant="outline" onClick={() => removeStep(selectedBlog.id, step.id)}>
                            제거
                          </Button>
                        ) : null}
                      </div>
                    </div>

                    {step.prompt_enabled ? (
                      <div className="mt-5 space-y-4">
                        <div className="space-y-2">
                          <Label htmlFor={`step-role-${step.id}`}>역할 / 페르소나</Label>
                          <Input
                            id={`step-role-${step.id}`}
                            value={step.role_name}
                            onChange={(event) => patchStep(selectedBlog.id, step.id, { role_name: event.target.value })}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor={`step-objective-${step.id}`}>단계 목적</Label>
                          <Textarea
                            id={`step-objective-${step.id}`}
                            className="min-h-[90px]"
                            value={step.objective ?? ""}
                            onChange={(event) => patchStep(selectedBlog.id, step.id, { objective: event.target.value })}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor={`step-prompt-${step.id}`}>프롬프트 본문</Label>
                          <Textarea
                            id={`step-prompt-${step.id}`}
                            className="min-h-[320px] font-mono text-[13px] leading-6"
                            value={step.prompt_template}
                            onChange={(event) => patchStep(selectedBlog.id, step.id, { prompt_template: event.target.value })}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor={`step-provider-${step.id}`}>Provider Hint</Label>
                          <Input
                            id={`step-provider-${step.id}`}
                            value={step.provider_hint ?? ""}
                            onChange={(event) => patchStep(selectedBlog.id, step.id, { provider_hint: event.target.value })}
                          />
                        </div>
                        <label className="flex items-center gap-3 text-sm text-slate-700">
                          <input
                            type="checkbox"
                            checked={step.is_enabled}
                            disabled={step.is_required}
                            onChange={(event) => patchStep(selectedBlog.id, step.id, { is_enabled: event.target.checked })}
                          />
                          단계 활성화
                        </label>
                      </div>
                    ) : (
                      <div className="mt-5 rounded-[24px] border border-ink/10 bg-mist px-4 py-4 text-sm leading-7 text-slate-700">
                        {stageDescriptions[step.stage_type] || step.objective || "이 단계는 시스템 로직으로 실행됩니다."}
                      </div>
                    )}

                    <div className="mt-5">
                      <Button type="button" onClick={() => saveStep(selectedBlog.id, step)} disabled={isPending}>
                        단계 저장
                      </Button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="rounded-[28px] border border-dashed border-ink/15 bg-white/60 p-5">
                <p className="text-sm font-semibold text-ink">선택 단계 추가</p>
                <div className="mt-4 flex flex-col gap-3 md:flex-row">
                  <select
                    className="flex h-11 flex-1 rounded-full border border-ink/10 bg-white px-4 text-sm text-ink outline-none"
                    value={newStageByBlog[selectedBlog.id] ?? ""}
                    onChange={(event) =>
                      setNewStageByBlog((current) => ({
                        ...current,
                        [selectedBlog.id]: event.target.value as WorkflowStageType | "",
                      }))
                    }
                  >
                    <option value="">추가할 단계 선택</option>
                    {missingStageOptions.map((stageType) => (
                      <option key={stageType} value={stageType}>
                        {stageLabels[stageType]}
                      </option>
                    ))}
                  </select>
                  <Button type="button" onClick={() => addStep(selectedBlog.id)} disabled={!newStageByBlog[selectedBlog.id]}>
                    + 단계 추가
                  </Button>
                </div>
              </div>
            </div>
          ) : null}

          {selectedBlog && activeTab === "monitoring" ? (
            <div className="space-y-6">
              {overviewLoading[selectedBlog.id] ? (
                <div className="rounded-[24px] border border-ink/10 bg-white/70 px-4 py-6 text-sm text-slate-600">
                  Google 모니터링 데이터를 불러오는 중입니다...
                </div>
              ) : overviewError[selectedBlog.id] ? (
                <div className="rounded-[24px] border border-rose-200 bg-rose-50 px-4 py-6 text-sm text-rose-900">
                  {overviewError[selectedBlog.id]}
                </div>
              ) : selectedOverview ? (
                <>
                  <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
                    <MetricTile
                      label="Blogger 7일"
                      value={formatNumber(selectedOverview.pageviews.find((item) => item.range === "7D")?.count)}
                    />
                    <MetricTile
                      label="Blogger 30일"
                      value={formatNumber(selectedOverview.pageviews.find((item) => item.range === "30D")?.count)}
                    />
                    <MetricTile label="SC 클릭" value={formatNumber(selectedOverview.search_console?.totals.clicks)} />
                    <MetricTile label="SC 노출" value={formatNumber(selectedOverview.search_console?.totals.impressions)} />
                    <MetricTile label="GA4 세션" value={formatNumber(selectedOverview.analytics?.totals.sessions)} />
                    <MetricTile
                      label="GA4 페이지뷰"
                      value={formatNumber(selectedOverview.analytics?.totals.screenPageViews)}
                    />
                  </div>

                  <div className="grid gap-4 xl:grid-cols-2">
                    <div className="rounded-[28px] border border-ink/10 bg-white/70 p-5">
                      <p className="text-sm font-semibold text-ink">최근 Blogger 글</p>
                      <div className="mt-4 space-y-3">
                        {selectedOverview.recent_posts.length ? (
                          selectedOverview.recent_posts.map((post) => (
                            <div key={post.id} className="rounded-[20px] border border-ink/10 px-4 py-3">
                              <p className="break-words font-medium text-ink">{post.title}</p>
                              <p className="mt-1 text-xs text-slate-500">{formatDate(post.updated || post.published)}</p>
                            </div>
                          ))
                        ) : (
                          <p className="text-sm text-slate-600">아직 표시할 Blogger 글 데이터가 없습니다.</p>
                        )}
                      </div>
                    </div>

                    <div className="rounded-[28px] border border-ink/10 bg-white/70 p-5">
                      <p className="text-sm font-semibold text-ink">검색어 / 페이지 상위</p>
                      <div className="mt-4 grid gap-4 lg:grid-cols-2">
                        <div className="space-y-3">
                          {(selectedOverview.search_console?.top_queries ?? []).slice(0, 5).map((row) => (
                            <div key={row.keys[0]} className="rounded-[20px] border border-ink/10 px-4 py-3">
                              <p className="break-words font-medium text-ink">{row.keys[0]}</p>
                              <p className="mt-1 text-xs text-slate-500">
                                클릭 {formatNumber(row.clicks)} / 노출 {formatNumber(row.impressions)}
                              </p>
                            </div>
                          ))}
                        </div>
                        <div className="space-y-3">
                          {(selectedOverview.analytics?.top_pages ?? []).slice(0, 5).map((page) => (
                            <div key={page.page_path} className="rounded-[20px] border border-ink/10 px-4 py-3">
                              <p className="break-all font-medium text-ink">{page.page_path || "/"}</p>
                              <p className="mt-1 text-xs text-slate-500">
                                페이지뷰 {formatNumber(page.screenPageViews)} / 세션 {formatNumber(page.sessions)}
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="rounded-[24px] border border-dashed border-ink/15 bg-white/50 px-4 py-8 text-sm text-slate-600">
                  연결된 Google 데이터가 아직 없습니다.
                </div>
              )}
            </div>
          ) : null}

          {status ? <p className="mt-6 text-sm text-slate-600">{status}</p> : null}
        </CardContent>
      </Card>
    </div>
  );
}

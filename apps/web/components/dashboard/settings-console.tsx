"use client";

import { type ReactNode, useEffect, useMemo, useRef, useState, useTransition } from "react";

import {
  createChannelPromptFlowStep,
  deleteChannelPromptFlowStep,
  getBlogArchive,
  getBlogs,
  getChannelPromptFlow,
  getChannels,
  getCloudflarePosts,
  getModelPolicy,
  reorderChannelPromptFlow,
  updateChannelPromptFlowStep,
  updateSettings,
} from "@/lib/api";
import type {
  Blog,
  BloggerConfigRead,
  ManagedChannelRead,
  ModelPolicyRead,
  PromptFlowRead,
  PromptFlowStepRead,
  SettingRead,
  WorkflowStageType,
} from "@/lib/types";

type SettingsConsoleProps = {
  settings: SettingRead[];
  config: BloggerConfigRead;
};

type SettingsTab = "workspace" | "channels" | "pipeline" | "models" | "planner" | "automation" | "publishing" | "integrations";

type PreviewItem = {
  id: string;
  title: string;
  url: string | null;
  publishedAt: string | null;
};

type StepDraft = {
  id: string;
  name: string;
  objective: string;
  promptTemplate: string;
  providerModel: string;
  isEnabled: boolean;
};

const TABS: Array<{ key: SettingsTab; label: string }> = [
  { key: "workspace", label: "기본 설정" },
  { key: "channels", label: "채널 관리" },
  { key: "pipeline", label: "프롬프트 플로우" },
  { key: "models", label: "모델" },
  { key: "planner", label: "플래너" },
  { key: "automation", label: "자동화" },
  { key: "publishing", label: "발행" },
  { key: "integrations", label: "연동 (TODO)" },
];

const STAGE_LABELS: Record<string, string> = {
  topic_discovery: "주제 발굴",
  article_generation: "글 작성",
  image_prompt_generation: "이미지 프롬프트",
  related_posts: "관련 글",
  image_generation: "이미지 생성",
  html_assembly: "HTML 조립",
  publishing: "발행",
};

const STAGE_ORDER: WorkflowStageType[] = [
  "topic_discovery",
  "article_generation",
  "image_prompt_generation",
  "related_posts",
  "image_generation",
  "html_assembly",
  "publishing",
];

const SETTING_GROUPS: Array<{ key: SettingsTab; items: (item: SettingRead) => boolean }> = [
  {
    key: "workspace",
    items: (item) =>
      !(
        item.key.startsWith("automation_") ||
        item.key.startsWith("cloudflare_") ||
        item.key.startsWith("google_") ||
        item.key.startsWith("blogger_") ||
        item.key.includes("model") ||
        item.key.startsWith("planner_") ||
        item.key.startsWith("publish_")
      ),
  },
  { key: "models", items: (item) => item.key.includes("model") },
  { key: "planner", items: (item) => item.key.startsWith("planner_") || item.key.startsWith("schedule_") || item.key.includes("category") },
  { key: "automation", items: (item) => item.key.startsWith("automation_") },
  { key: "publishing", items: (item) => item.key.startsWith("publish_") },
  {
    key: "integrations",
    items: (item) =>
      item.key.startsWith("cloudflare_") ||
      item.key.startsWith("google_") ||
      item.key.startsWith("blogger_") ||
      item.key.startsWith("telegram_") ||
      item.key.startsWith("openai_"),
  },
];

function sortSteps(steps: PromptFlowStepRead[]) {
  return [...steps].sort((a, b) => {
    const stageGap = STAGE_ORDER.indexOf(a.stageType as WorkflowStageType) - STAGE_ORDER.indexOf(b.stageType as WorkflowStageType);
    if (stageGap !== 0) {
      return stageGap;
    }
    return a.sortOrder - b.sortOrder;
  });
}

function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "미기록";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function prettifyKey(key: string) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase())
    .replace(/Openai/g, "OpenAI");
}

function isSecretKey(item: SettingRead) {
  return item.is_secret || /(secret|token|password|key)/i.test(item.key);
}

function buildDraft(step: PromptFlowStepRead): StepDraft {
  return {
    id: step.id,
    name: step.name,
    objective: step.objective ?? "",
    promptTemplate: step.promptTemplate,
    providerModel: step.providerModel ?? "",
    isEnabled: step.isEnabled,
  };
}

async function loadChannelPreviews(channelList: ManagedChannelRead[], blogList: Blog[]) {
  const previewMap: Record<string, PreviewItem[]> = {};

  const cloudflareChannel = channelList.find((item) => item.provider === "cloudflare");
  if (cloudflareChannel) {
    try {
      const items = await getCloudflarePosts();
      previewMap[cloudflareChannel.channelId] = items.slice(0, 3).map((item) => ({
        id: item.remote_id,
        title: item.title,
        url: item.published_url ?? null,
        publishedAt: item.published_at ?? null,
      }));
    } catch {
      previewMap[cloudflareChannel.channelId] = [];
    }
  }

  await Promise.all(
    channelList
      .filter((item) => item.provider === "blogger")
      .map(async (channel) => {
        const matchedBlog = blogList.find((blog) => blog.name === channel.name || blog.blogger_url === channel.baseUrl);
        if (!matchedBlog) {
          previewMap[channel.channelId] = [];
          return;
        }
        try {
          const page = await getBlogArchive(matchedBlog.id, 1, 3);
          previewMap[channel.channelId] = page.items.slice(0, 3).map((item) => ({
            id: item.id,
            title: item.title,
            url: item.published_url ?? null,
            publishedAt: item.published_at ?? null,
          }));
        } catch {
          previewMap[channel.channelId] = [];
        }
      }),
  );

  return previewMap;
}

export function SettingsConsole({ settings, config }: SettingsConsoleProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("workspace");
  const [localSettings, setLocalSettings] = useState<Record<string, string>>(() => Object.fromEntries(settings.map((item) => [item.key, item.value])));
  const [saveMessage, setSaveMessage] = useState("");
  const [channels, setChannels] = useState<ManagedChannelRead[]>([]);
  const [channelPreviews, setChannelPreviews] = useState<Record<string, PreviewItem[]>>({});
  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [selectedCloudflareCategory, setSelectedCloudflareCategory] = useState("");
  const [flow, setFlow] = useState<PromptFlowRead | null>(null);
  const [selectedStepId, setSelectedStepId] = useState("");
  const [draft, setDraft] = useState<StepDraft | null>(null);
  const [flowSaveState, setFlowSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [modelPolicy, setModelPolicy] = useState<ModelPolicyRead | null>(null);
  const [selectedStageType, setSelectedStageType] = useState<string>(STAGE_ORDER[0]);
  const [isPending, startTransition] = useTransition();
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let mounted = true;
    startTransition(() => {
      void Promise.all([getChannels(), getModelPolicy(), getBlogs()]).then(async ([channelList, policy, blogList]) => {
        if (!mounted) {
          return;
        }
        setChannels(channelList);
        setModelPolicy(policy);
        const defaultChannel = channelList.find((item) => item.promptFlowSupported) ?? channelList[0] ?? null;
        if (defaultChannel) {
          setSelectedChannelId((current) => current || defaultChannel.channelId);
        }
        const previews = await loadChannelPreviews(channelList, blogList);
        if (mounted) {
          setChannelPreviews(previews);
        }
      });
    });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedChannelId) {
      return;
    }
    let mounted = true;
    startTransition(() => {
      void getChannelPromptFlow(selectedChannelId).then((payload) => {
        if (!mounted) {
          return;
        }
        const ordered = sortSteps(payload.steps);
        setFlow({ ...payload, steps: ordered });
        setSelectedStageType(payload.availableStageTypes[0] ?? STAGE_ORDER[0]);
        if (payload.provider === "cloudflare") {
          const categories = Array.from(new Set(ordered.map((step) => step.id.split("::")[0]).filter(Boolean)));
          setSelectedCloudflareCategory((current) => (current && categories.includes(current) ? current : categories[0] ?? ""));
        } else {
          setSelectedCloudflareCategory("");
        }
      });
    });
    return () => {
      mounted = false;
    };
  }, [selectedChannelId]);

  const selectedChannel = useMemo(
    () => channels.find((item) => item.channelId === selectedChannelId) ?? channels[0] ?? null,
    [channels, selectedChannelId],
  );

  const availableModels = useMemo(() => {
    const values = new Set<string>();
    (modelPolicy?.large ?? []).forEach((item) => values.add(item));
    (modelPolicy?.small ?? []).forEach((item) => values.add(item));
    return Array.from(values);
  }, [modelPolicy]);

  const cloudflareCategories = useMemo(() => {
    if (!flow || flow.provider !== "cloudflare") {
      return [] as string[];
    }
    return Array.from(new Set(flow.steps.map((step) => step.id.split("::")[0]).filter(Boolean)));
  }, [flow]);

  const visibleSteps = useMemo(() => {
    if (!flow) {
      return [];
    }
    if (flow.provider !== "cloudflare") {
      return sortSteps(flow.steps);
    }
    return sortSteps(flow.steps).filter((step) => step.id.split("::")[0] === selectedCloudflareCategory);
  }, [flow, selectedCloudflareCategory]);

  useEffect(() => {
    if (!visibleSteps.length) {
      setSelectedStepId("");
      setDraft(null);
      return;
    }
    setSelectedStepId((current) => (current && visibleSteps.some((step) => step.id === current) ? current : visibleSteps[0].id));
  }, [visibleSteps]);

  const selectedStep = useMemo(() => visibleSteps.find((item) => item.id === selectedStepId) ?? null, [selectedStepId, visibleSteps]);

  useEffect(() => {
    if (!selectedStep) {
      setDraft(null);
      return;
    }
    setDraft(buildDraft(selectedStep));
  }, [selectedStep]);

  useEffect(() => {
    return () => {
      if (saveTimer.current) {
        clearTimeout(saveTimer.current);
      }
    };
  }, []);

  const groupedSettings = useMemo(
    () =>
      SETTING_GROUPS.map((group) => ({
        key: group.key,
        items: settings.filter(group.items),
      })).filter((group) => group.items.length > 0),
    [settings],
  );

  function handleSettingChange(key: string, value: string) {
    setLocalSettings((current) => ({ ...current, [key]: value }));
  }

  async function handleSaveSettings(keys: string[]) {
    const payload = Object.fromEntries(keys.map((key) => [key, localSettings[key] ?? ""]));
    await updateSettings(payload);
    setSaveMessage("설정이 저장되었습니다.");
    window.setTimeout(() => setSaveMessage(""), 1600);
  }

  async function applyFlowUpdate(patch: Partial<StepDraft>, immediate = false) {
    if (!selectedStep || !draft || !selectedChannel) {
      return;
    }
    const nextDraft = { ...draft, ...patch };
    setDraft(nextDraft);
    setFlow((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        steps: current.steps.map((step) =>
          step.id === selectedStep.id
            ? {
                ...step,
                name: nextDraft.name,
                objective: nextDraft.objective,
                promptTemplate: nextDraft.promptTemplate,
                providerModel: nextDraft.providerModel || null,
                isEnabled: nextDraft.isEnabled,
              }
            : step,
        ),
      };
    });

    const submit = async () => {
      setFlowSaveState("saving");
      try {
        const updated = await updateChannelPromptFlowStep(selectedChannel.channelId, selectedStep.id, {
          name: nextDraft.name,
          objective: nextDraft.objective,
          prompt_template: nextDraft.promptTemplate,
          provider_model: nextDraft.providerModel || null,
          is_enabled: nextDraft.isEnabled,
        });
        setFlow({ ...updated, steps: sortSteps(updated.steps) });
        setFlowSaveState("saved");
        window.setTimeout(() => setFlowSaveState("idle"), 1200);
      } catch {
        setFlowSaveState("error");
      }
    };

    if (saveTimer.current) {
      clearTimeout(saveTimer.current);
    }
    if (immediate) {
      await submit();
      return;
    }
    saveTimer.current = setTimeout(() => {
      void submit();
    }, 700);
  }

  async function handleMoveStep(stepId: string, direction: "left" | "right") {
    if (!flow?.structureEditable || !selectedChannel) {
      return;
    }
    const ordered = sortSteps(flow.steps);
    const index = ordered.findIndex((step) => step.id === stepId);
    if (index < 0) {
      return;
    }
    const targetIndex = direction === "left" ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= ordered.length) {
      return;
    }
    const next = [...ordered];
    const [moved] = next.splice(index, 1);
    next.splice(targetIndex, 0, moved);
    const updated = await reorderChannelPromptFlow(selectedChannel.channelId, next.map((step) => step.id));
    setFlow({ ...updated, steps: sortSteps(updated.steps) });
  }

  async function handleAddStep() {
    if (!flow?.structureEditable || !selectedChannel || !selectedStageType) {
      return;
    }
    const updated = await createChannelPromptFlowStep(selectedChannel.channelId, selectedStageType);
    setFlow({ ...updated, steps: sortSteps(updated.steps) });
  }

  async function handleRemoveStep(step: PromptFlowStepRead) {
    if (!step.removable || !selectedChannel) {
      return;
    }
    const updated = await deleteChannelPromptFlowStep(selectedChannel.channelId, step.id);
    setFlow({ ...updated, steps: sortSteps(updated.steps) });
  }

  return (
    <div className="space-y-5">
      <section className="rounded-[28px] border border-slate-200 bg-white px-5 py-5 shadow-sm lg:px-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Settings Workspace</p>
            <h2 className="text-[28px] font-semibold tracking-tight text-slate-950">설정 콘솔</h2>
            <p className="max-w-3xl text-sm leading-6 text-slate-600">운영 설정, 채널 관리, 프롬프트 파이프라인을 한 화면에서 편집합니다. 긴 텍스트는 블록 안에서 펼치지 않고, 상세 편집기는 아래에서만 엽니다.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <GuideStep number="01" title="일간 기준 운영" description="기준값은 일간 운영 데이터로 저장합니다." />
            <GuideStep number="02" title="채널별 파이프라인" description="블로그·Cloudflare별 단계를 따로 관리합니다." />
            <GuideStep number="03" title="월간 공유 반영" description="설정 변경은 계획·분석 화면에 바로 공유됩니다." />
          </div>
        </div>
      </section>

      <div className="flex flex-wrap gap-2">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={[
              "rounded-full px-4 py-2 text-sm font-medium transition",
              activeTab === tab.key ? "bg-slate-950 text-white shadow-sm" : "bg-white text-slate-600 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50 hover:text-slate-900",
            ].join(" ")}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "channels" ? (
        <section className="grid gap-4 xl:grid-cols-3">
          {channels.map((channel) => {
            const previews = channelPreviews[channel.channelId] ?? [];
            return (
              <article key={channel.channelId} className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <FlagPill tone="slate">{channel.provider === "cloudflare" ? "Cloudflare" : "Blogger"}</FlagPill>
                      <FlagPill tone={channel.status === "connected" ? "emerald" : "amber"}>{channel.status || "확인 필요"}</FlagPill>
                      <FlagPill tone={channel.plannerSupported ? "indigo" : "slate"}>{channel.plannerSupported ? "계획 지원" : "계획 미지원"}</FlagPill>
                    </div>
                    <h3 className="line-clamp-2 text-lg font-semibold text-slate-950">{channel.name}</h3>
                    <p className="truncate text-sm text-slate-500">{channel.baseUrl || "기본 URL 미설정"}</p>
                  </div>
                  <div className="grid shrink-0 grid-cols-3 gap-2 text-center">
                    <StatTile label="게시글" value={String(channel.postsCount)} />
                    <StatTile label="카테고리" value={String(channel.categoriesCount)} />
                    <StatTile label="프롬프트" value={String(channel.promptsCount)} />
                  </div>
                </div>
                <div className="mt-4 grid gap-2 text-sm text-slate-600">
                  <InfoRow label="대표 카테고리" value={channel.primaryCategory || "미설정"} />
                  <InfoRow label="운영 목적" value={channel.purpose || "설명 없음"} />
                  <InfoRow label="분석 포함" value={channel.analyticsSupported ? "예" : "아니오"} />
                </div>
                <div className="mt-5 border-t border-slate-200 pt-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-slate-900">최근 게시글</h4>
                    <span className="text-xs text-slate-400">최대 3건</span>
                  </div>
                  <div className="space-y-2">
                    {previews.length ? (
                      previews.map((item) => (
                        <div key={item.id} className="rounded-2xl bg-slate-50 px-3 py-3">
                          <p className="line-clamp-2 text-sm font-medium text-slate-900">{item.title}</p>
                          <div className="mt-1 flex items-center justify-between gap-2 text-xs text-slate-500">
                            <span className="truncate">{item.url || "URL 없음"}</span>
                            <span className="shrink-0">{formatDateTime(item.publishedAt)}</span>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-5 text-sm text-slate-500">최근 게시글을 불러오지 못했습니다.</div>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </section>
      ) : null}

      {activeTab === "pipeline" && selectedChannel ? (
        <section className="space-y-4 rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm lg:p-6">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="grid gap-3 lg:grid-cols-[minmax(240px,300px)_minmax(220px,260px)_minmax(0,1fr)]">
              <SelectField label="관리 채널" value={selectedChannel.channelId} onChange={setSelectedChannelId}>
                {channels.filter((item) => item.promptFlowSupported).map((item) => (
                  <option key={item.channelId} value={item.channelId}>
                    {item.name}
                  </option>
                ))}
              </SelectField>
              {flow?.provider === "cloudflare" ? (
                <SelectField label="카테고리" value={selectedCloudflareCategory} onChange={setSelectedCloudflareCategory}>
                  {cloudflareCategories.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </SelectField>
              ) : (
                <ReadonlyField label="편집 범위" value="전체 블로그 파이프라인" />
              )}
              <div className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
                <p className="font-semibold text-slate-900">가로형 파이프라인</p>
                <p className="mt-1 leading-6">블록 안에는 단계 요약만 표시합니다. 본문과 세부 설정은 아래 편집기에서 수정됩니다.</p>
              </div>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              {flow?.structureEditable ? (
                <>
                  <SelectField label="단계 추가" value={selectedStageType} onChange={setSelectedStageType}>
                    {(flow.availableStageTypes.length ? flow.availableStageTypes : STAGE_ORDER).map((stage) => (
                      <option key={stage} value={stage}>
                        {STAGE_LABELS[stage] ?? stage}
                      </option>
                    ))}
                  </SelectField>
                  <button
                    type="button"
                    onClick={() => void handleAddStep()}
                    className="rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
                  >
                    단계 추가
                  </button>
                </>
              ) : (
                <FlagPill tone="slate">구조 고정 채널</FlagPill>
              )}
            </div>
          </div>

          <div className="overflow-x-auto pb-2">
            <div className="flex min-w-max items-stretch gap-4 pr-4">
              {visibleSteps.map((step, index) => {
                const active = step.id === selectedStepId;
                return (
                  <div key={step.id} className="flex items-center gap-4">
                    <button
                      type="button"
                      onClick={() => setSelectedStepId(step.id)}
                      className={[
                        "w-[248px] rounded-[24px] border p-4 text-left shadow-sm transition",
                        active ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white text-slate-900 hover:border-slate-300",
                      ].join(" ")}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 space-y-2">
                          <div className="flex flex-wrap items-center gap-2 text-[11px] font-medium">
                            <span className={active ? "text-slate-300" : "text-slate-500"}>{String(index + 1).padStart(2, "0")}</span>
                            <FlagPill tone={step.isRequired ? (active ? "dark" : "indigo") : active ? "dark" : "slate"}>{step.isRequired ? "필수" : "선택"}</FlagPill>
                            <FlagPill tone={step.isEnabled ? (active ? "dark" : "emerald") : active ? "dark" : "amber"}>{step.isEnabled ? "사용" : "중지"}</FlagPill>
                          </div>
                          <p className={active ? "text-xs text-slate-300" : "text-xs text-slate-500"}>{STAGE_LABELS[step.stageType] ?? step.stageLabel}</p>
                          <h3 className="line-clamp-2 text-sm font-semibold leading-6">{step.name}</h3>
                          <p className={active ? "line-clamp-1 text-xs text-slate-300" : "line-clamp-1 text-xs text-slate-500"}>{step.providerModel || "기본값 상속"}</p>
                          <p className={active ? "line-clamp-2 text-xs text-slate-300" : "line-clamp-2 text-xs text-slate-500"}>{step.objective || "목적 미설정"}</p>
                        </div>
                        {flow?.structureEditable ? (
                          <div className="flex shrink-0 flex-col gap-2">
                            <button type="button" className={blockActionClass(active)} onClick={(event) => { event.stopPropagation(); void handleMoveStep(step.id, "left"); }}>←</button>
                            <button type="button" className={blockActionClass(active)} onClick={(event) => { event.stopPropagation(); void handleMoveStep(step.id, "right"); }}>→</button>
                            {step.removable ? (
                              <button type="button" className={blockActionClass(active)} onClick={(event) => { event.stopPropagation(); void handleRemoveStep(step); }}>삭제</button>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    </button>
                    {index < visibleSteps.length - 1 ? <div className="text-slate-300">→</div> : null}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4 lg:p-5">
            {selectedStep && draft ? (
              <div className="space-y-5">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">선택 단계 편집기</p>
                    <h3 className="mt-1 text-xl font-semibold text-slate-950">{STAGE_LABELS[selectedStep.stageType] ?? selectedStep.stageLabel}</h3>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <FlagPill tone="slate">{selectedChannel.name}</FlagPill>
                    <FlagPill tone={flowSaveState === "error" ? "amber" : flowSaveState === "saved" ? "emerald" : "slate"}>
                      {flowSaveState === "saving" ? "저장 중" : flowSaveState === "saved" ? "저장 완료" : flowSaveState === "error" ? "저장 실패" : "자동 저장"}
                    </FlagPill>
                  </div>
                </div>

                <div className="grid gap-4 xl:grid-cols-2">
                  <FieldGroup label="단계 제목">
                    <input value={draft.name} onChange={(event) => void applyFlowUpdate({ name: event.target.value })} className={inputClass()} />
                  </FieldGroup>
                  <FieldGroup label="모델 선택">
                    <select value={draft.providerModel} onChange={(event) => void applyFlowUpdate({ providerModel: event.target.value }, true)} className={inputClass()}>
                      <option value="">기본값 상속</option>
                      {availableModels.map((model) => (
                        <option key={model} value={model}>
                          {model}
                        </option>
                      ))}
                    </select>
                  </FieldGroup>
                  <FieldGroup label="목적 / 설명" className="xl:col-span-2">
                    <textarea value={draft.objective} onChange={(event) => void applyFlowUpdate({ objective: event.target.value })} rows={2} className={textareaClass("min-h-[92px]")} />
                  </FieldGroup>
                  <FieldGroup label="사용 상태">
                    <label className="flex h-[44px] items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-700">
                      <input type="checkbox" checked={draft.isEnabled} onChange={(event) => void applyFlowUpdate({ isEnabled: event.target.checked }, true)} />
                      현재 단계 사용
                    </label>
                  </FieldGroup>
                  <ReadonlyField label="구조 변경 가능" value={selectedStep.structureEditable ? "예" : "아니오"} />
                  <FieldGroup label="프롬프트 본문" className="xl:col-span-2">
                    <textarea value={draft.promptTemplate} onChange={(event) => void applyFlowUpdate({ promptTemplate: event.target.value })} rows={14} className={textareaClass("min-h-[320px]")} />
                  </FieldGroup>
                </div>
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-12 text-center text-sm text-slate-500">편집할 단계를 선택하세요.</div>
            )}
          </div>
        </section>
      ) : null}

      {activeTab !== "channels" && activeTab !== "pipeline" ? (
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm lg:p-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-xl font-semibold text-slate-950">{TABS.find((item) => item.key === activeTab)?.label}</h3>
                <p className="mt-1 text-sm text-slate-500">내부 키 대신 읽을 수 있는 한글 중심으로 정리했습니다.</p>
              </div>
              <button
                type="button"
                onClick={() => void handleSaveSettings((groupedSettings.find((group) => group.key === activeTab)?.items ?? []).map((item) => item.key))}
                className="rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
              >
                설정 저장
              </button>
            </div>
            <div className="mt-5 grid gap-4 xl:grid-cols-2">
              {(groupedSettings.find((group) => group.key === activeTab)?.items ?? []).map((item) => (
                <div key={item.key} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="line-clamp-2 text-sm font-semibold text-slate-900">{prettifyKey(item.key)}</p>
                      <p className="mt-1 text-xs text-slate-500">{item.description || item.key}</p>
                    </div>
                    {isSecretKey(item) ? <FlagPill tone="amber">보호됨</FlagPill> : null}
                  </div>
                  {isSecretKey(item) ? (
                    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500">읽기 전용 보안 항목</div>
                  ) : (
                    <textarea
                      value={localSettings[item.key] ?? ""}
                      onChange={(event) => handleSettingChange(item.key, event.target.value)}
                      rows={4}
                      className={textareaClass("min-h-[112px]")}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
          <aside className="space-y-4 rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">운영 메모</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">자동화는 기본값 OFF로 유지합니다. 인증·비밀값은 읽기 전용으로 두고, 기능 구조와 프롬프트 흐름을 먼저 안정화합니다.</p>
            </div>
            <InfoRow label="Blogger 연결 블로그" value={String(config.blogs.length)} />
            <InfoRow label="OAuth 연결 상태" value={config.connected ? "연결됨" : "확인 필요"} />
            <InfoRow label="저장 상태" value={saveMessage || "대기"} />
          </aside>
        </section>
      ) : null}

      {isPending ? <div className="text-xs text-slate-400">데이터를 불러오는 중입니다.</div> : null}
    </div>
  );
}

function GuideStep({ number, title, description }: { number: string; title: string; description: string }) {
  return (
    <div className="rounded-[22px] bg-slate-50 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">{number}</p>
      <p className="mt-1 text-sm font-semibold text-slate-900">{title}</p>
      <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-slate-50 px-3 py-2">
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-slate-900">{value}</p>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-dashed border-slate-200 pb-2 text-sm last:border-none last:pb-0">
      <span className="shrink-0 text-slate-500">{label}</span>
      <span className="min-w-0 text-right text-slate-900">{value}</span>
    </div>
  );
}

function FieldGroup({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <div className={className}>
      <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</label>
      {children}
    </div>
  );
}

function ReadonlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</label>
      <div className="flex h-[44px] items-center rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-700">{value}</div>
    </div>
  );
}

function SelectField({ label, value, onChange, children }: { label: string; value: string; onChange: (value: string) => void; children: ReactNode }) {
  return (
    <div>
      <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</label>
      <select value={value} onChange={(event) => onChange(event.target.value)} className={inputClass()}>
        {children}
      </select>
    </div>
  );
}

function FlagPill({ children, tone }: { children: ReactNode; tone: "slate" | "emerald" | "amber" | "indigo" | "dark" }) {
  const toneClass = {
    slate: "bg-slate-100 text-slate-600",
    emerald: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100 text-amber-700",
    indigo: "bg-indigo-100 text-indigo-700",
    dark: "bg-white/15 text-white",
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold ${toneClass}`}>{children}</span>;
}

function inputClass() {
  return "h-[44px] w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200";
}

function textareaClass(extra: string) {
  return `w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 ${extra}`;
}

function blockActionClass(active: boolean) {
  return [
    "rounded-full px-2.5 py-1 text-[11px] font-medium transition",
    active ? "bg-white/15 text-white hover:bg-white/20" : "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900",
  ].join(" ");
}



"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  createChannelPromptFlowStep,
  deleteChannelPromptFlowStep,
  getChannelPromptFlow,
  getChannels,
  getCloudflarePosts,
  getModelPolicy,
  getSyncedBloggerPosts,
  reorderChannelPromptFlow,
  updateChannelPromptFlowStep,
  updateSettings,
} from "@/lib/api";
import type {
  BloggerConfigRead,
  ManagedChannelRead,
  ModelPolicyRead,
  PromptFlowRead,
  PromptFlowStepRead,
  SettingRead,
} from "@/lib/types";

type SettingsConsoleProps = {
  settings: SettingRead[];
  config: BloggerConfigRead;
};

const TABS = ["기본 설정", "채널 관리", "프롬프트 플로우", "모델", "플래너", "자동화", "발행", "연동 (TODO)"] as const;
type TabName = (typeof TABS)[number];

type FieldConfig = {
  label: string;
  description: string;
  type?: "text" | "select" | "time" | "number" | "boolean";
  options?: Array<{ label: string; value: string }>;
};

const SECTION_FIELDS: Record<Exclude<TabName, "채널 관리" | "프롬프트 플로우" | "연동 (TODO)">, Record<string, FieldConfig>> = {
  "기본 설정": {
    app_name: { label: "서비스 이름", description: "운영 콘솔과 기본 메타데이터에 표시되는 서비스 이름입니다." },
    default_blog_timezone: { label: "기본 시간대", description: "블로그 일정과 예약 기준 시간대입니다." },
  },
  모델: {
    openai_text_model: { label: "기본 텍스트 모델", description: "공통 텍스트 생성에 사용하는 기본 모델입니다.", type: "select" },
    topic_discovery_model: { label: "주제 발굴 모델", description: "주제 발굴 단계에 사용하는 모델입니다.", type: "select" },
    article_generation_model: { label: "글 작성 모델", description: "본문 작성 단계에 사용하는 모델입니다.", type: "select" },
  },
  플래너: {
    planner_default_daily_posts: { label: "일일 기본 슬롯 수", description: "월간 계획 생성 시 하루에 배치할 기본 슬롯 수입니다.", type: "number" },
    planner_day_start_time: { label: "일정 시작 시각", description: "플래너 자동 배치가 시작되는 기준 시각입니다.", type: "time" },
    planner_day_end_time: { label: "일정 종료 시각", description: "플래너 자동 배치가 끝나는 기준 시각입니다.", type: "time" },
  },
  자동화: {
    automation_master_enabled: { label: "전체 자동화", description: "전체 자동화 마스터 스위치입니다.", type: "boolean" },
    automation_scheduler_enabled: { label: "스케줄러", description: "예약 실행 스케줄러를 켭니다.", type: "boolean" },
    automation_publish_queue_enabled: { label: "발행 큐", description: "발행 큐 자동 처리를 켭니다.", type: "boolean" },
    automation_content_review_enabled: { label: "콘텐츠 검토", description: "품질 점검 자동화를 켭니다.", type: "boolean" },
    automation_telegram_enabled: { label: "텔레그램 알림", description: "텔레그램 폴링/알림을 켭니다.", type: "boolean" },
    automation_sheet_enabled: { label: "시트 동기화", description: "구글 시트 동기화 자동화를 켭니다.", type: "boolean" },
    automation_cloudflare_enabled: { label: "Cloudflare 채널", description: "Cloudflare 채널 생성 자동화를 켭니다.", type: "boolean" },
    automation_training_enabled: { label: "학습 작업", description: "학습/재학습 자동화를 켭니다.", type: "boolean" },
  },
  발행: {
    default_publish_mode: {
      label: "기본 발행 모드",
      description: "글 발행 시 사용할 기본 모드입니다.",
      type: "select",
      options: [
        { label: "임시 저장", value: "draft" },
        { label: "즉시 발행", value: "publish" },
      ],
    },
    default_writer_tone: { label: "기본 문체", description: "글 작성 시 기본으로 적용할 문체 설명입니다." },
  },
};

const STAGE_LABELS: Record<string, string> = {
  topic_discovery: "주제 발굴",
  article_generation: "글 작성",
  image_prompt_generation: "이미지 프롬프트",
  related_posts: "관련 글 연결",
  image_generation: "이미지 생성",
  html_assembly: "HTML 조립",
  publishing: "발행",
};

export function SettingsConsole({ settings, config }: SettingsConsoleProps) {
  const [activeTab, setActiveTab] = useState<TabName>("기본 설정");
  const [draft, setDraft] = useState<Record<string, string>>(() => Object.fromEntries(settings.map((item) => [item.key, item.value])));
  const [modelPolicy, setModelPolicy] = useState<ModelPolicyRead | null>(null);
  const [channels, setChannels] = useState<ManagedChannelRead[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null);
  const [promptFlow, setPromptFlow] = useState<PromptFlowRead | null>(null);
  const [settingsNotice, setSettingsNotice] = useState<string>("");
  const [flowNotice, setFlowNotice] = useState<string>("");
  const [newStageType, setNewStageType] = useState<string>("");
  const [channelPreviews, setChannelPreviews] = useState<Record<string, Array<{ title: string; url: string | null; meta: string }>>>({});
  const saveTimersRef = useRef<Record<string, number>>({});
  const flowRef = useRef<PromptFlowRead | null>(null);

  useEffect(() => {
    flowRef.current = promptFlow;
  }, [promptFlow]);

  useEffect(() => {
    void Promise.all([getModelPolicy(), getChannels()])
      .then(([policy, channelList]) => {
        setModelPolicy(policy);
        setChannels(channelList);
        const preferred = channelList.find((item) => item.promptFlowSupported)?.channelId ?? channelList[0]?.channelId ?? null;
        setSelectedChannelId((current) => current ?? preferred);
      })
      .catch(console.error);
  }, []);

  useEffect(() => {
    if (!selectedChannelId) return;
    void loadPromptFlow(selectedChannelId);
  }, [selectedChannelId]);

  useEffect(() => {
    if (activeTab !== "채널 관리" || channels.length === 0) return;
    const missing = channels.filter((channel) => !channelPreviews[channel.channelId]);
    if (missing.length === 0) return;
    void Promise.all(
      missing.map(async (channel) => {
        if (channel.provider === "blogger") {
          const blogId = Number(channel.channelId.split(":")[1]);
          const page = await getSyncedBloggerPosts(blogId, 1, 3);
          return [
            channel.channelId,
            (page.items ?? []).slice(0, 3).map((item) => ({
              title: item.title,
              url: item.url ?? null,
              meta: `${item.published ?? "발행일 없음"} · ${item.status ?? "상태 없음"}`,
            })),
          ] as const;
        }
        const posts = await getCloudflarePosts();
        return [
          channel.channelId,
          (posts ?? []).slice(0, 3).map((item: any) => ({
            title: item.title,
            url: item.published_url ?? null,
            meta: `${item.category_slug ?? "카테고리 없음"} · ${item.status ?? "상태 없음"}`,
          })),
        ] as const;
      }),
    )
      .then((entries) => {
        setChannelPreviews((current) => ({
          ...current,
          ...Object.fromEntries(entries),
        }));
      })
      .catch(console.error);
  }, [activeTab, channelPreviews, channels]);

  const selectedChannel = useMemo(
    () => channels.find((channel) => channel.channelId === selectedChannelId) ?? null,
    [channels, selectedChannelId],
  );

  const groupedCloudflareSteps = useMemo(() => {
    if (promptFlow?.provider !== "cloudflare") return [] as Array<{ categoryName: string; steps: PromptFlowStepRead[] }>;
    const map = new Map<string, PromptFlowStepRead[]>();
    for (const step of promptFlow.steps) {
      const categoryName = step.name.split(" · ")[0] || step.name;
      const current = map.get(categoryName) ?? [];
      current.push(step);
      map.set(categoryName, current);
    }
    return [...map.entries()].map(([categoryName, steps]) => ({
      categoryName,
      steps: steps.slice().sort((left, right) => left.sortOrder - right.sortOrder),
    }));
  }, [promptFlow]);

  async function loadPromptFlow(channelId: string) {
    try {
      const payload = await getChannelPromptFlow(channelId);
      setPromptFlow(payload);
      setNewStageType(payload.availableStageTypes[0] ?? "");
      setFlowNotice("");
    } catch (error) {
      console.error(error);
      setFlowNotice("프롬프트 플로우를 불러오지 못했습니다.");
    }
  }

  async function saveSettings(keys: string[]) {
    const payload = Object.fromEntries(keys.map((key) => [key, draft[key] ?? ""]));
    await updateSettings(payload);
    setSettingsNotice("현재 탭 설정을 저장했습니다.");
  }

  function scheduleStepSave(stepId: string, patch: Partial<PromptFlowStepRead>) {
    setPromptFlow((current) => {
      if (!current) return current;
      return {
        ...current,
        steps: current.steps.map((step) => (step.id === stepId ? { ...step, ...patch } : step)),
      };
    });
    setFlowNotice("입력 내용을 저장 중입니다...");
    const existing = saveTimersRef.current[stepId];
    if (existing) {
      window.clearTimeout(existing);
    }
    saveTimersRef.current[stepId] = window.setTimeout(async () => {
      const currentFlow = flowRef.current;
      const currentStep = currentFlow?.steps.find((step) => step.id === stepId);
      if (!currentFlow || !currentStep || !selectedChannelId) return;
      try {
        const next = await updateChannelPromptFlowStep(
          selectedChannelId,
          stepId,
          currentFlow.provider === "cloudflare"
            ? { prompt_template: currentStep.promptTemplate }
            : {
                name: currentStep.name,
                role_name: currentStep.roleName ?? "담당 단계",
                objective: currentStep.objective,
                prompt_template: currentStep.promptTemplate,
                provider_hint: currentStep.providerHint,
                provider_model: currentStep.providerModel,
                is_enabled: currentStep.isEnabled,
              },
        );
        setPromptFlow(next);
        setFlowNotice("프롬프트 플로우를 저장했습니다.");
      } catch (error) {
        console.error(error);
        setFlowNotice("프롬프트 저장에 실패했습니다.");
      }
    }, 700);
  }

  async function moveStep(stepId: string, direction: -1 | 1) {
    if (!promptFlow?.structureEditable || !selectedChannelId) return;
    const steps = [...promptFlow.steps];
    const index = steps.findIndex((step) => step.id === stepId);
    const nextIndex = index + direction;
    if (index < 0 || nextIndex < 0 || nextIndex >= steps.length) return;
    const [item] = steps.splice(index, 1);
    steps.splice(nextIndex, 0, item);
    try {
      const next = await reorderChannelPromptFlow(selectedChannelId, steps.map((step) => step.id));
      setPromptFlow(next);
      setFlowNotice("단계 순서를 반영했습니다.");
    } catch (error) {
      console.error(error);
      setFlowNotice("단계 순서 저장에 실패했습니다.");
    }
  }

  async function addStep() {
    if (!selectedChannelId || !newStageType) return;
    try {
      const next = await createChannelPromptFlowStep(selectedChannelId, newStageType);
      setPromptFlow(next);
      setNewStageType(next.availableStageTypes[0] ?? "");
      setFlowNotice("단계를 추가했습니다.");
    } catch (error) {
      console.error(error);
      setFlowNotice("단계 추가에 실패했습니다.");
    }
  }

  async function removeStep(stepId: string) {
    if (!selectedChannelId) return;
    try {
      const next = await deleteChannelPromptFlowStep(selectedChannelId, stepId);
      setPromptFlow(next);
      setFlowNotice("단계를 제거했습니다.");
    } catch (error) {
      console.error(error);
      setFlowNotice("단계 제거에 실패했습니다.");
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="rounded-[28px] border border-slate-200 bg-white p-4 shadow-sm">
        <p className="px-3 pb-4 text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">설정 메뉴</p>
        <nav className="space-y-2">
          {TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`w-full rounded-2xl px-4 py-3 text-left text-sm font-medium transition ${
                activeTab === tab ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              }`}
            >
              {tab}
            </button>
          ))}
        </nav>
      </aside>

      <section className="space-y-6 rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-indigo-500">설정 콘솔</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">{activeTab}</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
              설정도 같은 운영 기준을 공유합니다. 일간 계획에서 쓰는 기준값이 주간/월간 보기와 분석 리포트까지 이어지도록 관리합니다.
            </p>
          </div>
          {settingsNotice ? <p className="text-sm text-indigo-600">{settingsNotice}</p> : null}
        </div>

        <div className="grid gap-4 lg:grid-cols-[1fr_auto_1fr_auto_1fr]">
          <article className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">1. 일간 운영 기준</p>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              모델, 자동화, 프롬프트 흐름, 카테고리 운영값을 일간 생산 기준으로 맞춥니다.
            </p>
          </article>
          <div className="hidden items-center justify-center lg:flex">
            <div className="h-px w-full bg-slate-200" />
          </div>
          <article className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">2. 주간·월간 공유</p>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              설정값 하나를 바꾸면 플래너의 주간/월간 보기와 분석 기준에 같은 규칙이 반영됩니다.
            </p>
          </article>
          <div className="hidden items-center justify-center lg:flex">
            <div className="h-px w-full bg-slate-200" />
          </div>
          <article className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">3. 채널별 적용</p>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              관리 채널, 프롬프트 플로우, 발행 정책을 같은 운영 구조 안에서 채널별로 나눠서 적용합니다.
            </p>
          </article>
        </div>

        {activeTab === "채널 관리" ? (
          <div className="space-y-5">
            <div className="grid gap-4 xl:grid-cols-3">
              {channels.map((channel) => (
                <article key={channel.channelId} className="rounded-[24px] border border-slate-200 bg-slate-50 p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">{channel.provider}</p>
                      <h2 className="mt-2 text-lg font-semibold text-slate-900">{channel.name}</h2>
                    </div>
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${channel.status === "connected" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
                      {channel.status === "connected" ? "연결됨" : channel.status}
                    </span>
                  </div>
                  <div className="mt-4 grid gap-3 text-sm text-slate-600">
                    <InfoRow label="기본 URL" value={channel.baseUrl ?? "미설정"} />
                    <InfoRow label="대표 카테고리" value={channel.primaryCategory ?? "미설정"} />
                    <InfoRow label="운영 목적" value={channel.purpose ?? "설명 없음"} />
                    <InfoRow label="게시 수" value={`${channel.postsCount}건`} />
                    <div className="flex flex-wrap gap-2 pt-1">
                      <FlagPill active={channel.plannerSupported} label={channel.plannerSupported ? "플래너 지원" : "계획 미지원"} />
                      <FlagPill active={channel.analyticsSupported} label={channel.analyticsSupported ? "분석 포함" : "분석 제외"} />
                      <FlagPill active={channel.promptFlowSupported} label={channel.promptFlowSupported ? "프롬프트 관리" : "프롬프트 미지원"} />
                    </div>
                    <div className="mt-2 rounded-2xl border border-slate-200 bg-white p-3">
                      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">최근 게시글</p>
                      <div className="mt-3 space-y-2">
                        {(channelPreviews[channel.channelId] ?? []).map((item, index) => (
                          <div key={`${channel.channelId}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <p className="text-sm font-semibold text-slate-900">{item.title}</p>
                                <p className="mt-1 text-xs text-slate-500">{item.meta}</p>
                              </div>
                              {item.url ? (
                                <a href={item.url} target="_blank" rel="noreferrer" className="text-xs font-semibold text-indigo-600">
                                  열기
                                </a>
                              ) : null}
                            </div>
                          </div>
                        ))}
                        {(channelPreviews[channel.channelId] ?? []).length === 0 ? (
                          <p className="text-sm text-slate-500">최근 게시글을 불러오는 중입니다.</p>
                        ) : null}
                      </div>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        ) : null}

        {activeTab === "프롬프트 플로우" ? (
          <div className="grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
            <aside className="space-y-4 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">관리 채널</p>
                <div className="mt-3 space-y-2">
                  {channels.filter((item) => item.promptFlowSupported).map((channel) => (
                    <button
                      key={channel.channelId}
                      type="button"
                      onClick={() => setSelectedChannelId(channel.channelId)}
                      className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                        selectedChannelId === channel.channelId ? "border-indigo-200 bg-white text-slate-900" : "border-transparent bg-white/60 text-slate-600 hover:border-slate-200"
                      }`}
                    >
                      <p className="text-sm font-semibold">{channel.name}</p>
                      <p className="mt-1 text-xs text-slate-500">{channel.provider} · {channel.plannerSupported ? "플로우 편집 가능" : "구조 편집 제한"}</p>
                    </button>
                  ))}
                </div>
              </div>
              {promptFlow?.structureEditable ? (
                <div className="rounded-2xl border border-slate-200 bg-white p-4">
                  <p className="text-sm font-semibold text-slate-900">단계 추가</p>
                  <div className="mt-3 space-y-3">
                    <select className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900" value={newStageType} onChange={(event) => setNewStageType(event.target.value)}>
                      {(promptFlow?.availableStageTypes ?? []).map((stage) => (
                        <option key={stage} value={stage}>{STAGE_LABELS[stage] ?? stage}</option>
                      ))}
                    </select>
                    <button type="button" onClick={addStep} disabled={!newStageType} className="w-full rounded-2xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">
                      단계 추가
                    </button>
                  </div>
                </div>
              ) : (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
                  이 채널은 카테고리/스테이지 묶음 단위로 프롬프트 본문만 수정합니다. 구조 편집은 Blogger 워크플로우에서만 가능합니다.
                </div>
              )}
            </aside>

            <div className="space-y-5">
              <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">프롬프트 플로우</p>
                    <h2 className="mt-2 text-2xl font-semibold text-slate-900">{promptFlow?.channelName ?? selectedChannel?.name ?? "채널 선택"}</h2>
                    <p className="mt-2 text-sm text-slate-500">{promptFlow?.provider === "cloudflare" ? "카테고리별로 스테이지 프롬프트를 묶어서 관리합니다." : "단계 제목, 목적, 프롬프트 본문을 순서대로 관리합니다."}</p>
                  </div>
                  {flowNotice ? <p className="text-sm text-indigo-600">{flowNotice}</p> : null}
                </div>
              </div>

              {promptFlow?.provider === "cloudflare" ? (
                <div className="space-y-4">
                  {groupedCloudflareSteps.map((group) => (
                    <article key={group.categoryName} className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">카테고리</p>
                          <h3 className="mt-2 text-xl font-semibold text-slate-900">{group.categoryName}</h3>
                        </div>
                        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">{group.steps.length}개 스테이지</span>
                      </div>
                      <div className="mt-5 grid gap-4 xl:grid-cols-2">
                        {group.steps.map((step) => (
                          <div key={step.id} className="rounded-[20px] border border-slate-200 bg-slate-50 p-4">
                            <div className="flex items-center justify-between gap-3">
                              <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-indigo-700">{STAGE_LABELS[step.stageType] ?? step.stageType}</span>
                              <span className="text-xs text-slate-500">자동 저장</span>
                            </div>
                            <textarea
                              className="mt-4 min-h-[220px] w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 font-mono text-sm leading-6 text-slate-700"
                              value={step.promptTemplate}
                              onChange={(event) => scheduleStepSave(step.id, { promptTemplate: event.target.value })}
                            />
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="space-y-4">
                  {(promptFlow?.steps ?? []).map((step, index) => (
                    <div key={step.id} className="grid grid-cols-[24px_minmax(0,1fr)] gap-4">
                      <div className="flex flex-col items-center">
                        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-[11px] font-semibold text-white">{index + 1}</div>
                        {index < (promptFlow?.steps.length ?? 0) - 1 ? <div className="mt-2 h-full w-px bg-indigo-200" /> : null}
                      </div>
                      <article className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
                        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                          <div className="space-y-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700">{STAGE_LABELS[step.stageType] ?? step.stageLabel}</span>
                              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${step.isRequired ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>{step.isRequired ? "필수 단계" : "선택 단계"}</span>
                              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${step.isEnabled ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`}>{step.isEnabled ? "사용" : "중지"}</span>
                            </div>
                            <input className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-lg font-semibold text-slate-900" value={step.name} onChange={(event) => scheduleStepSave(step.id, { name: event.target.value })} />
                            <input className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700" value={step.roleName ?? ""} onChange={(event) => scheduleStepSave(step.id, { roleName: event.target.value })} placeholder="역할 설명" />
                          </div>
                          <div className="flex flex-wrap gap-2 xl:justify-end">
                            <button type="button" onClick={() => moveStep(step.id, -1)} className="rounded-2xl border border-slate-200 px-3 py-2 text-sm text-slate-600">위로</button>
                            <button type="button" onClick={() => moveStep(step.id, 1)} className="rounded-2xl border border-slate-200 px-3 py-2 text-sm text-slate-600">아래로</button>
                            {step.removable ? <button type="button" onClick={() => removeStep(step.id)} className="rounded-2xl border border-rose-200 px-3 py-2 text-sm text-rose-600">제거</button> : null}
                          </div>
                        </div>

                        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_220px]">
                          <div className="space-y-3">
                            <textarea className="min-h-[120px] w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700" value={step.objective ?? ""} onChange={(event) => scheduleStepSave(step.id, { objective: event.target.value })} placeholder="단계 목적" />
                            <textarea className="min-h-[260px] w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 font-mono text-sm leading-6 text-slate-700" value={step.promptTemplate} onChange={(event) => scheduleStepSave(step.id, { promptTemplate: event.target.value })} placeholder="프롬프트 본문" />
                          </div>
                          <div className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                            <InfoRow label="단계 유형" value={STAGE_LABELS[step.stageType] ?? step.stageType} />
                            <InfoRow label="모델 힌트" value={step.providerModel ?? step.providerHint ?? "기본값 사용"} />
                            <InfoRow label="편집 권한" value="구조/본문 편집 가능" />
                            <label className="block space-y-2">
                              <span className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">사용 여부</span>
                              <select className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" value={step.isEnabled ? "true" : "false"} onChange={(event) => scheduleStepSave(step.id, { isEnabled: event.target.value === "true" })}>
                                <option value="true">사용</option>
                                <option value="false">중지</option>
                              </select>
                            </label>
                          </div>
                        </div>
                      </article>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}

        {activeTab === "연동 (TODO)" ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <ReadonlyCard label="Blogger 클라이언트" value={config.client_name || "미설정"} />
            <ReadonlyCard label="Client ID" value={config.client_id_configured ? "설정됨" : "미설정"} />
            <ReadonlyCard label="Client Secret" value={config.client_secret_configured ? "설정됨" : "미설정"} />
            <ReadonlyCard label="Refresh Token" value={config.refresh_token_configured ? "설정됨" : "미설정"} />
            <ReadonlyCard label="현재 상태" value="이번 단계에서는 인증값과 env를 수정하지 않습니다." />
          </div>
        ) : null}

        {activeTab !== "채널 관리" && activeTab !== "프롬프트 플로우" && activeTab !== "연동 (TODO)" ? (
          <div className="space-y-5">
            <div className="grid gap-4 lg:grid-cols-2">
              {Object.entries(SECTION_FIELDS[activeTab]).map(([key, field]) => (
                <label key={key} className="space-y-3 rounded-[24px] border border-slate-200 bg-slate-50 p-5">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{field.label}</p>
                    <p className="mt-1 text-sm leading-6 text-slate-500">{field.description}</p>
                  </div>
                  <FieldInput config={field} models={modelPolicy} value={draft[key] ?? ""} onChange={(value) => setDraft((current) => ({ ...current, [key]: value }))} />
                </label>
              ))}
            </div>
            <div className="flex items-center justify-end">
              <button type="button" onClick={() => saveSettings(Object.keys(SECTION_FIELDS[activeTab]))} className="rounded-2xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white">
                현재 탭 저장
              </button>
            </div>
            {activeTab === "모델" && modelPolicy ? (
              <div className="grid gap-4 xl:grid-cols-2">
                <PolicyCard title="대형 모델" items={modelPolicy.large} />
                <PolicyCard title="소형 모델" items={modelPolicy.small} />
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}

function FieldInput({ config, value, onChange, models }: { config: FieldConfig; value: string; onChange: (value: string) => void; models: ModelPolicyRead | null }) {
  if (config.type === "boolean") {
    return (
      <select className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" value={value || "false"} onChange={(event) => onChange(event.target.value)}>
        <option value="false">OFF</option>
        <option value="true">ON</option>
      </select>
    );
  }
  if (config.type === "select") {
    const options = config.options ?? [...(models?.large ?? []), ...(models?.small ?? [])].map((model) => ({ label: model, value: model }));
    return (
      <select className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    );
  }
  return (
    <input type={config.type === "time" ? "time" : config.type === "number" ? "number" : "text"} className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900" value={value} onChange={(event) => onChange(event.target.value)} />
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-3">
      <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</span>
      <span className="break-all text-sm text-slate-700">{value}</span>
    </div>
  );
}

function FlagPill({ active, label }: { active: boolean; label: string }) {
  return <span className={`rounded-full px-3 py-1 text-xs font-semibold ${active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{label}</span>;
}

function ReadonlyCard({ label, value }: { label: string; value: string }) {
  return (
    <article className="rounded-[24px] border border-slate-200 bg-slate-50 p-5">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{label}</p>
      <p className="mt-3 break-all text-sm leading-6 text-slate-700">{value}</p>
    </article>
  );
}

function PolicyCard({ title, items }: { title: string; items: string[] }) {
  return (
    <article className="rounded-[24px] border border-slate-200 bg-slate-50 p-5">
      <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      <ul className="mt-4 space-y-2 text-sm text-slate-600">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </article>
  );
}

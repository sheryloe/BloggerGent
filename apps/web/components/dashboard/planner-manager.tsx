"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import {
  buildPlannerMonthPlan,
  cancelPlannerSlot,
  createPlannerSlot,
  generatePlannerSlot,
  getPlannerCalendar,
  updatePlannerSlot,
} from "@/lib/api";
import type { ManagedChannelRead, PlannerCalendarRead, PlannerCategoryRead, PlannerDayRead } from "@/lib/types";

type PlannerManagerProps = {
  channels: ManagedChannelRead[];
};

type DetailTab = "day" | "month";

type SlotDraft = {
  categoryKey: string;
  scheduledFor: string;
  briefTopic: string;
  briefAudience: string;
  briefInformationLevel: string;
  briefExtraContext: string;
};

type CalendarCell = {
  dateKey: string;
  dayNumber: number;
  plannerDay: PlannerDayRead | null;
};

function defaultMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function formatDateKey(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseDateKey(value: string) {
  return new Date(`${value}T12:00:00`);
}

function formatMonthLabel(month: string) {
  const [yearText, monthText] = month.split("-");
  return `${yearText}년 ${Number(monthText)}월`;
}

function formatDayLabel(dateKey: string) {
  const date = parseDateKey(dateKey);
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

function formatWeekday(dateKey: string) {
  const weekdays = ["일", "월", "화", "수", "목", "금", "토"];
  return weekdays[parseDateKey(dateKey).getDay()];
}

function toDatetimeLocal(value?: string | null) {
  if (!value) return "";
  return value.slice(0, 16);
}

function withSeconds(value: string) {
  if (!value) return value;
  return value.length === 16 ? `${value}:00` : value;
}

function buildMonthCells(month: string, days: PlannerDayRead[]): Array<CalendarCell | null> {
  const [yearText, monthText] = month.split("-");
  const year = Number(yearText);
  const monthIndex = Number(monthText) - 1;
  const firstDay = new Date(Date.UTC(year, monthIndex, 1));
  const daysInMonth = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
  const mondayOffset = (firstDay.getUTCDay() + 6) % 7;
  const dayMap = new Map(days.map((day) => [day.planDate, day]));
  const cells: Array<CalendarCell | null> = Array.from({ length: mondayOffset }, () => null);

  for (let dayNumber = 1; dayNumber <= daysInMonth; dayNumber += 1) {
    const dateKey = `${month}-${String(dayNumber).padStart(2, "0")}`;
    cells.push({
      dateKey,
      dayNumber,
      plannerDay: dayMap.get(dateKey) ?? null,
    });
  }

  return cells;
}

function statusText(status: string) {
  const labels: Record<string, string> = {
    planned: "계획",
    brief_ready: "준비 완료",
    queued: "생성 대기",
    generating: "생성 중",
    generated: "생성 완료",
    published: "발행 완료",
    failed: "실패",
    canceled: "취소",
  };
  return labels[status] ?? status;
}

function statusTone(status: string) {
  if (status === "generated" || status === "published") return "bg-emerald-50 text-emerald-700";
  if (status === "queued" || status === "generating") return "bg-indigo-50 text-indigo-700";
  if (status === "failed" || status === "canceled") return "bg-rose-50 text-rose-700";
  if (status === "brief_ready") return "bg-amber-50 text-amber-700";
  return "bg-slate-100 text-slate-600";
}

function scoreText(value: number | null | undefined) {
  if (value == null) return "미집계";
  return Number(value).toFixed(1);
}

function parseDetailTab(value: string | null): DetailTab {
  return value === "month" ? "month" : "day";
}

function providerTypeLabel(provider: string) {
  if (provider === "blogger") return "블로그";
  if (provider === "youtube") return "유튜브";
  if (provider === "instagram") return "인스타그램";
  if (provider === "cloudflare") return "Cloudflare";
  return provider;
}

function publishModeText(value?: string | null) {
  const normalized = (value ?? "").toLowerCase();
  if (normalized === "draft") return "초안";
  if (normalized === "publish") return "즉시 게시";
  if (normalized === "scheduled") return "예약 게시";
  return value ?? "초안";
}

function defaultDraft(dateKey: string, categories: PlannerCategoryRead[]): SlotDraft {
  return {
    categoryKey: categories[0]?.key ?? "",
    scheduledFor: `${dateKey}T09:00`,
    briefTopic: "",
    briefAudience: "",
    briefInformationLevel: "",
    briefExtraContext: "",
  };
}

export function PlannerManager({ channels }: PlannerManagerProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const plannerChannels = useMemo(() => channels.filter((item) => item.plannerSupported), [channels]);
  const plannerTypeKeys = useMemo(
    () => Array.from(new Set(plannerChannels.map((channel) => channel.provider).filter(Boolean))),
    [plannerChannels],
  );
  const todayDateKey = useMemo(() => formatDateKey(new Date()), []);
  const month = searchParams.get("month") ?? defaultMonth();
  const selectedTab = parseDetailTab(searchParams.get("panel"));
  const legacyBlogId = searchParams.get("blog");
  const requestedType = searchParams.get("type");
  const selectedType = requestedType && plannerTypeKeys.includes(requestedType) ? requestedType : plannerTypeKeys[0] ?? "";
  const typeFilteredChannels = useMemo(
    () => plannerChannels.filter((channel) => channel.provider === selectedType),
    [plannerChannels, selectedType],
  );
  const requestedChannelId = searchParams.get("channel") ?? (legacyBlogId ? `blogger:${legacyBlogId}` : "");
  const selectedChannelId =
    typeFilteredChannels.find((channel) => channel.channelId === requestedChannelId)?.channelId ??
    typeFilteredChannels[0]?.channelId ??
    plannerChannels[0]?.channelId ??
    "";

  const [calendar, setCalendar] = useState<PlannerCalendarRead | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [selectedSlotId, setSelectedSlotId] = useState<number | null>(null);
  const [draft, setDraft] = useState<SlotDraft | null>(null);

  const categories = calendar?.categories ?? [];
  const categoryMap = useMemo(() => new Map(categories.map((item) => [item.key, item])), [categories]);
  const selectedDayKey = searchParams.get("selectedDate") ?? todayDateKey;

  const selectedDay = useMemo(() => {
    if (!calendar?.days.length) return null;
    return calendar.days.find((day) => day.planDate === selectedDayKey) ?? calendar.days.find((day) => day.planDate === todayDateKey) ?? calendar.days[0] ?? null;
  }, [calendar, selectedDayKey, todayDateKey]);

  const selectedSlot = useMemo(() => {
    if (!selectedDay?.slots.length) return null;
    return selectedDay.slots.find((slot) => slot.id === selectedSlotId) ?? selectedDay.slots[0] ?? null;
  }, [selectedDay, selectedSlotId]);

  const monthCells = useMemo(() => buildMonthCells(month, calendar?.days ?? []), [calendar, month]);
  const monthSummary = useMemo(() => {
    const days = calendar?.days ?? [];
    return {
      target: days.reduce((sum, day) => sum + day.targetPostCount, 0),
      slots: days.reduce((sum, day) => sum + day.slotCount, 0),
      generated: days.reduce((sum, day) => sum + day.slots.filter((slot) => slot.status === "generated" || slot.status === "published").length, 0),
      published: days.reduce((sum, day) => sum + day.slots.filter((slot) => slot.articlePublishStatus === "published" || slot.resultStatus === "published").length, 0),
    };
  }, [calendar]);

  const monthCategoryStats = useMemo(() => {
    const actualMap = new Map<string, number>();
    for (const day of calendar?.days ?? []) {
      for (const slot of day.slots) {
        const key = slot.categoryKey ?? "";
        if (!key) continue;
        actualMap.set(key, (actualMap.get(key) ?? 0) + 1);
      }
    }
    const totalTarget = monthSummary.target || 1;
    const totalWeight = categories.reduce((sum, category) => sum + category.weight, 0) || 1;
    return categories.map((category) => ({
      ...category,
      planned: Math.round((totalTarget * category.weight) / totalWeight),
      actual: actualMap.get(category.key) ?? 0,
    }));
  }, [calendar, categories, monthSummary.target]);

  function setQuery(updates: Record<string, string | null | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (!value) next.delete(key);
      else next.set(key, value);
    }
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  async function loadCalendar(preferredDate?: string | null) {
    if (!selectedChannelId) return;
    try {
      setStatusMessage("플래너를 불러오는 중입니다.");
      const next = await getPlannerCalendar(selectedChannelId, month);
      setCalendar(next);
      const nextDate = preferredDate && next.days.some((day) => day.planDate === preferredDate)
        ? preferredDate
        : next.days.find((day) => day.planDate === todayDateKey)?.planDate ?? next.days[0]?.planDate ?? null;
      if (nextDate && nextDate !== searchParams.get("selectedDate")) {
        setQuery({ selectedDate: nextDate });
      }
      setStatusMessage("");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "플래너를 불러오지 못했습니다.");
    }
  }

  useEffect(() => {
    if (!selectedChannelId) return;
    void loadCalendar(searchParams.get("selectedDate"));
  }, [selectedChannelId, month]);

  useEffect(() => {
    if (!selectedDay?.slots.length) {
      setSelectedSlotId(null);
      return;
    }
    if (!selectedSlot || !selectedDay.slots.some((slot) => slot.id === selectedSlot.id)) {
      setSelectedSlotId(selectedDay.slots[0]?.id ?? null);
    }
  }, [selectedDay?.planDate, selectedDay?.slots.length]);

  useEffect(() => {
    if (selectedSlot) {
      setDraft({
        categoryKey: selectedSlot.categoryKey ?? categories[0]?.key ?? "",
        scheduledFor: toDatetimeLocal(selectedSlot.scheduledFor) || `${selectedDay?.planDate ?? todayDateKey}T09:00`,
        briefTopic: selectedSlot.briefTopic ?? "",
        briefAudience: selectedSlot.briefAudience ?? "",
        briefInformationLevel: selectedSlot.briefInformationLevel ?? "",
        briefExtraContext: selectedSlot.briefExtraContext ?? "",
      });
      return;
    }
    if (selectedDay) {
      setDraft(defaultDraft(selectedDay.planDate, categories));
      return;
    }
    setDraft(null);
  }, [selectedSlot?.id, selectedDay?.planDate, categories]);

  async function handleRebuildMonthPlan() {
    if (!selectedChannelId) return;
    try {
      setStatusMessage("월간 계획을 다시 만드는 중입니다.");
      const next = await buildPlannerMonthPlan({ channelId: selectedChannelId, month, overwrite: true });
      setCalendar(next);
      const nextDate = next.days.find((day) => day.planDate === todayDateKey)?.planDate ?? next.days[0]?.planDate ?? null;
      if (nextDate) {
        setQuery({ selectedDate: nextDate, panel: "day" });
      }
      setStatusMessage("월간 계획을 다시 만들었습니다.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "월간 계획을 다시 만들지 못했습니다.");
    }
  }

  async function handleAddSlot() {
    if (!selectedDay || !draft) return;
    try {
      setStatusMessage("슬롯을 추가하는 중입니다.");
      const created = await createPlannerSlot({
        planDayId: selectedDay.id,
        categoryKey: draft.categoryKey,
        scheduledFor: withSeconds(draft.scheduledFor),
        briefTopic: draft.briefTopic,
        briefAudience: draft.briefAudience,
        briefInformationLevel: draft.briefInformationLevel,
        briefExtraContext: draft.briefExtraContext,
      });
      await loadCalendar(selectedDay.planDate);
      setSelectedSlotId(created.id);
      setStatusMessage("슬롯을 추가했습니다.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "슬롯을 추가하지 못했습니다.");
    }
  }

  async function handleSaveSlot() {
    if (!selectedSlot || !draft) return;
    try {
      setStatusMessage("슬롯을 저장하는 중입니다.");
      await updatePlannerSlot(selectedSlot.id, {
        categoryKey: draft.categoryKey,
        scheduledFor: withSeconds(draft.scheduledFor),
        briefTopic: draft.briefTopic,
        briefAudience: draft.briefAudience,
        briefInformationLevel: draft.briefInformationLevel,
        briefExtraContext: draft.briefExtraContext,
      });
      await loadCalendar(selectedDay?.planDate ?? null);
      setStatusMessage("슬롯을 저장했습니다.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "슬롯을 저장하지 못했습니다.");
    }
  }

  async function handleGenerateSlot() {
    if (!selectedSlot) return;
    try {
      setStatusMessage("선택한 슬롯을 실행하는 중입니다.");
      await generatePlannerSlot(selectedSlot.id);
      await loadCalendar(selectedDay?.planDate ?? null);
      setStatusMessage("슬롯 실행을 요청했습니다.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "슬롯 실행에 실패했습니다.");
    }
  }

  async function handleCancelSlot() {
    if (!selectedSlot) return;
    try {
      setStatusMessage("슬롯을 취소하는 중입니다.");
      await cancelPlannerSlot(selectedSlot.id);
      await loadCalendar(selectedDay?.planDate ?? null);
      setStatusMessage("슬롯을 취소했습니다.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "슬롯 취소에 실패했습니다.");
    }
  }

  const selectedChannel = typeFilteredChannels.find((item) => item.channelId === selectedChannelId) ?? typeFilteredChannels[0] ?? null;

  if (!plannerChannels.length) {
    return (
      <div className="rounded-[28px] border border-dashed border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
        플래너를 지원하는 연결 채널이 없습니다. 먼저 연동 설정에서 채널을 연결하세요.
      </div>
    );
  }

  return (
    <div className="space-y-6 rounded-[32px] bg-[#f5f7ff] p-6 text-slate-900 shadow-[0_24px_80px_rgba(15,23,42,0.08)] md:p-8">
      <section className="rounded-[28px] bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-500">Planner</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">게시 플래너 운영</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              타입을 먼저 고르고, 그 안에서 실제 연결된 채널별로 월간 배분과 일간 슬롯을 관리합니다. 프롬프트 편집은 관리자 설정의 7단계 플로우에서 처리합니다.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/admin" className="rounded-full bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-200">
              관리자 설정 열기
            </Link>
            <button type="button" onClick={handleRebuildMonthPlan} className="rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800">
              월간 계획 다시 만들기
            </button>
          </div>
        </div>
        <div className="mt-6 grid gap-4 xl:grid-cols-[minmax(180px,220px)_minmax(220px,280px)_200px_minmax(0,1fr)]">
          <Field label="타입">
            <select
              value={selectedType}
              onChange={(event) => {
                const nextType = event.target.value;
                const nextChannel =
                  plannerChannels.find((channel) => channel.provider === nextType)?.channelId ??
                  plannerChannels[0]?.channelId ??
                  "";
                setQuery({ type: nextType, channel: nextChannel, blog: null, selectedDate: null });
              }}
              className={inputClass()}
            >
              {plannerTypeKeys.map((provider) => (
                <option key={provider} value={provider}>
                  {providerTypeLabel(provider)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="운영 채널">
            <select value={selectedChannelId} onChange={(event) => setQuery({ channel: event.target.value, blog: null, selectedDate: null })} className={inputClass()}>
              {typeFilteredChannels.map((channel) => (
                <option key={channel.channelId} value={channel.channelId}>
                  {channel.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="기준 월">
            <input type="month" value={month} onChange={(event) => setQuery({ month: event.target.value, selectedDate: null })} className={inputClass()} />
          </Field>
          <div className="grid gap-3 rounded-[24px] bg-slate-50 p-4 md:grid-cols-3">
            <MetricCard label="목표 슬롯" value={`${monthSummary.target}건`} />
            <MetricCard label="생성 완료" value={`${monthSummary.generated}건`} />
            <MetricCard label="발행 완료" value={`${monthSummary.published}건`} />
          </div>
        </div>
        {statusMessage ? <p className="mt-4 text-sm text-indigo-600">{statusMessage}</p> : null}
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(380px,0.95fr)]">
        <div className="rounded-[28px] bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">월간 캘린더</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-950">{formatMonthLabel(month)}</h2>
            </div>
            {selectedChannel ? <FlagPill tone="slate">{selectedChannel.name}</FlagPill> : null}
          </div>
          <div className="mt-5 overflow-x-auto">
            <div className="min-w-[780px]">
              <div className="grid grid-cols-7 gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
                {["월", "화", "수", "목", "금", "토", "일"].map((label) => (
                  <div key={label} className="px-2">{label}</div>
                ))}
              </div>
              <div className="mt-3 grid grid-cols-7 gap-2">
                {monthCells.map((cell, index) => {
                  if (!cell) return <div key={`empty-${index}`} className="min-h-[160px] rounded-[24px] bg-transparent" />;
                  const day = cell.plannerDay;
                  const isSelected = cell.dateKey === selectedDay?.planDate;
                  const chips = Object.entries(day?.categoryMix ?? {}).slice(0, 3);
                  return (
                    <button
                      key={cell.dateKey}
                      type="button"
                      onClick={() => setQuery({ selectedDate: cell.dateKey, panel: "day" })}
                      className={`min-h-[160px] rounded-[24px] p-4 text-left transition ${isSelected ? "bg-indigo-50 ring-2 ring-indigo-200" : "bg-slate-50 hover:bg-slate-100"}`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-lg font-semibold text-slate-950">{cell.dayNumber}</p>
                          <p className="mt-1 text-xs text-slate-500">{formatWeekday(cell.dateKey)}요일</p>
                        </div>
                        <FlagPill tone="slate">{day?.slotCount ?? 0} 슬롯</FlagPill>
                      </div>
                      <div className="mt-4 space-y-2 text-xs text-slate-500">
                        <p>생성 완료 {day?.slots.filter((slot) => slot.status === "generated" || slot.status === "published").length ?? 0}</p>
                        <div className="flex flex-wrap gap-1.5">
                          {chips.length ? chips.map(([key, count]) => (
                            <span key={key} className="rounded-full px-2.5 py-1 text-[11px] font-medium text-slate-700" style={{ backgroundColor: `${categoryMap.get(key)?.color ?? "#cbd5e1"}33` }}>
                              {categoryMap.get(key)?.name ?? key} {count}
                            </span>
                          )) : <span className="text-slate-400">배정 없음</span>}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-[28px] bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 rounded-full bg-slate-100 p-1 text-sm">
              <button type="button" onClick={() => setQuery({ panel: "day" })} className={`rounded-full px-4 py-2 font-medium ${selectedTab === "day" ? "bg-white text-slate-950 shadow-sm" : "text-slate-600"}`}>
                일간 계획
              </button>
              <button type="button" onClick={() => setQuery({ panel: "month" })} className={`rounded-full px-4 py-2 font-medium ${selectedTab === "month" ? "bg-white text-slate-950 shadow-sm" : "text-slate-600"}`}>
                월간 집계
              </button>
            </div>
          </div>

          {selectedTab === "day" ? (
            <div className="space-y-4 rounded-[28px] bg-white p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">선택 날짜</p>
                  <h2 className="mt-2 text-2xl font-semibold text-slate-950">{selectedDay ? `${formatDayLabel(selectedDay.planDate)} · ${formatWeekday(selectedDay.planDate)}요일` : "날짜를 선택하세요"}</h2>
                </div>
                <button type="button" onClick={handleAddSlot} disabled={!selectedDay || !draft} className="rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300">
                  슬롯 추가
                </button>
              </div>

              <div className="space-y-2">
                {(selectedDay?.slots ?? []).length ? (
                  selectedDay?.slots.map((slot) => (
                    <button key={slot.id} type="button" onClick={() => setSelectedSlotId(slot.id)} className={`flex w-full items-center justify-between rounded-[22px] border px-4 py-3 text-left transition ${selectedSlot?.id === slot.id ? "border-indigo-200 bg-indigo-50" : "border-slate-200 bg-slate-50 hover:bg-slate-100"}`}>
                      <div>
                        <p className="text-sm font-semibold text-slate-950">{slot.briefTopic || "주제 미입력"}</p>
                        <p className="mt-1 text-xs text-slate-500">{slot.categoryName || "카테고리 미선택"} · {toDatetimeLocal(slot.scheduledFor).slice(11, 16) || "시간 미정"}</p>
                      </div>
                      <FlagPill tone="slate">{statusText(slot.status)}</FlagPill>
                    </button>
                  ))
                ) : (
                  <div className="rounded-[24px] border border-dashed border-slate-200 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">선택한 날짜에 아직 슬롯이 없습니다.</div>
                )}
              </div>

              {draft ? (
                <div className="space-y-4 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <Field label="주제">
                      <input value={draft.briefTopic} onChange={(event) => setDraft((current) => current ? { ...current, briefTopic: event.target.value } : current)} className={inputClass()} />
                    </Field>
                    <Field label="독자 타겟">
                      <input value={draft.briefAudience} onChange={(event) => setDraft((current) => current ? { ...current, briefAudience: event.target.value } : current)} className={inputClass()} />
                    </Field>
                    <Field label="카테고리">
                      <select value={draft.categoryKey} onChange={(event) => setDraft((current) => current ? { ...current, categoryKey: event.target.value } : current)} className={inputClass()}>
                        {categories.map((category) => <option key={category.key} value={category.key}>{category.name}</option>)}
                      </select>
                    </Field>
                    <Field label="예약 시간">
                      <input type="datetime-local" value={draft.scheduledFor} onChange={(event) => setDraft((current) => current ? { ...current, scheduledFor: event.target.value } : current)} className={inputClass()} />
                    </Field>
                  </div>

                  <details className="rounded-[20px] border border-slate-200 bg-white p-4">
                    <summary className="cursor-pointer text-sm font-semibold text-slate-900">추가 입력</summary>
                    <div className="mt-4 grid gap-4">
                      <Field label="정보 수준">
                        <input value={draft.briefInformationLevel} onChange={(event) => setDraft((current) => current ? { ...current, briefInformationLevel: event.target.value } : current)} className={inputClass()} />
                      </Field>
                      <Field label="기타 정보">
                        <textarea value={draft.briefExtraContext} onChange={(event) => setDraft((current) => current ? { ...current, briefExtraContext: event.target.value } : current)} rows={4} className={textareaClass()} />
                      </Field>
                    </div>
                  </details>

                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={handleSaveSlot} disabled={!selectedSlot} className="rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300">
                      슬롯 저장
                    </button>
                    <button type="button" onClick={handleGenerateSlot} disabled={!selectedSlot} className="rounded-full bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-indigo-200">
                      실행
                    </button>
                    <button type="button" onClick={handleCancelSlot} disabled={!selectedSlot} className="rounded-full bg-rose-50 px-4 py-2 text-sm font-medium text-rose-700 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:text-rose-300">
                      취소
                    </button>
                  </div>
                </div>
              ) : null}

              <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-950">실행 상태</p>
                    <p className="mt-1 text-xs text-slate-500">발행 관련 상세 조건은 관리자 설정에서 관리하고, 여기서는 결과 상태와 링크만 확인합니다.</p>
                  </div>
                  {selectedSlot ? <span className={`rounded-full px-3 py-1 text-xs font-medium ${statusTone(selectedSlot.status)}`}>{statusText(selectedSlot.status)}</span> : null}
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <ReadonlyItem label="발행 모드" value={publishModeText(selectedSlot?.publishMode)} />
                  <ReadonlyItem label="품질 게이트" value={selectedSlot?.qualityGateStatus || selectedSlot?.articleQualityStatus || "대기"} />
                  <ReadonlyItem label="예약 상태" value={selectedSlot?.scheduledFor ? `${formatDayLabel(selectedSlot.scheduledFor.slice(0, 10))} ${toDatetimeLocal(selectedSlot.scheduledFor).slice(11, 16)}` : "미정"} />
                  <ReadonlyItem label="결과 상태" value={selectedSlot?.resultStatus || selectedSlot?.articlePublishStatus || "대기"} />
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <ReadonlyItem label="SEO 점수" value={scoreText(selectedSlot?.articleSeoScore)} />
                  <ReadonlyItem label="GEO 점수" value={scoreText(selectedSlot?.articleGeoScore)} />
                </div>
                <div className="mt-4 rounded-[20px] bg-white p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">생성 결과 링크</p>
                  {selectedSlot?.resultUrl || selectedSlot?.articlePublishedUrl ? (
                    <a href={selectedSlot.resultUrl || selectedSlot.articlePublishedUrl || "#"} target="_blank" rel="noreferrer" className="mt-2 inline-flex rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800">
                      사이트 열기
                    </a>
                  ) : (
                    <p className="mt-2 text-sm text-slate-500">아직 생성 결과가 없습니다.</p>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-4 rounded-[28px] bg-white p-5 shadow-sm">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">월간 집계</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-950">카테고리 배분 현황</h2>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {monthCategoryStats.map((category) => (
                  <div key={category.key} className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <span className="h-3 w-3 rounded-full" style={{ backgroundColor: category.color ?? "#cbd5e1" }} />
                        <p className="text-sm font-semibold text-slate-950">{category.name}</p>
                      </div>
                      <FlagPill tone="slate">가중치 {category.weight}</FlagPill>
                    </div>
                    <p className="mt-3 text-sm text-slate-600">목표 {category.planned}건 / 실제 {category.actual}건</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-2">
      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</span>
      {children}
    </label>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] bg-white px-4 py-3 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</p>
      <p className="mt-2 text-lg font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function ReadonlyItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] bg-white px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</p>
      <p className="mt-2 text-sm font-medium text-slate-900">{value}</p>
    </div>
  );
}

function FlagPill({ children, tone }: { children: ReactNode; tone: "slate" }) {
  return <span className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">{children}</span>;
}

function inputClass() {
  return "h-[44px] w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200";
}

function textareaClass() {
  return "w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200";
}

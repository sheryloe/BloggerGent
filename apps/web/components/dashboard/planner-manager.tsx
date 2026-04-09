"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import {
  applyPlannerDayBrief,
  buildPlannerMonthPlan,
  cancelPlannerSlot,
  createPlannerSlot,
  generatePlannerSlot,
  getPlannerDayBriefRuns,
  getPlannerCalendar,
  runPlannerDayBriefAnalysis,
  updatePlannerCategoryRules,
  updatePlannerSlot,
} from "@/lib/api";
import type {
  ManagedChannelRead,
  PlannerBriefRun,
  PlannerBriefSuggestion,
  PlannerCalendarRead,
  PlannerCategoryRead,
  PlannerCategoryRuleUpdateRequest,
  PlannerDayRead,
} from "@/lib/types";

type PlannerManagerProps = {
  channels: ManagedChannelRead[];
};

type DetailTab = "day" | "rules" | "month";

type SlotDraft = {
  categoryKey: string;
  scheduledFor: string;
  briefTopic: string;
  briefAudience: string;
  briefInformationLevel: string;
  briefExtraContext: string;
};

type BriefSuggestionDraft = {
  slotId: number;
  slotOrder: number;
  categoryKey: string;
  topic: string;
  audience: string;
  informationLevel: string;
  extraContext: string;
  expectedCtrLift: string;
  confidence: string;
  signalSource: string;
  reason: string;
};

type CategoryRuleDraft = {
  categoryKey: string;
  planningMode: "auto" | "weekly" | "weekdays";
  weeklyTarget: string;
  weekdays: number[];
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

function weekdayShortLabel(weekday: number) {
  return ["월", "화", "수", "목", "금", "토", "일"][weekday] ?? "";
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
  if (value === "month" || value === "rules") return value;
  return "day";
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
    scheduledFor: `${dateKey}T11:00`,
    briefTopic: "",
    briefAudience: "",
    briefInformationLevel: "",
    briefExtraContext: "",
  };
}

function confidenceToInput(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "";
  return String(value);
}

function buildSuggestionDrafts(day: PlannerDayRead | null, run: PlannerBriefRun | null): BriefSuggestionDraft[] {
  if (!day) return [];
  const suggestionMap = new Map<number, PlannerBriefSuggestion>((run?.slotSuggestions ?? []).map((item) => [item.slotId, item]));
  return day.slots
    .slice()
    .sort((a, b) => a.slotOrder - b.slotOrder)
    .map((slot) => {
      const suggestion = suggestionMap.get(slot.id);
      return {
        slotId: slot.id,
        slotOrder: slot.slotOrder,
        categoryKey: slot.categoryKey ?? suggestion?.categoryKey ?? "",
        topic: suggestion?.topic ?? slot.briefTopic ?? "",
        audience: suggestion?.audience ?? slot.briefAudience ?? "",
        informationLevel: suggestion?.informationLevel ?? slot.briefInformationLevel ?? "",
        extraContext: suggestion?.extraContext ?? slot.briefExtraContext ?? "",
        expectedCtrLift: suggestion?.expectedCtrLift ?? "",
        confidence: confidenceToInput(suggestion?.confidence),
        signalSource: suggestion?.signalSource ?? "",
        reason: suggestion?.reason ?? "",
      };
    });
}

function buildCategoryRuleDrafts(categories: PlannerCategoryRead[]): CategoryRuleDraft[] {
  return categories
    .slice()
    .sort((left, right) => left.sortOrder - right.sortOrder)
    .map((category) => ({
      categoryKey: category.key,
      planningMode: category.planningMode ?? "auto",
      weeklyTarget: category.weeklyTarget ? String(category.weeklyTarget) : "",
      weekdays: [...(category.weekdays ?? [])].sort((left, right) => left - right),
    }));
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
  const [analysisPromptOverride, setAnalysisPromptOverride] = useState("");
  const [briefRuns, setBriefRuns] = useState<PlannerBriefRun[]>([]);
  const [selectedBriefRunId, setSelectedBriefRunId] = useState<number | null>(null);
  const [suggestionDrafts, setSuggestionDrafts] = useState<BriefSuggestionDraft[]>([]);
  const [categoryRuleDrafts, setCategoryRuleDrafts] = useState<CategoryRuleDraft[]>([]);
  const [categoryRuleFilter, setCategoryRuleFilter] = useState("");

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
  const selectedBriefRun = useMemo(() => {
    if (!briefRuns.length) return null;
    return briefRuns.find((run) => run.id === selectedBriefRunId) ?? briefRuns[0] ?? null;
  }, [briefRuns, selectedBriefRunId]);

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
    const scheduledMap = new Map<string, number>();
    const generatedMap = new Map<string, number>();
    for (const day of calendar?.days ?? []) {
      for (const slot of day.slots) {
        const key = slot.categoryKey ?? "";
        if (!key) continue;
        scheduledMap.set(key, (scheduledMap.get(key) ?? 0) + 1);
        if (slot.status === "generated" || slot.status === "published") {
          generatedMap.set(key, (generatedMap.get(key) ?? 0) + 1);
        }
      }
    }
    return categories.map((category) => ({
      ...category,
      planned: scheduledMap.get(category.key) ?? 0,
      actual: generatedMap.get(category.key) ?? 0,
    }));
  }, [calendar, categories]);

  const filteredCategoryRuleDrafts = useMemo(() => {
    const keyword = categoryRuleFilter.trim().toLowerCase();
    const categoryNameMap = new Map(categories.map((category) => [category.key, category.name]));
    return categoryRuleDrafts.filter((draft) => {
      if (!keyword) return true;
      const name = categoryNameMap.get(draft.categoryKey) ?? draft.categoryKey;
      return `${name} ${draft.categoryKey}`.toLowerCase().includes(keyword);
    });
  }, [categories, categoryRuleDrafts, categoryRuleFilter]);

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

  async function loadBriefRuns(day: PlannerDayRead, preferredRunId?: number | null) {
    try {
      const runs = await getPlannerDayBriefRuns(day.id, 20);
      setBriefRuns(runs);
      const resolvedRunId =
        preferredRunId && runs.some((run) => run.id === preferredRunId)
          ? preferredRunId
          : runs[0]?.id ?? null;
      setSelectedBriefRunId(resolvedRunId);
      const resolvedRun = runs.find((run) => run.id === resolvedRunId) ?? null;
      setSuggestionDrafts(buildSuggestionDrafts(day, resolvedRun));
    } catch (error) {
      setBriefRuns([]);
      setSelectedBriefRunId(null);
      setSuggestionDrafts(buildSuggestionDrafts(day, null));
      setStatusMessage(error instanceof Error ? error.message : "분석 이력을 불러오지 못했습니다.");
    }
  }

  useEffect(() => {
    if (!selectedChannelId) return;
    void loadCalendar(searchParams.get("selectedDate"));
  }, [selectedChannelId, month]);

  useEffect(() => {
    if (!selectedDay) {
      setBriefRuns([]);
      setSelectedBriefRunId(null);
      setSuggestionDrafts([]);
      return;
    }
    void loadBriefRuns(selectedDay);
  }, [selectedDay?.id]);

  useEffect(() => {
    if (!selectedDay) return;
    setSuggestionDrafts(buildSuggestionDrafts(selectedDay, selectedBriefRun));
  }, [selectedDay?.id, selectedBriefRun?.id, briefRuns]);

  useEffect(() => {
    setCategoryRuleDrafts(buildCategoryRuleDrafts(categories));
  }, [categories]);

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
        scheduledFor: toDatetimeLocal(selectedSlot.scheduledFor) || `${selectedDay?.planDate ?? todayDateKey}T11:00`,
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

  async function autofillMonthBriefs(next: PlannerCalendarRead) {
    const targetDays = next.days.filter((day) => day.slots.length > 0);
    if (!targetDays.length) {
      return { analyzedDays: 0, appliedSlots: 0, skippedSlots: 0, failedDays: 0 };
    }

    let appliedSlots = 0;
    let skippedSlots = 0;
    let failedDays = 0;

    for (let index = 0; index < targetDays.length; index += 1) {
      const day = targetDays[index];
      try {
        setStatusMessage(`소형 모델로 월간 브리프 자동 채우는 중... ${index + 1}/${targetDays.length} (${formatDayLabel(day.planDate)})`);
        const analysis = await runPlannerDayBriefAnalysis(day.id);
        const applied = await applyPlannerDayBrief(day.id, {
          runId: analysis.run.id,
        });
        appliedSlots += applied.appliedSlotIds.length;
        skippedSlots += applied.skippedSlotIds.length;
      } catch {
        failedDays += 1;
      }
    }

    return {
      analyzedDays: targetDays.length,
      appliedSlots,
      skippedSlots,
      failedDays,
    };
  }

  async function handleRebuildMonthPlan() {
    if (!selectedChannelId) return;
    try {
      setStatusMessage("월간 계획과 브리프를 다시 만드는 중입니다.");
      const next = await buildPlannerMonthPlan({ channelId: selectedChannelId, month, overwrite: true });
      setCalendar(next);
      const nextDate = next.days.find((day) => day.planDate === todayDateKey)?.planDate ?? next.days[0]?.planDate ?? null;
      if (nextDate) {
        setQuery({ selectedDate: nextDate, panel: "day" });
      }
      const fillResult = await autofillMonthBriefs(next);
      await loadCalendar(nextDate);
      if (fillResult.failedDays > 0) {
        setStatusMessage(
          `월간 계획 생성 완료. 브리프 반영 ${fillResult.appliedSlots}개, 유지 ${fillResult.skippedSlots}개, 실패 일자 ${fillResult.failedDays}건`,
        );
        return;
      }
      setStatusMessage(
        `월간 계획과 브리프 자동 채우기 완료. 반영 ${fillResult.appliedSlots}개, 유지 ${fillResult.skippedSlots}개`,
      );
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "월간 계획과 브리프를 다시 만들지 못했습니다.");
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

  async function handleRunDayAnalysis() {
    if (!selectedDay) return;
    try {
      setStatusMessage("일별 CTR 분석을 실행하는 중입니다.");
      const response = await runPlannerDayBriefAnalysis(selectedDay.id, {
        promptOverride: analysisPromptOverride || null,
      });
      await loadBriefRuns(selectedDay, response.run.id);
      setStatusMessage("일별 CTR 분석 결과를 불러왔습니다.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "일별 CTR 분석에 실패했습니다.");
    }
  }

  async function handleApplyDayAnalysis() {
    if (!selectedDay || !suggestionDrafts.length) return;
    try {
      setStatusMessage("분석 결과를 적용하는 중입니다. (빈 칸만 채우기)");
      const response = await applyPlannerDayBrief(selectedDay.id, {
        runId: selectedBriefRun?.id ?? null,
        slotSuggestions: suggestionDrafts.map((item) => {
          const confidence = item.confidence.trim() === "" ? null : Number(item.confidence);
          return {
            slotId: item.slotId,
            topic: item.topic || null,
            audience: item.audience || null,
            informationLevel: item.informationLevel || null,
            extraContext: item.extraContext || null,
            expectedCtrLift: item.expectedCtrLift || null,
            confidence: Number.isFinite(confidence as number) ? (confidence as number) : null,
            signalSource: item.signalSource || null,
            reason: item.reason || null,
          };
        }),
      });
      await loadCalendar(selectedDay.planDate);
      await loadBriefRuns(selectedDay, response.runId ?? selectedBriefRun?.id ?? null);
      setStatusMessage(`적용 완료: ${response.appliedSlotIds.length}개 반영, ${response.skippedSlotIds.length}개 유지`);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "분석 결과 적용에 실패했습니다.");
    }
  }

  function updateSuggestionDraft(slotId: number, key: keyof BriefSuggestionDraft, value: string) {
    setSuggestionDrafts((current) =>
      current.map((item) => (item.slotId === slotId ? { ...item, [key]: value } : item)),
    );
  }

  function updateCategoryRuleDraft(categoryKey: string, patch: Partial<CategoryRuleDraft>) {
    setCategoryRuleDrafts((current) =>
      current.map((item) => (item.categoryKey === categoryKey ? { ...item, ...patch } : item)),
    );
  }

  function toggleCategoryWeekday(categoryKey: string, weekday: number) {
    setCategoryRuleDrafts((current) =>
      current.map((item) => {
        if (item.categoryKey !== categoryKey) return item;
        const weekdaySet = new Set(item.weekdays);
        if (weekdaySet.has(weekday)) weekdaySet.delete(weekday);
        else weekdaySet.add(weekday);
        return {
          ...item,
          weekdays: Array.from(weekdaySet).sort((left, right) => left - right),
        };
      }),
    );
  }

  async function handleSaveCategoryRules() {
    if (!selectedChannelId) return;
    try {
      setStatusMessage("카테고리 배정 규칙을 저장하고 달력을 재정렬하는 중입니다.");
      const payload: PlannerCategoryRuleUpdateRequest[] = categoryRuleDrafts.map((item) => {
        const weeklyValue = item.weeklyTarget.trim();
        return {
          categoryKey: item.categoryKey,
          planningMode: item.planningMode,
          weeklyTarget:
            item.planningMode === "weekly" && weeklyValue !== "" && Number.isFinite(Number(weeklyValue))
              ? Math.max(1, Math.min(7, Number(weeklyValue)))
              : null,
          weekdays: item.planningMode === "weekdays" ? item.weekdays : [],
        };
      });
      await updatePlannerCategoryRules(selectedChannelId, payload);
      await loadCalendar(selectedDay?.planDate ?? null);
      setStatusMessage("카테고리 배정 규칙을 저장했습니다.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "카테고리 배정 규칙 저장에 실패했습니다.");
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
    <div className="space-y-3 rounded-[24px] bg-[#f5f7ff] p-3.5 text-slate-900 shadow-[0_24px_80px_rgba(15,23,42,0.08)] md:p-4">
      <section className="rounded-[22px] bg-white p-3.5 shadow-sm">
        <div className="grid gap-2.5 xl:grid-cols-[minmax(140px,168px)_minmax(220px,1fr)_150px_minmax(240px,320px)_auto] xl:items-end">
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
          <div className="grid gap-2 rounded-[18px] bg-slate-50 p-2.5 md:grid-cols-3">
            <MetricCard label="목표 슬롯" value={`${monthSummary.target}건`} />
            <MetricCard label="생성 완료" value={`${monthSummary.generated}건`} />
            <MetricCard label="발행 완료" value={`${monthSummary.published}건`} />
          </div>
          <div className="flex flex-wrap gap-2 xl:justify-end">
            <Link href="/admin" className="rounded-full bg-slate-100 px-3.5 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-200">
              관리자 설정
            </Link>
            <button type="button" onClick={handleRebuildMonthPlan} className="rounded-full bg-slate-950 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-slate-800">
              월간 계획 다시 만들기
            </button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-slate-600">
          <span className="font-semibold text-slate-900">현재 기준</span>
          {selectedChannel ? <FlagPill tone="slate">{selectedChannel.name}</FlagPill> : null}
          <FlagPill tone="slate">{providerTypeLabel(selectedType)}</FlagPill>
          <span>{formatMonthLabel(month)} 운영 계획</span>
        </div>
        {statusMessage ? <p className="mt-4 text-sm text-indigo-600">{statusMessage}</p> : null}
      </section>

      <section className="grid gap-3 xl:grid-cols-[minmax(0,1.92fr)_minmax(340px,0.72fr)]">
        <div className="rounded-[22px] bg-white p-3.5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold tracking-[0.16em] text-slate-400">월간 캘린더</p>
              <h2 className="mt-1 text-xl font-semibold text-slate-950">{formatMonthLabel(month)}</h2>
              <p className="mt-1 text-[13px] text-slate-500">{selectedChannel ? `${selectedChannel.name} 기준 월간 계획` : "선택한 채널 기준 월간 계획"}</p>
            </div>
            {selectedChannel ? <FlagPill tone="slate">{selectedChannel.name}</FlagPill> : null}
          </div>
          <div className="mt-3 overflow-x-auto">
            <div className="min-w-[760px]">
              <div className="grid grid-cols-7 gap-1.5 text-[11px] font-semibold tracking-[0.14em] text-slate-400">
                {["월", "화", "수", "목", "금", "토", "일"].map((label) => (
                  <div key={label} className="px-2">{label}</div>
                ))}
              </div>
              <div className="mt-2 grid grid-cols-7 gap-1.5">
                {monthCells.map((cell, index) => {
                  if (!cell) return <div key={`empty-${index}`} className="min-h-[108px] rounded-[18px] bg-transparent" />;
                  const day = cell.plannerDay;
                  const isSelected = cell.dateKey === selectedDay?.planDate;
                  const chips = Object.entries(day?.categoryMix ?? {}).slice(0, 3);
                  return (
                    <button
                      key={cell.dateKey}
                      type="button"
                      onClick={() => setQuery({ selectedDate: cell.dateKey, panel: "day" })}
                      className={`min-h-[108px] rounded-[18px] p-2.5 text-left transition ${isSelected ? "bg-indigo-50 ring-2 ring-indigo-200" : "bg-slate-50 hover:bg-slate-100"}`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="text-[15px] font-semibold text-slate-950">{cell.dayNumber}</p>
                          <p className="mt-0.5 text-[11px] text-slate-500">{formatWeekday(cell.dateKey)}요일</p>
                        </div>
                        <FlagPill tone="slate">{day?.slotCount ?? 0} 슬롯</FlagPill>
                      </div>
                      <div className="mt-2.5 space-y-1 text-[11px] text-slate-500">
                        <p>생성 완료 {day?.slots.filter((slot) => slot.status === "generated" || slot.status === "published").length ?? 0}</p>
                        <div className="flex flex-wrap gap-1">
                          {chips.length ? chips.map(([key, count]) => (
                            <span key={key} className="rounded-full px-2 py-1 text-[10px] font-medium text-slate-700" style={{ backgroundColor: `${categoryMap.get(key)?.color ?? "#cbd5e1"}33` }}>
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
          <div className="rounded-[22px] bg-white p-2.5 shadow-sm">
            <div className="flex items-center gap-1 rounded-full bg-slate-100 p-1 text-[12px]">
              <button type="button" onClick={() => setQuery({ panel: "day" })} className={`rounded-full px-3 py-1.5 font-semibold ${selectedTab === "day" ? "bg-white text-slate-950 shadow-sm" : "text-slate-600"}`}>
                일간 계획
              </button>
              <button type="button" onClick={() => setQuery({ panel: "rules" })} className={`rounded-full px-3 py-1.5 font-semibold ${selectedTab === "rules" ? "bg-white text-slate-950 shadow-sm" : "text-slate-600"}`}>
                카테고리 규칙
              </button>
              <button type="button" onClick={() => setQuery({ panel: "month" })} className={`rounded-full px-3 py-1.5 font-semibold ${selectedTab === "month" ? "bg-white text-slate-950 shadow-sm" : "text-slate-600"}`}>
                월간 집계
              </button>
            </div>
          </div>

          {selectedTab === "day" ? (
            <div className="space-y-4 rounded-[22px] bg-white p-3.5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold tracking-[0.16em] text-slate-400">선택 날짜</p>
                  <h2 className="mt-1 text-xl font-semibold text-slate-950">{selectedDay ? `${formatDayLabel(selectedDay.planDate)} · ${formatWeekday(selectedDay.planDate)}요일` : "날짜를 선택하세요"}</h2>
                </div>
                <button type="button" onClick={handleAddSlot} disabled={!selectedDay || !draft} className="rounded-full bg-slate-950 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300">
                  슬롯 추가
                </button>
              </div>

              <div className="rounded-[20px] border border-slate-200 bg-slate-50 p-3.5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-950">일별 CTR 분석</p>
                    <p className="mt-1 text-[13px] text-slate-500">각 채널의 1단계 주제 발굴 프롬프트를 기준으로, 관리용 브리프는 채널 언어와 무관하게 모두 한글로 제안하고 빈 칸만 반영합니다.</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={handleRunDayAnalysis}
                      disabled={!selectedDay}
                        className="rounded-full bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-indigo-200"
                    >
                      분석 실행
                    </button>
                    <button
                      type="button"
                      onClick={handleRunDayAnalysis}
                      disabled={!selectedDay}
                        className="rounded-full bg-slate-800 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      분석 재실행
                    </button>
                    <button
                      type="button"
                      onClick={handleApplyDayAnalysis}
                      disabled={!selectedDay || !suggestionDrafts.length}
                        className="rounded-full bg-emerald-600 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-emerald-200"
                    >
                      적용(빈 칸만 채우기)
                    </button>
                  </div>
                </div>

                <div className="mt-4 grid gap-4">
                  <Field label="분석 프롬프트 오버라이드">
                    <textarea
                      value={analysisPromptOverride}
                      onChange={(event) => setAnalysisPromptOverride(event.target.value)}
                      rows={3}
                      placeholder="추가 지시가 있으면 입력하세요. 비우면 기본 템플릿만 사용합니다."
                      className={textareaClass()}
                    />
                  </Field>

                  <Field label="분석 실행 이력">
                    <select
                      value={selectedBriefRun?.id ?? ""}
                      onChange={(event) => setSelectedBriefRunId(event.target.value ? Number(event.target.value) : null)}
                      className={inputClass()}
                    >
                        {!briefRuns.length ? <option value="">이력이 없습니다</option> : null}
                        {briefRuns.map((run) => (
                          <option key={run.id} value={run.id}>
                          #{run.id} · {run.status} · {run.model ?? "모델 정보 없음"} · {run.createdAt.slice(0, 16).replace("T", " ")}
                          </option>
                        ))}
                      </select>
                    </Field>

                  {selectedBriefRun ? (
                    <details className="rounded-[18px] border border-slate-200 bg-white p-3">
                      <summary className="cursor-pointer text-sm font-semibold text-slate-900">원본 프롬프트 / 모델 응답</summary>
                      <div className="mt-4 grid gap-4">
                        <Field label="실행 프롬프트">
                          <textarea value={selectedBriefRun.prompt} readOnly rows={6} className={textareaClass()} />
                        </Field>
                        <Field label="모델 원응답(JSON)">
                          <textarea
                            value={JSON.stringify(selectedBriefRun.rawResponse ?? {}, null, 2)}
                            readOnly
                            rows={8}
                            className={`${textareaClass()} font-mono text-xs`}
                          />
                        </Field>
                      </div>
                    </details>
                  ) : null}

                  {suggestionDrafts.length ? (
                    <div className="space-y-3">
                      {suggestionDrafts.map((item) => (
                        <div key={item.slotId} className="rounded-[18px] border border-slate-200 bg-white p-3.5">
                          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                            <p className="text-sm font-semibold text-slate-900">
                              슬롯 #{item.slotOrder} · {item.categoryKey || "카테고리 미지정"}
                            </p>
                            <FlagPill tone="slate">슬롯 ID {item.slotId}</FlagPill>
                          </div>
                          <div className="grid gap-3 md:grid-cols-2">
                            <Field label="주제">
                              <input value={item.topic} onChange={(event) => updateSuggestionDraft(item.slotId, "topic", event.target.value)} className={inputClass()} />
                            </Field>
                            <Field label="독자 타겟">
                              <input value={item.audience} onChange={(event) => updateSuggestionDraft(item.slotId, "audience", event.target.value)} className={inputClass()} />
                            </Field>
                            <Field label="정보 수준">
                              <input value={item.informationLevel} onChange={(event) => updateSuggestionDraft(item.slotId, "informationLevel", event.target.value)} className={inputClass()} />
                            </Field>
                            <Field label="예상 CTR 개선">
                              <input value={item.expectedCtrLift} onChange={(event) => updateSuggestionDraft(item.slotId, "expectedCtrLift", event.target.value)} className={inputClass()} />
                            </Field>
                            <Field label="신뢰도 (0~1)">
                              <input value={item.confidence} onChange={(event) => updateSuggestionDraft(item.slotId, "confidence", event.target.value)} className={inputClass()} />
                            </Field>
                            <Field label="신호 출처">
                              <input value={item.signalSource} onChange={(event) => updateSuggestionDraft(item.slotId, "signalSource", event.target.value)} className={inputClass()} />
                            </Field>
                          </div>
                          <div className="mt-3 grid gap-3">
                            <Field label="기타 정보">
                              <textarea value={item.extraContext} onChange={(event) => updateSuggestionDraft(item.slotId, "extraContext", event.target.value)} rows={3} className={textareaClass()} />
                            </Field>
                            <Field label="근거">
                              <textarea value={item.reason} onChange={(event) => updateSuggestionDraft(item.slotId, "reason", event.target.value)} rows={2} className={textareaClass()} />
                            </Field>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-[20px] border border-dashed border-slate-200 bg-white px-4 py-6 text-sm text-slate-500">
                      분석 이력을 선택하거나 분석 실행 버튼으로 추천값을 생성하세요.
                    </div>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                {(selectedDay?.slots ?? []).length ? (
                  selectedDay?.slots.map((slot) => (
                    <button key={slot.id} type="button" onClick={() => setSelectedSlotId(slot.id)} className={`flex w-full items-center justify-between rounded-[18px] border px-3.5 py-2.5 text-left transition ${selectedSlot?.id === slot.id ? "border-indigo-200 bg-indigo-50" : "border-slate-200 bg-slate-50 hover:bg-slate-100"}`}>
                      <div>
                        <p className="text-sm font-semibold text-slate-950">{slot.briefTopic || "주제 미입력"}</p>
                        <p className="mt-1 text-xs text-slate-500">{slot.categoryName || "카테고리 미선택"} · {toDatetimeLocal(slot.scheduledFor).slice(11, 16) || "시간 미정"}</p>
                      </div>
                      <FlagPill tone="slate">{statusText(slot.status)}</FlagPill>
                    </button>
                  ))
                ) : (
                  <div className="rounded-[20px] border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">선택한 날짜에 아직 슬롯이 없습니다.</div>
                )}
              </div>

              {draft ? (
                <div className="space-y-4 rounded-[20px] border border-slate-200 bg-slate-50 p-3.5">
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

                    <details className="rounded-[18px] border border-slate-200 bg-white p-3">
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
                      <button type="button" onClick={handleSaveSlot} disabled={!selectedSlot} className="rounded-full bg-slate-950 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300">
                        슬롯 저장
                      </button>
                      <button type="button" onClick={handleGenerateSlot} disabled={!selectedSlot} className="rounded-full bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-indigo-200">
                        실행
                      </button>
                      <button type="button" onClick={handleCancelSlot} disabled={!selectedSlot} className="rounded-full bg-rose-50 px-3.5 py-2 text-xs font-semibold text-rose-700 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:text-rose-300">
                        취소
                      </button>
                    </div>
                  </div>
                ) : null}

              <div className="rounded-[20px] border border-slate-200 bg-slate-50 p-3.5">
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
          ) : selectedTab === "rules" ? (
            <div className="space-y-4 rounded-[22px] bg-white p-3.5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold tracking-[0.16em] text-slate-400">카테고리 배정 규칙</p>
                  <h2 className="mt-1 text-lg font-semibold text-slate-950">주간 횟수 / 요일별 배정</h2>
                  <p className="mt-1 text-[12px] text-slate-500">
                    저장하면 현재 월의 미실행 슬롯 카테고리가 즉시 다시 배정됩니다. Cloudflare처럼 카테고리가 많은 채널은 검색으로 빠르게 찾을 수 있습니다.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleSaveCategoryRules}
                  className="rounded-full bg-slate-950 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-slate-800"
                >
                  규칙 저장
                </button>
              </div>

              <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
                <Field label="카테고리 검색">
                  <input
                    value={categoryRuleFilter}
                    onChange={(event) => setCategoryRuleFilter(event.target.value)}
                    placeholder="카테고리명 또는 키워드 검색"
                    className={inputClass()}
                  />
                </Field>
                <div className="rounded-[16px] bg-slate-50 px-3 py-2.5 text-[12px] text-slate-600">
                  {selectedChannel ? `${selectedChannel.name} · ${categories.length}개 카테고리` : `${categories.length}개 카테고리`}
                </div>
              </div>

              <div className="max-h-[720px] space-y-2 overflow-y-auto pr-1">
                {filteredCategoryRuleDrafts.length ? (
                  filteredCategoryRuleDrafts.map((item) => {
                    const category = categoryMap.get(item.categoryKey);
                    return (
                      <div key={item.categoryKey} className="rounded-[18px] border border-slate-200 bg-slate-50 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: category?.color ?? "#cbd5e1" }} />
                            <div>
                              <p className="text-sm font-semibold text-slate-950">{category?.name ?? item.categoryKey}</p>
                              <p className="text-[11px] text-slate-500">{item.categoryKey}</p>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <select
                              value={item.planningMode}
                              onChange={(event) =>
                                updateCategoryRuleDraft(item.categoryKey, {
                                  planningMode: event.target.value as CategoryRuleDraft["planningMode"],
                                  weeklyTarget: event.target.value === "weekly" ? item.weeklyTarget || "1" : "",
                                  weekdays: event.target.value === "weekdays" ? item.weekdays : [],
                                })
                              }
                              className={inputClass()}
                            >
                              <option value="auto">자동 배정</option>
                              <option value="weekly">주간 횟수</option>
                              <option value="weekdays">요일 고정</option>
                            </select>
                          </div>
                        </div>

                        {item.planningMode === "weekly" ? (
                          <div className="mt-3 grid gap-3 md:grid-cols-[140px_minmax(0,1fr)] md:items-end">
                            <Field label="주간 횟수">
                              <select
                                value={item.weeklyTarget || "1"}
                                onChange={(event) => updateCategoryRuleDraft(item.categoryKey, { weeklyTarget: event.target.value })}
                                className={inputClass()}
                              >
                                {Array.from({ length: 7 }, (_value, index) => (
                                  <option key={index + 1} value={String(index + 1)}>
                                    주 {index + 1}회
                                  </option>
                                ))}
                              </select>
                            </Field>
                            <p className="text-[12px] leading-5 text-slate-500">
                              이 카테고리를 해당 채널에서 한 주에 몇 번 넣을지 지정합니다. 나머지 슬롯은 자동 배정 카테고리로 채워집니다.
                            </p>
                          </div>
                        ) : null}

                        {item.planningMode === "weekdays" ? (
                          <div className="mt-3 space-y-2">
                            <p className="text-[11px] font-semibold text-slate-500">요일 선택</p>
                            <div className="flex flex-wrap gap-1.5">
                              {Array.from({ length: 7 }, (_value, weekday) => {
                                const active = item.weekdays.includes(weekday);
                                return (
                                  <button
                                    key={weekday}
                                    type="button"
                                    onClick={() => toggleCategoryWeekday(item.categoryKey, weekday)}
                                    className={`rounded-full px-2.5 py-1.5 text-[11px] font-semibold transition ${
                                      active ? "bg-slate-950 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100"
                                    }`}
                                  >
                                    {weekdayShortLabel(weekday)}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        ) : null}

                        {item.planningMode === "auto" ? (
                          <p className="mt-3 text-[12px] text-slate-500">
                            고정 규칙 없이 자동 가중치 배정으로 들어갑니다.
                          </p>
                        ) : null}
                      </div>
                    );
                  })
                ) : (
                  <div className="rounded-[18px] border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                    검색 결과가 없습니다.
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-4 rounded-[22px] bg-white p-3.5 shadow-sm">
              <div>
                <p className="text-[11px] font-semibold tracking-[0.16em] text-slate-400">월간 집계</p>
                <h2 className="mt-1 text-xl font-semibold text-slate-950">카테고리 배분 현황</h2>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {monthCategoryStats.map((category) => (
                  <div key={category.key} className="rounded-[18px] border border-slate-200 bg-slate-50 p-3.5">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <span className="h-3 w-3 rounded-full" style={{ backgroundColor: category.color ?? "#cbd5e1" }} />
                        <p className="text-sm font-semibold text-slate-950">{category.name}</p>
                      </div>
                      <FlagPill tone="slate">
                        {category.planningMode === "weekly"
                          ? `주 ${category.weeklyTarget ?? 0}회`
                          : category.planningMode === "weekdays"
                            ? `${(category.weekdays ?? []).map(weekdayShortLabel).join("/") || "요일 없음"}`
                            : `가중치 ${category.weight}`}
                      </FlagPill>
                    </div>
                    <p className="mt-3 text-sm text-slate-600">배정 {category.planned}건 / 생성 완료 {category.actual}건</p>
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
      <span className="text-[11px] font-semibold text-slate-500">{label}</span>
      {children}
    </label>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[16px] bg-white px-3 py-2.5 shadow-sm">
      <p className="text-[10px] font-semibold tracking-[0.12em] text-slate-400">{label}</p>
      <p className="mt-1.5 text-base font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function ReadonlyItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[16px] bg-white px-3 py-2.5">
      <p className="text-[10px] font-semibold tracking-[0.12em] text-slate-400">{label}</p>
      <p className="mt-1.5 text-[13px] font-medium text-slate-900">{value}</p>
    </div>
  );
}

function FlagPill({ children, tone }: { children: ReactNode; tone: "slate" }) {
  return <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-700">{children}</span>;
}

function inputClass() {
  return "h-[40px] w-full rounded-[18px] border border-slate-200 bg-white px-3 text-[13px] text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200";
}

function textareaClass() {
  return "w-full rounded-[18px] border border-slate-200 bg-white px-3 py-2.5 text-[13px] leading-5 text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200";
}

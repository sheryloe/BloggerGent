"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  buildPlannerMonthPlan,
  cancelPlannerSlot,
  createPlannerSlot,
  generatePlannerSlot,
  getChannelPromptFlow,
  getPlannerCalendar,
  updatePlannerSlot,
} from "@/lib/api";
import type {
  BlogRead,
  PlannerCalendarRead,
  PlannerCategoryRead,
  PlannerDayRead,
  PlannerSlotRead,
  PromptFlowRead,
} from "@/lib/types";

type PlannerManagerProps = {
  blogs: BlogRead[];
};

type DetailTab = "day" | "week" | "month";

type SlotDraft = {
  themeId: number;
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

type MonthCategoryStat = {
  key: string;
  name: string;
  color: string;
  planned: number;
  actual: number;
  gap: number;
};

function defaultMonth() {
  return new Date().toISOString().slice(0, 7);
}

function parseBlogId(value: string | null, fallback: number) {
  if (!value) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseDetailTab(value: string | null): DetailTab {
  if (value === "day" || value === "week" || value === "month") return value;
  return "day";
}

function parseDateKey(value: string) {
  return new Date(`${value}T12:00:00`);
}

function formatDateKey(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatKoreanDate(value: string) {
  const date = parseDateKey(value);
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

function formatWeekday(value: string) {
  const date = parseDateKey(value);
  const dayNames = ["일", "월", "화", "수", "목", "금", "토"];
  return dayNames[date.getDay()];
}

function formatWeekRange(anchorDate: string) {
  const days = buildWeekDays(anchorDate);
  if (!days.length) return "";
  const start = parseDateKey(days[0]);
  const end = parseDateKey(days[6]);
  return `${start.getMonth() + 1}월 ${start.getDate()}일 - ${end.getMonth() + 1}월 ${end.getDate()}일`;
}

function toDatetimeLocal(value?: string | null) {
  if (!value) return "";
  return value.slice(0, 16);
}

function withSeconds(value: string) {
  if (!value) return value;
  return value.length === 16 ? `${value}:00` : value;
}

function monthLabel(month: string) {
  const [yearText, monthText] = month.split("-");
  return `${yearText}년 ${Number(monthText)}월`;
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

function buildWeekDays(anchorDate: string) {
  const anchor = parseDateKey(anchorDate);
  const monday = new Date(anchor);
  monday.setDate(anchor.getDate() - ((anchor.getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, index) => {
    const next = new Date(monday);
    next.setDate(monday.getDate() + index);
    return formatDateKey(next);
  });
}

function dayCompletion(day: PlannerDayRead | null) {
  if (!day || day.slotCount === 0) return 0;
  const completed = day.slots.filter((slot) => slot.articleId || ["generated", "published"].includes(slot.status)).length;
  return Math.round((completed / day.slotCount) * 100);
}

function generatedCount(day: PlannerDayRead | null) {
  if (!day) return 0;
  return day.slots.filter((slot) => slot.articleId || ["generated", "published"].includes(slot.status)).length;
}

function publishedCount(day: PlannerDayRead | null) {
  if (!day) return 0;
  return day.slots.filter((slot) => slot.articlePublishedUrl || slot.articlePublishStatus === "published" || slot.articlePublishStatus === "live").length;
}

function statusText(status: string) {
  const map: Record<string, string> = {
    planned: "계획",
    brief_ready: "준비 완료",
    queued: "대기",
    generating: "생성 중",
    generated: "생성 완료",
    published: "발행 완료",
    canceled: "취소",
  };
  return map[status] ?? status;
}

function scoreText(value: number | null | undefined) {
  if (value === null || value === undefined) return "N/A";
  return Number(value).toFixed(1);
}

function scoreTone(value: number | null | undefined) {
  if (value === null || value === undefined) return "bg-slate-100 text-slate-500";
  if (value >= 80) return "bg-emerald-50 text-emerald-700";
  if (value >= 60) return "bg-amber-50 text-amber-700";
  return "bg-rose-50 text-rose-700";
}

function publishTone(status: string | null | undefined) {
  if (!status) return "bg-slate-100 text-slate-500";
  if (status === "published" || status === "live") return "bg-emerald-50 text-emerald-700";
  if (status === "draft") return "bg-amber-50 text-amber-700";
  return "bg-slate-100 text-slate-600";
}

function completionCount(slot: PlannerSlotRead) {
  return [slot.briefTopic, slot.briefAudience, slot.briefInformationLevel, slot.briefExtraContext].filter(Boolean).length;
}

function buildMonthCategoryStats(categories: PlannerCategoryRead[], days: PlannerDayRead[]) {
  const actualMap = new Map<string, number>();
  const totalTarget = days.reduce((sum, day) => sum + day.targetPostCount, 0);
  const totalWeight = categories.reduce((sum, category) => sum + category.weight, 0) || 1;

  for (const day of days) {
    for (const slot of day.slots) {
      const key = slot.categoryKey ?? slot.themeKey ?? "";
      if (!key) continue;
      actualMap.set(key, (actualMap.get(key) ?? 0) + 1);
    }
  }

  return categories
    .filter((category) => category.isActive)
    .map((category) => {
      const planned = Math.round((totalTarget * category.weight) / totalWeight);
      const actual = actualMap.get(category.key) ?? 0;
      return {
        key: category.key,
        name: category.name,
        color: category.color ?? "#94a3b8",
        planned,
        actual,
        gap: planned - actual,
      } satisfies MonthCategoryStat;
    })
    .sort((left, right) => right.gap - left.gap);
}

export function PlannerManager({ blogs }: PlannerManagerProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const panelRef = useRef<HTMLDivElement | null>(null);

  const today = useMemo(() => new Date(), []);
  const todayMonth = useMemo(() => defaultMonth(), []);
  const todayDateKey = useMemo(() => formatDateKey(today), [today]);

  const blogId = parseBlogId(searchParams.get("blog"), blogs[0]?.id ?? 0);
  const month = searchParams.get("month") ?? todayMonth;
  const selectedDateFromQuery = searchParams.get("selectedDate");
  const detailTab = parseDetailTab(searchParams.get("detailTab"));

  const [calendar, setCalendar] = useState<PlannerCalendarRead | null>(null);
  const [status, setStatus] = useState("");
  const [selectedSlotId, setSelectedSlotId] = useState<number | null>(null);
  const [draft, setDraft] = useState<SlotDraft | null>(null);
  const [draggingSlotId, setDraggingSlotId] = useState<number | null>(null);
  const [dragOverSlotId, setDragOverSlotId] = useState<number | null>(null);
  const [promptFlow, setPromptFlow] = useState<PromptFlowRead | null>(null);
  const [mobileSheetOpen, setMobileSheetOpen] = useState(false);

  const categories = useMemo(() => (calendar?.categories?.length ? calendar.categories : calendar?.themes ?? []), [calendar]);
  const categoryColorMap = useMemo(() => new Map(categories.map((item) => [item.key, item.color ?? "#94a3b8"])), [categories]);
  const monthCells = useMemo(() => buildMonthCells(month, calendar?.days ?? []), [calendar, month]);

  const selectedDay = useMemo(() => {
    if (!calendar?.days.length) return null;
    if (selectedDateFromQuery) {
      return calendar.days.find((day) => day.planDate === selectedDateFromQuery) ?? null;
    }
    return calendar.days.find((day) => day.planDate === todayDateKey) ?? calendar.days[0] ?? null;
  }, [calendar, selectedDateFromQuery, todayDateKey]);

  const orderedSlots = useMemo(() => {
    return [...(selectedDay?.slots ?? [])].sort((left, right) => left.slotOrder - right.slotOrder || left.id - right.id);
  }, [selectedDay]);

  const selectedSlot = useMemo(() => {
    if (!orderedSlots.length) return null;
    if (selectedSlotId) {
      return orderedSlots.find((slot) => slot.id === selectedSlotId) ?? orderedSlots[0] ?? null;
    }
    return orderedSlots[0] ?? null;
  }, [orderedSlots, selectedSlotId]);

  const selectedCategoryName = useMemo(() => {
    if (!draft) return "미정";
    return categories.find((category) => category.id === draft.themeId)?.name ?? selectedSlot?.categoryName ?? selectedSlot?.themeName ?? "미정";
  }, [categories, draft, selectedSlot]);

  const weekDateKeys = useMemo(() => buildWeekDays(selectedDay?.planDate ?? todayDateKey), [selectedDay?.planDate, todayDateKey]);
  const weekDays = useMemo(
    () => weekDateKeys.map((dateKey) => calendar?.days.find((day) => day.planDate === dateKey) ?? null),
    [calendar, weekDateKeys],
  );

  const monthCategoryStats = useMemo(() => buildMonthCategoryStats(categories, calendar?.days ?? []), [calendar, categories]);

  const monthSummary = useMemo(() => {
    const days = calendar?.days ?? [];
    return {
      target: days.reduce((sum, day) => sum + day.targetPostCount, 0),
      slots: days.reduce((sum, day) => sum + day.slotCount, 0),
      generated: days.reduce((sum, day) => sum + generatedCount(day), 0),
      published: days.reduce((sum, day) => sum + publishedCount(day), 0),
    };
  }, [calendar]);

  const promptRecommendations = useMemo(() => {
    if (!promptFlow || !draft) return [];
    const preferredStages = ["article_generation", "topic_discovery", "publishing"];
    return promptFlow.steps
      .filter((step) => preferredStages.includes(step.stageType) && step.promptEnabled)
      .map((step) => ({
        id: step.id,
        stageLabel: step.stageLabel || step.stageType,
        title: step.name,
        content: step.promptTemplate,
        excerpt: step.promptTemplate.slice(0, 220).trim(),
        context: [`카테고리: ${selectedCategoryName}`, `글 주제: ${draft.briefTopic || "미입력"}`, `독자 타겟: ${draft.briefAudience || "미입력"}`, `정보 수준: ${draft.briefInformationLevel || "미입력"}`].join(" / "),
      }));
  }, [draft, promptFlow, selectedCategoryName]);

  function setQuery(updates: Record<string, string | null | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === undefined || value === "") next.delete(key);
      else next.set(key, value);
    }
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  function focusDetailPanel() {
    setMobileSheetOpen(true);
    setTimeout(() => {
      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 40);
  }

  async function loadCalendar(preferredDate?: string | null) {
    if (!blogId) return;
    try {
      setStatus("플래너를 불러오는 중입니다.");
      const next = await getPlannerCalendar(blogId, month);
      setCalendar(next);
      setStatus("");

      const availableDates = next.days.map((day) => day.planDate);
      const fallbackDate = preferredDate && availableDates.includes(preferredDate)
        ? preferredDate
        : availableDates.includes(todayDateKey)
          ? todayDateKey
          : availableDates[0] ?? null;

      if (fallbackDate && fallbackDate !== selectedDateFromQuery) {
        setQuery({ selectedDate: fallbackDate });
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "플래너를 불러오지 못했습니다.");
    }
  }

  useEffect(() => {
    void loadCalendar(selectedDateFromQuery);
  }, [blogId, month]);

  useEffect(() => {
    if (!blogId) return;
    getChannelPromptFlow(`blogger:${blogId}`)
      .then(setPromptFlow)
      .catch(() => setPromptFlow(null));
  }, [blogId]);

  useEffect(() => {
    if (!selectedDay) {
      setSelectedSlotId(null);
      return;
    }
    if (!selectedSlotId || !selectedDay.slots.some((slot) => slot.id === selectedSlotId)) {
      setSelectedSlotId(selectedDay.slots[0]?.id ?? null);
    }
  }, [selectedDay, selectedSlotId]);

  useEffect(() => {
    if (selectedSlot) {
      setDraft({
        themeId: selectedSlot.categoryId ?? selectedSlot.themeId,
        scheduledFor: toDatetimeLocal(selectedSlot.scheduledFor),
        briefTopic: selectedSlot.briefTopic ?? "",
        briefAudience: selectedSlot.briefAudience ?? "",
        briefInformationLevel: selectedSlot.briefInformationLevel ?? "",
        briefExtraContext: selectedSlot.briefExtraContext ?? "",
      });
      return;
    }
    if (selectedDay && categories[0]) {
      setDraft({
        themeId: categories[0].id,
        scheduledFor: `${selectedDay.planDate}T09:00`,
        briefTopic: "",
        briefAudience: "",
        briefInformationLevel: "",
        briefExtraContext: "",
      });
      return;
    }
    setDraft(null);
  }, [selectedSlot, selectedDay, categories]);

  async function handleRebuildMonthPlan() {
    try {
      setStatus("월간 계획을 다시 만드는 중입니다.");
      const next = await buildPlannerMonthPlan({ blogId, month, overwrite: true });
      setCalendar(next);
      const fallbackDate = next.days.find((day) => day.planDate === todayDateKey)?.planDate ?? next.days[0]?.planDate ?? null;
      if (fallbackDate) {
        setQuery({ selectedDate: fallbackDate, detailTab: "month" });
      }
      setStatus("월간 계획을 다시 만들었습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "월간 계획을 다시 만들지 못했습니다.");
    }
  }

  async function handleCreateSlot() {
    if (!selectedDay || !draft) return;
    try {
      setStatus("새 슬롯을 추가하는 중입니다.");
      const created = await createPlannerSlot({
        planDayId: selectedDay.id,
        themeId: draft.themeId,
        scheduledFor: withSeconds(draft.scheduledFor || `${selectedDay.planDate}T09:00`),
        briefTopic: draft.briefTopic,
        briefAudience: draft.briefAudience,
        briefInformationLevel: draft.briefInformationLevel,
        briefExtraContext: draft.briefExtraContext,
      });
      await loadCalendar(selectedDay.planDate);
      setSelectedSlotId(created.id);
      setStatus("새 슬롯을 추가했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "새 슬롯을 추가하지 못했습니다.");
    }
  }

  async function handleSaveSlot() {
    if (!selectedSlot || !draft) return;
    try {
      setStatus("슬롯을 저장하는 중입니다.");
      await updatePlannerSlot(selectedSlot.id, {
        themeId: draft.themeId,
        scheduledFor: withSeconds(draft.scheduledFor),
        briefTopic: draft.briefTopic,
        briefAudience: draft.briefAudience,
        briefInformationLevel: draft.briefInformationLevel,
        briefExtraContext: draft.briefExtraContext,
      });
      await loadCalendar(selectedDay?.planDate ?? null);
      setStatus("슬롯을 저장했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "슬롯을 저장하지 못했습니다.");
    }
  }

  async function handleGenerateSlot() {
    if (!selectedSlot) return;
    try {
      if (draft) {
        await updatePlannerSlot(selectedSlot.id, {
          themeId: draft.themeId,
          scheduledFor: withSeconds(draft.scheduledFor),
          briefTopic: draft.briefTopic,
          briefAudience: draft.briefAudience,
          briefInformationLevel: draft.briefInformationLevel,
          briefExtraContext: draft.briefExtraContext,
        });
      }
      setStatus("선택한 슬롯 생성을 시작합니다.");
      await generatePlannerSlot(selectedSlot.id);
      await loadCalendar(selectedDay?.planDate ?? null);
      setStatus("슬롯 생성을 요청했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "슬롯 생성을 요청하지 못했습니다.");
    }
  }

  async function handleCancelSlot() {
    if (!selectedSlot) return;
    try {
      setStatus("선택한 슬롯을 취소하는 중입니다.");
      await cancelPlannerSlot(selectedSlot.id);
      await loadCalendar(selectedDay?.planDate ?? null);
      setStatus("선택한 슬롯을 취소했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "슬롯을 취소하지 못했습니다.");
    }
  }

  async function handleDropSlot(targetSlotId: number) {
    if (!selectedDay || !draggingSlotId || draggingSlotId === targetSlotId) return;
    const current = [...orderedSlots];
    const fromIndex = current.findIndex((slot) => slot.id === draggingSlotId);
    const toIndex = current.findIndex((slot) => slot.id === targetSlotId);
    if (fromIndex < 0 || toIndex < 0) return;

    const [moved] = current.splice(fromIndex, 1);
    current.splice(toIndex, 0, moved);

    try {
      setStatus("같은 날짜 안에서 슬롯 순서를 정리하는 중입니다.");
      await Promise.all(current.map((slot, index) => updatePlannerSlot(slot.id, { slotOrder: index + 1 })));
      setDraggingSlotId(null);
      setDragOverSlotId(null);
      await loadCalendar(selectedDay.planDate);
      setStatus("슬롯 순서를 저장했습니다.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "슬롯 순서를 저장하지 못했습니다.");
    }
  }

  async function handleCopyPrompt(content: string) {
    try {
      await navigator.clipboard.writeText(content);
      setStatus("추천 프롬프트를 복사했습니다.");
    } catch {
      setStatus("클립보드 복사에 실패했습니다.");
    }
  }

  function handleInsertPrompt(content: string) {
    setDraft((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        briefExtraContext: prev.briefExtraContext ? `${prev.briefExtraContext}\n\n${content}` : content,
      };
    });
    setStatus("추천 프롬프트를 기타 정보에 삽입했습니다. 저장을 누르면 반영됩니다.");
  }

  function openDate(dateKey: string, nextTab?: DetailTab) {
    setQuery({ selectedDate: dateKey, detailTab: nextTab ?? detailTab });
    setSelectedSlotId(null);
    focusDetailPanel();
  }

  function quickSelect(mode: DetailTab) {
    setQuery({ month: todayMonth, selectedDate: todayDateKey, detailTab: mode });
    setSelectedSlotId(null);
    focusDetailPanel();
  }

  const canGenerate = !!draft?.scheduledFor && !!draft?.briefTopic && !!draft?.briefAudience && !!draft?.briefInformationLevel && !!draft?.briefExtraContext;

  const detailPanel = (
    <div className="flex h-full flex-col rounded-[28px] bg-[#eef2ff] p-5 text-slate-900 shadow-[0_18px_60px_rgba(15,23,42,0.08)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-500">상세 패널</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-900">{selectedDay ? formatKoreanDate(selectedDay.planDate) : "날짜를 선택하세요"}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            {selectedDay ? `선택 날짜 기준으로 일간 편집, 주간 흐름, 월간 집계를 나눠서 봅니다.` : "월간 캘린더에서 날짜를 누르면 우측에서 세부 정보를 확인합니다."}
          </p>
        </div>
        <div className="rounded-2xl bg-white px-4 py-3 text-xs leading-5 text-slate-500 shadow-sm">
          저장 기준은 일간입니다.
          <br />
          주간/월간은 같은 원본을 읽기 전용으로 보여줍니다.
        </div>
      </div>

      <div className="mt-5 grid grid-cols-3 gap-2 rounded-[24px] bg-white p-2 shadow-sm">
        <DetailTabButton active={detailTab === "day"} onClick={() => setQuery({ detailTab: "day" })} label="일간 계획" />
        <DetailTabButton active={detailTab === "week"} onClick={() => setQuery({ detailTab: "week" })} label="주간 흐름" />
        <DetailTabButton active={detailTab === "month"} onClick={() => setQuery({ detailTab: "month" })} label="월간 집계" />
      </div>

      <div className="mt-5 min-h-0 flex-1 overflow-y-auto">
        {detailTab === "day" ? (
          selectedDay ? (
            <div className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-3">
                <MiniMetric label="총 슬롯" value={`${selectedDay.slotCount}개`} />
                <MiniMetric label="생성 완료" value={`${generatedCount(selectedDay)}개`} />
                <MiniMetric label="발행 완료" value={`${publishedCount(selectedDay)}개`} />
              </div>

              <div className="rounded-[24px] bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">당일 슬롯</p>
                    <p className="mt-1 text-xs text-slate-500">같은 날짜 안에서만 드래그로 순서를 바꿀 수 있습니다.</p>
                  </div>
                  <button type="button" onClick={handleCreateSlot} className="rounded-2xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500">
                    슬롯 추가
                  </button>
                </div>

                <div className="mt-4 space-y-3">
                  {orderedSlots.length ? (
                    orderedSlots.map((slot) => {
                      const selected = slot.id === selectedSlot?.id;
                      return (
                        <button
                          key={slot.id}
                          type="button"
                          draggable
                          onDragStart={() => setDraggingSlotId(slot.id)}
                          onDragEnd={() => {
                            setDraggingSlotId(null);
                            setDragOverSlotId(null);
                          }}
                          onDragOver={(event) => {
                            event.preventDefault();
                            setDragOverSlotId(slot.id);
                          }}
                          onDrop={(event) => {
                            event.preventDefault();
                            void handleDropSlot(slot.id);
                          }}
                          onClick={() => setSelectedSlotId(slot.id)}
                          className={`w-full rounded-[24px] px-4 py-4 text-left transition ${selected ? "bg-indigo-50 ring-2 ring-indigo-200" : "bg-slate-50 hover:bg-slate-100"} ${dragOverSlotId === slot.id ? "ring-2 ring-indigo-300" : ""}`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-sm font-semibold text-slate-900">{slot.categoryName ?? slot.themeName ?? "미분류"}</p>
                              <p className="mt-1 text-xs text-slate-500">{toDatetimeLocal(slot.scheduledFor) || "시간 미설정"}</p>
                            </div>
                            <div className="flex flex-wrap justify-end gap-2 text-[11px]">
                              <Badge className="bg-white text-slate-600">{statusText(slot.status)}</Badge>
                              <Badge className={publishTone(slot.articlePublishStatus)}>{slot.articlePublishStatus ?? "미발행"}</Badge>
                            </div>
                          </div>

                          <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                            <Badge className={scoreTone(slot.articleSeoScore)}>SEO {scoreText(slot.articleSeoScore)}</Badge>
                            <Badge className={scoreTone(slot.articleGeoScore)}>GEO {scoreText(slot.articleGeoScore)}</Badge>
                            <Badge className={scoreTone(slot.articleSimilarityScore)}>유사도 {scoreText(slot.articleSimilarityScore)}</Badge>
                            <Badge className="bg-white text-slate-600">브리프 {completionCount(slot)}/4</Badge>
                          </div>

                          <div className="mt-3 space-y-1 text-xs text-slate-500">
                            <p>{slot.articleTitle ?? slot.briefTopic ?? "제목 미설정"}</p>
                            <p>job #{slot.jobId ?? "-"} / article #{slot.articleId ?? "-"}</p>
                            {slot.articleMostSimilarUrl ? (
                              <a href={slot.articleMostSimilarUrl} target="_blank" rel="noreferrer" className="block break-all text-indigo-600 hover:underline">
                                가장 유사한 URL: {slot.articleMostSimilarUrl}
                              </a>
                            ) : null}
                          </div>
                        </button>
                      );
                    })
                  ) : (
                    <EmptyBlock title="당일 슬롯이 없습니다" body="우측 편집 초안을 그대로 이용해 첫 슬롯을 추가할 수 있습니다." />
                  )}
                </div>
              </div>

              <div className="rounded-[24px] bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">선택 슬롯 상세 편집</p>
                    <p className="mt-1 text-xs text-slate-500">일간 계획 탭에서만 실제 수정이 가능합니다.</p>
                  </div>
                  {selectedSlot ? <Badge className="bg-slate-100 text-slate-600">slot #{selectedSlot.id}</Badge> : null}
                </div>

                {draft ? (
                  <div className="mt-4 space-y-4">
                    <Field label="카테고리">
                      <select
                        value={draft.themeId}
                        onChange={(event) => setDraft((prev) => (prev ? { ...prev, themeId: Number(event.target.value) } : prev))}
                        className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none ring-1 ring-transparent transition focus:bg-white focus:ring-indigo-200"
                      >
                        {categories.map((category) => (
                          <option key={category.id} value={category.id}>
                            {category.name}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="예약 시간">
                      <input
                        type="datetime-local"
                        value={draft.scheduledFor}
                        onChange={(event) => setDraft((prev) => (prev ? { ...prev, scheduledFor: event.target.value } : prev))}
                        className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none ring-1 ring-transparent transition focus:bg-white focus:ring-indigo-200"
                      />
                    </Field>
                    <Field label="글 주제">
                      <input type="text" value={draft.briefTopic} onChange={(event) => setDraft((prev) => (prev ? { ...prev, briefTopic: event.target.value } : prev))} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none ring-1 ring-transparent transition focus:bg-white focus:ring-indigo-200" />
                    </Field>
                    <Field label="독자 타겟">
                      <input type="text" value={draft.briefAudience} onChange={(event) => setDraft((prev) => (prev ? { ...prev, briefAudience: event.target.value } : prev))} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none ring-1 ring-transparent transition focus:bg-white focus:ring-indigo-200" />
                    </Field>
                    <Field label="정보 수준">
                      <input type="text" value={draft.briefInformationLevel} onChange={(event) => setDraft((prev) => (prev ? { ...prev, briefInformationLevel: event.target.value } : prev))} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none ring-1 ring-transparent transition focus:bg-white focus:ring-indigo-200" />
                    </Field>
                    <Field label="기타 정보">
                      <textarea value={draft.briefExtraContext} onChange={(event) => setDraft((prev) => (prev ? { ...prev, briefExtraContext: event.target.value } : prev))} rows={6} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none ring-1 ring-transparent transition focus:bg-white focus:ring-indigo-200" />
                    </Field>

                    <div className="grid gap-2 sm:grid-cols-3">
                      <button type="button" onClick={handleSaveSlot} className="rounded-2xl bg-slate-900 px-4 py-3 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300" disabled={!selectedSlot}>
                        저장
                      </button>
                      <button type="button" onClick={handleGenerateSlot} className="rounded-2xl bg-indigo-600 px-4 py-3 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-indigo-200" disabled={!selectedSlot || !canGenerate}>
                        생성 실행
                      </button>
                      <button type="button" onClick={handleCancelSlot} className="rounded-2xl bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:text-rose-300" disabled={!selectedSlot}>
                        취소
                      </button>
                    </div>
                  </div>
                ) : (
                  <EmptyBlock title="편집할 슬롯이 없습니다" body="날짜를 선택하고 슬롯을 추가한 뒤 편집하세요." />
                )}
              </div>

              <div className="rounded-[24px] bg-white p-4 shadow-sm">
                <div>
                  <p className="text-sm font-semibold text-slate-900">카테고리별 기본 프롬프트 추천</p>
                  <p className="mt-1 text-xs text-slate-500">현재 브리프 문맥에 맞는 기본 프롬프트를 복사하거나 기타 정보에 삽입할 수 있습니다.</p>
                </div>
                <div className="mt-4 space-y-3">
                  {promptRecommendations.length ? (
                    promptRecommendations.map((item) => (
                      <article key={item.id} className="rounded-[22px] bg-slate-50 p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-500">{item.stageLabel}</p>
                            <p className="mt-2 text-sm font-semibold text-slate-900">{item.title}</p>
                            <p className="mt-2 text-xs leading-5 text-slate-500">{item.context}</p>
                          </div>
                          <div className="flex gap-2">
                            <button type="button" onClick={() => void handleCopyPrompt(item.content)} className="rounded-2xl bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100">복사</button>
                            <button type="button" onClick={() => handleInsertPrompt(item.content)} className="rounded-2xl bg-indigo-50 px-3 py-2 text-xs font-medium text-indigo-700 hover:bg-indigo-100">삽입</button>
                          </div>
                        </div>
                        <p className="mt-3 text-sm leading-6 text-slate-600">{item.excerpt || "본문 미리보기가 없습니다."}</p>
                      </article>
                    ))
                  ) : (
                    <EmptyBlock title="추천 프롬프트가 없습니다" body="채널 프롬프트 플로우에서 생성 단계가 활성화되면 여기서 추천됩니다." />
                  )}
                </div>
              </div>
            </div>
          ) : (
            <EmptyBlock title="선택한 날짜에 계획 데이터가 없습니다" body="월간 계획을 다시 만들거나 다른 날짜를 선택하세요." />
          )
        ) : detailTab === "week" ? (
          <div className="space-y-5">
            <div className="rounded-[24px] bg-white p-4 shadow-sm">
              <p className="text-sm font-semibold text-slate-900">주간 흐름</p>
              <p className="mt-1 text-sm text-slate-500">{formatWeekRange(selectedDay?.planDate ?? todayDateKey)}</p>
            </div>
            <div className="grid gap-3">
              {weekDays.map((day, index) => {
                const dateKey = weekDateKeys[index];
                return (
                  <article key={dateKey} className="rounded-[24px] bg-white p-4 shadow-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{formatKoreanDate(dateKey)} ({formatWeekday(dateKey)})</p>
                        <p className="mt-1 text-xs text-slate-500">슬롯 {day?.slotCount ?? 0}개 / 완료율 {dayCompletion(day)}%</p>
                      </div>
                      <button type="button" onClick={() => openDate(dateKey, "day")} className="rounded-2xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-200">당일 이동</button>
                    </div>
                    <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full rounded-full bg-indigo-500" style={{ width: `${dayCompletion(day)}%` }} />
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {Object.entries(day?.categoryMix ?? day?.themeMix ?? {}).length ? (
                        Object.entries(day?.categoryMix ?? day?.themeMix ?? {}).map(([key, count]) => (
                          <span key={key} className="inline-flex rounded-full px-3 py-1 text-xs font-medium text-slate-700" style={{ backgroundColor: `${categoryColorMap.get(key) ?? "#e2e8f0"}33` }}>
                            {key} {count}
                          </span>
                        ))
                      ) : (
                        <span className="text-xs text-slate-400">카테고리 데이터 없음</span>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <MiniMetric label="월 목표 슬롯" value={`${monthSummary.target}개`} />
              <MiniMetric label="실제 슬롯" value={`${monthSummary.slots}개`} />
              <MiniMetric label="생성 완료" value={`${monthSummary.generated}개`} />
              <MiniMetric label="발행 완료" value={`${monthSummary.published}개`} />
            </div>
            <div className="rounded-[24px] bg-white p-4 shadow-sm">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">월간 카테고리 집계</p>
                  <p className="mt-1 text-xs text-slate-500">카테고리 기준으로 목표 대비 편차를 읽기 전용으로 확인합니다.</p>
                </div>
              </div>
              <div className="mt-4 space-y-3">
                {monthCategoryStats.map((stat) => (
                  <article key={stat.key} className="rounded-[22px] bg-slate-50 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="h-3 w-3 rounded-full" style={{ backgroundColor: stat.color }} />
                          <p className="text-sm font-semibold text-slate-900">{stat.name}</p>
                        </div>
                        <p className="mt-2 text-xs text-slate-500">목표 {stat.planned}개 / 실제 {stat.actual}개</p>
                      </div>
                      <Badge className={stat.gap > 0 ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}>
                        편차 {stat.gap > 0 ? `+${stat.gap}` : stat.gap}
                      </Badge>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="rounded-[32px] bg-[#f5f7ff] p-6 text-slate-900 shadow-[0_24px_80px_rgba(15,23,42,0.08)] md:p-8">
      <div className="space-y-8">
        <section className="rounded-[28px] bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-500">플래너</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">월간 메인 캔버스 + 우측 상세 탭</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">메인 화면은 항상 월간 캘린더로 유지하고, 날짜를 누르면 우측에서 일간 계획·주간 흐름·월간 집계를 나눠서 확인합니다.</p>
            </div>
            <div className="rounded-[24px] bg-indigo-50 px-5 py-4 text-sm leading-6 text-indigo-700">
              저장 기준: 일간
              <br />
              주간/월간은 같은 원본을 공유합니다.
            </div>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_auto_1fr_auto_1fr]">
            <GuideStep title="일간 저장" body="슬롯 시간, 카테고리, 브리프, 실행 상태는 일간 데이터로 저장됩니다." />
            <GuideArrow />
            <GuideStep title="주간 공유" body="선택 날짜가 포함된 7일 흐름은 같은 일간 원본을 읽기 전용으로 묶어 보여줍니다." />
            <GuideArrow />
            <GuideStep title="월간 집계" body="월간 비중, 생성/발행 누적, 부족 카테고리도 같은 원본을 기준으로 계산합니다." />
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_430px]">
          <div className="space-y-4">
            <div className="rounded-[28px] bg-white p-5 shadow-sm">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[220px_180px_auto] xl:items-end">
                  <Field label="운영 블로그">
                    <select value={String(blogId)} onChange={(event) => setQuery({ blog: event.target.value, selectedDate: null })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none ring-1 ring-transparent transition focus:bg-white focus:ring-indigo-200">
                      {blogs.map((blog) => (
                        <option key={blog.id} value={blog.id}>{blog.name}</option>
                      ))}
                    </select>
                  </Field>
                  <Field label="기준 월">
                    <input type="month" value={month} onChange={(event) => setQuery({ month: event.target.value, selectedDate: null })} className="w-full rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none ring-1 ring-transparent transition focus:bg-white focus:ring-indigo-200" />
                  </Field>
                  <div className="flex flex-wrap gap-2 xl:justify-end">
                    <QuickButton onClick={() => quickSelect("day")}>오늘</QuickButton>
                    <QuickButton onClick={() => quickSelect("week")}>이번 주</QuickButton>
                    <QuickButton onClick={() => quickSelect("month")}>이번 달</QuickButton>
                    <button type="button" onClick={handleRebuildMonthPlan} className="rounded-2xl bg-slate-900 px-4 py-3 text-sm font-medium text-white hover:bg-slate-800">월간 계획 다시 만들기</button>
                  </div>
                </div>
              </div>

              <div className="mt-4 rounded-[22px] bg-[#eef2ff] px-4 py-3 text-sm text-slate-600">
                같은 날짜 안에서만 드래그로 슬롯 순서를 정리합니다. 메인 캘린더는 월간 요약만 보여주고, 세부 편집은 우측 패널에서 처리합니다.
              </div>
              {status ? <p className="mt-3 text-sm text-indigo-600">{status}</p> : null}
            </div>

            <section className="rounded-[28px] bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">월간 메인 캔버스</p>
                  <h2 className="mt-2 text-2xl font-semibold text-slate-900">{monthLabel(month)}</h2>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-slate-500 sm:grid-cols-4">
                  <CanvasMiniStat label="목표" value={`${monthSummary.target}`} />
                  <CanvasMiniStat label="슬롯" value={`${monthSummary.slots}`} />
                  <CanvasMiniStat label="생성" value={`${monthSummary.generated}`} />
                  <CanvasMiniStat label="발행" value={`${monthSummary.published}`} />
                </div>
              </div>

              <div className="mt-5 grid grid-cols-7 gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
                {['월', '화', '수', '목', '금', '토', '일'].map((label) => <div key={label} className="px-2">{label}</div>)}
              </div>

              <div className="mt-3 grid grid-cols-7 gap-3">
                {monthCells.map((cell, index) => {
                  if (!cell) return <div key={`empty-${index}`} className="min-h-[180px] rounded-[26px] bg-transparent" />;
                  const completion = dayCompletion(cell.plannerDay);
                  const generated = generatedCount(cell.plannerDay);
                  const published = publishedCount(cell.plannerDay);
                  const isSelected = cell.dateKey === selectedDay?.planDate;
                  const mixes = Object.entries(cell.plannerDay?.categoryMix ?? cell.plannerDay?.themeMix ?? {});
                  return (
                    <button key={cell.dateKey} type="button" onClick={() => openDate(cell.dateKey, "day")} className={`min-h-[180px] rounded-[26px] p-4 text-left transition ${isSelected ? "bg-indigo-50 ring-2 ring-indigo-200" : "bg-slate-50 hover:bg-slate-100"}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-lg font-semibold text-slate-900">{cell.dayNumber}</p>
                          <p className="mt-1 text-xs text-slate-500">{formatWeekday(cell.dateKey)}요일</p>
                        </div>
                        <Badge className="bg-white text-slate-600">슬롯 {cell.plannerDay?.slotCount ?? 0}</Badge>
                      </div>
                      <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-slate-500">
                        <span>생성 {generated}</span>
                        <span>발행 {published}</span>
                      </div>
                      <div className="mt-4 h-2 overflow-hidden rounded-full bg-white">
                        <div className="h-full rounded-full bg-indigo-500" style={{ width: `${completion}%` }} />
                      </div>
                      <p className="mt-2 text-xs text-slate-500">완료율 {completion}%</p>
                      <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-white">
                        {mixes.length ? mixes.map(([key, count]) => (
                          <div key={key} className="h-full" style={{ width: `${Math.max(8, (count / Math.max(1, cell.plannerDay?.slotCount ?? 1)) * 100)}%`, backgroundColor: categoryColorMap.get(key) ?? '#cbd5e1' }} />
                        )) : <div className="h-full w-full bg-slate-200" />}
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          </div>

          <div ref={panelRef} className="hidden xl:block">{detailPanel}</div>
        </section>
      </div>

      {mobileSheetOpen ? (
        <div className="fixed inset-0 z-40 bg-slate-900/30 xl:hidden" onClick={() => setMobileSheetOpen(false)}>
          <div className="absolute inset-x-0 bottom-0 max-h-[86vh] overflow-hidden rounded-t-[32px] bg-[#f5f7ff] p-4" onClick={(event) => event.stopPropagation()}>
            <div className="mb-3 flex justify-center">
              <div className="h-1.5 w-14 rounded-full bg-slate-300" />
            </div>
            <div className="max-h-[78vh] overflow-y-auto">{detailPanel}</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function GuideStep({ title, body }: { title: string; body: string }) {
  return (
    <article className="rounded-[24px] bg-slate-50 p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{title}</p>
      <p className="mt-3 text-sm leading-6 text-slate-600">{body}</p>
    </article>
  );
}

function GuideArrow() {
  return <div className="hidden items-center justify-center lg:flex"><div className="h-px w-full bg-slate-200" /></div>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="space-y-2 block">
      <span className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{label}</span>
      {children}
    </label>
  );
}

function Badge({ className, children }: { className: string; children: ReactNode }) {
  return <span className={`inline-flex rounded-full px-3 py-1 text-[11px] font-medium ${className}`}>{children}</span>;
}

function DetailTabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return <button type="button" onClick={onClick} className={`rounded-2xl px-4 py-3 text-sm font-medium transition ${active ? 'bg-indigo-600 text-white' : 'text-slate-600 hover:bg-slate-50'}`}>{label}</button>;
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return <article className="rounded-[22px] bg-slate-50 p-4"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{label}</p><p className="mt-2 text-2xl font-semibold text-slate-900">{value}</p></article>;
}

function CanvasMiniStat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-2xl bg-slate-50 px-3 py-2 text-center"><p>{label}</p><p className="mt-1 text-sm font-semibold text-slate-900">{value}</p></div>;
}

function EmptyBlock({ title, body }: { title: string; body: string }) {
  return <article className="rounded-[24px] bg-white p-5 text-center shadow-sm"><p className="text-sm font-semibold text-slate-900">{title}</p><p className="mt-2 text-sm leading-6 text-slate-500">{body}</p></article>;
}

function QuickButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="rounded-2xl bg-slate-100 px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-200">{children}</button>;
}



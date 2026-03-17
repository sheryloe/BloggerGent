"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import { Button } from "@/components/ui/button";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

type PublishState = "unpublished" | "draft" | "scheduled" | "published";

function defaultScheduleValue() {
  const next = new Date();
  next.setDate(next.getDate() + 1);
  next.setHours(9, 0, 0, 0);
  const tzOffset = next.getTimezoneOffset() * 60_000;
  return new Date(next.getTime() - tzOffset).toISOString().slice(0, 16);
}

function formatErrorMessage(payload: unknown) {
  if (!payload || typeof payload !== "object") {
    return "게시 요청에 실패했습니다.";
  }

  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (detail && typeof detail === "object") {
    const message = (detail as { message?: string }).message;
    const conflicts = (detail as { conflicts?: Array<{ title?: string }> }).conflicts ?? [];
    const titles = conflicts.map((item) => item.title).filter(Boolean).slice(0, 2);
    if (typeof message === "string" && message.trim()) {
      return titles.length ? `${message} 충돌 글: ${titles.join(", ")}` : message;
    }
  }

  return "게시 요청에 실패했습니다.";
}

export function PublishArticleButton({
  articleId,
  publishState,
}: {
  articleId: number;
  publishState: PublishState;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState("");
  const [scheduleValue, setScheduleValue] = useState(defaultScheduleValue);
  const disabled = publishState === "published" || publishState === "scheduled";

  const helperText = useMemo(() => {
    if (publishState === "published") return "이미 공개된 글입니다.";
    if (publishState === "scheduled") return "이미 예약된 글입니다.";
    if (publishState === "draft") return "Blogger 초안을 즉시 공개하거나 예약 발행할 수 있습니다.";
    return "아직 Blogger에 올라가지 않은 글입니다.";
  }, [publishState]);

  async function submit(mode: "publish" | "schedule") {
    if (disabled) {
      setError(helperText);
      return;
    }

    setError("");
    const body =
      mode === "schedule"
        ? { mode, scheduled_for: new Date(scheduleValue).toISOString() }
        : { mode };

    const response = await fetch(`${apiBase}/articles/${articleId}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setError(formatErrorMessage(payload));
      return;
    }

    startTransition(() => {
      router.refresh();
    });
  }

  return (
    <div className="space-y-3">
      <p className="text-sm leading-6 text-slate-600">{helperText}</p>

      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => void submit("publish")} disabled={isPending || disabled}>
          {isPending ? "처리 중..." : publishState === "draft" ? "초안 즉시 공개" : "즉시 발행"}
        </Button>
      </div>

      <div className="space-y-2 rounded-2xl border border-ink/10 bg-white/70 p-3">
        <label htmlFor={`schedule-${articleId}`} className="block text-xs font-medium uppercase tracking-[0.16em] text-slate-500">
          예약 발행
        </label>
        <input
          id={`schedule-${articleId}`}
          type="datetime-local"
          value={scheduleValue}
          onChange={(event) => setScheduleValue(event.target.value)}
          className="h-11 w-full rounded-xl border border-ink/10 px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
          disabled={isPending || disabled}
        />
        <Button type="button" variant="outline" onClick={() => void submit("schedule")} disabled={isPending || disabled}>
          예약 발행 저장
        </Button>
      </div>

      {error ? <p className="text-sm text-rose-700">{error}</p> : null}
    </div>
  );
}

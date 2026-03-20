"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import type { PublishQueueItem } from "@/lib/types";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

type PublishState = "unpublished" | "draft" | "scheduled" | "published" | "queued";

function defaultScheduleValue() {
  const next = new Date();
  next.setDate(next.getDate() + 1);
  next.setHours(9, 0, 0, 0);
  const tzOffset = next.getTimezoneOffset() * 60_000;
  return new Date(next.getTime() - tzOffset).toISOString().slice(0, 16);
}

function formatErrorMessage(payload: unknown) {
  if (!payload || typeof payload !== "object") return "Publish request failed.";
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: string }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return "Publish request failed.";
}

function queueMessage(queueItem?: PublishQueueItem | null) {
  if (!queueItem) return "";
  if (queueItem.status === "processing") return "This publish request is currently being processed.";
  if (queueItem.status === "queued") return `Queued for publish. Earliest execution: ${new Date(queueItem.not_before).toLocaleString("ko-KR")}`;
  if (queueItem.status === "scheduled") return `Queued for scheduled publish. Earliest execution: ${new Date(queueItem.not_before).toLocaleString("ko-KR")}`;
  if (queueItem.status === "failed") return queueItem.last_error || "The previous publish attempt failed.";
  return "";
}

export function PublishArticleButton({ articleId, publishState, publishQueue }: { articleId: number; publishState: PublishState; publishQueue?: PublishQueueItem | null }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState("");
  const [scheduleValue, setScheduleValue] = useState(defaultScheduleValue);
  const queueActive = Boolean(publishQueue && ["queued", "scheduled", "processing"].includes(publishQueue.status));
  const disabled = publishState === "published" || publishState === "scheduled" || publishState === "queued" || queueActive;

  const helperText = useMemo(() => {
    if (publishState === "published") return "This article is already public.";
    if (publishState === "scheduled") return "This article is already scheduled in Blogger.";
    if (publishState === "queued") return queueMessage(publishQueue);
    if (publishState === "draft") return "A Blogger draft exists. New publish requests will still respect the queue interval.";
    return "Requests are queued first. The worker publishes one item at a time per blog using the configured minimum interval.";
  }, [publishQueue, publishState]);

  async function submit(mode: "publish" | "schedule") {
    if (disabled) {
      setError(helperText);
      return;
    }

    setError("");
    const body = mode === "schedule" ? { mode, scheduled_for: new Date(scheduleValue).toISOString() } : { mode };
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

    startTransition(() => router.refresh());
  }

  return (
    <div className="space-y-3">
      <p className="text-sm leading-6 text-slate-600">{helperText}</p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => void submit("publish")} disabled={isPending || disabled}>
          {isPending ? "Submitting..." : "Queue publish"}
        </Button>
      </div>
      <div className="space-y-2 rounded-2xl border border-ink/10 bg-white/70 p-3">
        <label htmlFor={`schedule-${articleId}`} className="block text-xs font-medium uppercase tracking-[0.16em] text-slate-500">Schedule publish</label>
        <input
          id={`schedule-${articleId}`}
          type="datetime-local"
          value={scheduleValue}
          onChange={(event) => setScheduleValue(event.target.value)}
          className="h-11 w-full rounded-xl border border-ink/10 px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
          disabled={isPending || disabled}
        />
        <Button type="button" variant="outline" onClick={() => void submit("schedule")} disabled={isPending || disabled}>
          Queue scheduled publish
        </Button>
      </div>
      {error ? <p className="text-sm text-rose-700">{error}</p> : null}
    </div>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Button } from "@/components/ui/button";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

async function readApiError(response: Response) {
  try {
    const payload = (await response.json()) as {
      detail?: string | { message?: string; detail?: string };
    };

    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }

    if (payload.detail && typeof payload.detail === "object") {
      if (typeof payload.detail.detail === "string" && payload.detail.detail.trim()) {
        return payload.detail.detail;
      }
      if (typeof payload.detail.message === "string" && payload.detail.message.trim()) {
        return payload.detail.message;
      }
    }
  } catch {}

  return `요청이 실패했습니다. (${response.status})`;
}

export function GooglePostSyncButton({ blogId }: { blogId: number }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [message, setMessage] = useState<string>("");
  const [error, setError] = useState<string>("");

  async function handleSync() {
    setMessage("");
    setError("");

    const response = await fetch(`${apiBase}/google/blogs/${blogId}/synced-posts/refresh`, {
      method: "POST",
    });

    if (!response.ok) {
      setError(await readApiError(response));
      return;
    }

    const payload = (await response.json()) as { count?: number };
    setMessage(`현재 게시글 ${payload.count ?? 0}건을 다시 동기화했습니다.`);
    startTransition(() => {
      router.refresh();
    });
  }

  return (
    <div className="space-y-2">
      <Button type="button" variant="outline" onClick={() => void handleSync()} disabled={isPending}>
        {isPending ? "동기화 중..." : "현재 게시글 동기화"}
      </Button>
      {message ? <p className="text-sm text-emerald-700">{message}</p> : null}
      {error ? <p className="text-sm text-rose-700">{error}</p> : null}
    </div>
  );
}

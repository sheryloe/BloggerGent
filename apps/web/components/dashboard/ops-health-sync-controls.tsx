"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Button } from "@/components/ui/button";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const MANUAL_SYNC_COMMAND = "docker compose --env-file .env exec -T api python -m app.tools.ops_health_report";

type OpsHealthSyncResponse = {
  status?: string;
  file_path?: string;
};

async function readApiError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: string | { message?: string; detail?: string } };

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
  } catch {
    // ignore json parse error
  }

  return `요청 실패 (${response.status})`;
}

export function OpsHealthSyncControls() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [showManual, setShowManual] = useState(false);
  const [copied, setCopied] = useState(false);

  async function handleRealtimeSync() {
    setMessage("");
    setError("");
    setCopied(false);

    const response = await fetch(`${apiBase}/admin/ops-health/sync`, {
      method: "POST",
    });

    if (!response.ok) {
      setError(await readApiError(response));
      setShowManual(true);
      return;
    }

    const payload = (await response.json()) as OpsHealthSyncResponse;
    const path = (payload.file_path || "").trim();
    setMessage(path ? `실시간 동기화 완료: ${path}` : "실시간 동기화를 완료했습니다.");
    setShowManual(false);

    startTransition(() => {
      router.refresh();
    });
  }

  async function handleCopyManualCommand() {
    setCopied(false);
    setError("");
    try {
      await navigator.clipboard.writeText(MANUAL_SYNC_COMMAND);
      setCopied(true);
      setShowManual(true);
    } catch {
      setError("클립보드 복사에 실패했습니다. 아래 명령을 직접 복사해 실행하세요.");
      setShowManual(true);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => void handleRealtimeSync()} disabled={isPending}>
          {isPending ? "동기화 중..." : "실시간 동기화"}
        </Button>
        <Button type="button" variant="outline" onClick={() => setShowManual((prev) => !prev)} disabled={isPending}>
          수동 동기화
        </Button>
        <Button type="button" variant="ghost" onClick={() => void handleCopyManualCommand()} disabled={isPending}>
          {copied ? "수동 명령 복사됨" : "수동 명령 복사"}
        </Button>
      </div>

      {message ? <p className="text-sm text-emerald-700">{message}</p> : null}
      {error ? <p className="text-sm text-rose-700">{error}</p> : null}

      {showManual ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-sm text-slate-700">실시간 동기화 실패 시 아래 명령으로 수동 동기화를 실행하세요.</p>
          <pre className="mt-2 overflow-x-auto rounded-lg border border-slate-200 bg-white p-2 text-xs">{MANUAL_SYNC_COMMAND}</pre>
        </div>
      ) : null}
    </div>
  );
}

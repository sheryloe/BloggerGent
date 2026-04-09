"use client";

import { useMemo, useState, useSyncExternalStore } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { requestGoogleIndexStatusRefresh, requestGooglePlaywrightIndexing } from "@/lib/api";

type IndexScope = "blogger" | "cloudflare";

type IndexingSnapshot = {
  status: string;
  checkedAt?: string | null;
  nextEligibleAt?: string | null;
  lastError?: string | null;
};

let globalBusy = false;
const busyListeners = new Set<() => void>();

function setGlobalBusy(next: boolean) {
  globalBusy = next;
  busyListeners.forEach((listener) => listener());
}

function subscribeGlobalBusy(listener: () => void) {
  busyListeners.add(listener);
  return () => {
    busyListeners.delete(listener);
  };
}

function useGlobalBusy() {
  return useSyncExternalStore(subscribeGlobalBusy, () => globalBusy, () => false);
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function normalizeStatus(value?: string | null) {
  const normalized = String(value || "unknown").trim().toLowerCase();
  if (!normalized) return "unknown";
  return normalized;
}

function statusTone(value: string) {
  const normalized = normalizeStatus(value);
  if (normalized === "indexed") return "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (normalized === "submitted" || normalized === "pending") return "bg-sky-50 text-sky-700 border-sky-200";
  if (normalized === "failed") return "bg-rose-50 text-rose-700 border-rose-200";
  return "bg-slate-50 text-slate-700 border-slate-200";
}

export function GoogleIndexingRowActions({
  url,
  targetScope,
  indexStatus,
  indexLastCheckedAt,
  nextEligibleAt,
  lastError,
}: {
  url: string;
  targetScope: IndexScope;
  indexStatus?: string | null;
  indexLastCheckedAt?: string | null;
  nextEligibleAt?: string | null;
  lastError?: string | null;
}) {
  const busy = useGlobalBusy();
  const [snapshot, setSnapshot] = useState<IndexingSnapshot>({
    status: normalizeStatus(indexStatus),
    checkedAt: indexLastCheckedAt ?? null,
    nextEligibleAt: nextEligibleAt ?? null,
    lastError: lastError ?? null,
  });
  const [message, setMessage] = useState<string>("");
  const [error, setError] = useState<string>("");

  const normalizedUrl = useMemo(() => String(url || "").trim(), [url]);
  const disabled = busy || !normalizedUrl;

  async function handleRefresh() {
    if (!normalizedUrl) return;
    setMessage("");
    setError("");
    setGlobalBusy(true);
    try {
      const response = await requestGoogleIndexStatusRefresh({
        urls: [normalizedUrl],
        targetScope,
        force: true,
      });
      const first = response.results[0];
      if (!first) {
        if (response.reason) {
          setError(response.reason);
        } else {
          setMessage("갱신 대상이 없습니다.");
        }
        return;
      }
      setSnapshot({
        status: normalizeStatus(first.indexStatus),
        checkedAt: first.indexLastCheckedAt ?? new Date().toISOString(),
        nextEligibleAt: first.nextEligibleAt ?? null,
        lastError: first.lastError ?? null,
      });
      if (first.status === "ok") {
        setMessage("색인 상태를 갱신했습니다.");
      } else {
        setError(first.code || first.reason || first.lastError || "상태 갱신에 실패했습니다.");
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "상태 갱신 요청에 실패했습니다.");
    } finally {
      setGlobalBusy(false);
    }
  }

  async function handleRequest() {
    if (!normalizedUrl) return;
    setMessage("");
    setError("");
    setGlobalBusy(true);
    try {
      const response = await requestGooglePlaywrightIndexing({
        count: 1,
        runTest: false,
        urls: [normalizedUrl],
        targetScope,
      });
      const first = response.results[0];
      if (!first) {
        if (response.reason) {
          setError(response.reason);
        } else {
          setMessage("요청 대상이 없습니다.");
        }
        return;
      }
      setSnapshot({
        status: normalizeStatus(first.indexStatus),
        checkedAt: first.indexLastCheckedAt ?? new Date().toISOString(),
        nextEligibleAt: first.nextEligibleAt ?? null,
        lastError: first.lastError ?? null,
      });
      if (first.status === "ok") {
        setMessage("색인 요청을 보냈습니다.");
      } else {
        setError(first.code || first.reason || first.lastError || "색인 요청에 실패했습니다.");
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "색인 요청에 실패했습니다.");
    } finally {
      setGlobalBusy(false);
    }
  }

  return (
    <div className="mt-3 space-y-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={statusTone(snapshot.status)}>{snapshot.status}</Badge>
        <span className="text-xs text-slate-500">마지막 확인: {formatDateTime(snapshot.checkedAt)}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => void handleRefresh()} disabled={disabled}>
          색인 확인
        </Button>
        <Button type="button" size="sm" onClick={() => void handleRequest()} disabled={disabled}>
          색인 실행(1건)
        </Button>
      </div>
      <p className="text-xs text-slate-500">다음 가능 시각: {formatDateTime(snapshot.nextEligibleAt)}</p>
      {message ? <p className="text-xs text-emerald-700">{message}</p> : null}
      {error ? <p className="text-xs text-rose-700">{error}</p> : null}
      {snapshot.lastError ? <p className="text-xs text-rose-700">최근 오류: {snapshot.lastError}</p> : null}
    </div>
  );
}

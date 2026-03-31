"use client";

import { useEffect, useState } from "react";
import { BarChart3, RefreshCw, X } from "lucide-react";

import { OpenAIFreeUsage } from "@/lib/types";

function resolveApiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("ko-KR").format(value);
}

function normalizeFetchError(error: unknown) {
  if (!(error instanceof Error)) return "사용량 정보를 불러오지 못했습니다.";
  return error.message || "사용량 정보를 불러오지 못했습니다.";
}

function updatedText(usage: OpenAIFreeUsage | null, loading: boolean) {
  if (usage?.window_end_utc) {
    return usage.window_end_utc.slice(0, 19).replace("T", " ");
  }
  return loading ? "불러오는 중" : "대기 중";
}

export function OpenAIFreeUsageWidget() {
  const [expanded, setExpanded] = useState(false);
  const [usage, setUsage] = useState<OpenAIFreeUsage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadUsage() {
    setLoading(true);
    try {
      const response = await fetch(`${resolveApiBaseUrl()}/settings/openai-free-usage`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`usage request failed: ${response.status}`);
      }
      const payload = (await response.json()) as OpenAIFreeUsage;
      setUsage(payload);
      setError("");
    } catch (fetchError) {
      setError(normalizeFetchError(fetchError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!expanded || usage) return;
    void loadUsage();
  }, [expanded, usage]);

  useEffect(() => {
    if (!expanded) return;
    const timer = window.setInterval(() => {
      void loadUsage();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [expanded]);

  return (
    <div className="fixed bottom-5 right-5 z-40">
      {!expanded ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-3 text-xs font-semibold text-slate-700 shadow-[0_12px_32px_rgba(15,23,42,0.12)]"
        >
          <BarChart3 className="h-4 w-4 text-indigo-600" />
          <span>사용량</span>
        </button>
      ) : (
        <div className="w-[320px] rounded-[28px] border border-slate-200 bg-white p-4 text-slate-900 shadow-[0_24px_80px_rgba(15,23,42,0.12)]">
          <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">OpenAI</p>
              <h2 className="mt-1 text-sm font-semibold">무료 사용량</h2>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void loadUsage()}
                className="rounded-full border border-slate-200 p-2 text-slate-500 transition hover:border-indigo-200 hover:text-indigo-600"
              >
                <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              </button>
              <button
                type="button"
                onClick={() => setExpanded(false)}
                className="rounded-full border border-slate-200 p-2 text-slate-500 transition hover:border-rose-200 hover:text-rose-600"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {error ? <p className="mt-4 rounded-2xl bg-rose-50 px-3 py-3 text-sm text-rose-700">{error}</p> : null}

          <div className="mt-4 grid gap-3">
            <UsageRow label="업데이트 시각" value={updatedText(usage, loading)} />
            <UsageRow label="1M 토큰 남은 요청" value={usage ? `${formatNumber(usage.large.remaining_tokens)}토큰` : "N/A"} />
            <UsageRow label="10M 토큰 남은 요청" value={usage ? `${formatNumber(usage.small.remaining_tokens)}토큰` : "N/A"} />
            <UsageRow label="현재 키 모드" value={usage?.key_mode ?? "N/A"} />
          </div>
        </div>
      )}
    </div>
  );
}

function UsageRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-slate-50 px-3 py-3">
      <span className="text-sm text-slate-500">{label}</span>
      <span className="text-sm font-semibold text-slate-900">{value}</span>
    </div>
  );
}

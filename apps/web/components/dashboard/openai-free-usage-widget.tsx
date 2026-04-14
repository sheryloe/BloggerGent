"use client";

import { useEffect, useState } from "react";
import { BarChart3, RefreshCw, X } from "lucide-react";

import { OpenAIFreeUsage } from "@/lib/types";

type OpenAIFreeUsageBucket = OpenAIFreeUsage["large"];

function resolveApiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("ko-KR").format(value);
}

function formatPercent(value: number) {
  return `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(value)}%`;
}

function clampPercent(value: number) {
  if (!Number.isFinite(value)) return 0;
  return Math.min(Math.max(value, 0), 100);
}

function buildUsageSegments(bucket: OpenAIFreeUsageBucket) {
  const limit = bucket.limit_tokens;
  if (limit <= 0) {
    return { inputPercent: 0, outputPercent: 0, usedPercent: 0 };
  }

  const rawInputPercent = (bucket.input_tokens / limit) * 100;
  const rawOutputPercent = (bucket.output_tokens / limit) * 100;
  const rawUsedPercent = ((bucket.input_tokens + bucket.output_tokens) / limit) * 100;

  if (rawUsedPercent <= 100) {
    return {
      inputPercent: clampPercent(rawInputPercent),
      outputPercent: clampPercent(rawOutputPercent),
      usedPercent: clampPercent(rawUsedPercent),
    };
  }

  const scale = 100 / rawUsedPercent;
  return {
    inputPercent: clampPercent(rawInputPercent * scale),
    outputPercent: clampPercent(rawOutputPercent * scale),
    usedPercent: 100,
  };
}

function normalizeFetchError(error: unknown) {
  if (!(error instanceof Error)) return "Failed to load OpenAI usage.";
  return error.message || "Failed to load OpenAI usage.";
}

function updatedText(usage: OpenAIFreeUsage | null, loading: boolean) {
  if (usage?.window_end_utc) {
    return usage.window_end_utc.slice(0, 19).replace("T", " ");
  }
  return loading ? "Loading..." : "Idle";
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
          <span>Usage</span>
        </button>
      ) : (
        <div className="w-[360px] max-w-[calc(100vw-2rem)] rounded-[28px] border border-slate-200 bg-white p-4 text-slate-900 shadow-[0_24px_80px_rgba(15,23,42,0.12)]">
          <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">OpenAI</p>
              <h2 className="mt-1 text-sm font-semibold">Free Usage</h2>
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
            <UsageRow label="Updated" value={updatedText(usage, loading)} />
            <UsageRow
              label="Large remaining"
              value={usage ? `${formatNumber(usage.large.remaining_tokens)} tokens` : "N/A"}
            />
            <UsageRow
              label="Small remaining"
              value={usage ? `${formatNumber(usage.small.remaining_tokens)} tokens` : "N/A"}
            />
            <UsageRow label="Key mode" value={usage?.key_mode ?? "N/A"} />
            <UsageRow
              label="Hard cap"
              value={
                usage
                  ? usage.blocked_due_to_usage_cap
                    ? "blocked"
                    : usage.hard_cap_enabled
                      ? "enabled"
                      : "disabled"
                  : "N/A"
              }
            />
            <UsageRow
              label="Usage unavailable"
              value={usage ? (usage.blocked_due_to_usage_unavailable ? "blocked" : "ok") : "N/A"}
            />
            <UsageRow
              label="Unexpected text API"
              value={usage ? `${formatNumber(usage.unexpected_text_api_call_count)} calls / 24h` : "N/A"}
            />
          </div>

          {usage ? (
            <div className="mt-4 grid gap-3">
              <UsageBucketCard bucket={usage.large} />
              <UsageBucketCard bucket={usage.small} />
            </div>
          ) : null}

          {usage?.warning ? (
            <p className="mt-4 rounded-2xl bg-amber-50 px-3 py-3 text-xs text-amber-700">{usage.warning}</p>
          ) : null}
        </div>
      )}
    </div>
  );
}

function UsageBucketCard({ bucket }: { bucket: OpenAIFreeUsageBucket }) {
  const segments = buildUsageSegments(bucket);

  return (
    <section className="rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">{bucket.label}</p>
          <p className="mt-1 text-xs text-slate-500">
            {formatNumber(bucket.used_tokens)} / {formatNumber(bucket.limit_tokens)} tokens
          </p>
        </div>
        <div className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">
          {formatPercent(bucket.usage_percent)}
        </div>
      </div>

      <div className="mt-3 h-3 overflow-hidden rounded-full bg-slate-200">
        <div className="flex h-full w-full">
          <div
            className="h-full bg-blue-500 transition-[width]"
            style={{ width: `${segments.inputPercent}%` }}
            title={`Input ${formatPercent(segments.inputPercent)}`}
          />
          <div
            className="h-full bg-red-500 transition-[width]"
            style={{ width: `${segments.outputPercent}%` }}
            title={`Output ${formatPercent(segments.outputPercent)}`}
          />
        </div>
      </div>

      <div className="mt-3 flex items-center gap-3 text-[11px] font-medium text-slate-500">
        <LegendChip colorClassName="bg-blue-500" label={`Input ${formatNumber(bucket.input_tokens)}`} />
        <LegendChip colorClassName="bg-red-500" label={`Output ${formatNumber(bucket.output_tokens)}`} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <UsageMetric label="Input" value={`${formatNumber(bucket.input_tokens)} tokens`} />
        <UsageMetric label="Output" value={`${formatNumber(bucket.output_tokens)} tokens`} />
        <UsageMetric label="Combined" value={`${formatNumber(bucket.used_tokens)} tokens`} />
        <UsageMetric label="Usage" value={formatPercent(bucket.usage_percent)} />
      </div>
    </section>
  );
}

function LegendChip({ colorClassName, label }: { colorClassName: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-full ${colorClassName}`} />
      <span>{label}</span>
    </span>
  );
}

function UsageMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-white px-3 py-2">
      <p className="text-[11px] uppercase tracking-[0.14em] text-slate-400">{label}</p>
      <p className="mt-1 text-sm font-semibold text-slate-900">{value}</p>
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

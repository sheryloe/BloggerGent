"use client";

import { useEffect, useRef, useState } from "react";
import { GripHorizontal, Maximize2, Minimize2, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { OpenAIFreeUsage } from "@/lib/types";

const POSITION_STORAGE_KEY = "bloggent-openai-free-usage-widget-position";
const COLLAPSED_STORAGE_KEY = "bloggent-openai-free-usage-widget-collapsed";

function resolveApiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("ko-KR").format(value);
}

function defaultPosition() {
  if (typeof window === "undefined") {
    return { x: 0, y: 0 };
  }
  const panelWidth = Math.min(360, window.innerWidth - 24);
  return {
    x: Math.max(window.innerWidth - panelWidth - 24, 12),
    y: window.innerWidth >= 1280 ? 148 : Math.max(window.innerHeight - 260, 16),
  };
}

function UsageRow({
  label,
  used,
  remaining,
  limit,
  percent,
}: {
  label: string;
  used: number;
  remaining: number;
  limit: number;
  percent: number;
}) {
  return (
    <div className="rounded-[22px] border border-slate-200/70 bg-white/80 px-4 py-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-900">{label}</p>
        <Badge className="border border-emerald-200/80 bg-emerald-500/10 text-emerald-700">
          {percent.toFixed(2)}%
        </Badge>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-emerald-500 transition-all duration-500" style={{ width: `${Math.min(percent, 100)}%` }} />
      </div>
      <div className="mt-3 grid gap-1 text-xs leading-5 text-slate-600">
        <p>사용: {formatNumber(used)}</p>
        <p>남음: {formatNumber(remaining)}</p>
        <p>무료 한도: {formatNumber(limit)}</p>
      </div>
    </div>
  );
}

export function OpenAIFreeUsageWidget() {
  const [usage, setUsage] = useState<OpenAIFreeUsage | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const draggingRef = useRef(false);

  async function loadUsage() {
    setLoading(true);
    try {
      const response = await fetch(`${resolveApiBaseUrl()}/settings/openai-free-usage`, {
        cache: "no-store",
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as
          | { detail?: string | { message?: string; detail?: string }; message?: string }
          | null;
        const detailMessage =
          typeof payload?.detail === "string"
            ? payload.detail
            : payload?.detail?.detail || payload?.detail?.message;
        throw new Error(detailMessage || payload?.message || `usage request failed: ${response.status}`);
      }
      const payload = (await response.json()) as OpenAIFreeUsage;
      setUsage(payload);
      setError("");
    } catch (fetchError) {
      const message = fetchError instanceof Error ? fetchError.message : "OpenAI 사용량을 불러오지 못했습니다.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsage();
    const interval = window.setInterval(() => {
      void loadUsage();
    }, 60_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const savedPosition = window.localStorage.getItem(POSITION_STORAGE_KEY);
    const savedCollapsed = window.localStorage.getItem(COLLAPSED_STORAGE_KEY);
    if (savedPosition) {
      try {
        const parsed = JSON.parse(savedPosition) as { x: number; y: number };
        setPosition(parsed);
      } catch {
        setPosition(defaultPosition());
      }
    } else {
      setPosition(defaultPosition());
    }
    if (savedCollapsed) {
      setCollapsed(savedCollapsed === "true");
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !position) return;
    window.localStorage.setItem(POSITION_STORAGE_KEY, JSON.stringify(position));
  }, [position]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(COLLAPSED_STORAGE_KEY, String(collapsed));
  }, [collapsed]);

  useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      if (!draggingRef.current) return;
      setPosition({
        x: Math.max(8, event.clientX - dragOffsetRef.current.x),
        y: Math.max(8, event.clientY - dragOffsetRef.current.y),
      });
    }

    function handlePointerUp() {
      draggingRef.current = false;
      setDragging(false);
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, []);

  if (!position) {
    return null;
  }

  return (
    <div
      className="fixed z-40 w-[min(360px,calc(100vw-24px))]"
      style={{ left: `${position.x}px`, top: `${position.y}px` }}
    >
      <Card className={`border-slate-200/80 bg-white/90 shadow-[0_30px_80px_rgba(15,23,42,0.18)] ${dragging ? "select-none" : ""}`}>
        <CardHeader
          className="cursor-grab touch-none select-none pb-3 active:cursor-grabbing"
          onPointerDown={(event) => {
            const target = event.target as HTMLElement;
            if (target.closest("button")) return;
            draggingRef.current = true;
            setDragging(true);
            dragOffsetRef.current = {
              x: event.clientX - position.x,
              y: event.clientY - position.y,
            };
          }}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-slate-500">
                <GripHorizontal className="h-4 w-4" />
                <span className="text-[11px] font-semibold uppercase tracking-[0.18em]">Floating Usage</span>
              </div>
              <CardTitle className="text-lg">OpenAI 무료 토큰</CardTitle>
            </div>
            <div className="flex items-center gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => void loadUsage()} disabled={loading}>
                <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setCollapsed((current) => !current)}>
                {collapsed ? <Maximize2 className="h-4 w-4" /> : <Minimize2 className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </CardHeader>
        {!collapsed ? (
          <CardContent className="space-y-4 pt-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="border border-slate-200/80 bg-white text-slate-700">{usage?.date_label ?? "오늘 UTC"}</Badge>
              {usage ? (
                <Badge className="border border-slate-200/80 bg-white text-slate-700">
                  {usage.key_mode === "admin" ? "Admin Key" : "Standard Key"}
                </Badge>
              ) : null}
            </div>

            {error ? (
              <div className="rounded-[22px] border border-rose-200/80 bg-rose-50 px-4 py-4 text-sm leading-6 text-rose-700">
                {error}
              </div>
            ) : null}

            {usage ? (
              <div className="space-y-3">
                <UsageRow
                  label="대형 모델"
                  used={usage.large.used_tokens}
                  remaining={usage.large.remaining_tokens}
                  limit={usage.large.limit_tokens}
                  percent={usage.large.usage_percent}
                />
                <UsageRow
                  label="소형 모델"
                  used={usage.small.used_tokens}
                  remaining={usage.small.remaining_tokens}
                  limit={usage.small.limit_tokens}
                  percent={usage.small.usage_percent}
                />
                <div className="rounded-[22px] border border-slate-200/70 bg-slate-50 px-4 py-4 text-xs leading-5 text-slate-600">
                  <p>2026-03-31까지 Gemini를 쓰고, 2026-04-01부터 GPT로 전환할 때 이 패널로 잔량을 바로 볼 수 있습니다.</p>
                  {usage.warning ? <p className="mt-2">{usage.warning}</p> : null}
                  {usage.large.matched_models.length > 0 ? (
                    <p className="mt-2">대형 사용 모델: {usage.large.matched_models.join(", ")}</p>
                  ) : null}
                  {usage.small.matched_models.length > 0 ? (
                    <p className="mt-1">소형 사용 모델: {usage.small.matched_models.join(", ")}</p>
                  ) : null}
                </div>
              </div>
            ) : loading ? (
              <div className="rounded-[22px] border border-slate-200/70 bg-slate-50 px-4 py-4 text-sm text-slate-600">
                사용량을 불러오는 중입니다.
              </div>
            ) : null}
          </CardContent>
        ) : null}
      </Card>
    </div>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { requestGoogleBlogIndexing, testGoogleBlogIndexing } from "@/lib/api";
import type { GoogleBlogIndexingRequestRead, GoogleBlogIndexingTestRead } from "@/lib/types";

function parseUrls(raw: string): string[] {
  const seen = new Set<string>();
  const results: string[] = [];
  raw
    .split(/\r?\n|,|\s+/g)
    .map((item) => item.trim())
    .filter(Boolean)
    .forEach((item) => {
      if (seen.has(item)) return;
      seen.add(item);
      results.push(item);
    });
  return results;
}

function summarizeActionStatus(value: string) {
  if (value === "ok") return "성공";
  if (value === "failed") return "실패";
  if (value === "skipped") return "스킵";
  if (value === "partial") return "부분 성공";
  if (value === "idle") return "대상 없음";
  return value;
}

export function GoogleIndexingControls({ blogId }: { blogId: number }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [countInput, setCountInput] = useState<string>("10");
  const [urlsInput, setUrlsInput] = useState<string>("");
  const [runTest, setRunTest] = useState<boolean>(true);
  const [force, setForce] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [testResult, setTestResult] = useState<GoogleBlogIndexingTestRead | null>(null);
  const [requestResult, setRequestResult] = useState<GoogleBlogIndexingRequestRead | null>(null);

  const parsedUrls = useMemo(() => parseUrls(urlsInput), [urlsInput]);
  const requestedCount = useMemo(() => {
    const parsed = Number.parseInt(countInput, 10);
    if (Number.isNaN(parsed)) return 10;
    return Math.max(1, Math.min(parsed, 500));
  }, [countInput]);

  async function handleTest() {
    setError("");
    setRequestResult(null);
    try {
      const payload = await testGoogleBlogIndexing({
        blogId,
        urls: parsedUrls.length ? parsedUrls : undefined,
        limit: parsedUrls.length ? Math.max(parsedUrls.length, 1) : 80,
      });
      setTestResult(payload);
      startTransition(() => router.refresh());
    } catch (err) {
      setError(err instanceof Error ? err.message : "URL 테스트 요청에 실패했습니다.");
    }
  }

  async function handleRequest() {
    setError("");
    try {
      const payload = await requestGoogleBlogIndexing({
        blogId,
        count: requestedCount,
        urls: parsedUrls.length ? parsedUrls : undefined,
        force,
        runTest,
        testLimit: parsedUrls.length ? Math.max(parsedUrls.length, 1) : 120,
      });
      setRequestResult(payload);
      startTransition(() => router.refresh());
    } catch (err) {
      setError(err instanceof Error ? err.message : "색인 요청에 실패했습니다.");
    }
  }

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">URL 테스트 / 색인 요청</h3>
        <p className="text-xs text-slate-500">Google Indexing API 일일 쿼터를 자동 반영합니다.</p>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <label className="space-y-1 text-xs text-slate-600">
          <span>요청 개수</span>
          <Input value={countInput} onChange={(event) => setCountInput(event.target.value)} inputMode="numeric" />
        </label>
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={runTest}
            onChange={(event) => setRunTest(event.target.checked)}
            className="h-4 w-4"
          />
          URL 테스트 선행
        </label>
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
          <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} className="h-4 w-4" />
          쿨다운 무시(force)
        </label>
      </div>

      <label className="space-y-1 text-xs text-slate-600">
        <span>대상 URL(선택, 줄바꿈/쉼표 구분)</span>
        <Textarea
          value={urlsInput}
          onChange={(event) => setUrlsInput(event.target.value)}
          placeholder="비워두면 최근 게시글 URL을 자동 선택합니다."
          rows={5}
        />
      </label>

      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={() => void handleTest()} disabled={isPending}>
          {isPending ? "실행 중..." : "URL 테스트"}
        </Button>
        <Button type="button" onClick={() => void handleRequest()} disabled={isPending}>
          {isPending ? "실행 중..." : "URL 테스트 후 색인요청"}
        </Button>
      </div>

      {testResult ? (
        <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-700">
          <p className="font-medium">테스트 상태: {summarizeActionStatus(testResult.status)}</p>
          <p>
            요청 {testResult.refresh.requested}건 / 갱신 {testResult.refresh.refreshed}건 / 실패 {testResult.refresh.failed}건
          </p>
        </div>
      ) : null}

      {requestResult ? (
        <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-700">
          <p className="font-medium">요청 상태: {summarizeActionStatus(requestResult.status)}</p>
          <p>
            요청 {requestResult.requestedCount}건 · 쿼터 반영 대상 {requestResult.plannedCount}건 · 실제 시도 {requestResult.attempted}건
          </p>
          <p>
            성공 {requestResult.success}건 / 실패 {requestResult.failed}건 / 스킵 {requestResult.skipped}건 · 잔여 쿼터{" "}
            {requestResult.remainingQuotaBefore} → {requestResult.remainingQuotaAfter}
          </p>
          {requestResult.reason ? <p className="text-amber-700">사유: {requestResult.reason}</p> : null}
          {requestResult.results.length ? (
            <div className="space-y-1 text-xs text-slate-600">
              {requestResult.results.slice(0, 5).map((item) => (
                <p key={`${item.url}-${item.status}`}>
                  [{summarizeActionStatus(item.status)}] {item.url}
                </p>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {error ? <p className="text-sm text-rose-700">{error}</p> : null}
    </div>
  );
}

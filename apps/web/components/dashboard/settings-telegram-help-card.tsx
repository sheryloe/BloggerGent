"use client";

import { useMemo, useState } from "react";

import { pollTelegramNow, testTelegram } from "@/lib/api";

const COMMANDS = [
  "/ops status",
  "/ops queue",
  "/ops review <id>",
  "/ops approve <id>",
  "/ops apply <id>",
  "/ops menu",
  "/help",
  "/help ops",
  "/help settings",
  "/help runbook <id>",
  "/help search <keyword>",
];

export function SettingsTelegramHelpCard() {
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<string>("");

  const summary = useMemo(() => (result ? result : "아직 실행 기록이 없습니다."), [result]);

  async function handleTest() {
    setIsLoading(true);
    try {
      const response = await testTelegram("Bloggent 설정 화면 테스트 메시지");
      setResult(`test: ${response.delivery_status}${response.error_message ? ` (${response.error_message})` : ""}`);
    } catch (exc) {
      setResult(`test: failed (${exc instanceof Error ? exc.message : "unknown error"})`);
    } finally {
      setIsLoading(false);
    }
  }

  async function handlePollNow() {
    setIsLoading(true);
    try {
      const response = await pollTelegramNow();
      setResult(`poll-now: ${response.status} (processed=${response.processed}, ignored=${response.ignored})`);
    } catch (exc) {
      setResult(`poll-now: failed (${exc instanceof Error ? exc.message : "unknown error"})`);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="rounded-[24px] border border-slate-200 bg-white p-5">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Telegram 운영 블록</p>
      <h2 className="mt-1 text-lg font-semibold text-slate-950">테스트 발송 / 수동 폴링 / 명령 가이드</h2>
      <p className="mt-1 text-sm text-slate-600">
        이 블록은 `/api/v1/telegram/test`, `/api/v1/telegram/poll-now` 를 직접 호출합니다.
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void handleTest()}
          disabled={isLoading}
          className="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          Telegram 테스트 발송
        </button>
        <button
          type="button"
          onClick={() => void handlePollNow()}
          disabled={isLoading}
          className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:bg-slate-100"
        >
          Poll 1회 실행
        </button>
      </div>

      <p className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">{summary}</p>

      <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-3">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">지원 명령</p>
        <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
          {COMMANDS.map((command) => (
            <p key={command} className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 font-mono text-[12px] text-slate-700">
              {command}
            </p>
          ))}
        </div>
      </div>
    </section>
  );
}

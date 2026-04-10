"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { getHelpTopic, getHelpTopics } from "@/lib/api";
import type { HelpTopicRead } from "@/lib/types";

type HelpCenterProps = {
  initialTopics: HelpTopicRead[];
};

export function HelpCenter({ initialTopics }: HelpCenterProps) {
  const [keyword, setKeyword] = useState("");
  const [topics, setTopics] = useState<HelpTopicRead[]>(initialTopics);
  const [selectedTopic, setSelectedTopic] = useState<HelpTopicRead | null>(initialTopics[0] ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const nextTopics = await getHelpTopics(keyword.trim() ? { keyword: keyword.trim() } : undefined);
        if (cancelled) {
          return;
        }
        setTopics(nextTopics);
        if (!selectedTopic || !nextTopics.some((item) => item.topicId === selectedTopic.topicId)) {
          setSelectedTopic(nextTopics[0] ?? null);
        }
      } catch (exc) {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : "도움말 목록을 불러오지 못했습니다.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [keyword, selectedTopic]);

  async function handleSelectTopic(topicId: string) {
    setLoading(true);
    setError(null);
    try {
      const detail = await getHelpTopic(topicId);
      setSelectedTopic(detail);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "도움말 상세를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  const empty = useMemo(() => !loading && topics.length === 0, [loading, topics.length]);

  return (
    <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
      <section className="rounded-[24px] border border-slate-200 bg-white p-4">
        <h2 className="text-base font-semibold text-slate-950">운영 도움말 토픽</h2>
        <p className="mt-1 text-sm text-slate-500">Telegram `/help`와 동일한 카탈로그를 사용합니다.</p>
        <input
          className="mt-3 h-10 w-full rounded-xl border border-slate-200 px-3 text-sm outline-none focus:border-slate-400"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="토픽 검색 (예: telegram, indexing)"
        />
        <div className="mt-3 space-y-2">
          {topics.map((topic) => {
            const active = selectedTopic?.topicId === topic.topicId;
            return (
              <button
                key={topic.topicId}
                type="button"
                onClick={() => void handleSelectTopic(topic.topicId)}
                className={`w-full rounded-xl border px-3 py-2 text-left transition ${
                  active ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-slate-50 hover:border-slate-300"
                }`}
              >
                <p className="text-sm font-semibold">{topic.title}</p>
                <p className={`mt-1 line-clamp-2 text-xs ${active ? "text-slate-200" : "text-slate-500"}`}>{topic.summary}</p>
              </button>
            );
          })}
        </div>
        {empty ? <p className="mt-4 text-sm text-slate-500">검색 결과가 없습니다.</p> : null}
      </section>

      <section className="rounded-[24px] border border-slate-200 bg-white p-5">
        {selectedTopic ? (
          <div className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">{selectedTopic.topicId}</p>
              <h3 className="mt-1 text-xl font-semibold text-slate-950">{selectedTopic.title}</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">{selectedTopic.summary}</p>
            </div>

            <div className="flex flex-wrap gap-2">
              {selectedTopic.tags.map((tag) => (
                <span key={`${selectedTopic.topicId}-${tag}`} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600">
                  #{tag}
                </span>
              ))}
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <article className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">명령 / 엔드포인트</p>
                <div className="mt-2 space-y-1.5">
                  {selectedTopic.commands.map((command) => (
                    <p key={`${selectedTopic.topicId}-${command}`} className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 font-mono text-[12px] text-slate-700">
                      {command}
                    </p>
                  ))}
                </div>
              </article>
              <article className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">관련 화면</p>
                <div className="mt-2 space-y-2">
                  {selectedTopic.deepLinks.map((link) => (
                    <Link key={`${selectedTopic.topicId}-${link}`} href={link} className="block rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 hover:bg-slate-100">
                      {link}
                    </Link>
                  ))}
                </div>
              </article>
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-500">왼쪽에서 토픽을 선택하세요.</p>
        )}
        {loading ? <p className="mt-4 text-xs text-slate-400">불러오는 중...</p> : null}
        {error ? <p className="mt-4 text-sm text-rose-600">{error}</p> : null}
      </section>
    </div>
  );
}

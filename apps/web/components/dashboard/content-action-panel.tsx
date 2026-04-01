"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, PencilLine, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Blog, Topic } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

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

async function fetchTopics(blogId: number) {
  const response = await fetch(`${API_BASE}/topics?blog_id=${blogId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return (await response.json()) as Topic[];
}

export function ContentActionPanel({ blogs }: { blogs: Blog[] }) {
  const router = useRouter();
  const [selectedBlogId, setSelectedBlogId] = useState<number>(blogs[0]?.id ?? 0);
  const [keyword, setKeyword] = useState("");
  const [topics, setTopics] = useState<Topic[]>([]);
  const [topicsLoading, setTopicsLoading] = useState(false);
  const [pendingAction, setPendingAction] = useState<"manual" | "discover" | null>(null);
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  const selectedBlog = useMemo(
    () => blogs.find((blog) => blog.id === selectedBlogId) ?? null,
    [blogs, selectedBlogId],
  );
  const recentTopics = useMemo(() => topics.slice(0, 6), [topics]);

  useEffect(() => {
    if (!selectedBlogId) {
      setTopics([]);
      return;
    }

    let cancelled = false;
    setTopicsLoading(true);

    void fetchTopics(selectedBlogId)
      .then((nextTopics) => {
        if (!cancelled) {
          setTopics(nextTopics);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setTopics([]);
          setFeedback({
            tone: "error",
            message: error instanceof Error ? error.message : "최근 주제를 불러오지 못했습니다.",
          });
        }
      })
      .finally(() => {
        if (!cancelled) {
          setTopicsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedBlogId]);

  async function handleManualCreate() {
    if (!selectedBlog || !keyword.trim() || pendingAction) return;

    setPendingAction("manual");
    setFeedback(null);

    try {
      const response = await fetch(`${API_BASE}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          blog_id: selectedBlog.id,
          keyword: keyword.trim(),
          publish_mode: "draft",
        }),
      });

      if (!response.ok) {
        setFeedback({ tone: "error", message: await readApiError(response) });
        return;
      }

      const job = (await response.json()) as { keyword_snapshot: string };
      setFeedback({
        tone: "success",
        message: `"${job.keyword_snapshot}" 작업을 초안 큐에 등록했습니다.`,
      });
      setKeyword("");
      router.refresh();
      setTopics(await fetchTopics(selectedBlog.id));
    } catch {
      setFeedback({ tone: "error", message: "글 생성 요청 중 네트워크 오류가 발생했습니다." });
    } finally {
      setPendingAction(null);
    }
  }

  async function handleDiscover() {
    if (!selectedBlog || pendingAction) return;

    setPendingAction("discover");
    setFeedback(null);

    try {
      const response = await fetch(`${API_BASE}/topics/discover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          blog_id: selectedBlog.id,
          publish_mode: "draft",
        }),
      });

      if (!response.ok) {
        setFeedback({ tone: "error", message: await readApiError(response) });
        return;
      }

      const payload = (await response.json()) as { queued_topics: number; message: string };
      setFeedback({
        tone: "success",
        message: payload.queued_topics
          ? `${payload.queued_topics}개의 주제를 발굴해서 초안 작업으로 등록했습니다.`
          : payload.message || "주제 자동 생성 요청을 보냈습니다.",
      });
      router.refresh();
      setTopics(await fetchTopics(selectedBlog.id));
    } catch {
      setFeedback({ tone: "error", message: "주제 자동 생성 요청 중 네트워크 오류가 발생했습니다." });
    } finally {
      setPendingAction(null);
    }
  }

  if (!blogs.length) {
    return (
      <Card>
        <CardHeader>
          <CardDescription>글 생성</CardDescription>
          <CardTitle>먼저 블로그를 연결해야 합니다.</CardTitle>
        </CardHeader>
        <CardContent className="text-sm leading-7 text-slate-500 dark:text-zinc-400">
          설정 화면에서 Blogger 블로그를 가져오면 주제 자동 생성과 수동 글 생성 기능을 바로 사용할 수 있습니다.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b border-slate-200/70 bg-gradient-to-r from-indigo-500/10 via-transparent to-emerald-500/10 dark:border-white/10">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <CardDescription>글 생성</CardDescription>
            <CardTitle className="text-2xl sm:text-[28px]">주제 발굴과 수동 생성</CardTitle>
            <p className="mt-2 text-sm leading-7 text-slate-500 dark:text-zinc-400">
              블로그 성격에 맞는 주제를 자동으로 발굴하거나, 원하는 키워드를 직접 넣어 초안 작업을 시작할 수 있습니다.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge className="border-indigo-200/80 bg-indigo-500/10 text-indigo-700 dark:border-indigo-500/20 dark:bg-indigo-500/15 dark:text-indigo-200">
              수동 생성
            </Badge>
            <Badge className="border-emerald-200/80 bg-emerald-500/10 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/15 dark:text-emerald-200">
              자동 발굴
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="grid gap-6 p-5 sm:p-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(280px,0.85fr)]">
        <div className="min-w-0 space-y-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-[22px] border border-slate-200/70 bg-slate-50/80 px-4 py-4 dark:border-white/10 dark:bg-white/5">
              <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">선택 블로그</p>
              <p className="mt-2 truncate text-base font-semibold text-slate-950 dark:text-zinc-50">
                {selectedBlog?.name ?? "미선택"}
              </p>
            </div>
            <div className="rounded-[22px] border border-slate-200/70 bg-slate-50/80 px-4 py-4 dark:border-white/10 dark:bg-white/5">
              <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">카테고리</p>
              <p className="mt-2 truncate text-base font-semibold text-slate-950 dark:text-zinc-50">
                {selectedBlog?.content_category ?? "미설정"}
              </p>
            </div>
            <div className="rounded-[22px] border border-slate-200/70 bg-slate-50/80 px-4 py-4 dark:border-white/10 dark:bg-white/5">
              <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">언어</p>
              <p className="mt-2 truncate text-base font-semibold text-slate-950 dark:text-zinc-50">
                {selectedBlog?.primary_language ?? "미설정"}
              </p>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
            <div className="min-w-0 space-y-2">
              <Label htmlFor="content-blog-select">대상 블로그</Label>
              <select
                id="content-blog-select"
                className="flex h-12 w-full truncate rounded-2xl border border-slate-200/80 bg-white/85 px-4 text-sm text-slate-900 outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 dark:border-white/10 dark:bg-white/5 dark:text-zinc-100"
                value={selectedBlogId}
                onChange={(event) => {
                  setSelectedBlogId(Number(event.target.value));
                  setFeedback(null);
                }}
              >
                {blogs.map((blog) => (
                  <option key={blog.id} value={blog.id}>
                    {blog.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="min-w-0 space-y-2">
              <Label htmlFor="manual-keyword">직접 생성할 주제</Label>
              <Input
                id="manual-keyword"
                value={keyword}
                placeholder="예: 서울 성수동 1일 로컬 코스"
                onChange={(event) => {
                  setKeyword(event.target.value);
                  setFeedback(null);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void handleManualCreate();
                  }
                }}
              />
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <button
              type="button"
              onClick={() => void handleDiscover()}
              disabled={!!pendingAction}
              className="rounded-[28px] border border-emerald-200/70 bg-emerald-500/10 px-5 py-5 text-left text-slate-900 transition hover:-translate-y-0.5 hover:bg-emerald-500/15 disabled:cursor-not-allowed disabled:opacity-60 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-zinc-100 dark:hover:bg-emerald-500/15"
            >
              <div className="flex items-start gap-3">
                <div className="rounded-2xl bg-emerald-500/15 p-3 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200">
                  <Sparkles className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <p className="text-base font-semibold">
                    {pendingAction === "discover" ? "주제 발굴 중..." : "주제 자동 발굴"}
                  </p>
                  <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-600 dark:text-zinc-400">
                    선택한 블로그의 성격에 맞는 주제를 찾아서 초안 작업까지 연결합니다.
                  </p>
                </div>
              </div>
            </button>

            <button
              type="button"
              onClick={() => void handleManualCreate()}
              disabled={!keyword.trim() || !!pendingAction}
              className="rounded-[28px] border border-slate-200/70 bg-slate-950 px-5 py-5 text-left text-white transition hover:-translate-y-0.5 hover:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-60 dark:border-white/10 dark:bg-white dark:text-slate-950 dark:hover:bg-zinc-100"
            >
              <div className="flex items-start gap-3">
                <div className="rounded-2xl bg-white/10 p-3 text-white dark:bg-slate-950/10 dark:text-slate-950">
                  <PencilLine className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <p className="text-base font-semibold">
                    {pendingAction === "manual" ? "글 생성 중..." : "주제 직접 생성"}
                  </p>
                  <p className="mt-1 line-clamp-2 text-sm leading-6 text-white/75 dark:text-slate-600">
                    입력한 키워드로 바로 초안 생성 작업을 시작합니다.
                  </p>
                </div>
              </div>
            </button>
          </div>

          <div className="rounded-[28px] border border-slate-200/70 bg-slate-50/80 p-4 dark:border-white/10 dark:bg-white/5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge>{selectedBlog?.content_category ?? "custom"}</Badge>
              <Badge className="bg-transparent">{selectedBlog?.primary_language ?? "n/a"}</Badge>
            </div>
            <p className="mt-3 text-sm leading-6 text-slate-500 dark:text-zinc-400">
              여기서 생성하는 작업은 모두 초안 기준입니다. 실제 공개 여부는 글 보관 또는 발행 큐에서 최종 결정합니다.
            </p>
          </div>

          {feedback ? (
            <div
              className={`rounded-[24px] border px-4 py-4 text-sm leading-7 ${
                feedback.tone === "success"
                  ? "border-emerald-200/80 bg-emerald-500/10 text-emerald-800 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200"
                  : "border-rose-200/80 bg-rose-500/10 text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200"
              }`}
            >
              {feedback.message}
            </div>
          ) : null}
        </div>

        <div className="min-w-0 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">최근 발굴 주제</p>
              <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-zinc-400">
                클릭하면 입력창에 바로 채워집니다.
              </p>
            </div>
            <ArrowRight className="h-4 w-4 shrink-0 text-slate-400 dark:text-zinc-500" />
          </div>

          {topicsLoading ? (
            <div className="rounded-[28px] border border-dashed border-slate-200/80 bg-slate-50/80 px-4 py-5 text-sm leading-7 text-slate-500 dark:border-white/10 dark:bg-white/5 dark:text-zinc-400">
              최근 주제를 불러오는 중입니다.
            </div>
          ) : recentTopics.length ? (
            <div className="grid gap-3">
              {recentTopics.map((topic) => (
                <button
                  key={topic.id}
                  type="button"
                  onClick={() => {
                    setKeyword(topic.keyword);
                    setFeedback(null);
                  }}
                  className="rounded-[24px] border border-slate-200/70 bg-white/85 px-4 py-4 text-left transition hover:-translate-y-0.5 hover:bg-white dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10"
                >
                  <p className="line-clamp-2 text-sm font-semibold leading-6 text-slate-950 dark:text-zinc-100 sm:text-base">
                    {topic.keyword}
                  </p>
                  <div className="mt-3 flex items-center justify-between gap-3">
                    <p className="truncate text-xs uppercase tracking-[0.18em] text-slate-400 dark:text-zinc-500">
                      {topic.source}
                    </p>
                    <span className="shrink-0 text-xs text-slate-400 dark:text-zinc-500">채우기</span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="rounded-[28px] border border-dashed border-slate-200/80 bg-slate-50/80 px-4 py-5 text-sm leading-7 text-slate-500 dark:border-white/10 dark:bg-white/5 dark:text-zinc-400">
              아직 저장된 최근 주제가 없습니다. 자동 발굴을 먼저 실행하거나 직접 키워드를 입력하세요.
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { ArticlePreviewFrame } from "@/components/dashboard/article-preview-frame";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ArticleDetail, ArticleListItem, JobListItem } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function DashboardRecentActivity() {
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [featuredArticle, setFeaturedArticle] = useState<ArticleDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError("");
      try {
        const [nextJobs, articleList] = await Promise.all([
          fetchJson<JobListItem[]>("/jobs?limit=8"),
          fetchJson<ArticleListItem[]>("/articles?limit=1"),
        ]);
        const nextArticle = articleList[0]
          ? await fetchJson<ArticleDetail>(`/articles/${articleList[0].id}`).catch(() => null)
          : null;

        if (!cancelled) {
          setJobs(nextJobs);
          setFeaturedArticle(nextArticle);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "최근 데이터를 불러오지 못했습니다.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardDescription>최근 작업</CardDescription>
            <CardTitle>비동기 작업 큐</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {loading ? (
              <p className="text-sm leading-7 text-slate-600 dark:text-zinc-400">최근 작업을 불러오는 중입니다.</p>
            ) : error ? (
              <p className="text-sm leading-7 text-rose-700 dark:text-rose-300">{error}</p>
            ) : jobs.length > 0 ? (
              jobs.map((job) => (
                <Link
                  key={job.id}
                  href={`/content-ops?tab=jobs&job=${job.id}`}
                  prefetch={false}
                  className="block rounded-[24px] border border-slate-200/70 bg-white/80 px-4 py-4 transition hover:bg-white dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="line-clamp-2 font-semibold text-slate-950 dark:text-zinc-100">
                        {job.article?.title ?? job.keyword_snapshot}
                      </p>
                      <p className="mt-1 text-sm text-slate-500 dark:text-zinc-400">{job.blog?.name ?? "-"}</p>
                      <p className="mt-2 text-xs uppercase tracking-[0.16em] text-slate-400 dark:text-zinc-500">
                        {formatDateTime(job.created_at)}
                      </p>
                    </div>
                    <StatusBadge status={job.status} />
                  </div>
                </Link>
              ))
            ) : (
              <p className="text-sm leading-7 text-slate-600 dark:text-zinc-400">최근 작업이 없습니다.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardDescription>대표 미리보기</CardDescription>
            <CardTitle>최근 생성 글</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <p className="text-sm leading-7 text-slate-600 dark:text-zinc-400">대표 글을 준비하는 중입니다.</p>
            ) : featuredArticle ? (
              <>
                <div>
                  <p className="text-lg font-semibold text-slate-950 dark:text-zinc-100">{featuredArticle.title}</p>
                  <p className="mt-2 text-sm leading-7 text-slate-600 dark:text-zinc-400">
                    {featuredArticle.meta_description}
                  </p>
                </div>
                <ArticlePreviewFrame article={featuredArticle} height={320} />
                <Button asChild variant="outline" className="w-full">
                  <Link href="/content-ops?tab=articles" prefetch={false}>글 보관에서 이어서 보기</Link>
                </Button>
              </>
            ) : (
              <p className="text-sm leading-7 text-slate-600 dark:text-zinc-400">최근 생성 글이 없습니다.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

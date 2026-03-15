"use client";

import { useState } from "react";

import type { ArticleSeoMeta } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

function StatusBadge({ status }: { status: ArticleSeoMeta["head_meta_description_status"]["status"] }) {
  if (status === "ok") return <Badge className="bg-emerald-700 text-white">정상</Badge>;
  if (status === "warning") return <Badge className="bg-amber-100 text-amber-900">주의</Badge>;
  return <Badge className="bg-slate-200 text-slate-700">대기</Badge>;
}

function StatusRow({
  label,
  status,
}: {
  label: string;
  status: ArticleSeoMeta["head_meta_description_status"];
}) {
  return (
    <div className="rounded-[20px] border border-ink/10 bg-white/70 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-ink">{label}</p>
        <StatusBadge status={status.status} />
      </div>
      <p className="mt-2 text-sm leading-7 text-slate-600">{status.message}</p>
      {status.actual ? <p className="mt-2 break-all text-xs text-slate-500">actual: {status.actual}</p> : null}
      {status.expected ? <p className="mt-1 break-all text-xs text-slate-500">expected: {status.expected}</p> : null}
    </div>
  );
}

export function ArticleSeoMetaCard({
  articleId,
  initialMeta,
}: {
  articleId: number;
  initialMeta: ArticleSeoMeta;
}) {
  const [meta, setMeta] = useState(initialMeta);
  const [error, setError] = useState("");
  const [isPending, setIsPending] = useState(false);

  async function handleVerify() {
    setError("");
    setIsPending(true);
    try {
      const response = await fetch(`${apiBase}/articles/${articleId}/seo-meta/verify`, {
        method: "POST",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        setError(payload?.detail ?? "SEO 메타 검증에 실패했습니다.");
        return;
      }
      const payload = (await response.json()) as ArticleSeoMeta;
      setMeta(payload);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "SEO 메타 검증에 실패했습니다.");
    } finally {
      setIsPending(false);
    }
  }

  return (
    <div className="rounded-[24px] border border-ink/10 bg-white/70 p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-slate-500">SEO 메타 검증</p>
          <p className="mt-2 text-sm leading-7 text-slate-600">
            이 글의 공개 페이지 head 메타가 앱의 검색 설명과 실제로 일치하는지 확인합니다.
          </p>
          {meta.verification_target_url ? (
            <a
              href={meta.verification_target_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 block break-all text-sm font-medium text-ember underline-offset-4 hover:underline"
            >
              {meta.verification_target_url}
            </a>
          ) : null}
        </div>
        <Button type="button" variant="outline" onClick={handleVerify} disabled={isPending}>
          {isPending ? "검증 중..." : "글별 검증 실행"}
        </Button>
      </div>

      {meta.warnings.length ? (
        <div className="mt-4 rounded-[20px] border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-900">
          {meta.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      ) : null}

      {error ? (
        <div className="mt-4 rounded-[20px] border border-rose-200 bg-rose-50 p-4 text-sm leading-7 text-rose-900">{error}</div>
      ) : null}

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <StatusRow label="head meta description" status={meta.head_meta_description_status} />
        <StatusRow label="og:description" status={meta.og_description_status} />
        <StatusRow label="twitter:description" status={meta.twitter_description_status} />
      </div>
    </div>
  );
}

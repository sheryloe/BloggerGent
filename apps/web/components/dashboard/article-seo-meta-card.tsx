"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ArticleSearchDescriptionSync, ArticleSeoMeta } from "@/lib/types";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

function StatusBadge({ status }: { status: ArticleSeoMeta["head_meta_description_status"]["status"] }) {
  if (status === "ok") return <Badge className="bg-emerald-700 text-white">OK</Badge>;
  if (status === "warning") return <Badge className="bg-amber-100 text-amber-900">Warning</Badge>;
  return <Badge className="bg-slate-200 text-slate-700">Idle</Badge>;
}

function StatusRow({ label, status }: { label: string; status: ArticleSeoMeta["head_meta_description_status"] }) {
  return (
    <div className="rounded-[20px] border border-slate-200/80 bg-white/70 p-4 dark:border-white/10 dark:bg-white/5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-950 dark:text-zinc-100">{label}</p>
        <StatusBadge status={status.status} />
      </div>
      <p className="mt-2 text-sm leading-7 text-slate-600 dark:text-zinc-400">{status.message}</p>
      {status.actual ? <p className="mt-2 break-all text-xs text-slate-500 dark:text-zinc-500">actual: {status.actual}</p> : null}
      {status.expected ? <p className="mt-1 break-all text-xs text-slate-500 dark:text-zinc-500">expected: {status.expected}</p> : null}
    </div>
  );
}

function buildSummary(meta: ArticleSeoMeta) {
  const statuses = [meta.head_meta_description_status.status, meta.og_description_status.status, meta.twitter_description_status.status];

  if (statuses.every((status) => status === "idle")) {
    if (!meta.verification_target_url) {
      return "This article has not been published yet, so live meta tag verification is not available.";
    }
    return "This card checks whether description, og:description, and twitter:description match the expected article meta description.";
  }

  if (meta.warnings.length > 0) {
    return meta.warnings[0];
  }

  return "Verification compares the expected article description with the live meta tags on the public page.";
}

export function ArticleSeoMetaCard({ articleId, initialMeta }: { articleId: number; initialMeta: ArticleSeoMeta }) {
  const router = useRouter();
  const [meta, setMeta] = useState(initialMeta);
  const [error, setError] = useState("");
  const [syncMessage, setSyncMessage] = useState("");
  const [isVerifying, setIsVerifying] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);

  const summary = useMemo(() => buildSummary(meta), [meta]);

  async function refreshVerification() {
    const response = await fetch(`${apiBase}/articles/${articleId}/seo-meta/verify`, { method: "POST" });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? "SEO meta verification failed.");
    }

    const payload = (await response.json()) as ArticleSeoMeta;
    setMeta(payload);
    router.refresh();
  }

  async function handleVerify() {
    setError("");
    setSyncMessage("");
    setIsVerifying(true);
    try {
      await refreshVerification();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "SEO meta verification failed.");
    } finally {
      setIsVerifying(false);
    }
  }

  async function handleSyncSearchDescription() {
    setError("");
    setSyncMessage("");
    setIsSyncing(true);
    try {
      const response = await fetch(`${apiBase}/articles/${articleId}/search-description/sync`, { method: "POST" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Search description sync failed.");
      }

      const payload = (await response.json()) as ArticleSearchDescriptionSync;
      setSyncMessage(payload.message);
      await refreshVerification();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Search description sync failed.");
    } finally {
      setIsSyncing(false);
    }
  }

  return (
    <div className="rounded-[24px] border border-slate-200/80 bg-white/70 p-5 dark:border-white/10 dark:bg-white/5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-[0.16em] text-slate-500 dark:text-zinc-500">SEO verification</p>
          <p className="mt-2 text-sm leading-7 text-slate-600 dark:text-zinc-400">{summary}</p>
          {meta.verification_target_url ? (
            <a href={meta.verification_target_url} target="_blank" rel="noreferrer" className="mt-2 block break-all text-sm font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-300">
              {meta.verification_target_url}
            </a>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={handleVerify} disabled={isVerifying || isSyncing}>
            {isVerifying ? "Verifying..." : "Verify meta tags"}
          </Button>
          <Button type="button" onClick={handleSyncSearchDescription} disabled={isVerifying || isSyncing}>
            {isSyncing ? "Syncing..." : "Sync search description"}
          </Button>
        </div>
      </div>

      {meta.warnings.length ? <div className="mt-4 rounded-[20px] border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-900 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200">{meta.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div> : null}
      {error ? <div className="mt-4 rounded-[20px] border border-rose-200 bg-rose-50 p-4 text-sm leading-7 text-rose-900 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">{error}</div> : null}
      {syncMessage ? <div className="mt-4 rounded-[20px] border border-emerald-200 bg-emerald-50 p-4 text-sm leading-7 text-emerald-900 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200">{syncMessage}</div> : null}

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <StatusRow label="description" status={meta.head_meta_description_status} />
        <StatusRow label="og:description" status={meta.og_description_status} />
        <StatusRow label="twitter:description" status={meta.twitter_description_status} />
      </div>
    </div>
  );
}

"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type PageModeGuideCardProps = {
  title: string;
  purpose: string;
  whenToUse: string;
  dataSource: string;
  caution: string;
};

export function PageModeGuideCard({
  title,
  purpose,
  whenToUse,
  dataSource,
  caution,
}: PageModeGuideCardProps) {
  return (
    <Card className="border-slate-200/70 bg-white/85 shadow-sm dark:border-white/10 dark:bg-zinc-950/70">
      <CardHeader className="pb-4">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-zinc-400">
          모드 설명
        </p>
        <CardTitle className="text-2xl text-slate-950 dark:text-zinc-50">{title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-[22px] border border-slate-200/70 bg-slate-50/80 p-4 dark:border-white/10 dark:bg-white/5">
          <p className="text-sm font-semibold text-slate-900 dark:text-zinc-100">이 페이지에서 하는 일</p>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-zinc-400">{purpose}</p>
        </div>
        <div className="rounded-[22px] border border-slate-200/70 bg-slate-50/80 p-4 dark:border-white/10 dark:bg-white/5">
          <p className="text-sm font-semibold text-slate-900 dark:text-zinc-100">언제 들어오면 되는지</p>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-zinc-400">{whenToUse}</p>
        </div>
        <div className="rounded-[22px] border border-slate-200/70 bg-slate-50/80 p-4 dark:border-white/10 dark:bg-white/5">
          <p className="text-sm font-semibold text-slate-900 dark:text-zinc-100">데이터 출처</p>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-zinc-400">{dataSource}</p>
        </div>
        <div className="rounded-[22px] border border-slate-200/70 bg-slate-50/80 p-4 dark:border-white/10 dark:bg-white/5">
          <p className="text-sm font-semibold text-slate-900 dark:text-zinc-100">주의할 작업</p>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-zinc-400">{caution}</p>
        </div>
      </CardContent>
    </Card>
  );
}

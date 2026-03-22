"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  BookOpenText,
  Cpu,
  LayoutDashboard,
  MoonStar,
  Newspaper,
  Settings2,
  Sparkles,
  Workflow,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const items = [
  { href: "/", label: "대시보드", icon: LayoutDashboard },
  { href: "/guide", label: "가이드", icon: BookOpenText },
  { href: "/google", label: "구글 데이터", icon: BarChart3 },
  { href: "/jobs", label: "작업 현황", icon: Workflow },
  { href: "/articles", label: "글 보관함", icon: Newspaper },
  { href: "/settings", label: "설정", icon: Settings2 },
  { href: "/training", label: "학습 진행", icon: Cpu },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden min-h-screen w-[292px] shrink-0 border-r border-slate-200/70 bg-white/78 px-5 py-5 backdrop-blur-2xl dark:border-white/10 dark:bg-zinc-950/75 lg:block xl:w-[308px]">
      <div className="sticky top-5 flex h-[calc(100vh-2.5rem)] flex-col">
        <div className="space-y-5">
          <Badge className="w-fit border-indigo-200/80 bg-indigo-500/10 text-indigo-700 dark:border-indigo-500/20 dark:bg-indigo-500/15 dark:text-indigo-200">
            Publishing Console
          </Badge>

          <div className="rounded-[30px] border border-slate-200/70 bg-white/85 p-5 shadow-sm dark:border-white/10 dark:bg-white/5">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-slate-950 p-3 text-white dark:bg-white dark:text-slate-950">
                <Sparkles className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-950 dark:text-zinc-50">
                  Bloggent
                </h1>
                <p className="text-xs uppercase tracking-[0.24em] text-slate-400 dark:text-zinc-500">
                  Content Ops
                </p>
              </div>
            </div>
            <p className="mt-4 text-sm leading-7 text-slate-500 dark:text-zinc-400">
              글 생성, 발행, 구글 지표, Cloudflare 채널 상태를 한 콘솔에서 관리합니다.
            </p>
          </div>
        </div>

        <nav className="mt-8 space-y-2">
          {items.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;

            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "group flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition",
                  active
                    ? "bg-slate-950 text-white shadow-[0_18px_36px_rgba(15,23,42,0.18)] dark:bg-white dark:text-slate-950"
                    : "text-slate-600 hover:bg-slate-100/85 hover:text-slate-950 dark:text-zinc-300 dark:hover:bg-white/5 dark:hover:text-zinc-50",
                )}
              >
                <span
                  className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-xl transition",
                    active
                      ? "bg-white/15 text-white dark:bg-slate-950/10 dark:text-slate-950"
                      : "bg-slate-100 text-slate-500 group-hover:bg-white group-hover:text-slate-900 dark:bg-white/5 dark:text-zinc-400 dark:group-hover:bg-white/10 dark:group-hover:text-zinc-100",
                  )}
                >
                  <Icon className="h-4 w-4" />
                </span>
                <span className="truncate">{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto space-y-4">
          <div className="rounded-[28px] border border-slate-200/70 bg-gradient-to-br from-slate-950 to-slate-800 p-5 text-white shadow-[0_18px_40px_rgba(15,23,42,0.18)] dark:border-white/10 dark:from-zinc-900 dark:to-zinc-800">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-white/10 p-2">
                <MoonStar className="h-4 w-4" />
              </div>
              <div>
                <p className="text-sm font-semibold">테마 모드</p>
                <p className="text-xs uppercase tracking-[0.2em] text-white/55">Light / Dark</p>
              </div>
            </div>
            <p className="mt-4 text-sm leading-6 text-white/75">
              UI 표시만 전환하고 데이터나 발행 로직에는 영향을 주지 않습니다.
            </p>
          </div>

          <div className="rounded-[28px] border border-slate-200/70 bg-slate-50/80 p-5 dark:border-white/10 dark:bg-white/5">
            <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">현재 범위</p>
            <p className="mt-3 text-sm leading-7 text-slate-600 dark:text-zinc-300">
              Blogger 운영과 Cloudflare 채널 모니터링을 같은 대시보드에서 보도록 확장한 상태입니다.
            </p>
          </div>
        </div>
      </div>
    </aside>
  );
}

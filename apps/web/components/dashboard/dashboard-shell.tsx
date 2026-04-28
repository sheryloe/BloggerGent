"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Bot, ClipboardCheck, Gauge, LayoutGrid, LineChart, Link2, PlaySquare } from "lucide-react";

import { ThemeToggle } from "@/components/dashboard/theme-toggle";

type NavItem = {
  href: string;
  label: string;
};

type WorkspaceCard = {
  href: string;
  label: string;
  description: string;
  icon: typeof LayoutGrid;
  accent: string;
};

const PRIMARY_ROOMS: WorkspaceCard[] = [
  {
    href: "/dashboard",
    label: "운영 홈",
    description: "전체 자동화 상태, 실패, 최근 생성/게시 흐름을 봅니다.",
    icon: LayoutGrid,
    accent: "from-[#f97316] via-[#ea580c] to-[#c2410c]",
  },
  {
    href: "/planner",
    label: "생성 운영",
    description: "Antigravity가 읽을 생성 슬롯과 카테고리 규칙을 관리합니다.",
    icon: PlaySquare,
    accent: "from-[#0ea5e9] via-[#0284c7] to-[#0369a1]",
  },
  {
    href: "/analytics",
    label: "게시글 분석",
    description: "SEO, CTR, GEO, Lighthouse, 색인 상태를 확인합니다.",
    icon: LineChart,
    accent: "from-[#2563eb] via-[#1d4ed8] to-[#1e3a8a]",
  },
  {
    href: "/content-ops",
    label: "콘텐츠 검수",
    description: "게시글 검수, 작업 큐, 생성/동기화 글을 점검합니다.",
    icon: ClipboardCheck,
    accent: "from-[#10b981] via-[#059669] to-[#047857]",
  },
  {
    href: "/settings",
    label: "프롬프트/설정",
    description: "API, OAuth, R2, 모델, 채널, 프롬프트 플로우를 관리합니다.",
    icon: Link2,
    accent: "from-[#7c3aed] via-[#6d28d9] to-[#5b21b6]",
  },
  {
    href: "/ops-health",
    label: "운영 상태",
    description: "런타임, 실패 작업, 토큰 사용량, 동기화 상태를 확인합니다.",
    icon: Activity,
    accent: "from-[#06b6d4] via-[#0891b2] to-[#0e7490]",
  },
];

function isActivePath(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function DashboardShell({ children, nav }: { children: React.ReactNode; nav?: NavItem[] }) {
  const pathname = usePathname();
  const navSet = new Set((nav ?? []).map((item) => item.href));
  const primaryRooms = PRIMARY_ROOMS.filter((item) => navSet.size === 0 || navSet.has(item.href));
  const compactWorkspace = pathname.startsWith("/planner");
  const shellGridClass = compactWorkspace
    ? "mx-auto grid min-h-[calc(100vh-2rem)] w-full gap-3 xl:grid-cols-[256px_minmax(0,1fr)] 2xl:grid-cols-[256px_minmax(0,1fr)]"
    : "mx-auto grid min-h-[calc(100vh-2rem)] w-full gap-4 xl:grid-cols-[256px_minmax(0,1fr)] 2xl:grid-cols-[256px_minmax(0,1fr)]";
  const mainCardClass = compactWorkspace
    ? "min-w-0 rounded-[30px] border border-slate-200 bg-white/95 p-3 shadow-[0_20px_50px_rgba(15,23,42,0.06)] backdrop-blur dark:border-white/10 dark:bg-slate-900/70 dark:shadow-[0_20px_50px_rgba(0,0,0,0.42)] sm:p-4 lg:p-5"
    : "min-w-0 rounded-[30px] border border-slate-200 bg-white/95 p-4 shadow-[0_20px_50px_rgba(15,23,42,0.06)] backdrop-blur dark:border-white/10 dark:bg-slate-900/70 dark:shadow-[0_20px_50px_rgba(0,0,0,0.42)] sm:p-5 lg:p-6";

  return (
    <div
      className={`dashboard-shell min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(251,146,60,0.14),_transparent_28%),radial-gradient(circle_at_top_right,_rgba(14,165,233,0.12),_transparent_24%),linear-gradient(180deg,#f8fafc_0%,#eef2ff_100%)] text-slate-950 dark:bg-[radial-gradient(circle_at_top_left,_rgba(249,115,22,0.18),_transparent_26%),radial-gradient(circle_at_top_right,_rgba(37,99,235,0.18),_transparent_24%),linear-gradient(180deg,#030712_0%,#0b1220_100%)] dark:text-zinc-100 ${compactWorkspace ? "px-3 py-3 sm:px-4 lg:px-5" : "px-4 py-4 sm:px-5 lg:px-6"}`}
    >
      <div className="mx-auto mb-3 flex w-full justify-end">
        <ThemeToggle />
      </div>

      <div className={shellGridClass}>
        <aside className="rounded-[30px] border border-slate-200 bg-white/95 p-4 shadow-[0_20px_50px_rgba(15,23,42,0.08)] backdrop-blur dark:border-white/10 dark:bg-slate-900/70 dark:shadow-[0_20px_50px_rgba(0,0,0,0.45)] sm:p-5">
          <div className="rounded-[26px] bg-[linear-gradient(135deg,#0f172a_0%,#1e293b_45%,#334155_100%)] p-5 text-white">
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-white/70">Antigravity Console</p>
            <h1 className="mt-3 text-[26px] font-semibold leading-tight">자동 블로그 운영</h1>
            <p className="mt-3 text-sm leading-6 text-white/82">
              자동 생성은 Antigravity가 수행하고, 이 콘솔에서는 검수와 분석, 연동 설정, 프롬프트 규칙을 관리합니다.
            </p>
          </div>

          <div className="mt-5">
            <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500 dark:text-zinc-400">운영 메뉴</p>
            <nav className="mt-3 space-y-2">
              {primaryRooms.map((item) => {
                const active = isActivePath(pathname, item.href);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`flex items-start gap-3 rounded-[22px] border px-4 py-3 transition ${
                      active
                        ? "border-slate-950 bg-slate-950 text-white shadow-sm dark:border-zinc-200 dark:bg-zinc-100 dark:text-zinc-950"
                        : "border-slate-200 bg-white text-slate-900 hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-slate-900/60 dark:text-zinc-100 dark:hover:bg-slate-800/70"
                    }`}
                  >
                    <div className={`rounded-[18px] bg-gradient-to-br p-2.5 text-white ${item.accent}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <p className={`text-sm font-semibold ${active ? "text-inherit" : "text-slate-900 dark:text-zinc-100"}`}>
                        {item.label}
                      </p>
                      <p
                        className={`mt-1 text-xs leading-5 ${
                          active ? "text-slate-200 dark:text-zinc-700" : "text-slate-600 dark:text-zinc-400"
                        }`}
                      >
                        {item.description}
                      </p>
                    </div>
                  </Link>
                );
              })}
            </nav>
          </div>

          <div className="mt-5 rounded-[24px] border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-slate-900/60">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500 dark:text-zinc-400">운영 루프</p>
                <p className="mt-2 text-sm font-semibold text-slate-950 dark:text-zinc-100">주제/규칙 → 자동 생성 → 검수 → 분석</p>
              </div>
              <Bot className="h-5 w-5 text-slate-500 dark:text-zinc-400" />
            </div>
            <div className="mt-4 grid gap-2">
              <span className="rounded-2xl bg-[#fff7ed] px-3 py-2 text-sm font-semibold text-[#9a3412] dark:bg-amber-500/15 dark:text-amber-200">
                주제/규칙
              </span>
              <span className="rounded-2xl bg-[#eff6ff] px-3 py-2 text-sm font-semibold text-[#1d4ed8] dark:bg-sky-500/15 dark:text-sky-200">
                자동 생성
              </span>
              <span className="rounded-2xl bg-[#ecfdf5] px-3 py-2 text-sm font-semibold text-[#047857] dark:bg-emerald-500/15 dark:text-emerald-200">
                검수
              </span>
              <span className="rounded-2xl bg-[#f5f3ff] px-3 py-2 text-sm font-semibold text-[#6d28d9] dark:bg-violet-500/15 dark:text-violet-200">
                분석
              </span>
            </div>
          </div>

          <div className="mt-5 rounded-[24px] border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-slate-900/60">
            <div className="flex items-center gap-3">
              <Gauge className="h-5 w-5 text-slate-500 dark:text-zinc-400" />
              <div>
                <p className="text-sm font-semibold text-slate-950 dark:text-zinc-100">운영 기준</p>
                <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-zinc-400">
                  자동화는 설정에서 제어하고, 문제는 운영 상태와 분석 화면에서 확인합니다.
                </p>
              </div>
            </div>
          </div>
        </aside>

        <main className={mainCardClass}>{children}</main>
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  ArrowUpRight,
  Bot,
  Compass,
  FileStack,
  LayoutGrid,
  LineChart,
  Link2,
  Orbit,
  PanelsTopLeft,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

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
    label: "미션 컨트롤",
    description: "운영 상태와 실행 신호를 한 화면에서 확인합니다.",
    icon: PanelsTopLeft,
    accent: "from-[#f97316] via-[#ea580c] to-[#c2410c]",
  },
  {
    href: "/planner",
    label: "게시 플래너 운영",
    description: "월간 계획, 배치, 발행 흐름을 관리합니다.",
    icon: Compass,
    accent: "from-[#0ea5e9] via-[#0284c7] to-[#0369a1]",
  },
  {
    href: "/content-ops",
    label: "콘텐츠 운영",
    description: "블로그, 유튜브, 인스타 작업 흐름을 분리해 운영합니다.",
    icon: Sparkles,
    accent: "from-[#10b981] via-[#059669] to-[#047857]",
  },
  {
    href: "/analytics",
    label: "분석",
    description: "채널 성과와 개선 신호를 추적합니다.",
    icon: LineChart,
    accent: "from-[#2563eb] via-[#1d4ed8] to-[#1e3a8a]",
  },
  {
    href: "/settings",
    label: "연동 설정",
    description: "OAuth, API 키, 플랫폼 연결을 구성합니다.",
    icon: Link2,
    accent: "from-[#7c3aed] via-[#6d28d9] to-[#5b21b6]",
  },
  {
    href: "/admin",
    label: "관리자 설정",
    description: "운영 기본값과 자동화 정책을 제어합니다.",
    icon: ShieldCheck,
    accent: "from-[#475569] via-[#334155] to-[#0f172a]",
  },
  {
    href: "/ops-health",
    label: "운영 모니터",
    description: "실시간 동기화와 장애 징후를 감시합니다.",
    icon: Activity,
    accent: "from-[#06b6d4] via-[#0891b2] to-[#0e7490]",
  },
];

const OPERATOR_LINKS: WorkspaceCard[] = [
  {
    href: "/jobs",
    label: "작업 큐",
    description: "실행 중이거나 실패한 작업을 빠르게 확인합니다.",
    icon: FileStack,
    accent: "from-[#ec4899] via-[#db2777] to-[#be185d]",
  },
  {
    href: "/articles",
    label: "글 보관",
    description: "생성 결과와 발행 콘텐츠를 조회합니다.",
    icon: Orbit,
    accent: "from-[#14b8a6] via-[#0f766e] to-[#134e4a]",
  },
  {
    href: "/content-overview",
    label: "콘텐츠 현황",
    description: "전체 건수와 카테고리 상태를 점검합니다.",
    icon: Bot,
    accent: "from-[#a855f7] via-[#9333ea] to-[#7e22ce]",
  },
  {
    href: "/guide",
    label: "가이드",
    description: "운영 절차와 흐름 문서를 확인합니다.",
    icon: ArrowUpRight,
    accent: "from-[#94a3b8] via-[#64748b] to-[#475569]",
  },
  {
    href: "/help",
    label: "운영형 도움말",
    description: "Telegram /help 카탈로그를 검색하고 runbook 기준으로 실행합니다.",
    icon: Orbit,
    accent: "from-[#0ea5e9] via-[#0284c7] to-[#0369a1]",
  },
  {
    href: "/training",
    label: "학습",
    description: "학습 상태와 운영 기록을 확인합니다.",
    icon: Activity,
    accent: "from-[#22c55e] via-[#16a34a] to-[#166534]",
  },
];

function isActivePath(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function DashboardShell({ children, nav }: { children: React.ReactNode; nav?: NavItem[] }) {
  const pathname = usePathname();
  const navSet = new Set((nav ?? []).map((item) => item.href));
  const primaryRooms = PRIMARY_ROOMS.filter((item) => navSet.size === 0 || navSet.has(item.href));
  const compactWorkspace = pathname.startsWith("/planner") || pathname.startsWith("/admin");
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
          <div className="rounded-[26px] bg-[linear-gradient(135deg,#0f172a_0%,#1e293b_40%,#334155_100%)] p-5 text-white">
            <p className="text-[11px] font-semibold uppercase tracking-[0.32em] text-white/70">동그리 자동 블로그전트</p>
            <h1 className="mt-3 text-[28px] font-semibold leading-none">운영 작업공간</h1>
            <p className="mt-3 text-sm leading-6 text-white/82">
              대시보드, 관리자 설정, 연동 설정, 운영 모니터를 분리해 관리합니다.
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
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500 dark:text-zinc-400">운영 루프</p>
                <p className="mt-2 text-sm font-semibold text-slate-950 dark:text-zinc-100">초안 {"->"} 검토 {"->"} 게시 {"->"} 피드백</p>
              </div>
              <Bot className="h-5 w-5 text-slate-500 dark:text-zinc-400" />
            </div>
            <div className="mt-4 grid gap-2">
              <span className="rounded-2xl bg-[#fff7ed] px-3 py-2 text-sm font-semibold text-[#9a3412] dark:bg-amber-500/15 dark:text-amber-200">
                초안
              </span>
              <span className="rounded-2xl bg-[#eff6ff] px-3 py-2 text-sm font-semibold text-[#1d4ed8] dark:bg-sky-500/15 dark:text-sky-200">
                검토
              </span>
              <span className="rounded-2xl bg-[#ecfdf5] px-3 py-2 text-sm font-semibold text-[#047857] dark:bg-emerald-500/15 dark:text-emerald-200">
                게시
              </span>
              <span className="rounded-2xl bg-[#f5f3ff] px-3 py-2 text-sm font-semibold text-[#6d28d9] dark:bg-violet-500/15 dark:text-violet-200">
                피드백
              </span>
            </div>
          </div>

          <div className="mt-5">
            <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500 dark:text-zinc-400">보조 도구</p>
            <div className="mt-3 grid gap-2">
              {OPERATOR_LINKS.map((item) => {
                const active = isActivePath(pathname, item.href);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`flex items-start gap-3 rounded-[22px] border px-4 py-3 transition ${
                      active
                        ? "border-slate-300 bg-slate-100 dark:border-white/20 dark:bg-slate-800/70"
                        : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-slate-900/60 dark:hover:bg-slate-800/70"
                    }`}
                  >
                    <div className={`rounded-[16px] bg-gradient-to-br p-2 text-white ${item.accent}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-900 dark:text-zinc-100">{item.label}</p>
                      <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-zinc-400">{item.description}</p>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        </aside>

        <main className={mainCardClass}>
          {children}
        </main>
      </div>
    </div>
  );
}

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
  Radar,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

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
    description: "플랫폼 현황과 운영 루프를 한 화면에서 정리합니다.",
    icon: PanelsTopLeft,
    accent: "from-[#f97316] via-[#ea580c] to-[#c2410c]",
  },
  {
    href: "/planner",
    label: "게시 플래너 운영",
    description: "타입과 채널 기준으로 예약, 배분, 발행 흐름을 관리합니다.",
    icon: Compass,
    accent: "from-[#0ea5e9] via-[#0284c7] to-[#0369a1]",
  },
  {
    href: "/content-ops",
    label: "콘텐츠 운영",
    description: "블로그, 유튜브, 인스타그램 작업 흐름을 분리해 봅니다.",
    icon: Sparkles,
    accent: "from-[#10b981] via-[#059669] to-[#047857]",
  },
  {
    href: "/analytics",
    label: "분석",
    description: "채널 성과와 개선 신호를 확인합니다.",
    icon: LineChart,
    accent: "from-[#2563eb] via-[#1d4ed8] to-[#1e3a8a]",
  },
  {
    href: "/google",
    label: "SEO / 색인",
    description: "연결된 블로그별 색인, 검색 분석 상태를 관리합니다.",
    icon: Radar,
    accent: "from-[#f59e0b] via-[#d97706] to-[#b45309]",
  },
  {
    href: "/settings",
    label: "연동 설정",
    description: "OAuth, API 키, 플랫폼 연결만 관리합니다.",
    icon: Link2,
    accent: "from-[#7c3aed] via-[#6d28d9] to-[#5b21b6]",
  },
  {
    href: "/admin",
    label: "관리자 설정",
    description: "운영 기본값, 자동화, 예정 기능을 관리합니다.",
    icon: ShieldCheck,
    accent: "from-[#475569] via-[#334155] to-[#0f172a]",
  },
  {
    href: "/ops-health",
    label: "Ops Monitor",
    description: "실시간 동기화, 수동 동기화, 장애 징후를 확인합니다.",
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
    label: "글 보관함",
    description: "생성된 글과 발행 결과를 조회합니다.",
    icon: Orbit,
    accent: "from-[#14b8a6] via-[#0f766e] to-[#134e4a]",
  },
  {
    href: "/content-overview",
    label: "콘텐츠 현황",
    description: "전체 점수, 유사도, 카테고리 상태를 확인합니다.",
    icon: Bot,
    accent: "from-[#a855f7] via-[#9333ea] to-[#7e22ce]",
  },
  {
    href: "/guide",
    label: "가이드",
    description: "운영과 연동 흐름 설명을 확인합니다.",
    icon: ArrowUpRight,
    accent: "from-[#94a3b8] via-[#64748b] to-[#475569]",
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

function findCurrentRoom(pathname: string) {
  return [...PRIMARY_ROOMS, ...OPERATOR_LINKS].find((item) => isActivePath(pathname, item.href)) ?? PRIMARY_ROOMS[0];
}

function StatusChip({ label, value, tone }: { label: string; value: string; tone: "amber" | "sky" | "emerald" }) {
  const toneClass = {
    amber: "border-amber-200 bg-amber-50 text-amber-800",
    sky: "border-sky-200 bg-sky-50 text-sky-800",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
  }[tone];

  return (
    <div className={`rounded-2xl border px-3 py-2 ${toneClass}`}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em]">{label}</p>
      <p className="mt-1 text-sm font-semibold">{value}</p>
    </div>
  );
}

export function DashboardShell({ children, nav }: { children: React.ReactNode; nav?: NavItem[] }) {
  const pathname = usePathname();
  const currentRoom = findCurrentRoom(pathname);
  const navSet = new Set((nav ?? []).map((item) => item.href));
  const primaryRooms = PRIMARY_ROOMS.filter((item) => navSet.size === 0 || navSet.has(item.href));

  return (
    <div className="dashboard-shell min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(251,146,60,0.14),_transparent_28%),radial-gradient(circle_at_top_right,_rgba(14,165,233,0.12),_transparent_24%),linear-gradient(180deg,#f8fafc_0%,#eef2ff_100%)] px-4 py-4 text-slate-950 sm:px-5 lg:px-6">
      <div className="mx-auto grid min-h-[calc(100vh-2rem)] w-full gap-4 2xl:grid-cols-[300px_minmax(0,1fr)_320px] xl:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="rounded-[30px] border border-slate-200 bg-white/95 p-4 shadow-[0_20px_50px_rgba(15,23,42,0.08)] backdrop-blur sm:p-5">
          <div className="rounded-[26px] bg-[linear-gradient(135deg,#0f172a_0%,#1e293b_40%,#334155_100%)] p-5 text-white">
            <p className="text-[11px] font-semibold uppercase tracking-[0.32em] text-white/70">동그리 자동 블로그전트</p>
            <h1 className="mt-3 text-[28px] font-semibold leading-none">운영 작업공간</h1>
            <p className="mt-3 text-sm leading-6 text-white/82">
              대시보드, 관리자 설정, 연동 설정, 운영 모니터를 분리해 관리합니다.
            </p>
          </div>

          <div className="mt-5">
            <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">운영 메뉴</p>
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
                        ? "border-slate-950 bg-slate-950 text-white shadow-sm"
                        : "border-slate-200 bg-white text-slate-900 hover:border-slate-300 hover:bg-slate-50"
                    }`}
                  >
                    <div className={`rounded-[18px] bg-gradient-to-br p-2.5 text-white ${item.accent}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <p className={`text-sm font-semibold ${active ? "text-white" : "text-slate-900"}`}>{item.label}</p>
                      <p className={`mt-1 text-xs leading-5 ${active ? "text-slate-200" : "text-slate-600"}`}>{item.description}</p>
                    </div>
                  </Link>
                );
              })}
            </nav>
          </div>

          <div className="mt-5 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">운영 루프</p>
                <p className="mt-2 text-sm font-semibold text-slate-950">초안 {"->"} 검토 {"->"} 게시 {"->"} 피드백</p>
              </div>
              <Bot className="h-5 w-5 text-slate-500" />
            </div>
            <div className="mt-4 grid gap-2">
              <span className="rounded-2xl bg-[#fff7ed] px-3 py-2 text-sm font-semibold text-[#9a3412]">초안</span>
              <span className="rounded-2xl bg-[#eff6ff] px-3 py-2 text-sm font-semibold text-[#1d4ed8]">검토</span>
              <span className="rounded-2xl bg-[#ecfdf5] px-3 py-2 text-sm font-semibold text-[#047857]">게시</span>
              <span className="rounded-2xl bg-[#f5f3ff] px-3 py-2 text-sm font-semibold text-[#6d28d9]">피드백</span>
            </div>
          </div>

          <div className="mt-5">
            <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">보조 도구</p>
            <div className="mt-3 grid gap-2">
              {OPERATOR_LINKS.map((item) => {
                const active = isActivePath(pathname, item.href);
                const Icon = item.icon;
                return (
                  <Link key={item.href} href={item.href} className={`flex items-start gap-3 rounded-[22px] border px-4 py-3 transition ${active ? "border-slate-300 bg-slate-100" : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"}`}>
                    <div className={`rounded-[16px] bg-gradient-to-br p-2 text-white ${item.accent}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-900">{item.label}</p>
                      <p className="mt-1 text-xs leading-5 text-slate-600">{item.description}</p>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        </aside>

        <main className="min-w-0 rounded-[30px] border border-slate-200 bg-white/95 p-4 shadow-[0_20px_50px_rgba(15,23,42,0.06)] backdrop-blur sm:p-5 lg:p-6">
          {children}
        </main>

        <aside className="hidden rounded-[30px] border border-slate-200 bg-white/95 p-5 shadow-[0_20px_50px_rgba(15,23,42,0.08)] backdrop-blur 2xl:block">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Current Room</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">{currentRoom.label}</h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">{currentRoom.description}</p>
          </div>

          <div className="mt-5 space-y-3">
            <StatusChip label="브랜드" value="동그리 자동 블로그전트" tone="sky" />
            <StatusChip label="셸" value="3-Zone Layout" tone="amber" />
            <StatusChip label="도킹" value="Operator Dock" tone="emerald" />
          </div>
        </aside>
      </div>
    </div>
  );
}

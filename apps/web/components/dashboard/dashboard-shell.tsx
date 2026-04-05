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
    label: "Mission Control",
    description: "플랫폼 현황과 운영 루프를 한 화면에서 정리합니다.",
    icon: PanelsTopLeft,
    accent: "from-[#fb923c] via-[#f97316] to-[#ef4444]",
  },
  {
    href: "/planner",
    label: "Publishing",
    description: "월간 슬롯, 예약 발행, 우선순위를 조정합니다.",
    icon: Compass,
    accent: "from-[#38bdf8] via-[#0ea5e9] to-[#2563eb]",
  },
  {
    href: "/content-ops",
    label: "Content Lab",
    description: "글, 이미지, 검토 대기 항목을 집중 편집합니다.",
    icon: Sparkles,
    accent: "from-[#34d399] via-[#10b981] to-[#059669]",
  },
  {
    href: "/analytics",
    label: "Analytics",
    description: "성과와 품질 점수를 비교하고 후속 액션을 결정합니다.",
    icon: LineChart,
    accent: "from-[#a78bfa] via-[#8b5cf6] to-[#6366f1]",
  },
  {
    href: "/google",
    label: "SEO / Indexing",
    description: "검색 성과, 색인 상태, Google 연동을 점검합니다.",
    icon: Radar,
    accent: "from-[#facc15] via-[#f59e0b] to-[#d97706]",
  },
  {
    href: "/settings",
    label: "Integrations",
    description: "모델, 채널, 연결 상태를 관리합니다.",
    icon: Link2,
    accent: "from-[#60a5fa] via-[#3b82f6] to-[#1d4ed8]",
  },
  {
    href: "/ops-health",
    label: "Admin",
    description: "런타임 상태와 운영 보조 도구를 확인합니다.",
    icon: ShieldCheck,
    accent: "from-[#94a3b8] via-[#64748b] to-[#334155]",
  },
];

const OPERATOR_LINKS: WorkspaceCard[] = [
  {
    href: "/jobs",
    label: "Task Tray",
    description: "실행 작업과 재시도 대상을 빠르게 엽니다.",
    icon: FileStack,
    accent: "from-[#e879f9] via-[#d946ef] to-[#a21caf]",
  },
  {
    href: "/articles",
    label: "Article Vault",
    description: "게시 결과와 원문 자산을 추적합니다.",
    icon: Orbit,
    accent: "from-[#14b8a6] via-[#0f766e] to-[#134e4a]",
  },
  {
    href: "/content-overview",
    label: "Review Deck",
    description: "콘텐츠 상태를 유형별로 확인합니다.",
    icon: Bot,
    accent: "from-[#f472b6] via-[#ec4899] to-[#be185d]",
  },
  {
    href: "/guide",
    label: "Guide",
    description: "운영 모드와 사용 가이드를 확인합니다.",
    icon: ArrowUpRight,
    accent: "from-[#cbd5e1] via-[#94a3b8] to-[#64748b]",
  },
  {
    href: "/training",
    label: "Training",
    description: "학습 및 자동화 상태를 제어합니다.",
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

export function DashboardShell({ children, nav }: { children: React.ReactNode; nav?: NavItem[] }) {
  const pathname = usePathname();
  const currentRoom = findCurrentRoom(pathname);
  const navSet = new Set((nav ?? []).map((item) => item.href));
  const primaryRooms = PRIMARY_ROOMS.filter((item) => navSet.size === 0 || navSet.has(item.href) || item.href === "/ops-health");

  return (
    <div className="dashboard-shell min-h-screen px-4 py-4 text-slate-950 sm:px-5 lg:px-6">
      <div className="mx-auto grid min-h-[calc(100vh-2rem)] w-full gap-4 2xl:grid-cols-[280px_minmax(0,1fr)_320px] xl:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="office-panel office-panel-strong flex min-h-0 flex-col overflow-hidden rounded-[30px] p-4 sm:p-5">
          <div className="office-plaque rounded-[26px] p-5 text-white">
            <p className="text-[11px] font-semibold uppercase tracking-[0.36em] text-white/70">Bloggent OS</p>
            <h1 className="mt-3 font-display text-[30px] font-semibold leading-none">Workspace Shell</h1>
            <p className="mt-3 text-sm leading-6 text-white/82">
              Blogger, YouTube, Instagram 운영 흐름을 하나의 콘솔로 묶는 Mission Control 레이어입니다.
            </p>
          </div>

          <div className="mt-4">
            <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">Office Nav</p>
            <nav className="mt-3 space-y-2">
              {primaryRooms.map((item) => {
                const active = isActivePath(pathname, item.href);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`office-nav-card group flex items-start gap-3 rounded-[22px] px-4 py-3 ${
                      active ? "office-nav-card-active" : ""
                    }`}
                  >
                    <div className={`rounded-[18px] bg-gradient-to-br p-2.5 text-white shadow-lg ${item.accent}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-900">{item.label}</p>
                      <p className="mt-1 text-xs leading-5 text-slate-500">{item.description}</p>
                    </div>
                  </Link>
                );
              })}
            </nav>
          </div>

          <div className="mt-4 rounded-[24px] border border-white/60 bg-white/75 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Control Loop</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">Draft -&gt; Review -&gt; Publish -&gt; Feedback</p>
              </div>
              <Bot className="h-5 w-5 text-slate-400" />
            </div>
            <div className="mt-4 grid grid-cols-4 gap-2 text-center text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
              <span className="rounded-2xl bg-[#fff1dd] px-2 py-2 text-[#9a3412]">Draft</span>
              <span className="rounded-2xl bg-[#ecfeff] px-2 py-2 text-[#155e75]">Review</span>
              <span className="rounded-2xl bg-[#ecfccb] px-2 py-2 text-[#3f6212]">Publish</span>
              <span className="rounded-2xl bg-[#ede9fe] px-2 py-2 text-[#5b21b6]">Feedback</span>
            </div>
          </div>
        </aside>

        <main className="office-panel flex min-h-0 flex-col overflow-hidden rounded-[30px]">
          <header className="border-b border-slate-200/70 px-5 py-5 sm:px-7">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.36em] text-slate-400">Current Room</p>
                <h2 className="mt-2 font-display text-[34px] font-semibold leading-none text-slate-950">{currentRoom.label}</h2>
                <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">{currentRoom.description}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <StatusChip label="Workspace" value="3-zone shell" tone="amber" />
                <StatusChip label="Routes" value="compatible" tone="sky" />
                <StatusChip label="Operator Dock" value="live" tone="emerald" />
              </div>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-x-auto overflow-y-auto px-4 py-4 sm:px-5 sm:py-5 lg:px-7 lg:py-6">
            {children}
          </div>
        </main>

        <aside className="office-panel office-panel-dark hidden min-h-0 flex-col rounded-[30px] p-4 text-white sm:p-5 2xl:flex">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.34em] text-slate-300">Operator Dock</p>
            <h3 className="mt-3 font-display text-[28px] font-semibold leading-none">Desk</h3>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              빠른 이동, 운영 규칙, 보조 화면을 한쪽 도크에 고정했습니다.
            </p>
          </div>

          <div className="mt-5 grid gap-3">
            {OPERATOR_LINKS.map((item) => {
              const Icon = item.icon;
              const active = isActivePath(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-[22px] border px-4 py-4 transition ${
                    active
                      ? "border-white/30 bg-white/[0.14]"
                      : "border-white/10 bg-white/[0.04] hover:border-white/20 hover:bg-white/[0.08]"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className={`rounded-[18px] bg-gradient-to-br p-2.5 text-white ${item.accent}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-white">{item.label}</p>
                      <p className="mt-1 text-xs leading-5 text-slate-300">{item.description}</p>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>

          <div className="mt-5 rounded-[24px] border border-white/10 bg-white/[0.05] p-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Dock Rules</p>
            <div className="mt-3 space-y-3 text-sm leading-6 text-slate-200">
              <p>1. 게시 전에 대기열과 검토 항목을 먼저 확인합니다.</p>
              <p>2. SEO / Indexing 화면에서 Google 연결 상태를 함께 확인합니다.</p>
              <p>3. 실패 작업은 `Task Tray`에서 재시도하거나 설정을 수정합니다.</p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function StatusChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "amber" | "sky" | "emerald";
}) {
  const toneClasses = {
    amber: "border-[#fed7aa] bg-[#fff7ed] text-[#9a3412]",
    sky: "border-[#bae6fd] bg-[#f0f9ff] text-[#0c4a6e]",
    emerald: "border-[#bbf7d0] bg-[#ecfdf5] text-[#166534]",
  }[tone];

  return (
    <div className={`rounded-full border px-3 py-2 text-xs font-semibold ${toneClasses}`}>
      <span className="mr-2 uppercase tracking-[0.2em] opacity-70">{label}</span>
      <span>{value}</span>
    </div>
  );
}

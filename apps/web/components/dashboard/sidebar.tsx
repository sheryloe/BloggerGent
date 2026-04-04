"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, CalendarDays, FileChartColumn, FolderKanban, LayoutGrid, Settings } from "lucide-react";

type NavItem = {
  href: string;
  label: string;
  description: string;
  icon: typeof LayoutGrid;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "대시보드", description: "운영 개요", icon: LayoutGrid },
  { href: "/planner", label: "플래너", description: "월간 일정 관리", icon: CalendarDays },
  { href: "/analytics", label: "분석", description: "성과 리포트", icon: FileChartColumn },
  { href: "/content-ops", label: "콘텐츠", description: "보관함과 검토", icon: FolderKanban },
  { href: "/settings", label: "설정", description: "모델, 채널, 자동화", icon: Settings },
  { href: "/ops-health", label: "상태", description: "서비스 상태", icon: Activity },
];

export function DashboardSidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-full rounded-[32px] border border-slate-200 bg-white p-5 shadow-[0_24px_80px_rgba(15,23,42,0.06)]">
      <div className="rounded-[28px] bg-gradient-to-br from-indigo-600 to-sky-500 p-5 text-white">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-indigo-100">Bloggent</p>
        <h2 className="mt-3 text-2xl font-semibold tracking-tight">운영 콘솔</h2>
        <p className="mt-2 text-sm leading-6 text-indigo-50">
          월간 계획을 세우고, 분석 리포트로 결과를 확인한 뒤 다음 달 비중까지 조정하는 운영 화면입니다.
        </p>
      </div>

      <nav className="mt-6 space-y-2">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-start gap-3 rounded-2xl border px-4 py-4 transition ${
                active
                  ? "border-indigo-200 bg-indigo-50"
                  : "border-transparent bg-transparent hover:border-slate-200 hover:bg-slate-50"
              }`}
            >
              <div className={`rounded-2xl p-2.5 ${active ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-500"}`}>
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

      <div className="mt-6 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">자동화 상태</p>
        <p className="mt-2 text-sm font-semibold text-slate-900">기본값 OFF</p>
        <p className="mt-1 text-xs leading-5 text-slate-500">현재는 계획과 분석 구조를 먼저 안정화하는 단계입니다.</p>
      </div>
    </aside>
  );
}

export const Sidebar = DashboardSidebar;

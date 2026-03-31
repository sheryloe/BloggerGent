import nextDynamic from "next/dynamic";
import Link from "next/link";

import { Sidebar } from "@/components/dashboard/sidebar";

const OpenAIFreeUsageWidget = nextDynamic(
  () => import("@/components/dashboard/openai-free-usage-widget").then((module) => module.OpenAIFreeUsageWidget),
  { ssr: false },
);

export const dynamic = "force-dynamic";

const nav = [
  { href: "/", label: "대시보드" },
  { href: "/planner", label: "플래너" },
  { href: "/analytics", label: "분석" },
  { href: "/content-ops", label: "콘텐츠" },
  { href: "/settings", label: "설정" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#eef2ff]">
      <OpenAIFreeUsageWidget />
      <div className="mx-auto max-w-[1680px] px-4 py-4 lg:flex lg:gap-6 lg:px-6 lg:py-6 xl:px-8">
        <div className="hidden w-[300px] shrink-0 lg:block">
          <Sidebar />
        </div>
        <main className="min-w-0 flex-1">
          <header className="mb-4 hidden rounded-[28px] border border-slate-200 bg-white/90 px-5 py-4 shadow-sm backdrop-blur lg:block">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Bloggent</h1>
                <p className="text-sm text-slate-500">플래너와 분석을 중심으로 운영하는 블로그 관리 대시보드</p>
              </div>
              <nav className="flex flex-wrap gap-2">
                {nav.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    prefetch={false}
                    className="rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700"
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>
          <header className="sticky top-0 z-30 mb-4 rounded-[28px] border border-slate-200 bg-white/90 px-4 py-4 shadow-sm backdrop-blur xl:hidden">
            <div className="space-y-4">
              <div>
                <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Bloggent</h1>
                <p className="text-sm text-slate-500">블로그 운영 대시보드</p>
              </div>
              <nav className="flex flex-wrap gap-2">
                {nav.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    prefetch={false}
                    className="rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700"
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>
          <div className="space-y-6">{children}</div>
        </main>
      </div>
    </div>
  );
}

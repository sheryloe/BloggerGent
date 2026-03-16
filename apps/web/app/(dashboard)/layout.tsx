import Link from "next/link";

import { Sidebar } from "@/components/dashboard/sidebar";
import { Badge } from "@/components/ui/badge";

const nav = [
  { href: "/", label: "대시보드" },
  { href: "/guide", label: "가이드" },
  { href: "/google", label: "구글 데이터" },
  { href: "/jobs", label: "작업 현황" },
  { href: "/articles", label: "글 보관함" },
  { href: "/settings", label: "설정" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="dashboard-shell min-h-screen lg:flex">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/75 px-4 py-4 backdrop-blur-2xl dark:border-white/10 dark:bg-zinc-950/75 lg:hidden">
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h1 className="font-display text-2xl font-semibold tracking-tight text-slate-950 dark:text-zinc-50">
                  Bloggent
                </h1>
                <p className="text-sm text-slate-500 dark:text-zinc-400">글 작성과 발행 관리를 한 화면에서</p>
              </div>
              <Badge className="border-emerald-200/80 bg-emerald-500/10 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/15 dark:text-emerald-200">
                UI 개선
              </Badge>
            </div>
            <nav className="flex flex-wrap gap-2">
              {nav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-full border border-slate-200/80 bg-white/70 px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-950 dark:border-white/10 dark:bg-white/5 dark:text-zinc-300 dark:hover:bg-white/10 dark:hover:text-zinc-100"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <div className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 lg:px-8 xl:px-10 xl:py-8">{children}</div>
      </main>
    </div>
  );
}

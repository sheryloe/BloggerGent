import Link from "next/link";

import { Sidebar } from "@/components/dashboard/sidebar";

const nav = [
  { href: "/", label: "대시보드" },
  { href: "/guide", label: "사용 가이드" },
  { href: "/google", label: "Google 데이터" },
  { href: "/jobs", label: "작업 현황" },
  { href: "/articles", label: "생성 글" },
  { href: "/settings", label: "설정" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen lg:flex">
      <Sidebar />
      <main className="flex-1">
        <header className="border-b border-ink/10 px-5 py-5 lg:hidden">
          <div className="space-y-4">
            <div>
              <h1 className="font-display text-2xl font-semibold">Bloggent</h1>
              <p className="text-sm text-slate-600">
                Blogger 운영에 필요한 AI 생성, 이미지 공개, Google OAuth, 성과 확인 기능을 한곳에
                모아둔 대시보드입니다.
              </p>
            </div>
            <nav className="flex flex-wrap gap-2">
              {nav.map((item) => (
                <Link key={item.href} href={item.href} className="rounded-full border border-ink/10 px-4 py-2 text-sm">
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-10 lg:py-10">{children}</div>
      </main>
    </div>
  );
}

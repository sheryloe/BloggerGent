import Link from "next/link";
import { BarChart3, BookOpenText, LayoutDashboard, Newspaper, Settings2, Workflow } from "lucide-react";

import { Badge } from "@/components/ui/badge";

const items = [
  { href: "/", label: "대시보드", icon: LayoutDashboard },
  { href: "/guide", label: "사용 가이드", icon: BookOpenText },
  { href: "/google", label: "Google 데이터", icon: BarChart3 },
  { href: "/jobs", label: "작업 현황", icon: Workflow },
  { href: "/articles", label: "생성 글", icon: Newspaper },
  { href: "/settings", label: "설정", icon: Settings2 },
];

export function Sidebar() {
  return (
    <aside className="grid-bg hidden min-h-screen w-72 border-r border-ink/10 px-6 py-8 lg:block">
      <div className="sticky top-8 space-y-8">
        <div className="space-y-4">
          <Badge className="w-fit bg-white/90 text-spruce">Google Blogger 반자동 운영</Badge>
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight text-ink">Bloggent</h1>
            <p className="mt-3 max-w-xs text-sm leading-6 text-slate-600">
              블로그마다 다른 프롬프트와 워크플로를 배정하고, 주제 발굴부터 글 생성, 이미지, Blogger 게시와
              성과 확인까지 한 화면에서 관리합니다.
            </p>
          </div>
        </div>

        <nav className="space-y-2">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className="flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium text-ink transition hover:bg-white/70"
              >
                <Icon className="h-4 w-4 text-ember" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}

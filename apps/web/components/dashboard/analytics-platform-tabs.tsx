"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const PLATFORM_TABS = [
  { href: "/analytics/blogger", label: "Blogger" },
  { href: "/analytics/cloudflare", label: "Cloudflare" },
  { href: "/analytics/youtube", label: "유튜브" },
  { href: "/analytics/instagram", label: "인스타그램" },
] as const;

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AnalyticsPlatformTabs() {
  const pathname = usePathname();

  return (
    <div className="rounded-[24px] border border-slate-200 bg-white p-2 shadow-sm">
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {PLATFORM_TABS.map((tab) => {
          const active = isActive(pathname, tab.href);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`rounded-2xl px-4 py-3 text-center text-sm font-semibold transition ${
                active ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

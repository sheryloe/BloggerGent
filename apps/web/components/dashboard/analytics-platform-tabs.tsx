"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const PLATFORM_TABS = [
  { href: "/analytics/blogger", label: "Blogger" },
  { href: "/analytics/youtube", label: "YouTube" },
  { href: "/analytics/instagram", label: "Instagram" },
] as const;

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AnalyticsPlatformTabs() {
  const pathname = usePathname();

  return (
    <div className="rounded-[24px] border border-slate-200 bg-white p-2 shadow-sm">
      <div className="grid gap-2 sm:grid-cols-3">
        {PLATFORM_TABS.map((tab) => {
          const active = isActive(pathname, tab.href);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`rounded-2xl px-4 py-3 text-center text-sm font-semibold transition ${
                active ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
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

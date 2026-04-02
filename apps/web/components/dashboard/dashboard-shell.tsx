"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode } from "react";

type NavItem = {
  href: string;
  label: string;
};

type DashboardShellProps = {
  children: ReactNode;
  nav: NavItem[];
};

export function DashboardShell({ children, nav }: DashboardShellProps) {
  const pathname = usePathname();

  return (
    <div className="px-3 py-3 lg:px-5 lg:py-5 xl:px-6">
      <div className="rounded-[28px] border border-slate-200 bg-white/90 shadow-sm">
        <header className="border-b border-slate-200 px-4 py-4 lg:px-6">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Bloggent Workspace</p>
              <h1 className="mt-1 text-[28px] font-semibold tracking-tight text-slate-950">운영 작업 화면</h1>
            </div>
            <nav className="flex flex-wrap items-center gap-2">
              {nav.map((item) => {
                const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={[
                      "rounded-full px-4 py-2 text-sm font-medium transition",
                      active
                        ? "bg-slate-950 text-white shadow-sm"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900",
                    ].join(" ")}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
        </header>
        <main className="min-w-0 px-3 py-4 lg:px-5 lg:py-5 xl:px-6">{children}</main>
      </div>
    </div>
  );
}

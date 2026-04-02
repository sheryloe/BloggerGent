import nextDynamic from "next/dynamic";

import { DashboardShell } from "@/components/dashboard/dashboard-shell";

export const dynamic = process.env.GITHUB_ACTIONS === "true" ? "auto" : "force-dynamic";

const OpenAIFreeUsageWidget = nextDynamic(
  () => import("@/components/dashboard/openai-free-usage-widget").then((module) => module.OpenAIFreeUsageWidget),
  { ssr: false },
);

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
      <DashboardShell nav={nav}>{children}</DashboardShell>
    </div>
  );
}

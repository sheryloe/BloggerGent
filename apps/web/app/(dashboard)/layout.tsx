import nextDynamic from "next/dynamic";

import { DashboardShell } from "@/components/dashboard/dashboard-shell";

export const dynamic = process.env.GITHUB_ACTIONS === "true" ? "auto" : "force-dynamic";

const OpenAIFreeUsageWidget = nextDynamic(
  () => import("@/components/dashboard/openai-free-usage-widget").then((module) => module.OpenAIFreeUsageWidget),
  { ssr: false },
);

const nav = [
  { href: "/dashboard", label: "운영 홈" },
  { href: "/planner", label: "생성 운영" },
  { href: "/analytics", label: "게시글 분석" },
  { href: "/content-ops", label: "콘텐츠 검수" },
  { href: "/qms", label: "QMS / ISO 9001" },
  { href: "/settings", label: "프롬프트/설정" },
  { href: "/ops-health", label: "운영 상태" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-app-base">
      <OpenAIFreeUsageWidget />
      <DashboardShell nav={nav}>{children}</DashboardShell>
    </div>
  );
}

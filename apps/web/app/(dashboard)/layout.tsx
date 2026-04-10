import nextDynamic from "next/dynamic";

import { DashboardShell } from "@/components/dashboard/dashboard-shell";

export const dynamic = process.env.GITHUB_ACTIONS === "true" ? "auto" : "force-dynamic";

const OpenAIFreeUsageWidget = nextDynamic(
  () => import("@/components/dashboard/openai-free-usage-widget").then((module) => module.OpenAIFreeUsageWidget),
  { ssr: false },
);

const nav = [
  { href: "/dashboard", label: "미션 컨트롤" },
  { href: "/planner", label: "게시 플래너 운영" },
  { href: "/content-ops", label: "콘텐츠 운영" },
  { href: "/analytics", label: "분석" },
  { href: "/settings", label: "연동 설정" },
  { href: "/admin", label: "관리자 설정" },
  { href: "/ops-health", label: "운영 모니터" },
  { href: "/help", label: "운영형 도움말" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-app-base">
      <OpenAIFreeUsageWidget />
      <DashboardShell nav={nav}>{children}</DashboardShell>
    </div>
  );
}

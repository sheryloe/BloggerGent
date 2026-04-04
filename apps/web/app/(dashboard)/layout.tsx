import nextDynamic from "next/dynamic";

import { DashboardShell } from "@/components/dashboard/dashboard-shell";

export const dynamic = process.env.GITHUB_ACTIONS === "true" ? "auto" : "force-dynamic";

const OpenAIFreeUsageWidget = nextDynamic(
  () => import("@/components/dashboard/openai-free-usage-widget").then((module) => module.OpenAIFreeUsageWidget),
  { ssr: false },
);

const nav = [
  { href: "/dashboard", label: "Mission Control" },
  { href: "/planner", label: "Publishing" },
  { href: "/content-ops", label: "Content Lab" },
  { href: "/analytics", label: "Analytics" },
  { href: "/google", label: "SEO / Indexing" },
  { href: "/settings", label: "Integrations" },
  { href: "/ops-health", label: "Admin" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f3efe6]">
      <OpenAIFreeUsageWidget />
      <DashboardShell nav={nav}>{children}</DashboardShell>
    </div>
  );
}

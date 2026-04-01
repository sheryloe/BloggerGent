import { Suspense } from "react";

import { AnalyticsDashboard } from "@/components/dashboard/analytics-dashboard";
import { fetchBlogs, fetchChannels } from "@/lib/api";

export default async function AnalyticsPage() {
  const [blogs, channels] = await Promise.all([fetchBlogs(), fetchChannels()]);
  return (
    <Suspense fallback={<div className="rounded-[28px] border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">분석 화면을 불러오는 중입니다.</div>}>
      <AnalyticsDashboard blogs={blogs} channels={channels} />
    </Suspense>
  );
}

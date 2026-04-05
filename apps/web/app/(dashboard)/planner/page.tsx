import { Suspense } from "react";

import { PlannerManager } from "@/components/dashboard/planner-manager";
import { fetchChannels } from "@/lib/api";

export default async function PlannerPage() {
  const channels = await fetchChannels();
  return (
    <Suspense
      fallback={
        <div className="rounded-[28px] border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
          플래너를 불러오는 중입니다.
        </div>
      }
    >
      <PlannerManager channels={channels} />
    </Suspense>
  );
}

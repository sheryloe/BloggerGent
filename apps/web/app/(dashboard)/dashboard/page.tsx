import { MissionControl } from "@/components/dashboard/mission-control";
import { fetchChannels, getMissionControl } from "@/lib/api";
import type { MissionControlRead } from "@/lib/types";

export const revalidate = 5;

export default async function DashboardHomePage() {
  const missionValue = await getMissionControl().catch(() => null);
  const channels = missionValue?.channels?.length ? missionValue.channels : await fetchChannels().catch(() => []);

  const mission: MissionControlRead =
    missionValue
      ? missionValue
      : {
          workspaceLabel: "Donggr AutoBloggent",
          channels,
          workers: [],
          runs: [],
          recentContent: [],
          runtimeHealth: {
            totalWorkers: 0,
            liveWorkers: 0,
            queuedRuns: 0,
            failedRuns: 0,
            runtimeStatus: "standby",
            runtimes: [],
          },
          alerts: [],
        };

  return <MissionControl mission={mission} />;
}

import { MissionControl } from "@/components/dashboard/mission-control";
import { fetchChannels, getMissionControl } from "@/lib/api";
import type { MissionControlRead } from "@/lib/types";

export default async function DashboardHomePage() {
  const [missionResult, channelsResult] = await Promise.allSettled([getMissionControl(), fetchChannels()]);
  const channels = channelsResult.status === "fulfilled" ? channelsResult.value : [];

  const mission: MissionControlRead =
    missionResult.status === "fulfilled"
      ? missionResult.value
      : {
          workspaceLabel: "Bloggent Mission Control",
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

  return <MissionControl mission={{ ...mission, channels: mission.channels.length > 0 ? mission.channels : channels }} />;
}

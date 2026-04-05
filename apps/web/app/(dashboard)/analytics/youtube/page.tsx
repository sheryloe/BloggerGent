import { MediaAnalyticsWorkspace } from "@/components/dashboard/media-analytics-workspace";
import { fetchChannels } from "@/lib/api";

export default async function YouTubeAnalyticsPage() {
  const channels = await fetchChannels();
  return <MediaAnalyticsWorkspace provider="youtube" channels={channels} />;
}

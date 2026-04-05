import { MediaAnalyticsWorkspace } from "@/components/dashboard/media-analytics-workspace";
import { fetchChannels } from "@/lib/api";

export default async function InstagramAnalyticsPage() {
  const channels = await fetchChannels();
  return <MediaAnalyticsWorkspace provider="instagram" channels={channels} />;
}

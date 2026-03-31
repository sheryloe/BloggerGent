import { AnalyticsDashboard } from "@/components/dashboard/analytics-dashboard";
import { fetchBlogs, fetchChannels } from "@/lib/api";

export default async function AnalyticsPage() {
  const [blogs, channels] = await Promise.all([fetchBlogs(), fetchChannels()]);
  return <AnalyticsDashboard blogs={blogs} channels={channels} />;
}

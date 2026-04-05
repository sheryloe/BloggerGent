import { BloggerAnalyticsWorkspace } from "@/components/dashboard/blogger-analytics-workspace";
import { fetchBlogs, fetchChannels } from "@/lib/api";

export default async function BloggerAnalyticsPage() {
  const [blogs, channels] = await Promise.all([fetchBlogs(true), fetchChannels()]);
  return <BloggerAnalyticsWorkspace blogs={blogs} channels={channels} />;
}

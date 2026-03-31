import { PlannerManager } from "@/components/dashboard/planner-manager";
import { fetchBlogs } from "@/lib/api";

export default async function PlannerPage() {
  const blogs = await fetchBlogs();
  return <PlannerManager blogs={blogs} />;
}

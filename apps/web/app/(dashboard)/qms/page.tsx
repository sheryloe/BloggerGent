import { QmsWorkspace } from "@/components/dashboard/qms-workspace";
import { getQmsDashboard } from "@/lib/api";

export default async function QmsPage() {
  const dashboard = await getQmsDashboard().catch(() => null);
  return <QmsWorkspace initialDashboard={dashboard} />;
}

import { SettingsConsole } from "@/components/dashboard/settings-console";
import { fetchBloggerConfig, fetchSettings } from "@/lib/api";

export default async function SettingsPage() {
  const [settings, config] = await Promise.all([fetchSettings(), fetchBloggerConfig()]);

  return <SettingsConsole settings={settings} config={config} mode="integrations" />;
}

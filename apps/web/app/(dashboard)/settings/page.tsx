import { SettingsConsole } from "@/components/dashboard/settings-console";
import { SettingsTelegramHelpCard } from "@/components/dashboard/settings-telegram-help-card";
import { fetchBloggerConfig, fetchSettings } from "@/lib/api";

export default async function SettingsPage() {
  const [settings, config] = await Promise.all([fetchSettings(), fetchBloggerConfig()]);

  return (
    <div className="space-y-4">
      <SettingsTelegramHelpCard />
      <SettingsConsole settings={settings} config={config} mode="integrations" />
    </div>
  );
}

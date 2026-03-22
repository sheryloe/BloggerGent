import { TrainingControlPanel } from "@/components/dashboard/training-control-panel";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getSettings, getTrainingStatus } from "@/lib/api";

function settingValue(settings: Array<{ key: string; value: string }>, key: string, fallback = "-") {
  const found = settings.find((item) => item.key === key);
  if (!found) return fallback;
  const value = (found.value || "").trim();
  return value || fallback;
}

export default async function TrainingPage() {
  const [status, settings] = await Promise.all([getTrainingStatus(), getSettings()]);
  const providerMode = settingValue(settings, "provider_mode", "mock");
  const topicProvider = settingValue(settings, "topic_discovery_provider", "openai");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl font-semibold text-ink">Training Progress</h1>
        <p className="mt-2 text-sm leading-7 text-slate-600">
          Control training with manual start/pause/resume and daily schedule. Sessions run for 4 hours by default,
          save checkpoints periodically, and resume from the latest checkpoint.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Readonly Global Summary</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Badge className="border border-ink/15 bg-white text-ink">Provider mode: {providerMode}</Badge>
          <Badge className="border border-ink/15 bg-white text-ink">Article model: {status.model_name || "-"}</Badge>
          <Badge className="border border-ink/15 bg-white text-ink">Topic provider: {topicProvider}</Badge>
          <Badge className="border border-ink/15 bg-white text-ink">Data: {status.data_scope}</Badge>
        </CardContent>
      </Card>

      <TrainingControlPanel initialStatus={status} providerMode={providerMode} />
    </div>
  );
}

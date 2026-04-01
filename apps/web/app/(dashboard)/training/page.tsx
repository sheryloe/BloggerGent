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
        <h1 className="font-display text-4xl font-semibold text-ink">학습 진행 현황</h1>
        <p className="mt-2 text-sm leading-7 text-slate-600">
          수동 시작/일시정지/재개와 일일 스케줄을 함께 관리합니다. 기본 4시간 세션으로 동작하며,
          체크포인트를 주기적으로 저장하고 최신 체크포인트에서 재개합니다.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>읽기 전용 요약</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Badge className="border border-ink/15 bg-white text-ink">Provider 모드: {providerMode}</Badge>
          <Badge className="border border-ink/15 bg-white text-ink">글 모델: {status.model_name || "-"}</Badge>
          <Badge className="border border-ink/15 bg-white text-ink">주제 Provider: {topicProvider}</Badge>
          <Badge className="border border-ink/15 bg-white text-ink">데이터 범위: {status.data_scope}</Badge>
        </CardContent>
      </Card>

      <TrainingControlPanel initialStatus={status} providerMode={providerMode} />
    </div>
  );
}

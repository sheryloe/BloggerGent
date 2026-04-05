import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getChannels, getWorkspaceContentItems } from "@/lib/api";

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function providerLabel(provider: "youtube" | "instagram") {
  return provider === "youtube" ? "유튜브" : "인스타그램";
}

export async function ContentOpsPlatformPanel({
  provider,
  selectedChannelId,
}: {
  provider: "youtube" | "instagram";
  selectedChannelId?: string;
}) {
  const channels = (await getChannels()).filter((item) => item.provider === provider);
  const selectedChannel = channels.find((item) => item.channelId === selectedChannelId) ?? channels[0] ?? null;
  const items = selectedChannel
    ? await getWorkspaceContentItems({ provider, channelId: selectedChannel.channelId, limit: 80 }).catch(() => [])
    : [];

  const queued = items.filter((item) => ["queued", "scheduled", "generating"].includes(item.lifecycleStatus)).length;
  const blocked = items.filter((item) => item.lifecycleStatus === "blocked_asset").length;
  const failed = items.filter((item) => item.lifecycleStatus === "failed").length;
  const published = items.filter((item) => item.lifecycleStatus === "published").length;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardDescription>{providerLabel(provider)} 콘텐츠 운영</CardDescription>
          <CardTitle>{providerLabel(provider)} 채널별 관리</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {!channels.length ? (
            <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              아직 연동된 {providerLabel(provider)} 채널이 없습니다.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {channels.map((channel) => {
                const active = channel.channelId === selectedChannel?.channelId;
                return (
                  <Link
                    key={channel.channelId}
                    href={`/content-ops?type=${provider}&channel=${encodeURIComponent(channel.channelId)}`}
                    className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                      active ? "bg-slate-900 text-white" : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    {channel.name}
                  </Link>
                );
              })}
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-4">
            <MetricCard label="선택 채널" value={selectedChannel?.name ?? "-"} />
            <MetricCard label="게시 대기" value={String(queued)} />
            <MetricCard label="자산 보강 필요" value={String(blocked)} />
            <MetricCard label="실패 항목" value={String(failed)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription>상태 목록</CardDescription>
          <CardTitle>최근 {providerLabel(provider)} 콘텐츠</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {!selectedChannel ? (
            <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              먼저 연동된 채널을 선택하세요.
            </p>
          ) : !items.length ? (
            <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              선택한 채널에 표시할 콘텐츠가 없습니다.
            </p>
          ) : (
            items.map((item) => (
              <div key={item.id} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-slate-900">{item.title || "(제목 없음)"}</p>
                  <Badge className="bg-transparent">{item.lifecycleStatus}</Badge>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  업데이트: {formatDateTime(item.updatedAt)} · 타입: {item.contentType} · 발행 상태: {item.latestPublication?.publishStatus ?? "-"}
                </p>
                {item.latestPublication?.remoteUrl ? (
                  <a href={item.latestPublication.remoteUrl} target="_blank" rel="noreferrer" className="mt-2 inline-flex text-sm text-sky-700 hover:underline">
                    게시 URL 열기
                  </a>
                ) : null}
              </div>
            ))
          )}
          <div className="flex flex-wrap gap-2">
            <Link href={`/analytics/${provider}`} className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700">
              {providerLabel(provider)} 분석으로 이동
            </Link>
            <Link href="/ops-health" className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700">
              Ops Monitor로 이동
            </Link>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription>운영 메모</CardDescription>
          <CardTitle>권장 확인 순서</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-slate-700">
          <p>1. `자산 보강 필요` 항목부터 먼저 줄입니다.</p>
          <p>2. `게시 대기` 상태를 우선순위 기준으로 확인합니다.</p>
          <p>3. `실패 항목`은 Ops Monitor에서 원인과 재시도 여부를 확인합니다.</p>
          <p>4. `발행 완료` 항목은 분석 화면에서 성과를 확인합니다. 현재 {published}건입니다.</p>
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] border border-slate-200 bg-slate-50 p-4">
      <p className="text-xs uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  Film,
  Globe2,
  Image as ImageIcon,
  Instagram,
  Layers3,
  Newspaper,
  RadioTower,
  SearchCheck,
  Sparkles,
  Video,
  Youtube,
} from "lucide-react";

import type { AgentRunRead, AgentWorkerRead, ManagedChannelRead, MissionControlRead } from "@/lib/types";

type MissionControlProps = {
  mission: MissionControlRead;
};

type RoomDefinition = {
  key: string;
  label: string;
  route: string;
  icon: typeof Globe2;
  tint: string;
  summary: string;
};

const ROOM_DEFINITIONS: RoomDefinition[] = [
  {
    key: "blogger",
    label: "Blogger Room",
    route: "/planner",
    icon: Newspaper,
    tint: "from-[#fb923c] via-[#f97316] to-[#ef4444]",
    summary: "장문 아티클 생성, 게시, SEO 후속 수정 루프",
  },
  {
    key: "youtube",
    label: "YouTube Studio",
    route: "/content-ops",
    icon: Youtube,
    tint: "from-[#f87171] via-[#ef4444] to-[#b91c1c]",
    summary: "영상 메타데이터, 썸네일, 업로드 대기 흐름",
  },
  {
    key: "instagram",
    label: "Instagram Desk",
    route: "/content-ops",
    icon: Instagram,
    tint: "from-[#f472b6] via-[#d946ef] to-[#7c3aed]",
    summary: "이미지와 릴스 제작/검토 분리 운영",
  },
  {
    key: "seo",
    label: "SEO Lab",
    route: "/analytics",
    icon: SearchCheck,
    tint: "from-[#2dd4bf] via-[#14b8a6] to-[#0f766e]",
    summary: "CTR, 품질 점수, 검색 성과 분석",
  },
  {
    key: "review",
    label: "Review Desk",
    route: "/content-overview",
    icon: Layers3,
    tint: "from-[#60a5fa] via-[#3b82f6] to-[#1d4ed8]",
    summary: "초안, 검토, 실패 항목을 큐 단위로 정리",
  },
  {
    key: "indexing",
    label: "Indexing Desk",
    route: "/google",
    icon: RadioTower,
    tint: "from-[#fde047] via-[#f59e0b] to-[#ca8a04]",
    summary: "Google 연결과 검색 반영 상태 점검",
  },
];

const CONTENT_TYPE_LABELS: Record<string, string> = {
  blog_article: "Blog Article",
  youtube_video: "YouTube Video",
  instagram_image: "Instagram Image",
  instagram_reel: "Instagram Reel",
};

const RUNTIME_LABELS: Record<string, string> = {
  claude_cli: "Claude CLI",
  codex_cli: "Codex CLI",
  gemini_cli: "Gemini CLI",
};

export function MissionControl({ mission }: MissionControlProps) {
  const rooms = buildRooms(mission.channels);
  const liveWorkers = mission.runtimeHealth.liveWorkers || mission.workers.filter((worker) => worker.status === "running").length;
  const activeRuns = mission.runs.filter((run) => run.status === "running" || run.status === "queued");
  const failedRuns = mission.runs.filter((run) => run.status === "failed");

  return (
    <div className="space-y-6">
      <section className="grid gap-6 2xl:grid-cols-[minmax(0,1.45fr)_420px]">
        <article className="mission-hero rounded-[34px] p-6 text-white sm:p-8">
          <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <p className="text-[11px] font-semibold uppercase tracking-[0.36em] text-white/70">Mission Control</p>
              <h1 className="mt-3 font-display text-[44px] font-semibold leading-none">Multi-Platform Marketing OS</h1>
              <p className="mt-4 text-sm leading-7 text-white/80">
                블로그, 유튜브, 인스타그램 운영 상태를 한 화면에서 보고, 작업 큐와 분석 루프를 바로 이동할 수 있도록 재구성한 홈 화면입니다.
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <QuickJump href="/planner" label="Publishing 열기" />
                <QuickJump href="/analytics" label="Analytics 열기" subtle />
                <QuickJump href="/google" label="SEO / Indexing 열기" subtle />
              </div>
            </div>
            <div className="grid min-w-[280px] gap-3 sm:grid-cols-2">
              <HeroStat label="Managed Rooms" value={String(rooms.length)} helper="room cards" />
              <HeroStat label="Live Workers" value={String(liveWorkers)} helper="active operators" />
              <HeroStat label="Queued Runs" value={String(mission.runtimeHealth.queuedRuns)} helper="waiting in tray" />
              <HeroStat label="Failed Runs" value={String(failedRuns.length)} helper="needs recovery" />
            </div>
          </div>
        </article>

        <article className="office-panel rounded-[34px] p-6">
          <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Signal Board</p>
          <div className="mt-4 space-y-3">
            <SignalRow label="Workspace" value={mission.workspaceLabel} tone="sky" />
            <SignalRow label="Runtime" value={mission.runtimeHealth.runtimeStatus} tone={runtimeTone(mission.runtimeHealth.runtimeStatus)} />
            <SignalRow label="Recent Content" value={`${mission.recentContent.length} items`} tone="emerald" />
            <SignalRow label="Alerts" value={`${mission.alerts.length} active`} tone={mission.alerts.length > 0 ? "rose" : "emerald"} />
          </div>

          <div className="mt-5 rounded-[28px] border border-slate-200 bg-[#f8fafc] p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">Feedback Loop</p>
            <div className="mt-4 grid grid-cols-4 gap-2 text-center text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              <LoopPill icon={Sparkles} label="Draft" />
              <LoopPill icon={CheckCircle2} label="Review" />
              <LoopPill icon={RadioTower} label="Publish" />
              <LoopPill icon={SearchCheck} label="Score" />
            </div>
          </div>
        </article>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {rooms.map((room) => {
          const Icon = room.icon;
          return (
            <Link key={room.key} href={room.route} className="office-room-card group rounded-[30px] p-5">
              <div className="flex items-start justify-between gap-4">
                <div className={`rounded-[22px] bg-gradient-to-br p-3 text-white shadow-lg ${room.tint}`}>
                  <Icon className="h-5 w-5" />
                </div>
                <span className={`rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] ${statusPill(room.status)}`}>
                  {room.status}
                </span>
              </div>
              <h2 className="mt-5 text-xl font-semibold text-slate-950">{room.label}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">{room.summary}</p>
              <div className="mt-5 grid grid-cols-3 gap-2">
                <MiniMetric label="Posts" value={String(room.postsCount)} />
                <MiniMetric label="Queue" value={String(room.pendingItems)} />
                <MiniMetric label="Agents" value={String(room.liveWorkerCount)} />
              </div>
              <div className="mt-5 flex items-center justify-between text-sm font-semibold text-slate-700">
                <span>{room.caption}</span>
                <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
              </div>
            </Link>
          );
        })}
      </section>

      <section className="grid gap-6 2xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <article className="office-panel rounded-[32px] p-6">
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Task Tray</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-950">실행 큐와 피드백 대기 항목</h2>
            </div>
            <Link href="/jobs" className="text-sm font-semibold text-slate-700">
              전체 작업 보기
            </Link>
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="space-y-3">
              {activeRuns.slice(0, 6).map((run) => (
                <TaskRunCard key={run.id} run={run} worker={mission.workers.find((worker) => worker.id === run.agentWorkerId) ?? null} />
              ))}
              {activeRuns.length === 0 ? (
                <EmptyState
                  title="대기 중인 실행 작업이 없습니다."
                  description="현재 홈 화면은 Mission Control 중심으로 구성되어 있으며, 새 작업은 Publishing 또는 Content Lab에서 시작할 수 있습니다."
                />
              ) : null}
            </div>

            <div className="space-y-3">
              {mission.alerts.slice(0, 4).map((alert) => (
                <AlertCard key={alert.key} level={alert.level} title={alert.title} message={alert.message} />
              ))}
              {mission.alerts.length === 0 ? (
                <AlertCard
                  level="ok"
                  title="즉시 조치 알림 없음"
                  message="실패 런과 연결 이상이 감지되지 않았습니다. 다음 점검은 Analytics 또는 Google 화면에서 진행하면 됩니다."
                />
              ) : null}
            </div>
          </div>
        </article>

        <article className="office-panel rounded-[32px] p-6">
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Agent Roster</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-950">채널별 운영 에이전트</h2>
            </div>
            <Link href="/ops-health" className="text-sm font-semibold text-slate-700">
              상태 화면 열기
            </Link>
          </div>
          <div className="mt-5 space-y-3">
            {mission.workers.slice(0, 8).map((worker) => (
              <AgentWorkerCard key={worker.id} worker={worker} />
            ))}
            {mission.workers.length === 0 ? (
              <EmptyState
                title="등록된 에이전트가 없습니다."
                description="런타임 연결이 아직 없더라도 셸 구조는 유지됩니다. 연결 후 이 영역에 역할별 에이전트가 표시됩니다."
              />
            ) : null}
          </div>
        </article>
      </section>

      <section className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <article className="office-panel rounded-[32px] p-6">
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Recent Content</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-950">최근 생성/게시 항목</h2>
            </div>
            <Link href="/content-overview" className="text-sm font-semibold text-slate-700">
              전체 보기
            </Link>
          </div>
          <div className="mt-5 space-y-3">
            {mission.recentContent.slice(0, 6).map((item) => (
              <div key={item.id} className="rounded-[24px] border border-slate-200 bg-white px-4 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {contentTypeIcon(item.contentType)}
                      <span>{CONTENT_TYPE_LABELS[item.contentType] ?? item.contentType}</span>
                    </div>
                    <p className="mt-2 truncate text-sm font-semibold text-slate-950">{item.title}</p>
                    <p className="mt-1 max-h-12 overflow-hidden text-sm leading-6 text-slate-600">{item.summary || item.caption || "콘텐츠 요약이 아직 없습니다."}</p>
                  </div>
                  <span className={`shrink-0 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] ${statusPill(item.status)}`}>
                    {item.status}
                  </span>
                </div>
              </div>
            ))}
            {mission.recentContent.length === 0 ? (
              <EmptyState
                title="최근 콘텐츠가 없습니다."
                description="Planner 또는 Content Lab에서 첫 콘텐츠를 만들면 이 영역에 최근 결과가 쌓입니다."
              />
            ) : null}
          </div>
        </article>

        <article className="office-panel rounded-[32px] p-6">
          <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Next Actions</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-950">운영자가 바로 해야 할 일</h2>
          <div className="mt-5 space-y-3">
            <ActionRow
              title="Publishing 캘린더 점검"
              description="게시 슬롯, 채널 비중, 예약 상태를 먼저 정리합니다."
              href="/planner"
            />
            <ActionRow
              title="Analytics에서 점수 확인"
              description="SEO/CTR, 품질 점수, 다음 개선 포인트를 검토합니다."
              href="/analytics"
            />
            <ActionRow
              title="Google 연결 상태 확인"
              description="Search Console/Analytics 연동 상태와 인덱싱 동선을 점검합니다."
              href="/google"
            />
            <ActionRow
              title="Content Lab에서 초안 정리"
              description="검토 대기 중인 글, 이미지, 설명문을 수정합니다."
              href="/content-ops"
            />
          </div>
        </article>
      </section>
    </div>
  );
}

function buildRooms(channels: ManagedChannelRead[]) {
  return ROOM_DEFINITIONS.map((definition) => {
    const matchedChannel = channels.find((channel) => channel.provider === definition.key);
    const pendingItems = matchedChannel?.pendingItems ?? 0;
    const liveWorkerCount = matchedChannel?.liveWorkerCount ?? 0;
    return {
      ...definition,
      status: matchedChannel?.status ?? "standby",
      postsCount: matchedChannel?.postsCount ?? 0,
      pendingItems,
      liveWorkerCount,
      caption:
        matchedChannel != null
          ? `${matchedChannel.name} 연결됨`
          : definition.key === "youtube" || definition.key === "instagram"
            ? "UI 준비 완료"
            : "운영 보드 열기",
    };
  });
}

function HeroStat({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div className="rounded-[26px] border border-white/14 bg-white/10 p-4 backdrop-blur">
      <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-white/60">{label}</p>
      <p className="mt-2 text-3xl font-semibold text-white">{value}</p>
      <p className="mt-1 text-xs text-white/72">{helper}</p>
    </div>
  );
}

function SignalRow({ label, value, tone }: { label: string; value: string; tone: "emerald" | "rose" | "sky" }) {
  const toneClass = {
    emerald: "bg-[#ecfdf5] text-[#166534]",
    rose: "bg-[#fff1f2] text-[#9f1239]",
    sky: "bg-[#f0f9ff] text-[#0c4a6e]",
  }[tone];

  return (
    <div className="flex items-center justify-between gap-3 rounded-[22px] border border-slate-200 bg-white px-4 py-3">
      <span className="text-sm text-slate-500">{label}</span>
      <span className={`rounded-full px-3 py-1 text-xs font-semibold ${toneClass}`}>{value}</span>
    </div>
  );
}

function LoopPill({ icon: Icon, label }: { icon: typeof Sparkles; label: string }) {
  return (
    <div className="rounded-[18px] border border-slate-200 bg-white px-2 py-3">
      <Icon className="mx-auto h-4 w-4 text-slate-500" />
      <p className="mt-2">{label}</p>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] bg-[#f8fafc] px-3 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function TaskRunCard({ run, worker }: { run: AgentRunRead; worker: AgentWorkerRead | null }) {
  return (
    <div className="rounded-[26px] border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{runtimeLabel(run.runtimeKind)}</p>
          <p className="mt-2 text-sm font-semibold text-slate-950">{run.roleKey}</p>
          <p className="mt-1 text-sm text-slate-600">{worker?.displayName ?? "Unassigned worker"}</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] ${statusPill(run.status)}`}>
          {run.status}
        </span>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-500">
        <RunBadge icon={Clock3} label={`attempt ${run.attemptCount}/${run.maxAttempts}`} />
        <RunBadge icon={Bot} label={`priority ${run.queuePriority}`} />
      </div>
    </div>
  );
}

function AlertCard({ level, title, message }: { level: string; title: string; message: string }) {
  const isCritical = level === "critical" || level === "error" || level === "warning";
  return (
    <div className={`rounded-[26px] border px-4 py-4 ${isCritical ? "border-[#fecdd3] bg-[#fff1f2]" : "border-[#bbf7d0] bg-[#ecfdf5]"}`}>
      <div className="flex items-start gap-3">
        {isCritical ? <AlertTriangle className="mt-0.5 h-5 w-5 text-[#be123c]" /> : <CheckCircle2 className="mt-0.5 h-5 w-5 text-[#15803d]" />}
        <div>
          <p className="text-sm font-semibold text-slate-950">{title}</p>
          <p className="mt-1 text-sm leading-6 text-slate-600">{message}</p>
        </div>
      </div>
    </div>
  );
}

function AgentWorkerCard({ worker }: { worker: AgentWorkerRead }) {
  return (
    <div className="rounded-[26px] border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{runtimeLabel(worker.runtimeKind)}</p>
          <p className="mt-2 text-sm font-semibold text-slate-950">{worker.displayName}</p>
          <p className="mt-1 text-sm text-slate-600">{worker.roleKey}</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] ${statusPill(worker.status)}`}>
          {worker.status}
        </span>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-500">
        <RunBadge icon={Bot} label={`x${worker.concurrencyLimit} concurrency`} />
        <RunBadge icon={Globe2} label={worker.oauthSubject ?? "oauth ready"} />
      </div>
    </div>
  );
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-[26px] border border-dashed border-slate-300 bg-[#f8fafc] px-4 py-6">
      <p className="text-sm font-semibold text-slate-950">{title}</p>
      <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
    </div>
  );
}

function ActionRow({ title, description, href }: { title: string; description: string; href: string }) {
  return (
    <Link href={href} className="group block rounded-[26px] border border-slate-200 bg-white px-4 py-4 transition hover:-translate-y-0.5 hover:shadow-[0_24px_60px_rgba(15,23,42,0.08)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-950">{title}</p>
          <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
        </div>
        <ArrowRight className="mt-0.5 h-4 w-4 text-slate-400 transition group-hover:translate-x-1" />
      </div>
    </Link>
  );
}

function QuickJump({ href, label, subtle = false }: { href: string; label: string; subtle?: boolean }) {
  return (
    <Link
      href={href}
      className={`rounded-full px-4 py-3 text-sm font-semibold transition ${
        subtle ? "border border-white/20 bg-white/[0.08] text-white hover:bg-white/[0.14]" : "bg-white text-slate-950 hover:bg-white/90"
      }`}
    >
      {label}
    </Link>
  );
}

function RunBadge({ icon: Icon, label }: { icon: typeof Clock3; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-[#f8fafc] px-3 py-1.5">
      <Icon className="h-3.5 w-3.5" />
      <span>{label}</span>
    </span>
  );
}

function runtimeLabel(runtimeKind: string) {
  return RUNTIME_LABELS[runtimeKind] ?? runtimeKind;
}

function runtimeTone(status: string): "emerald" | "rose" | "sky" {
  if (status === "healthy" || status === "ready" || status === "live") {
    return "emerald";
  }
  if (status === "degraded" || status === "error" || status === "failed") {
    return "rose";
  }
  return "sky";
}

function statusPill(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "running" || normalized === "published" || normalized === "ready" || normalized === "healthy") {
    return "bg-[#ecfdf5] text-[#166534]";
  }
  if (normalized === "failed" || normalized === "error" || normalized === "warning") {
    return "bg-[#fff1f2] text-[#9f1239]";
  }
  if (normalized === "queued" || normalized === "review" || normalized === "scheduled") {
    return "bg-[#eff6ff] text-[#1d4ed8]";
  }
  return "bg-[#f8fafc] text-slate-600";
}

function contentTypeIcon(contentType: string) {
  if (contentType === "youtube_video") {
    return <Video className="h-3.5 w-3.5" />;
  }
  if (contentType === "instagram_image") {
    return <ImageIcon className="h-3.5 w-3.5" />;
  }
  if (contentType === "instagram_reel") {
    return <Film className="h-3.5 w-3.5" />;
  }
  return <Newspaper className="h-3.5 w-3.5" />;
}

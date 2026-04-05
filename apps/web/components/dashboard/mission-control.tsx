import Link from "next/link";
import {
  ArrowRight,
  Image as ImageIcon,
  RadioTower,
  SearchCheck,
  Sparkles,
} from "lucide-react";

import type { ManagedChannelRead, MissionControlRead } from "@/lib/types";

type MissionControlProps = {
  mission: MissionControlRead;
};

type BundleCard = {
  key: "generation" | "assets" | "upload" | "operations";
  title: string;
  purpose: string;
  summary: string;
  href: string;
  tone: string;
  icon: typeof Sparkles;
};

function formatCount(value: number) {
  return new Intl.NumberFormat("ko-KR").format(value);
}

function providerLabel(provider: string) {
  const normalized = provider.toLowerCase();
  if (normalized === "blogger") return "블로그";
  if (normalized === "youtube") return "유튜브";
  if (normalized === "instagram") return "인스타그램";
  if (normalized === "cloudflare") return "Cloudflare 블로그";
  return provider;
}

function statusLabel(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "connected") return "연결됨";
  if (normalized === "attention") return "확인 필요";
  if (normalized === "queued") return "대기";
  if (normalized === "review") return "검토";
  if (normalized === "draft") return "초안";
  if (normalized === "published") return "게시 완료";
  if (normalized === "failed") return "실패";
  if (normalized === "running") return "실행 중";
  if (normalized === "healthy") return "정상";
  if (normalized === "blocked_asset") return "자산 부족";
  if (normalized === "blocked") return "차단";
  if (normalized === "scheduled") return "예약";
  if (normalized === "ready") return "준비됨";
  if (normalized === "busy") return "처리 중";
  if (normalized === "disconnected") return "연결 끊김";
  if (normalized === "warning") return "경고";
  if (normalized === "error") return "오류";
  return status;
}

function buildBundleCards(mission: MissionControlRead): BundleCard[] {
  const generationCount = mission.recentContent.filter((item) => ["draft", "review", "ready_to_publish"].includes(item.lifecycleStatus)).length;
  const assetsCount = mission.recentContent.filter((item) => item.lifecycleStatus === "blocked_asset").length;
  const uploadCount = mission.recentContent.filter((item) => ["queued", "scheduled", "generating"].includes(item.lifecycleStatus)).length;
  const operationCount = mission.alerts.length + mission.runs.filter((run) => run.status === "failed").length;

  return [
    {
      key: "generation",
      title: "생성",
      purpose: "주제 발굴과 초안 작성을 시작하는 단계",
      summary: `최근 생성/검토 대상 ${formatCount(generationCount)}건`,
      href: "/content-ops?type=blog&tab=reviews",
      tone: "from-[#f97316] via-[#ea580c] to-[#c2410c]",
      icon: Sparkles,
    },
    {
      key: "assets",
      title: "자산",
      purpose: "이미지, 썸네일, 본문 자산을 보강하는 단계",
      summary: `보강 필요 자산 ${formatCount(assetsCount)}건`,
      href: "/content-ops?type=blog&tab=articles",
      tone: "from-[#7c3aed] via-[#6d28d9] to-[#5b21b6]",
      icon: ImageIcon,
    },
    {
      key: "upload",
      title: "업로드",
      purpose: "예약 큐와 게시 결과를 처리하는 단계",
      summary: `게시 대기/실행 큐 ${formatCount(uploadCount)}건`,
      href: "/planner",
      tone: "from-[#0ea5e9] via-[#0284c7] to-[#0369a1]",
      icon: RadioTower,
    },
    {
      key: "operations",
      title: "운영",
      purpose: "장애 징후를 확인하고 재시도를 제어하는 단계",
      summary: `운영 경보/실패 항목 ${formatCount(operationCount)}건`,
      href: "/ops-health",
      tone: "from-[#10b981] via-[#059669] to-[#047857]",
      icon: SearchCheck,
    },
  ];
}

function statusPill(status: string) {
  const normalized = status.toLowerCase();
  if (["running", "published", "healthy", "connected", "ready"].includes(normalized)) return "bg-emerald-50 text-emerald-700";
  if (["failed", "error", "warning", "disconnected"].includes(normalized)) return "bg-rose-50 text-rose-700";
  if (["queued", "review", "scheduled", "busy"].includes(normalized)) return "bg-indigo-50 text-indigo-700";
  if (["blocked", "blocked_asset", "attention"].includes(normalized)) return "bg-amber-50 text-amber-700";
  return "bg-slate-100 text-slate-600";
}

function roomDescription(room: ManagedChannelRead) {
  const purpose = (room.purpose || "").trim();
  if (purpose) return purpose;
  if (room.provider === "blogger") return "장문 글 생성, 게시, SEO 후속 수정 루프";
  if (room.provider === "youtube") return "영상 메타데이터, 업로드, 성과 점검 루프";
  if (room.provider === "instagram") return "이미지 또는 릴스 생성과 게시 상태 운영 루프";
  if (room.provider === "cloudflare") return "Cloudflare 블로그 생성과 게시 자동화 루프";
  return "운영 상태를 점검하는 채널";
}

function roomHref(room: ManagedChannelRead) {
  if (room.provider === "blogger") return "/planner";
  if (room.provider === "youtube") return `/content-ops?type=youtube&channel=${encodeURIComponent(room.channelId)}`;
  if (room.provider === "instagram") return `/content-ops?type=instagram&channel=${encodeURIComponent(room.channelId)}`;
  if (room.provider === "cloudflare") return "/google";
  return "/dashboard";
}

function signalTone(status: string): "emerald" | "rose" | "sky" {
  const normalized = status.toLowerCase();
  if (["healthy", "ready", "connected"].includes(normalized)) return "emerald";
  if (["error", "failed", "degraded"].includes(normalized)) return "rose";
  return "sky";
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

function HeroStat({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div className="rounded-[22px] border border-white/14 bg-white/10 p-4 backdrop-blur">
      <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-white/60">{label}</p>
      <p className="mt-2 text-3xl font-semibold text-white">{value}</p>
      <p className="mt-1 text-xs text-white/72">{helper}</p>
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

function QuickJump({ href, label, subtle = false }: { href: string; label: string; subtle?: boolean }) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center rounded-full px-4 py-2 text-sm font-semibold transition ${
        subtle ? "border border-white/20 bg-white/10 text-white hover:bg-white/15" : "bg-white text-slate-950 hover:bg-slate-100"
      }`}
    >
      {label}
    </Link>
  );
}

function ActionRow({ href, title, description }: { href: string; title: string; description: string }) {
  return (
    <Link href={href} className="block rounded-[22px] border border-slate-200 bg-white px-4 py-4 transition hover:border-slate-300 hover:bg-slate-50">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-950">{title}</p>
          <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
        </div>
        <ArrowRight className="mt-0.5 h-4 w-4 text-slate-500" />
      </div>
    </Link>
  );
}

export function MissionControl({ mission }: MissionControlProps) {
  const cards = buildBundleCards(mission);
  const failedRuns = mission.runs.filter((run) => run.status === "failed").length;

  return (
    <div className="space-y-6">
      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_380px]">
        <article className="rounded-[34px] bg-[linear-gradient(135deg,#0f172a_0%,#1e293b_45%,#334155_100%)] p-6 text-white sm:p-8">
          <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <p className="text-[11px] font-semibold uppercase tracking-[0.36em] text-white/70">동그리 자동 블로그전트</p>
              <h1 className="mt-3 text-[42px] font-semibold leading-none">운영 메인 대시보드</h1>
              <p className="mt-4 text-sm leading-7 text-white/82">
                생성, 자산, 업로드, 운영 4개 묶음을 기준으로 멀티 채널 실행 흐름을 한 화면에서 점검하고 바로 실행합니다.
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <QuickJump href="/planner" label="업로드 관리 열기" />
                <QuickJump href="/content-ops" label="자산 / 콘텐츠 관리" subtle />
                <QuickJump href="/ops-health" label="운영 점검 열기" subtle />
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <HeroStat label="운영 채널" value={String(mission.channels.length)} helper="실제 연결된 채널 수" />
              <HeroStat label="실행 워커" value={String(mission.runtimeHealth.liveWorkers)} helper="현재 동작 중" />
              <HeroStat label="대기 실행" value={String(mission.runtimeHealth.queuedRuns)} helper="큐 적재 상태" />
              <HeroStat label="실패 실행" value={String(failedRuns)} helper="복구 필요 항목" />
            </div>
          </div>
        </article>

        <article className="rounded-[34px] border border-slate-200 bg-white p-6">
          <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">신호 보드</p>
          <div className="mt-4 space-y-3">
            <SignalRow label="작업공간" value={mission.workspaceLabel} tone="sky" />
            <SignalRow label="런타임" value={statusLabel(mission.runtimeHealth.runtimeStatus)} tone={signalTone(mission.runtimeHealth.runtimeStatus)} />
            <SignalRow label="최근 콘텐츠" value={`${mission.recentContent.length}건`} tone="emerald" />
            <SignalRow label="경보" value={`${mission.alerts.length}건`} tone={mission.alerts.length > 0 ? "rose" : "emerald"} />
          </div>

          <div className="mt-5 rounded-[24px] border border-slate-200 bg-[#f8fafc] p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">제어 루프</p>
            <div className="mt-4 grid gap-2">
              <span className="rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm font-semibold text-slate-700">초안</span>
              <span className="rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm font-semibold text-slate-700">검토</span>
              <span className="rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm font-semibold text-slate-700">게시</span>
              <span className="rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm font-semibold text-slate-700">피드백</span>
            </div>
          </div>
        </article>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <Link key={card.key} href={card.href} className="group rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md">
              <div className={`inline-flex rounded-[18px] bg-gradient-to-br p-3 text-white ${card.tone}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="mt-4 space-y-2">
                <h2 className="text-xl font-semibold text-slate-950">{card.title}</h2>
                <p className="text-sm leading-6 text-slate-600">{card.purpose}</p>
                <p className="text-sm font-medium text-slate-900">{card.summary}</p>
              </div>
              <div className="mt-4 inline-flex items-center text-sm font-semibold text-slate-700 group-hover:text-slate-950">
                바로 이동
                <ArrowRight className="ml-2 h-4 w-4" />
              </div>
            </Link>
          );
        })}
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_360px]">
        <article className="rounded-[34px] border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Managed Rooms</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-950">연결 채널 운영실</h2>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">{mission.channels.length}개</span>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            {mission.channels.map((room) => (
              <article key={room.channelId} className="rounded-[26px] border border-slate-200 bg-slate-50 p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span className="rounded-full bg-white px-3 py-1 font-semibold text-slate-700">{providerLabel(room.provider)}</span>
                      <span className={`rounded-full px-3 py-1 font-semibold ${statusPill(room.status)}`}>{statusLabel(room.status)}</span>
                    </div>
                    <h3 className="mt-3 text-lg font-semibold text-slate-950">{room.name}</h3>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{roomDescription(room)}</p>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <MiniMetric label="게시글" value={String(room.postsCount)} />
                  <MiniMetric label="대기" value={String(room.pendingItems)} />
                  <MiniMetric label="워커" value={String(room.liveWorkerCount)} />
                  <MiniMetric label="실패" value={String(room.failedItems)} />
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <Link href={roomHref(room)} className="inline-flex items-center rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800">
                    운영 열기
                  </Link>
                  {room.baseUrl ? (
                    <a href={room.baseUrl} target="_blank" rel="noreferrer" className="inline-flex items-center rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100">
                      사이트 열기
                    </a>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </article>

        <article className="space-y-4 rounded-[34px] border border-slate-200 bg-white p-6 shadow-sm">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Quick Actions</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">바로 실행</h2>
          </div>
          <ActionRow href="/settings" title="연동 설정" description="OAuth, API 키, 플랫폼 연결을 먼저 정리합니다." />
          <ActionRow href="/admin" title="관리자 설정" description="게시 플래너 운영, 자동화, 품질 / 발행 기준을 조정합니다." />
          <ActionRow href="/google" title="SEO / 색인" description="연결된 블로그별 Search Console, GA4, 색인 상태를 봅니다." />
          <ActionRow href="/ops-health" title="Ops Monitor" description="실시간 동기화와 장애 징후, 수동 복구 경로를 확인합니다." />
        </article>
      </section>
    </div>
  );
}

import Link from "next/link";

import { fetchChannels } from "@/lib/api";

export default async function DashboardHomePage() {
  const channels = await fetchChannels();

  return (
    <div className="space-y-6">
      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_380px]">
        <article className="rounded-[32px] border border-slate-200 bg-white p-8 shadow-[0_24px_80px_rgba(15,23,42,0.06)]">
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-indigo-500">운영 개요</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-slate-900">블로그 운영 허브</h1>
          <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-500">
            월간 플래너에서 게시 비중과 시간을 정리하고, 분석 화면에서 기존 생성 글과 동기화된 글을 함께 검토합니다.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/planner" className="rounded-2xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-indigo-500">
              플래너 열기
            </Link>
            <Link href="/analytics" className="rounded-2xl border border-indigo-200 bg-indigo-50 px-5 py-3 text-sm font-semibold text-indigo-700 transition hover:bg-indigo-100">
              분석 대시보드 열기
            </Link>
            <Link href="/settings" className="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-100">
              설정 열기
            </Link>
          </div>
        </article>

        <article className="rounded-[32px] bg-gradient-to-br from-indigo-600 to-sky-500 p-6 text-white shadow-[0_24px_80px_rgba(79,70,229,0.18)]">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-100">운영 상태</p>
          <div className="mt-5 space-y-4">
            <QuickLine label="관리 채널" value={`${channels.length}개`} />
            <QuickLine label="자동화 기본값" value="OFF" />
            <QuickLine label="기본 작업 흐름" value="플래너 → 분석" />
            <QuickLine label="보고 기준" value="앱 생성 + 동기화" />
          </div>
        </article>
      </section>

      <section className="grid gap-4 lg:grid-cols-4">
        <MetricCard label="관리 채널" value={String(channels.length)} helper="Blogger + Cloudflare 포함" />
        <MetricCard label="운영 기준" value="플래너" helper="월간 캘린더 중심 운영" />
        <MetricCard label="성과 검토" value="분석" helper="글별 SEO/GEO 확인" />
        <MetricCard label="다음 달 반영" value="비중 조정" helper="카테고리 추천값 반영" />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_360px]">
        <article className="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">운영 흐름</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">이번 달 작업 순서</h2>
            </div>
            <Link href="/analytics" className="text-sm font-semibold text-indigo-600">
              분석 바로가기
            </Link>
          </div>
          <div className="mt-6 space-y-4">
            <FlowRow step="01" title="월간 계획 생성" description="블로그별 카테고리 비중과 게시 수를 기준으로 날짜별 슬롯을 배치합니다." />
            <FlowRow step="02" title="브리프 입력" description="시간, 글 주제, 독자 타겟, 정보 수준, 기타 맥락을 슬롯별로 채웁니다." />
            <FlowRow step="03" title="글 생성 및 발행" description="예약 순서대로 생성하고 발행 결과를 기록합니다." />
            <FlowRow step="04" title="월간 사후 분석" description="글별 점수와 카테고리 편차를 보고 다음 달 비중으로 연결합니다." />
          </div>
        </article>

        <article className="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">관리 채널</p>
          <div className="mt-4 space-y-3">
            {channels.map((channel) => (
              <div key={channel.channelId} className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-900">{channel.name}</p>
                    <p className="mt-1 text-sm text-slate-500">{channel.provider} · {channel.primaryCategory ?? "카테고리 미설정"}</p>
                  </div>
                  <span className={`shrink-0 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-semibold sm:px-3 sm:text-xs ${channel.plannerSupported ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                    {channel.plannerSupported ? "플래너 지원" : "계획 미지원"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </div>
  );
}

function MetricCard({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <article className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{label}</p>
      <p className="mt-4 text-3xl font-semibold text-slate-900">{value}</p>
      <p className="mt-2 text-sm text-slate-500">{helper}</p>
    </article>
  );
}

function FlowRow({ step, title, description }: { step: string; title: string; description: string }) {
  return (
    <div className="flex gap-4 rounded-[24px] bg-slate-50 p-4">
      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-indigo-600 text-sm font-semibold text-white">{step}</div>
      <div>
        <p className="font-semibold text-slate-900">{title}</p>
        <p className="mt-1 text-sm leading-6 text-slate-500">{description}</p>
      </div>
    </div>
  );
}

function QuickLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-white/10 px-4 py-3">
      <span className="text-sm text-indigo-100">{label}</span>
      <span className="font-semibold text-white">{value}</span>
    </div>
  );
}

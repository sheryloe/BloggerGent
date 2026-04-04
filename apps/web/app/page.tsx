import type { Metadata } from "next";
import Link from "next/link";

import { HeroCollageImage } from "@/components/marketing/hero-collage-image";

function resolveMetadataBase() {
  try {
    return new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://ringhyacinth.github.io/BloggerGent");
  } catch {
    return new URL("https://ringhyacinth.github.io/BloggerGent");
  }
}

export const metadata: Metadata = {
  metadataBase: resolveMetadataBase(),
  title: "Bloggent | 자동화 블로그·유튜브·인스타 운영 OS",
  description:
    "Blogger, YouTube, Instagram을 한 화면에서 운영하고 SEO/CTR/분석 루프로 재작성·재배포까지 연결하는 개인형 마케팅 자동화 시스템.",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    url: "/",
    title: "Bloggent | 자동화 블로그·유튜브·인스타 운영 OS",
    description:
      "게시만 자동화하지 않습니다. 게시 → 측정 → 분석 → 수정 → 재배포 루프를 하나의 워크스페이스로 연결합니다.",
    locale: "ko_KR",
    siteName: "Bloggent",
    images: [
      {
        url: "/marketing/dashboard-main.png",
        width: 1280,
        height: 720,
        alt: "Bloggent Dashboard Mission Control",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Bloggent | 자동화 블로그·유튜브·인스타 운영 OS",
    description:
      "Blogger, YouTube, Instagram을 SEO/CTR 피드백 루프로 운영하는 개인형 마케팅 자동화 시스템.",
    images: ["/marketing/dashboard-main.png"],
  },
};

const softwareApplicationJsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Bloggent",
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web, Docker, WSL",
  description:
    "개인 운영자를 위한 멀티 플랫폼 마케팅 운영 시스템. 콘텐츠 생성, 게시, 분석, SEO/CTR 개선 루프를 통합 제공.",
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "USD",
  },
  featureList: [
    "Blogger, YouTube, Instagram 채널 통합 운영",
    "OAuth 기반 채널 연결 및 게시 파이프라인",
    "Search Console/GA4 기반 SEO·CTR 분석 루프",
    "CLI 에이전트(Claude/Codex/Gemini) 실행 추적",
  ],
};

const faqJsonLd = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Bloggent는 무엇을 자동화하나요?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "콘텐츠 생성, 플랫폼별 게시 준비, 성과 수집, SEO/CTR 분석, 재작성 큐 생성을 자동화합니다.",
      },
    },
    {
      "@type": "Question",
      name: "무료 티어로도 운영 가능한가요?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "가능합니다. v0.1은 무료 티어와 OAuth 기반 연결을 기본 전제로 설계되었습니다.",
      },
    },
    {
      "@type": "Question",
      name: "메인 운영 화면은 어디인가요?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "소개 랜딩은 루트(/), 실제 운영 콘솔은 /dashboard 경로에서 사용합니다.",
      },
    },
  ],
};

export default function MarketingLandingPage() {
  return (
    <main className="min-h-screen bg-[#fbf8f2] text-slate-950">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(softwareApplicationJsonLd) }}
      />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }} />

      <section className="relative overflow-hidden border-b border-slate-200/70 bg-gradient-to-br from-[#fff8ee] via-[#f4f7ff] to-[#f4fffa]">
        <div className="mx-auto grid max-w-[1280px] gap-8 px-5 py-12 lg:grid-cols-[minmax(0,1.12fr)_minmax(0,0.88fr)] lg:px-8 lg:py-16">
          <div className="space-y-6">
            <p className="inline-flex rounded-full border border-slate-300 bg-white px-4 py-1.5 text-xs font-semibold uppercase tracking-[0.24em] text-slate-600">
              Bloggent v0.1 in progress
            </p>
            <h1 className="font-display text-[40px] font-semibold leading-[1.04] tracking-tight sm:text-[52px]">
              게시 자동화가 아니라
              <br />
              측정·분석·수정까지
              <br />
              연결된 운영 OS
            </h1>
            <p className="max-w-2xl text-base leading-8 text-slate-700">
              Blogger, YouTube, Instagram을 하나의 워크스페이스에서 운영하고, Search Console/GA4 기반 SEO·CTR 루프로 콘텐츠를 계속 개선하는
              나만의 자동화 마케팅 시스템입니다.
            </p>
            <div className="flex flex-wrap gap-3">
              <Link
                href="/dashboard"
                className="rounded-2xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
              >
                운영 콘솔 열기 (/dashboard)
              </Link>
              <a
                href="#architecture"
                className="rounded-2xl border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
              >
                구조 보기
              </a>
            </div>
          </div>

          <div className="relative min-h-[260px] overflow-hidden rounded-[30px] border border-white/70 bg-white p-3 shadow-[0_28px_80px_rgba(15,23,42,0.12)] sm:min-h-[380px]">
            <HeroCollageImage />
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-[1280px] px-5 py-12 lg:px-8">
        <div className="grid gap-4 md:grid-cols-3">
          <article className="rounded-[26px] border border-slate-200 bg-white p-5">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Value</p>
            <h2 className="mt-3 text-2xl font-semibold text-slate-950">Loop First</h2>
            <p className="mt-3 text-sm leading-7 text-slate-600">생성 후 끝나는 구조가 아니라 결과 지표를 기반으로 다음 액션을 자동 생성합니다.</p>
          </article>
          <article className="rounded-[26px] border border-slate-200 bg-white p-5">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Coverage</p>
            <h2 className="mt-3 text-2xl font-semibold text-slate-950">3 Channels</h2>
            <p className="mt-3 text-sm leading-7 text-slate-600">Blogger, YouTube, Instagram 채널별 전용 에이전트 팩으로 운영 흐름을 분리합니다.</p>
          </article>
          <article className="rounded-[26px] border border-slate-200 bg-white p-5">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Runtime</p>
            <h2 className="mt-3 text-2xl font-semibold text-slate-950">OAuth + CLI</h2>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              Claude CLI, Codex CLI, Gemini CLI의 로컬 OAuth 세션을 재활용해 자동화 런타임을 구성합니다.
            </p>
          </article>
        </div>
      </section>

      <section className="border-y border-slate-200/70 bg-white/70">
        <div className="mx-auto max-w-[1280px] px-5 py-12 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">SEO / CTR Loop</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight">게시 → 측정 → 분석 → 수정 → 재배포</h2>
          <div className="mt-6 grid gap-4 md:grid-cols-5">
            {["게시", "측정", "분석", "수정", "재배포"].map((step) => (
              <div key={step} className="rounded-2xl border border-slate-200 bg-white px-4 py-4 text-center text-sm font-semibold text-slate-700">
                {step}
              </div>
            ))}
          </div>
          <p className="mt-5 text-sm leading-7 text-slate-600">
            Search Console API, GA4, 플랫폼 지표를 함께 수집하고 점수화해 다음 콘텐츠 작업 큐를 자동 생성합니다.
          </p>
        </div>
      </section>

      <section id="architecture" className="mx-auto max-w-[1280px] px-5 py-12 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">Architecture Snapshot</p>
        <h2 className="mt-3 text-3xl font-semibold tracking-tight">실행 구조</h2>
        <div className="mt-6 overflow-x-auto rounded-[26px] border border-slate-200 bg-slate-950 p-5 text-[13px] leading-7 text-slate-100">
          <pre className="whitespace-pre-wrap font-mono">
{`[Landing /]
  -> [Dashboard /dashboard]
      -> ManagedChannel (blogger|youtube|instagram)
      -> ContentItem + PublicationRecord
      -> AgentRun + AgentWorker (claude/codex/gemini CLI)
      -> MetricFact (SEO/CTR/Performance)
      -> Feedback Queue (rewrite/recheck/republish)`}
          </pre>
        </div>
      </section>

      <section className="border-y border-slate-200/70 bg-gradient-to-br from-[#f8fafc] via-[#f5f3ff] to-[#f0fdf4]">
        <div className="mx-auto max-w-[1280px] px-5 py-12 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">Integrations</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight">핵심 연동</h2>
          <div className="mt-6 grid gap-4 md:grid-cols-2">
            <article className="rounded-[24px] border border-slate-200 bg-white p-5">
              <h3 className="text-lg font-semibold text-slate-900">Google Core</h3>
              <p className="mt-2 text-sm leading-7 text-slate-600">
                Blogger, Search Console, GA4를 중심으로 색인 상태 점검, CTR 분석, 리라이트 작업 재큐잉까지 연결합니다.
              </p>
            </article>
            <article className="rounded-[24px] border border-slate-200 bg-white p-5">
              <h3 className="text-lg font-semibold text-slate-900">YouTube + Instagram</h3>
              <p className="mt-2 text-sm leading-7 text-slate-600">
                YouTube는 업로드/메타데이터/썸네일 흐름을, Instagram은 이미지·릴스 분리 큐와 capability-gated publish 흐름을 제공합니다.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-[1280px] px-5 py-12 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-500">FAQ</p>
        <h2 className="mt-3 text-3xl font-semibold tracking-tight">자주 묻는 질문</h2>
        <div className="mt-6 space-y-3">
          <details className="rounded-[20px] border border-slate-200 bg-white p-4">
            <summary className="cursor-pointer text-sm font-semibold text-slate-900">v0.1에서 먼저 되는 기능은 무엇인가요?</summary>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              OAuth 콜백/토큰 갱신, YouTube 업로드 어댑터, Instagram capability-gated publish, Search Console/GA4 수집 파이프라인을 우선 구현합니다.
            </p>
          </details>
          <details className="rounded-[20px] border border-slate-200 bg-white p-4">
            <summary className="cursor-pointer text-sm font-semibold text-slate-900">GitHub Pages에서도 랜딩이 동작하나요?</summary>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              네. `apps/web/out` 정적 export 기준으로 설계되어 basePath 환경에서도 랜딩/자산/내부 링크가 동작합니다.
            </p>
          </details>
          <details className="rounded-[20px] border border-slate-200 bg-white p-4">
            <summary className="cursor-pointer text-sm font-semibold text-slate-900">콜라주 이미지는 어디서 바꾸나요?</summary>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              기본은 로컬 정적 자산을 사용합니다. `NEXT_PUBLIC_MARKETING_HERO_URL`을 설정하면 Cloudflare R2 같은 원격 URL로 override할 수 있습니다.
            </p>
          </details>
        </div>
      </section>

      <section className="border-t border-slate-200 bg-slate-950">
        <div className="mx-auto flex max-w-[1280px] flex-col items-start justify-between gap-4 px-5 py-10 text-white lg:flex-row lg:items-center lg:px-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">Start Now</p>
            <h2 className="mt-2 text-2xl font-semibold">나만의 블로그·유튜브·인스타 자동화 운영 시스템</h2>
            <p className="mt-2 text-sm text-slate-300">소개는 `/`, 운영은 `/dashboard`에서 시작합니다.</p>
          </div>
          <Link
            href="/dashboard"
            className="rounded-2xl bg-white px-5 py-3 text-sm font-semibold text-slate-900 transition hover:bg-slate-100"
          >
            Mission Control 열기
          </Link>
        </div>
      </section>
    </main>
  );
}

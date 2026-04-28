"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useTransition } from "react";
import { AlertTriangle, CheckCircle2, Clapperboard, Images, Loader2, Send, ShieldCheck } from "lucide-react";

import {
  checkWorkspaceContentItemDuplicate,
  createWorkspaceContentItem,
  getWorkspaceContentItems,
  queueWorkspaceContentItemPublish,
  reviewWorkspaceContentItem,
  updateWorkspaceContentItem,
} from "@/lib/api";
import type { ContentItemDuplicateCheckRead, ContentItemRead, ManagedChannelRead } from "@/lib/types";

type StudioMode = "overview" | "instagram" | "youtube" | "review";

type MediaStudioWorkspaceProps = {
  initialMode: StudioMode;
  channels: ManagedChannelRead[];
  initialItems: ContentItemRead[];
  initialError?: string | null;
};

type InstagramDraft = {
  channelId: string;
  title: string;
  topic: string;
  audience: string;
  cardCount: number;
  aspectRatio: "1:1" | "4:5" | "9:16";
  caption: string;
  hashtags: string;
  cta: string;
  cardLines: string;
};

type YoutubeDraft = {
  channelId: string;
  title: string;
  topic: string;
  audience: string;
  videoFormat: "long" | "shorts";
  durationMinutes: number;
  scriptBrief: string;
  thumbnailPrompt: string;
  description: string;
  tags: string;
  privacyStatus: "private" | "unlisted" | "public";
};

const STATUS_LABELS: Record<string, string> = {
  draft: "초안",
  review: "검수",
  approved: "승인",
  ready_to_publish: "발행 준비",
  queued: "큐 등록",
  published: "발행 완료",
  failed: "실패",
  blocked_asset: "자산 대기",
  blocked: "차단",
  scheduled: "예약",
};

const TABS: Array<{ mode: StudioMode; href: string; label: string }> = [
  { mode: "overview", href: "/media-studio", label: "운영 현황" },
  { mode: "instagram", href: "/media-studio/instagram", label: "Instagram 카드뉴스" },
  { mode: "youtube", href: "/media-studio/youtube", label: "YouTube" },
  { mode: "review", href: "/media-studio/review", label: "검수 큐" },
];

const inputClass =
  "w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#03c75a] focus:ring-4 focus:ring-[#03c75a]/10";
const buttonGhostClass =
  "rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-bold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-45";
const buttonPrimaryClass =
  "inline-flex items-center justify-center gap-2 rounded-xl bg-[#03c75a] px-5 py-3 text-sm font-black text-white shadow-sm transition hover:bg-[#02b351] disabled:cursor-not-allowed disabled:opacity-45";

function splitList(value: string) {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function makeCards(lines: string, cardCount: number) {
  const source = splitList(lines);
  return Array.from({ length: Math.max(1, Math.min(12, cardCount)) }, (_, index) => ({
    index: index + 1,
    headline: source[index] || `${index + 1}번 카드 핵심 메시지`,
    body: "",
    image_prompt: "",
  }));
}

function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status;
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function providerLabel(provider: string) {
  if (provider === "instagram") return "Instagram";
  if (provider === "youtube") return "YouTube";
  return provider;
}

function statCount(items: ContentItemRead[], status: string) {
  return items.filter((item) => item.lifecycleStatus === status).length;
}

function firstChannel(channels: ManagedChannelRead[], provider: "instagram" | "youtube") {
  return channels.find((channel) => channel.provider === provider)?.channelId ?? "";
}

function hasRequiredAsset(item: ContentItemRead) {
  const manifest = item.assetManifest ?? {};
  if (item.provider === "youtube") {
    return Boolean(String(manifest.video_file_path ?? manifest.video_url ?? "").trim());
  }
  return Boolean(String(manifest.image_url ?? "").trim());
}

function DuplicateResult({ result }: { result: ContentItemDuplicateCheckRead | null }) {
  if (!result) return null;
  const tone =
    result.riskLevel === "high"
      ? "border-red-200 bg-red-50 text-red-800"
      : result.riskLevel === "medium"
        ? "border-amber-200 bg-amber-50 text-amber-800"
        : "border-emerald-200 bg-emerald-50 text-emerald-800";
  return (
    <div className={`rounded-2xl border px-4 py-3 text-sm ${tone}`}>
      <div className="flex items-center gap-2 font-bold">
        {result.riskLevel === "high" ? <AlertTriangle className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
        중복 위험: {result.riskLevel}
      </div>
      {result.matchedItems.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {result.matchedItems.slice(0, 3).map((item) => (
            <li key={item.id}>
              #{item.id} {item.title} · {(item.similarityScore * 100).toFixed(0)}% · {statusLabel(item.lifecycleStatus)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1">같은 채널과 유형에서 유사 주제를 찾지 못했습니다.</p>
      )}
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className="text-xs font-bold text-slate-500">{children}</label>;
}

export function MediaStudioWorkspace({ initialMode, channels, initialItems, initialError }: MediaStudioWorkspaceProps) {
  const pathname = usePathname();
  const [items, setItems] = useState(initialItems);
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [message, setMessage] = useState<string | null>(null);
  const [duplicateResult, setDuplicateResult] = useState<ContentItemDuplicateCheckRead | null>(null);
  const [isPending, startTransition] = useTransition();

  const instagramChannels = channels.filter((channel) => channel.provider === "instagram");
  const youtubeChannels = channels.filter((channel) => channel.provider === "youtube");
  const mediaItems = items.filter((item) => item.provider === "instagram" || item.provider === "youtube");
  const visibleItems = initialMode === "review" ? mediaItems.filter((item) => item.lifecycleStatus !== "published") : mediaItems;

  const [instagramDraft, setInstagramDraft] = useState<InstagramDraft>({
    channelId: firstChannel(channels, "instagram"),
    title: "",
    topic: "",
    audience: "심리학, 일상 관계, 인간관계에 관심 있는 독자",
    cardCount: 7,
    aspectRatio: "4:5",
    caption: "",
    hashtags: "#심리학 #인간관계 #카드뉴스",
    cta: "저장해두고 관계가 흔들릴 때 다시 확인하세요",
    cardLines: "Hook\n상황 이해\n관계 심리\n주의점\n실천 방법\n체크 질문\n정리",
  });
  const [youtubeDraft, setYoutubeDraft] = useState<YoutubeDraft>({
    channelId: firstChannel(channels, "youtube"),
    title: "",
    topic: "",
    audience: "블로그 주제를 영상으로 확인하려는 시청자",
    videoFormat: "long",
    durationMinutes: 8,
    scriptBrief: "",
    thumbnailPrompt: "",
    description: "",
    tags: "psychology, relationships, self improvement",
    privacyStatus: "private",
  });

  async function reloadItems() {
    const [instagramItems, youtubeItems] = await Promise.all([
      getWorkspaceContentItems({ provider: "instagram", limit: 200 }),
      getWorkspaceContentItems({ provider: "youtube", limit: 200 }),
    ]);
    setItems([...instagramItems, ...youtubeItems]);
  }

  function runAction(action: () => Promise<void>) {
    setError(null);
    setMessage(null);
    startTransition(() => {
      action().catch((cause) => {
        setError(cause instanceof Error ? cause.message : "작업 처리 중 오류가 발생했습니다.");
      });
    });
  }

  async function checkDuplicate(provider: "instagram" | "youtube") {
    const draft = provider === "instagram" ? instagramDraft : youtubeDraft;
    const contentType = provider === "instagram" ? "instagram_image" : "youtube_video";
    const result = await checkWorkspaceContentItemDuplicate({
      provider,
      channelId: draft.channelId,
      contentType,
      topic: draft.topic,
      title: draft.title,
    });
    setDuplicateResult(result);
    return result;
  }

  function createInstagramDraft() {
    runAction(async () => {
      const duplicate = await checkDuplicate("instagram");
      if (duplicate.isDuplicate) {
        setMessage("중복 위험이 high라서 초안 생성을 중단했습니다. 제목이나 주제를 조정하세요.");
        return;
      }
      const cards = makeCards(instagramDraft.cardLines, instagramDraft.cardCount);
      await createWorkspaceContentItem({
        channelId: instagramDraft.channelId,
        contentType: "instagram_image",
        title: instagramDraft.title,
        description: instagramDraft.caption,
        bodyText: cards.map((card) => `${card.index}. ${card.headline}`).join("\n"),
        assetManifest: {
          image_url: "",
          aspect_ratio: instagramDraft.aspectRatio,
          card_count: cards.length,
          assets_required: ["image_url"],
        },
        briefPayload: {
          studio: "media-studio-3003",
          provider: "instagram",
          format: "card_news",
          topic: instagramDraft.topic,
          audience: instagramDraft.audience,
          card_count: cards.length,
          aspect_ratio: instagramDraft.aspectRatio,
          caption: instagramDraft.caption,
          hashtags: splitList(instagramDraft.hashtags),
          cta: instagramDraft.cta,
          cards,
        },
        createdByAgent: "media-studio-3003",
      });
      await reloadItems();
      setMessage("Instagram 카드뉴스 초안을 생성했습니다.");
    });
  }

  function createYoutubeDraft() {
    runAction(async () => {
      const duplicate = await checkDuplicate("youtube");
      if (duplicate.isDuplicate) {
        setMessage("중복 위험이 high라서 초안 생성을 중단했습니다. 제목이나 주제를 조정하세요.");
        return;
      }
      await createWorkspaceContentItem({
        channelId: youtubeDraft.channelId,
        contentType: "youtube_video",
        title: youtubeDraft.title,
        description: youtubeDraft.description,
        bodyText: youtubeDraft.scriptBrief,
        assetManifest: {
          video_file_path: "",
          thumbnail_file_path: "",
          privacy_status: youtubeDraft.privacyStatus,
          assets_required: ["video_file_path"],
        },
        briefPayload: {
          studio: "media-studio-3003",
          provider: "youtube",
          topic: youtubeDraft.topic,
          audience: youtubeDraft.audience,
          video_format: youtubeDraft.videoFormat,
          duration_minutes: youtubeDraft.durationMinutes,
          script_brief: youtubeDraft.scriptBrief,
          thumbnail_prompt: youtubeDraft.thumbnailPrompt,
          tags: splitList(youtubeDraft.tags),
          privacy_status: youtubeDraft.privacyStatus,
        },
        createdByAgent: "media-studio-3003",
      });
      await reloadItems();
      setMessage("YouTube 영상 초안을 생성했습니다.");
    });
  }

  function updateStatus(item: ContentItemRead, status: "review" | "approved" | "draft") {
    runAction(async () => {
      if (status === "review") {
        await reviewWorkspaceContentItem(item.id, {
          reviewNotes: [{ source: "media-studio-3003", note: "검수 큐로 이동" }],
          lastFeedback: "Media Studio에서 검수 요청",
        });
      } else {
        await updateWorkspaceContentItem(item.id, {
          lifecycleStatus: status,
          approvalStatus: status === "approved" ? "approved" : "pending",
        });
      }
      await reloadItems();
      setMessage(`#${item.id} 상태를 ${statusLabel(status)}로 변경했습니다.`);
    });
  }

  function queuePublish(item: ContentItemRead) {
    runAction(async () => {
      const next = await queueWorkspaceContentItemPublish(item.id);
      await reloadItems();
      setMessage(
        next.lifecycleStatus === "blocked_asset"
          ? `필수 자산이 없어 큐 등록을 막았습니다. ${next.blockedReason ?? "unknown"}`
          : `#${item.id} 발행 큐에 등록했습니다.`,
      );
    });
  }

  return (
    <main className="min-h-screen bg-[#f5f7f8] text-slate-900">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
        <header className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
            <div>
              <p className="text-xs font-black uppercase tracking-[0.22em] text-[#03c75a]">Port 3003 Media Studio</p>
              <h1 className="mt-2 text-3xl font-black tracking-tight text-slate-950 sm:text-5xl">Media Studio</h1>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-600">
                Instagram 카드뉴스와 YouTube 영상 초안을 관리합니다. Antigravity가 읽을 brief와 asset 상태를 DB에 저장하고, 검수 후 발행 큐로 넘깁니다.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              <StatCard label="전체" value={mediaItems.length} />
              <StatCard label="검수" value={statCount(mediaItems, "review")} />
              <StatCard label="실패" value={statCount(mediaItems, "failed")} />
              <StatCard label="발행" value={statCount(mediaItems, "published")} />
            </div>
          </div>
        </header>

        <nav className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm">
          {TABS.map((tab) => {
            const active = initialMode === tab.mode || pathname === tab.href;
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={`rounded-xl px-4 py-2.5 text-sm font-bold transition ${
                  active ? "bg-[#03c75a] text-white shadow-sm" : "text-slate-600 hover:bg-slate-50 hover:text-slate-950"
                }`}
              >
                {tab.label}
              </Link>
            );
          })}
          <Link href="/dashboard" className="ml-auto rounded-xl px-4 py-2.5 text-sm font-bold text-slate-500 hover:bg-slate-50 hover:text-slate-950">
            3001 콘솔로 이동
          </Link>
        </nav>

        {(error || message) && (
          <div className={`rounded-2xl border px-5 py-4 text-sm font-medium ${error ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
            {error ?? message}
          </div>
        )}

        {initialMode === "overview" && (
          <section className="grid gap-4 lg:grid-cols-2">
            <ProviderSummary provider="instagram" items={mediaItems.filter((item) => item.provider === "instagram")} />
            <ProviderSummary provider="youtube" items={mediaItems.filter((item) => item.provider === "youtube")} />
          </section>
        )}

        {initialMode === "instagram" && (
          <section className="grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <SectionTitle title="Instagram 카드뉴스 초안" description="주제, 카드 문구, 캡션, 해시태그를 DB에 저장합니다." />
              <div className="mt-5 grid gap-4">
                <FieldLabel>채널</FieldLabel>
                <select className={inputClass} value={instagramDraft.channelId} onChange={(event) => setInstagramDraft({ ...instagramDraft, channelId: event.target.value })}>
                  {instagramChannels.map((channel) => (
                    <option key={channel.channelId} value={channel.channelId}>{channel.name}</option>
                  ))}
                </select>
                <FieldLabel>제목</FieldLabel>
                <input className={inputClass} value={instagramDraft.title} onChange={(event) => setInstagramDraft({ ...instagramDraft, title: event.target.value })} placeholder="카드뉴스 제목" />
                <FieldLabel>주제</FieldLabel>
                <input className={inputClass} value={instagramDraft.topic} onChange={(event) => setInstagramDraft({ ...instagramDraft, topic: event.target.value })} placeholder="예: 회피형 관계에서 대화가 끊기는 이유" />
                <div className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <FieldLabel>카드 수</FieldLabel>
                    <input type="number" min={1} max={12} className={`${inputClass} mt-2`} value={instagramDraft.cardCount} onChange={(event) => setInstagramDraft({ ...instagramDraft, cardCount: Number(event.target.value) })} />
                  </div>
                  <div>
                    <FieldLabel>비율</FieldLabel>
                    <select className={`${inputClass} mt-2`} value={instagramDraft.aspectRatio} onChange={(event) => setInstagramDraft({ ...instagramDraft, aspectRatio: event.target.value as InstagramDraft["aspectRatio"] })}>
                      <option value="4:5">4:5 피드</option>
                      <option value="1:1">1:1 정방형</option>
                      <option value="9:16">9:16 스토리</option>
                    </select>
                  </div>
                  <div>
                    <FieldLabel>대상</FieldLabel>
                    <input className={`${inputClass} mt-2`} value={instagramDraft.audience} onChange={(event) => setInstagramDraft({ ...instagramDraft, audience: event.target.value })} />
                  </div>
                </div>
                <FieldLabel>카드별 핵심 문구</FieldLabel>
                <textarea rows={6} className={inputClass} value={instagramDraft.cardLines} onChange={(event) => setInstagramDraft({ ...instagramDraft, cardLines: event.target.value })} />
                <FieldLabel>캡션</FieldLabel>
                <textarea rows={3} className={inputClass} value={instagramDraft.caption} onChange={(event) => setInstagramDraft({ ...instagramDraft, caption: event.target.value })} />
                <div className="grid gap-3 sm:grid-cols-2">
                  <input className={inputClass} value={instagramDraft.hashtags} onChange={(event) => setInstagramDraft({ ...instagramDraft, hashtags: event.target.value })} placeholder="#심리학, #인간관계" />
                  <input className={inputClass} value={instagramDraft.cta} onChange={(event) => setInstagramDraft({ ...instagramDraft, cta: event.target.value })} placeholder="CTA" />
                </div>
                <div className="flex flex-wrap gap-3">
                  <button type="button" disabled={isPending || !instagramDraft.channelId || !instagramDraft.title} onClick={() => runAction(() => checkDuplicate("instagram").then(() => undefined))} className={buttonGhostClass}>
                    중복 검사
                  </button>
                  <button type="button" disabled={isPending || !instagramDraft.channelId || !instagramDraft.title} onClick={createInstagramDraft} className={buttonPrimaryClass}>
                    {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} 초안 생성
                  </button>
                </div>
                <DuplicateResult result={duplicateResult} />
              </div>
            </div>
            <QueuePanel items={visibleItems.filter((item) => item.provider === "instagram")} onReview={updateStatus} onQueue={queuePublish} isPending={isPending} />
          </section>
        )}

        {initialMode === "youtube" && (
          <section className="grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <SectionTitle title="YouTube 영상 초안" description="스크립트 브리프, 썸네일 프롬프트, 설명과 태그를 저장합니다." />
              <div className="mt-5 grid gap-4">
                <FieldLabel>채널</FieldLabel>
                <select className={inputClass} value={youtubeDraft.channelId} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, channelId: event.target.value })}>
                  {youtubeChannels.map((channel) => (
                    <option key={channel.channelId} value={channel.channelId}>{channel.name}</option>
                  ))}
                </select>
                <FieldLabel>제목</FieldLabel>
                <input className={inputClass} value={youtubeDraft.title} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, title: event.target.value })} placeholder="영상 제목" />
                <FieldLabel>주제</FieldLabel>
                <input className={inputClass} value={youtubeDraft.topic} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, topic: event.target.value })} placeholder="중복 검사 기준 주제" />
                <div className="grid gap-3 sm:grid-cols-4">
                  <div>
                    <FieldLabel>형식</FieldLabel>
                    <select className={`${inputClass} mt-2`} value={youtubeDraft.videoFormat} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, videoFormat: event.target.value as YoutubeDraft["videoFormat"] })}>
                      <option value="long">롱폼</option>
                      <option value="shorts">Shorts</option>
                    </select>
                  </div>
                  <div>
                    <FieldLabel>분량</FieldLabel>
                    <input type="number" min={1} max={60} className={`${inputClass} mt-2`} value={youtubeDraft.durationMinutes} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, durationMinutes: Number(event.target.value) })} />
                  </div>
                  <div>
                    <FieldLabel>공개</FieldLabel>
                    <select className={`${inputClass} mt-2`} value={youtubeDraft.privacyStatus} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, privacyStatus: event.target.value as YoutubeDraft["privacyStatus"] })}>
                      <option value="private">private</option>
                      <option value="unlisted">unlisted</option>
                      <option value="public">public</option>
                    </select>
                  </div>
                  <div>
                    <FieldLabel>대상</FieldLabel>
                    <input className={`${inputClass} mt-2`} value={youtubeDraft.audience} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, audience: event.target.value })} />
                  </div>
                </div>
                <FieldLabel>스크립트 브리프</FieldLabel>
                <textarea rows={7} className={inputClass} value={youtubeDraft.scriptBrief} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, scriptBrief: event.target.value })} />
                <FieldLabel>썸네일 프롬프트</FieldLabel>
                <textarea rows={3} className={inputClass} value={youtubeDraft.thumbnailPrompt} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, thumbnailPrompt: event.target.value })} />
                <div className="grid gap-3 sm:grid-cols-2">
                  <input className={inputClass} value={youtubeDraft.tags} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, tags: event.target.value })} placeholder="tag, tag2" />
                  <input className={inputClass} value={youtubeDraft.description} onChange={(event) => setYoutubeDraft({ ...youtubeDraft, description: event.target.value })} placeholder="영상 설명" />
                </div>
                <div className="flex flex-wrap gap-3">
                  <button type="button" disabled={isPending || !youtubeDraft.channelId || !youtubeDraft.title} onClick={() => runAction(() => checkDuplicate("youtube").then(() => undefined))} className={buttonGhostClass}>
                    중복 검사
                  </button>
                  <button type="button" disabled={isPending || !youtubeDraft.channelId || !youtubeDraft.title} onClick={createYoutubeDraft} className={buttonPrimaryClass}>
                    {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} 초안 생성
                  </button>
                </div>
                <DuplicateResult result={duplicateResult} />
              </div>
            </div>
            <QueuePanel items={visibleItems.filter((item) => item.provider === "youtube")} onReview={updateStatus} onQueue={queuePublish} isPending={isPending} />
          </section>
        )}

        {initialMode === "review" && <QueuePanel items={visibleItems} onReview={updateStatus} onQueue={queuePublish} isPending={isPending} expanded />}
      </div>
    </main>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-24 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
      <p className="text-xs font-bold text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-black text-slate-950">{value}</p>
    </div>
  );
}

function SectionTitle({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h2 className="text-2xl font-black text-slate-950">{title}</h2>
      <p className="mt-1 text-sm text-slate-500">{description}</p>
    </div>
  );
}

function ProviderSummary({ provider, items }: { provider: "instagram" | "youtube"; items: ContentItemRead[] }) {
  const icon =
    provider === "instagram" ? <Images className="h-6 w-6 text-[#03c75a]" /> : <Clapperboard className="h-6 w-6 text-[#03c75a]" />;
  const assetWaiting = items.filter((item) => !hasRequiredAsset(item) && item.lifecycleStatus !== "published").length;
  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#03c75a]/10">{icon}</div>
        <div>
          <h2 className="text-xl font-black text-slate-950">{providerLabel(provider)} 운영 현황</h2>
          <p className="text-sm text-slate-500">{items.length}개 콘텐츠 아이템</p>
        </div>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-3">
        {["draft", "review", "queued"].map((status) => (
          <div key={status} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-bold text-slate-500">{statusLabel(status)}</p>
            <p className="mt-2 text-3xl font-black text-slate-950">{statCount(items, status)}</p>
          </div>
        ))}
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <p className="text-xs font-bold text-slate-500">자산 대기</p>
          <p className="mt-2 text-3xl font-black text-slate-950">{assetWaiting}</p>
        </div>
      </div>
    </div>
  );
}

function QueuePanel({
  items,
  onReview,
  onQueue,
  isPending,
  expanded = false,
}: {
  items: ContentItemRead[];
  onReview: (item: ContentItemRead, status: "review" | "approved" | "draft") => void;
  onQueue: (item: ContentItemRead) => void;
  isPending: boolean;
  expanded?: boolean;
}) {
  return (
    <div className={`rounded-3xl border border-slate-200 bg-white p-5 shadow-sm ${expanded ? "" : "lg:max-h-[980px] lg:overflow-auto"}`}>
      <div className="flex items-center justify-between gap-3">
        <SectionTitle title="검수 큐" description="초안, 검수, 승인, 큐 등록 상태를 직접 전환합니다." />
        <CheckCircle2 className="h-6 w-6 text-[#03c75a]" />
      </div>
      <div className="mt-5 grid gap-3">
        {items.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">표시할 미디어 콘텐츠가 없습니다.</div>
        ) : (
          items.map((item) => (
            <article key={item.id} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col justify-between gap-3 sm:flex-row">
                <div className="min-w-0">
                  <p className="text-xs font-bold text-slate-400">
                    #{item.id} · {providerLabel(item.provider)} · {item.contentType}
                  </p>
                  <h3 className="mt-1 line-clamp-2 font-black text-slate-950">{item.title || "(제목 없음)"}</h3>
                  <p className="mt-2 line-clamp-2 text-sm text-slate-500">{item.description || item.bodyText || "설명 없음"}</p>
                  <p className="mt-2 text-xs text-slate-400">수정: {formatDate(item.updatedAt)}</p>
                </div>
                <span className="h-fit rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-700">{statusLabel(item.lifecycleStatus)}</span>
              </div>
              {item.blockedReason && <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs font-bold text-amber-800">자산 대기: {item.blockedReason}</p>}
              <div className="mt-4 flex flex-wrap gap-2">
                <button disabled={isPending} onClick={() => onReview(item, "review")} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-40">
                  검수 요청
                </button>
                <button disabled={isPending} onClick={() => onReview(item, "approved")} className="rounded-xl border border-[#03c75a]/30 px-3 py-2 text-xs font-bold text-[#03a64b] hover:bg-[#03c75a]/5 disabled:opacity-40">
                  승인
                </button>
                <button disabled={isPending} onClick={() => onQueue(item)} className="rounded-xl border border-[#03c75a]/30 bg-[#03c75a] px-3 py-2 text-xs font-bold text-white hover:bg-[#02b351] disabled:opacity-40">
                  발행 큐 등록
                </button>
                <button disabled={isPending} onClick={() => onReview(item, "draft")} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-500 hover:bg-slate-50 disabled:opacity-40">
                  초안으로
                </button>
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  );
}

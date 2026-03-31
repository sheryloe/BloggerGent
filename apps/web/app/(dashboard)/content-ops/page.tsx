import { redirect } from "next/navigation";

import { ContentOpsArticlesPanel } from "@/components/dashboard/content-ops-articles-panel";
import { ContentOpsJobsPanel } from "@/components/dashboard/content-ops-jobs-panel";
import { ContentOpsManager } from "@/components/dashboard/content-ops-manager";
import { ContentOpsTabNav } from "@/components/dashboard/content-ops-tab-nav";
import { ContentOverviewManager } from "@/components/dashboard/content-overview-manager";
import { PageModeGuideCard } from "@/components/dashboard/page-mode-guide-card";
import { getContentOpsReviews, getContentOpsStatus, getContentOverview } from "@/lib/api";

const isStaticPreview = process.env.GITHUB_ACTIONS === "true";

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function parsePositiveInt(value: string | string[] | undefined, fallback: number) {
  const resolved = firstParam(value);
  const parsed = Number(resolved);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function normalizeTab(value: string | string[] | undefined) {
  const resolved = firstParam(value);
  if (resolved === "jobs" || resolved === "articles" || resolved === "reviews" || resolved === "overview") {
    return resolved;
  }
  return "reviews";
}

function modeCardContent(tab: "jobs" | "articles" | "reviews" | "overview") {
  switch (tab) {
    case "jobs":
      return {
        title: "콘텐츠 운영 · 작업 큐",
        purpose: "최근 작업 상태와 상세 로그를 빠르게 확인합니다.",
        whenToUse: "스케줄 실패, 재시도, 발행 누락을 점검할 때 들어옵니다.",
        dataSource: "경량 작업 목록 API와 선택한 작업 상세 API를 사용합니다.",
        caution: "오래된 작업 전체를 한 번에 보지 않습니다. 최근 30건 기준입니다.",
      };
    case "articles":
      return {
        title: "콘텐츠 운영 · 글 보관",
        purpose: "블로그별 생성 글과 동기화 글을 함께 관리합니다.",
        whenToUse: "발행 전 검수, 동기화 상태 확인, 특정 글 재발행 전에 들어옵니다.",
        dataSource: "블로그 보관함 API와 선택한 글 상세 API를 사용합니다.",
        caution: "선택한 블로그만 조회합니다. 블로그를 바꾸면 목록과 상세가 함께 바뀝니다.",
      };
    case "overview":
      return {
        title: "콘텐츠 운영 · 전체 글 현황",
        purpose: "유사율, SEO, GEO, 카테고리와 품질 상태를 페이지 단위로 봅니다.",
        whenToUse: "시트 동기화 전후 비교, 품질 점수 재계산, 중복 점검할 때 들어옵니다.",
        dataSource: "DB에 저장된 품질 캐시와 구글 시트 동기화 결과를 사용합니다.",
        caution: "최신 계산이 필요하면 재계산 버튼을 먼저 실행하세요.",
      };
    default:
      return {
        title: "콘텐츠 운영 · 품질 검토",
        purpose: "리뷰 승인, 적용, 재실행과 운영 상태를 한 곳에서 처리합니다.",
        whenToUse: "자동 수정 후보를 확인하거나 리뷰 상태를 바꿔야 할 때 들어옵니다.",
        dataSource: "콘텐츠 리뷰 테이블, 자동 수정 로그, 운영 상태 API를 사용합니다.",
        caution: "적용 버튼은 실제 데이터에 반영됩니다. 위험도가 높은 항목은 먼저 내용을 확인하세요.",
      };
  }
}

export default async function ContentOpsPage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  if (isStaticPreview) {
    return (
      <div className="space-y-6">
        <PageModeGuideCard
          title="콘텐츠 운영 프리뷰"
          purpose="GitHub Pages에서는 플래너·분석·설정 중심 프리뷰만 제공합니다."
          whenToUse="실운영에서는 API가 연결된 대시보드에서 작업 큐와 리뷰 화면을 사용하세요."
          dataSource="정적 프리뷰 모드"
          caution="이 페이지는 정적 배포용 안내 화면입니다."
        />
      </div>
    );
  }

  const hasTab = Boolean(firstParam(searchParams?.tab));
  const tab = normalizeTab(searchParams?.tab);

  if (!hasTab) {
    redirect("/content-ops?tab=reviews");
  }

  const guide = modeCardContent(tab);

  return (
    <div className="space-y-6">
      <PageModeGuideCard {...guide} />
      <ContentOpsTabNav activeTab={tab} searchParams={searchParams} />

      {tab === "jobs" ? <ContentOpsJobsPanel searchParams={searchParams} /> : null}
      {tab === "articles" ? <ContentOpsArticlesPanel searchParams={searchParams} /> : null}
      {tab === "reviews" ? <ReviewsTab /> : null}
      {tab === "overview" ? <OverviewTab searchParams={searchParams} /> : null}
    </div>
  );
}

async function ReviewsTab() {
  const [status, reviews] = await Promise.all([getContentOpsStatus(), getContentOpsReviews(undefined, 50)]);
  return <ContentOpsManager initialStatus={status} initialReviews={reviews} />;
}

async function OverviewTab({ searchParams }: { searchParams?: Record<string, string | string[] | undefined> }) {
  const profile = firstParam(searchParams?.profile) ?? undefined;
  const publishedOnly = firstParam(searchParams?.published_only) === "true";
  const page = parsePositiveInt(searchParams?.page, 1);
  const pageSize = parsePositiveInt(searchParams?.page_size, 50);
  const data = await getContentOverview(profile, publishedOnly, page, pageSize);

  return (
    <ContentOverviewManager
      initialRows={data.rows}
      initialTotal={data.total}
      initialProfile={data.profile}
      initialPublishedOnly={data.published_only}
      initialPage={data.page}
      initialPageSize={data.page_size}
    />
  );
}

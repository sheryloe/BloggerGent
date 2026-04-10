"use client";

import { usePathname } from "next/navigation";

import { PageModeGuideCard } from "@/components/dashboard/page-mode-guide-card";

const guideByPath: Record<string, { title: string; purpose: string; whenToUse: string; dataSource: string; caution: string }> = {
  "/guide": {
    title: "가이드",
    purpose: "실운영 전 준비 항목과 연결 순서를 정리해 둡니다.",
    whenToUse: "초기 세팅, 권한 점검, 이미지 전달 구조를 다시 확인할 때 들어옵니다.",
    dataSource: "현재 저장된 설정값, Blogger 연결 상태, Google 연동 상태를 사용합니다.",
    caution: "가이드는 설명 페이지입니다. 실제 값 변경은 설정 페이지에서만 수행하세요.",
  },
  "/help": {
    title: "운영형 도움말",
    purpose: "Telegram `/help`와 동일한 토픽 카탈로그를 운영 화면에서 검색하고 실행 흐름으로 연결합니다.",
    whenToUse: "명령어를 바로 확인하거나, runbook ID 기준으로 단계별 실행 순서를 다시 확인할 때 사용합니다.",
    dataSource: "백엔드 정적 Help 카탈로그(`/api/v1/help/topics`, `/api/v1/help/topics/{id}`)를 사용합니다.",
    caution: "이 화면은 실행 가이드입니다. 실제 동작은 명령 실행 또는 각 운영 페이지에서 처리됩니다.",
  },
  "/ops-health": {
    title: "운영 점검",
    purpose: "무료토큰, 최근 실패 작업, 시트 헤더 이상, 클라우드플레어 배치 결과를 한 번에 점검합니다.",
    whenToUse: "배치 실행 전후, 장애 확인, 운영 상태 보고 전에 먼저 들어옵니다.",
    dataSource: "ops-health 리포트(JSON/MD), OpenAI 사용량 API, 최근 실패 작업/시트 메타데이터를 사용합니다.",
    caution: "이 화면은 점검/가시화용입니다. 실제 재시도·수정 작업은 콘텐츠 운영이나 스크립트 실행으로 처리하세요.",
  },
  "/settings": {
    title: "설정",
    purpose: "전역 공급자, Google OAuth, 블로그 연결, 프롬프트 템플릿을 관리합니다.",
    whenToUse: "API 키, OAuth, 발행 흐름, 워크플로 템플릿을 바꿔야 할 때 들어옵니다.",
    dataSource: "설정 테이블, Blogger 연결 상태, 블로그 워크플로 설정을 사용합니다.",
    caution: "여기서 바꾼 값은 실제 생성과 발행에 바로 영향을 줍니다. 운영 중에는 변경 범위를 최소화하세요.",
  },
  "/training": {
    title: "학습 진행",
    purpose: "학습 세션 상태, 체크포인트, 자동 스케줄을 관리합니다.",
    whenToUse: "학습을 수동 시작하거나, 일시정지/재개하거나, 스케줄 상태를 점검할 때 들어옵니다.",
    dataSource: "학습 상태 API와 저장된 전역 설정값을 사용합니다.",
    caution: "학습 제어는 실제 백그라운드 작업을 시작하거나 멈춥니다. 세션 시간과 저장 주기를 같이 확인하세요.",
  },
};

export function DashboardRouteGuide() {
  const pathname = usePathname();
  const guide = guideByPath[pathname];

  if (!guide) {
    return null;
  }

  return <PageModeGuideCard {...guide} />;
}

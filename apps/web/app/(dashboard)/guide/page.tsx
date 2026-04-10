import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const sections = [
  {
    id: "blogger",
    tag: "블로그",
    title: "Blogger 블로그 연동",
    steps: [
      "연동 설정에서 Google OAuth를 연결합니다.",
      "분석 화면에서 블로그별 Search Console, GA4, 색인 상태를 확인합니다.",
      "콘텐츠 운영과 플래너에서 초안, 자산, 업로드 흐름을 처리합니다.",
    ],
  },
  {
    id: "youtube",
    tag: "유튜브",
    title: "유튜브 연동",
    steps: [
      "연동 설정에서 유튜브 OAuth 상태를 연결합니다.",
      "콘텐츠 운영에서 채널별 게시 대상과 상태를 관리합니다.",
      "분석 화면에서 채널 성과와 실패 항목을 확인합니다.",
    ],
  },
  {
    id: "instagram",
    tag: "인스타그램",
    title: "인스타그램 연동",
    steps: [
      "연동 설정에서 인스타그램 OAuth와 권한 상태를 확인합니다.",
      "콘텐츠 운영에서 채널별 이미지/릴스 게시 흐름을 관리합니다.",
      "분석 화면에서 게시 상태와 운영 결과를 점검합니다.",
    ],
  },
];

export default function GuidePage() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardDescription>운영 가이드</CardDescription>
          <CardTitle>동그리 자동 블로그전트 운영 가이드</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-slate-600">
          <p>
            메인 진입은 <code>/dashboard</code> 이고, 이 화면은 연결과 운영 순서를 빠르게 확인하기 위한 가이드입니다.
          </p>
          <div className="flex flex-wrap gap-2">
            <Badge>동그리 자동 블로그전트</Badge>
            <Badge className="bg-transparent">관리자 설정 / 연동 설정 / Ops Monitor 분리</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/settings" className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700">
              연동 설정 이동
            </Link>
            <Link href="/help" className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700">
              운영형 도움말 이동
            </Link>
            <Link href="/admin" className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700">
              관리자 설정 이동
            </Link>
            <Link href="/ops-health" className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700">
              Ops Monitor 이동
            </Link>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        {sections.map((section) => (
          <Card key={section.id} id={section.id}>
            <CardHeader>
              <CardDescription>{section.tag}</CardDescription>
              <CardTitle>{section.title}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-slate-700">
              {section.steps.map((step, index) => (
                <p key={`${section.id}-${index}`}>
                  {index + 1}. {step}
                </p>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

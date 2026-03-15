import { Badge } from "@/components/ui/badge";
import { JobStatus } from "@/lib/types";

const statusClasses: Record<JobStatus, string> = {
  PENDING: "bg-white text-slate-700",
  DISCOVERING_TOPICS: "bg-amber-100 text-amber-900",
  GENERATING_ARTICLE: "bg-blue-100 text-blue-900",
  GENERATING_IMAGE_PROMPT: "bg-cyan-100 text-cyan-900",
  GENERATING_IMAGE: "bg-violet-100 text-violet-900",
  ASSEMBLING_HTML: "bg-indigo-100 text-indigo-900",
  FINDING_RELATED_POSTS: "bg-emerald-100 text-emerald-900",
  PUBLISHING: "bg-orange-100 text-orange-900",
  STOPPED: "bg-slate-200 text-slate-900",
  COMPLETED: "bg-emerald-200 text-emerald-950",
  FAILED: "bg-rose-100 text-rose-900",
};

const statusLabels: Record<JobStatus, string> = {
  PENDING: "대기",
  DISCOVERING_TOPICS: "주제 발굴",
  GENERATING_ARTICLE: "본문 생성",
  GENERATING_IMAGE_PROMPT: "이미지 프롬프트",
  GENERATING_IMAGE: "이미지 생성",
  ASSEMBLING_HTML: "HTML 조립",
  FINDING_RELATED_POSTS: "관련 글 연결",
  PUBLISHING: "게시 중",
  STOPPED: "중간 종료",
  COMPLETED: "완료",
  FAILED: "실패",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return <Badge className={statusClasses[status]}>{statusLabels[status]}</Badge>;
}

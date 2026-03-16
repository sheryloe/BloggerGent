import { Badge } from "@/components/ui/badge";
import { JobStatus } from "@/lib/types";

const statusClasses: Record<JobStatus, string> = {
  PENDING: "border-slate-200/80 bg-slate-100 text-slate-700 dark:border-white/10 dark:bg-white/5 dark:text-zinc-300",
  DISCOVERING_TOPICS:
    "border-amber-200/80 bg-amber-100 text-amber-900 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200",
  GENERATING_ARTICLE:
    "border-sky-200/80 bg-sky-100 text-sky-900 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-200",
  GENERATING_IMAGE_PROMPT:
    "border-cyan-200/80 bg-cyan-100 text-cyan-900 dark:border-cyan-500/20 dark:bg-cyan-500/10 dark:text-cyan-200",
  GENERATING_IMAGE:
    "border-violet-200/80 bg-violet-100 text-violet-900 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-200",
  ASSEMBLING_HTML:
    "border-indigo-200/80 bg-indigo-100 text-indigo-900 dark:border-indigo-500/20 dark:bg-indigo-500/10 dark:text-indigo-200",
  FINDING_RELATED_POSTS:
    "border-emerald-200/80 bg-emerald-100 text-emerald-900 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200",
  PUBLISHING:
    "border-orange-200/80 bg-orange-100 text-orange-900 dark:border-orange-500/20 dark:bg-orange-500/10 dark:text-orange-200",
  STOPPED: "border-slate-200/80 bg-slate-200 text-slate-900 dark:border-white/10 dark:bg-white/10 dark:text-zinc-100",
  COMPLETED:
    "border-emerald-200/80 bg-emerald-200 text-emerald-950 dark:border-emerald-500/20 dark:bg-emerald-500/15 dark:text-emerald-100",
  FAILED: "border-rose-200/80 bg-rose-100 text-rose-900 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200",
};

const statusLabels: Record<JobStatus, string> = {
  PENDING: "대기",
  DISCOVERING_TOPICS: "주제 발굴",
  GENERATING_ARTICLE: "글 생성",
  GENERATING_IMAGE_PROMPT: "프롬프트",
  GENERATING_IMAGE: "이미지",
  ASSEMBLING_HTML: "HTML",
  FINDING_RELATED_POSTS: "연관 글",
  PUBLISHING: "발행",
  STOPPED: "중지",
  COMPLETED: "완료",
  FAILED: "실패",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return <Badge className={statusClasses[status]}>{statusLabels[status]}</Badge>;
}

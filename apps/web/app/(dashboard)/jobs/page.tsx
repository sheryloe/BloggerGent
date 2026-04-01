import { redirect } from "next/navigation";

const isStaticPreview = process.env.GITHUB_ACTIONS === "true";

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

export default function JobsPage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  if (isStaticPreview) {
    return <div className="rounded-[28px] border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">GitHub Pages 프리뷰에서는 콘텐츠 운영 화면에서 작업 큐 탭을 확인하세요.</div>;
  }

  const params = new URLSearchParams();
  Object.entries(searchParams ?? {}).forEach(([key, value]) => {
    const resolved = firstParam(value);
    if (resolved) {
      params.set(key, resolved);
    }
  });
  params.set("tab", "jobs");
  redirect(`/content-ops?${params.toString()}`);
}

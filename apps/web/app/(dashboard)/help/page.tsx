import { HelpCenter } from "@/components/dashboard/help-center";
import { getHelpTopics } from "@/lib/api";

export default async function HelpPage() {
  const topics = await getHelpTopics();

  return (
    <div className="space-y-4">
      <header className="rounded-[24px] border border-slate-200 bg-white px-5 py-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Help Center</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">운영형 도움말</h1>
        <p className="mt-1 text-sm text-slate-600">Telegram `/help`와 동일한 실행 카탈로그입니다.</p>
      </header>
      <HelpCenter initialTopics={topics} />
    </div>
  );
}

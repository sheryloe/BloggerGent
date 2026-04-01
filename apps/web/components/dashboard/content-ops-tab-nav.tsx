import Link from "next/link";

const TAB_ITEMS = [
  { key: "jobs", label: "작업 큐" },
  { key: "articles", label: "글 보관" },
  { key: "reviews", label: "품질 검토" },
  { key: "overview", label: "전체 글 현황" },
] as const;

type TabKey = (typeof TAB_ITEMS)[number]["key"];

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function buildHref(
  searchParams: Record<string, string | string[] | undefined> | undefined,
  updates: Record<string, string | null>,
) {
  const params = new URLSearchParams();

  Object.entries(searchParams ?? {}).forEach(([key, value]) => {
    const resolved = firstParam(value);
    if (resolved && updates[key] !== null) {
      params.set(key, resolved);
    }
  });

  Object.entries(updates).forEach(([key, value]) => {
    if (!value) {
      params.delete(key);
      return;
    }
    params.set(key, value);
  });

  const query = params.toString();
  return query ? `/content-ops?${query}` : "/content-ops";
}

export function ContentOpsTabNav({
  activeTab,
  searchParams,
}: {
  activeTab: TabKey;
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {TAB_ITEMS.map((item) => {
        const href = buildHref(searchParams, {
          tab: item.key,
          job: item.key === "jobs" ? firstParam(searchParams?.job) ?? null : null,
          article: null,
          blog: item.key === "articles" ? firstParam(searchParams?.blog) ?? null : null,
          page: item.key === "articles" || item.key === "overview" ? firstParam(searchParams?.page) ?? null : null,
          source: item.key === "articles" ? firstParam(searchParams?.source) ?? null : null,
          item: item.key === "articles" ? firstParam(searchParams?.item) ?? null : null,
          profile: item.key === "overview" ? firstParam(searchParams?.profile) ?? null : null,
          published_only: item.key === "overview" ? firstParam(searchParams?.published_only) ?? null : null,
          page_size: item.key === "overview" ? firstParam(searchParams?.page_size) ?? null : null,
        });
        const active = item.key === activeTab;

        return (
          <Link
            key={item.key}
            href={href}
            prefetch={false}
            className={`rounded-full border px-4 py-2 text-sm font-medium transition ${
              active
                ? "border-slate-950 bg-slate-950 text-white dark:border-white dark:bg-white dark:text-slate-950"
                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-950 dark:border-white/10 dark:bg-white/5 dark:text-zinc-300"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}

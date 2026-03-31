import { redirect } from "next/navigation";

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

export default function JobsPage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
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

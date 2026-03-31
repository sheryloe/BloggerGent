"use client";

import { useRouter, useSearchParams } from "next/navigation";

import type { Blog } from "@/lib/types";

export function ArchiveBlogSelector({
  blogs,
  selectedBlogId,
  basePath = "/articles",
  fixedParams,
}: {
  blogs: Blog[];
  selectedBlogId: number;
  basePath?: string;
  fixedParams?: Record<string, string>;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  function handleChange(nextBlogId: number) {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(fixedParams ?? {}).forEach(([key, value]) => {
      params.set(key, value);
    });
    params.set("blog", String(nextBlogId));
    params.set("page", "1");
    params.delete("item");
    params.delete("source");
    params.delete("article");
    params.delete("job");
    const query = params.toString();
    router.push(query ? `${basePath}?${query}` : basePath);
  }

  return (
    <label className="flex flex-col gap-2 text-sm text-slate-600">
      <span className="font-medium text-slate-700">블로그 선택</span>
      <select
        value={selectedBlogId}
        onChange={(event) => handleChange(Number(event.target.value))}
        className="rounded-2xl border border-ink/10 bg-white px-4 py-3 text-sm text-ink outline-none transition focus:border-ink"
      >
        {blogs.map((blog) => (
          <option key={blog.id} value={blog.id}>
            {blog.name}
          </option>
        ))}
      </select>
    </label>
  );
}

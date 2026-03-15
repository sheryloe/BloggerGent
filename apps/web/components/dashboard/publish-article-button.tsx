"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Button } from "@/components/ui/button";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export function PublishArticleButton({
  articleId,
  publishState,
}: {
  articleId: number;
  publishState: "unpublished" | "draft" | "published";
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState("");

  async function handlePublish() {
    if (publishState === "published") {
      setError("이미 공개된 글은 덮어쓸 수 없습니다.");
      return;
    }
    setError("");
    const response = await fetch(`${apiBase}/articles/${articleId}/publish`, {
      method: "POST",
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setError(payload?.detail ?? "게시 요청에 실패했습니다.");
      return;
    }

    startTransition(() => {
      router.refresh();
    });
  }

  return (
    <div className="space-y-2">
      <Button type="button" onClick={handlePublish} disabled={isPending || publishState === "published"}>
        {isPending ? "게시 중..." : publishState === "draft" ? "초안 공개" : publishState === "published" ? "이미 공개됨" : "공개 게시"}
      </Button>
      {error ? <p className="text-sm text-rose-700">{error}</p> : null}
    </div>
  );
}

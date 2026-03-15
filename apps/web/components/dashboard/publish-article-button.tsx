"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Button } from "@/components/ui/button";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export function PublishArticleButton({
  articleId,
  isPublished,
}: {
  articleId: number;
  isPublished: boolean;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState("");

  async function handlePublish() {
    setError("");
    const response = await fetch(`${apiBase}/articles/${articleId}/publish`, {
      method: "POST",
    });

    if (!response.ok) {
      setError("게시 요청에 실패했습니다.");
      return;
    }

    startTransition(() => {
      router.refresh();
    });
  }

  return (
    <div className="space-y-2">
      <Button type="button" onClick={handlePublish} disabled={isPending}>
        {isPending ? "게시 중..." : isPublished ? "다시 게시" : "공개 게시"}
      </Button>
      {error ? <p className="text-sm text-rose-700">{error}</p> : null}
    </div>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export function RetryButton({ jobId }: { jobId: number }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  async function handleRetry() {
    await fetch(`${apiBase}/jobs/${jobId}/retry`, {
      method: "POST",
    });
    startTransition(() => {
      router.refresh();
    });
  }

  return (
    <Button variant="outline" size="sm" onClick={handleRetry} disabled={isPending}>
      {isPending ? "재실행 요청 중..." : "다시 실행"}
    </Button>
  );
}

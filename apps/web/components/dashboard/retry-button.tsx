"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";

export function RetryButton({ jobId }: { jobId: number }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  async function handleRetry() {
    await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/jobs/${jobId}/retry`, {
      method: "POST",
    });
    startTransition(() => {
      router.refresh();
    });
  }

  return (
    <Button variant="outline" size="sm" onClick={handleRetry} disabled={isPending}>
      {isPending ? "재시도 요청 중..." : "재시도"}
    </Button>
  );
}

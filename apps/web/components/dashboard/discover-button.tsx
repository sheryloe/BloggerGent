"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";

export function DiscoverButton({ blogId, label = "지금 주제 발굴 실행" }: { blogId: number; label?: string }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  async function handleClick() {
    await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/blogs/${blogId}/discover`, {
      method: "POST",
    });
    startTransition(() => {
      router.refresh();
    });
  }

  return (
    <Button variant="accent" onClick={handleClick} disabled={isPending}>
      {isPending ? "발굴 요청 중..." : label}
    </Button>
  );
}

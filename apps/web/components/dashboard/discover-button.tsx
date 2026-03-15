"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export function DiscoverButton({ blogId, label = "주제 발굴 실행" }: { blogId: number; label?: string }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  async function handleClick() {
    await fetch(`${apiBase}/blogs/${blogId}/discover?publish_mode=draft`, {
      method: "POST",
    });
    startTransition(() => {
      router.refresh();
    });
  }

  return (
    <Button variant="accent" onClick={handleClick} disabled={isPending}>
      {isPending ? "주제 발굴 요청 중..." : label}
    </Button>
  );
}

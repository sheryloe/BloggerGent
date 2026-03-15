"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export function ResetGeneratedDataButton() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [status, setStatus] = useState("");

  async function handleReset() {
    if (!window.confirm("생성 작업, 글, 이미지, 주제를 모두 정리할까요?")) {
      return;
    }

    setStatus("");
    const response = await fetch(`${apiBase}/jobs/generated-data`, {
      method: "DELETE",
    });

    if (!response.ok) {
      setStatus("생성 데이터 정리에 실패했습니다.");
      return;
    }

    const payload = (await response.json()) as { message: string };
    setStatus(payload.message);
    startTransition(() => router.refresh());
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button type="button" variant="outline" onClick={handleReset} disabled={isPending}>
        {isPending ? "정리 중..." : "생성 데이터 초기화"}
      </Button>
      {status ? <p className="text-sm text-slate-600">{status}</p> : null}
    </div>
  );
}

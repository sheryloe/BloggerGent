"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { PromptTemplate } from "@/lib/types";

export function PromptTemplatesForm({ prompts }: { prompts: PromptTemplate[] }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [status, setStatus] = useState("");
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(prompts.map((prompt) => [prompt.key, prompt.content])),
  );

  async function handleSaveAll() {
    setStatus("");
    const responses = await Promise.all(
      prompts.map((prompt) =>
        fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/prompts/${prompt.key}`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ content: values[prompt.key] ?? "" }),
        }),
      ),
    );

    if (responses.some((response) => !response.ok)) {
      setStatus("프롬프트 저장에 실패했습니다. API 로그를 확인해 주세요.");
      return;
    }

    setStatus("프롬프트 템플릿을 저장했습니다.");
    startTransition(() => {
      router.refresh();
    });
  }

  return (
    <div className="space-y-6">
      {prompts.map((prompt) => (
        <Card key={prompt.key}>
          <CardHeader>
            <CardDescription>{prompt.file_name}</CardDescription>
            <CardTitle>{prompt.title}</CardTitle>
            <p className="text-sm leading-6 text-slate-600">{prompt.description}</p>
            {prompt.placeholders.length ? (
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">
                치환 변수: {prompt.placeholders.join(", ")}
              </p>
            ) : null}
          </CardHeader>
          <CardContent>
            <Textarea
              className="min-h-[260px] font-mono text-[13px] leading-6"
              value={values[prompt.key] ?? ""}
              onChange={(event) => setValues((current) => ({ ...current, [prompt.key]: event.target.value }))}
            />
          </CardContent>
        </Card>
      ))}

      <div className="flex items-center gap-3">
        <Button type="button" onClick={handleSaveAll} disabled={isPending}>
          {isPending ? "저장 중..." : "프롬프트 템플릿 저장"}
        </Button>
        {status ? <p className="text-sm text-slate-600">{status}</p> : null}
      </div>
    </div>
  );
}

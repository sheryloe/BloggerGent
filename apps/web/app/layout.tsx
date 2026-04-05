import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "동그리 자동 블로그전트",
    template: "%s | 동그리 자동 블로그전트",
  },
  description: "동그리 자동 블로그전트는 생성, 자산, 업로드, 운영 흐름을 통합 관리하는 운영 콘솔입니다.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen text-slate-950 antialiased dark:text-zinc-50">{children}</body>
    </html>
  );
}

import type { Metadata } from "next";
import { IBM_Plex_Sans_KR, Space_Grotesk } from "next/font/google";

import "./globals.css";

const bodyFont = IBM_Plex_Sans_KR({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body"
});

const displayFont = Space_Grotesk({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display"
});

export const metadata: Metadata = {
  title: "Bloggent",
  description: "블로그별 AI 에이전트와 프롬프트를 운영하는 SEO 자동화 대시보드"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className={`${bodyFont.variable} ${displayFont.variable} min-h-screen text-slate-950 antialiased dark:text-zinc-50`}>
        {children}
      </body>
    </html>
  );
}

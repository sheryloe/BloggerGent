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
  title: {
    default: "Donggr AutoBloggent",
    template: "%s | Donggr AutoBloggent",
  },
  description: "Donggr AutoBloggent는 생성·자산·업로드·운영 루프를 통합한 멀티 플랫폼 마케팅 운영 시스템입니다.",
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

import type { Metadata } from "next";

import {
  THEME_PREFERENCE_STORAGE_KEY,
} from "@/lib/theme";

import stitchTheme from "./theme.stitch.dark.json";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "동그리 자동 블로그전트",
    template: "%s | 동그리 자동 블로그전트",
  },
  description: "동그리 자동 블로그전트는 생성, 자산, 업로드, 운영 흐름을 통합 관리하는 운영 콘솔입니다.",
};

const themeTokens = stitchTheme.tokens ?? {};

function tokenValue(value: string | undefined, fallback: string) {
  return value && value.trim().length > 0 ? value.trim() : fallback;
}

const darkThemeStyle = `
.dark {
  --app-bg: ${tokenValue(themeTokens.background, "#070b14")};
  --app-bg-elevated: ${tokenValue(themeTokens.backgroundElevated, "rgba(15, 23, 42, 0.78)")};
  --app-fg: ${tokenValue(themeTokens.foreground, "#e5ecf7")};
  --app-fg-muted: ${tokenValue(themeTokens.foregroundMuted, "#94a3b8")};
  --app-border: ${tokenValue(themeTokens.border, "rgba(148, 163, 184, 0.25)")};
  --app-shadow-soft: ${tokenValue(themeTokens.shadowSoft, "0 24px 64px rgba(2, 6, 23, 0.55)")};
  --app-accent-primary: ${tokenValue(themeTokens.accentPrimary, "#f97316")};
  --app-accent-secondary: ${tokenValue(themeTokens.accentSecondary, "#2563eb")};
  --app-accent-success: ${tokenValue(themeTokens.accentSuccess, "#10b981")};
}
`;

const themeBootstrapScript = `
(() => {
  const storageKey = "${THEME_PREFERENCE_STORAGE_KEY}";
  const root = document.documentElement;
  const isThemePreference = (value) => value === "light" || value === "dark" || value === "system";

  try {
    const stored = localStorage.getItem(storageKey);
    const preference = isThemePreference(stored) ? stored : "system";
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const effective = preference === "system" ? (prefersDark ? "dark" : "light") : preference;
    root.classList.toggle("dark", effective === "dark");
    root.dataset.themePreference = preference;
    root.style.colorScheme = effective;
  } catch {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.classList.toggle("dark", prefersDark);
    root.dataset.themePreference = "system";
    root.style.colorScheme = prefersDark ? "dark" : "light";
  }
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        <style id="stitch-dark-theme-vars" dangerouslySetInnerHTML={{ __html: darkThemeStyle }} />
        <script id="theme-bootstrap" dangerouslySetInnerHTML={{ __html: themeBootstrapScript }} />
      </head>
      <body className="min-h-screen bg-app-base text-app-base antialiased transition-colors">{children}</body>
    </html>
  );
}

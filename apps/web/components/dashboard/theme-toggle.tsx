"use client";

import { Laptop, Moon, Sun } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { cn } from "@/lib/utils";
import {
  THEME_PREFERENCE_STORAGE_KEY,
  type ThemePreference,
  normalizeThemePreference,
  resolveEffectiveTheme,
} from "@/lib/theme";

type ThemeOption = {
  value: ThemePreference;
  label: string;
  icon: typeof Sun;
};

const OPTIONS: ThemeOption[] = [
  { value: "light", label: "라이트", icon: Sun },
  { value: "dark", label: "다크", icon: Moon },
  { value: "system", label: "시스템", icon: Laptop },
];

function readStoredPreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  return normalizeThemePreference(window.localStorage.getItem(THEME_PREFERENCE_STORAGE_KEY));
}

function applyThemePreference(preference: ThemePreference) {
  const root = document.documentElement;
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const effective = resolveEffectiveTheme(preference, media.matches);
  root.classList.toggle("dark", effective === "dark");
  root.dataset.themePreference = preference;
  root.style.colorScheme = effective;
}

export function ThemeToggle() {
  const [preference, setPreference] = useState<ThemePreference>("system");
  const selectedLabel = useMemo(
    () => OPTIONS.find((option) => option.value === preference)?.label ?? "시스템",
    [preference],
  );

  useEffect(() => {
    const initial = readStoredPreference();
    setPreference(initial);
    applyThemePreference(initial);
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      if (preference === "system") {
        applyThemePreference("system");
      }
    };
    media.addEventListener("change", handleChange);
    return () => {
      media.removeEventListener("change", handleChange);
    };
  }, [preference]);

  const handleSelect = (nextPreference: ThemePreference) => {
    setPreference(nextPreference);
    window.localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, nextPreference);
    applyThemePreference(nextPreference);
  };

  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/90 px-2 py-1 shadow-sm dark:border-white/10 dark:bg-white/5">
      <span className="px-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-zinc-400">
        Theme
      </span>
      {OPTIONS.map((option) => {
        const Icon = option.icon;
        const active = preference === option.value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => handleSelect(option.value)}
            aria-pressed={active}
            aria-label={`${option.label} 테마`}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition",
              active
                ? "bg-slate-950 text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "text-slate-600 hover:bg-slate-100 dark:text-zinc-300 dark:hover:bg-white/10",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {option.label}
          </button>
        );
      })}
      <span className="hidden text-xs text-slate-500 dark:text-zinc-500 sm:inline">{selectedLabel}</span>
    </div>
  );
}

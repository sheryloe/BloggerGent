export type ThemePreference = "light" | "dark" | "system";

export const THEME_PREFERENCE_STORAGE_KEY = "bloggergent_theme_preference";

export const THEME_PREFERENCES: ThemePreference[] = ["light", "dark", "system"];

export function normalizeThemePreference(value: unknown): ThemePreference {
  if (value === "light" || value === "dark" || value === "system") {
    return value;
  }
  return "system";
}

export function resolveEffectiveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): "light" | "dark" {
  if (preference === "system") {
    return systemPrefersDark ? "dark" : "light";
  }
  return preference;
}

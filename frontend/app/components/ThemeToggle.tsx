"use client";

import { useEffect, useState } from "react";

type ThemeMode = "dark" | "light";

const STORAGE_KEY = "draftmind-theme";
const DEFAULT_THEME: ThemeMode = "light";

function isThemeMode(value: string | null): value is ThemeMode {
  return value === "dark" || value === "light";
}

function applyTheme(theme: ThemeMode) {
  document.documentElement.dataset.theme = theme;
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<ThemeMode | null>(null);

  useEffect(() => {
    const savedTheme = localStorage.getItem(STORAGE_KEY);
    const initialTheme = isThemeMode(savedTheme) ? savedTheme : DEFAULT_THEME;
    applyTheme(initialTheme);
    setTheme(initialTheme);
  }, []);

  function handleToggle() {
    const nextTheme: ThemeMode = theme === "light" ? "dark" : "light";
    applyTheme(nextTheme);
    localStorage.setItem(STORAGE_KEY, nextTheme);
    setTheme(nextTheme);
  }

  const label =
    theme === "light" ? "浅色模式" : theme === "dark" ? "深色模式" : "主题模式";
  const nextLabel = theme === "light" ? "切换到深色" : "切换到浅色";

  return (
    <button
      aria-label={nextLabel}
      aria-pressed={theme === "light"}
      className="inline-flex h-10 items-center gap-2 rounded-full border border-court-border bg-court-panel/90 px-4 text-xs font-semibold text-court-text shadow-glow transition hover:border-court-line/70 hover:text-court-line active:scale-95"
      onClick={handleToggle}
      type="button"
    >
      <span
        aria-hidden="true"
        className="h-2.5 w-2.5 rounded-full bg-court-line"
      />
      <span>{label}</span>
    </button>
  );
}

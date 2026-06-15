"use client";

/** Zustand: UI-only state. Server state belongs to TanStack Query, never here. */

import { create } from "zustand";

export type Theme = "light" | "dark";

interface UiState {
  sidebarOpen: boolean;
  entity: "NIFTY" | "SENSEX";
  theme: Theme;
  paletteOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  setEntity: (entity: "NIFTY" | "SENSEX") => void;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setPaletteOpen: (open: boolean) => void;
}

/** Reads the class the no-flash <head> script already applied, so the store
 * starts in sync with what the user actually sees (no first-paint mismatch). */
function initialTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", theme === "dark");
  try {
    localStorage.setItem("theme", theme);
  } catch {
    /* private mode / storage disabled — theme still applies for the session */
  }
}

export const useUiStore = create<UiState>((set, get) => ({
  sidebarOpen: false,
  entity: "NIFTY",
  theme: initialTheme(),
  paletteOpen: false,
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setEntity: (entity) => set({ entity }),
  setTheme: (theme) => {
    applyTheme(theme);
    set({ theme });
  },
  toggleTheme: () => {
    const next: Theme = get().theme === "dark" ? "light" : "dark";
    applyTheme(next);
    set({ theme: next });
  },
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
}));

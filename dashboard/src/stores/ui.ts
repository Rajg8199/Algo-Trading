"use client";

/** Zustand: UI-only state. Server state belongs to TanStack Query, never here. */

import { create } from "zustand";

interface UiState {
  sidebarOpen: boolean;
  entity: "NIFTY" | "SENSEX";
  setSidebarOpen: (open: boolean) => void;
  setEntity: (entity: "NIFTY" | "SENSEX") => void;
}

export const useUiStore = create<UiState>((set) => ({
  sidebarOpen: false,
  entity: "NIFTY",
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setEntity: (entity) => set({ entity }),
}));

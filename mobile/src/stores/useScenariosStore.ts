/**
 * Scenarios Store — manages automation routines and execution events.
 */

import { create } from 'zustand';
import { sakuraClient } from '../api/client';
import { Scenario } from '../api/types';

interface ScenariosState {
  scenarios: Scenario[];
  runningScenarioId: string | null;
  isLoading: boolean;
  bound: boolean;

  bindEvents: () => void;
  fetchScenarios: () => Promise<void>;
  runScenario: (id: string) => Promise<void>;
}

export const useScenariosStore = create<ScenariosState>((set, get) => ({
  scenarios: [],
  runningScenarioId: null,
  isLoading: false,
  bound: false,

  bindEvents: () => {
    if (get().bound) return;

    sakuraClient.on<any>('scenario_event', (payload) => {
      if (payload?.status === 'done' || payload?.status === 'error') {
        set({ runningScenarioId: null });
      }
    });

    sakuraClient.onLinkState((state) => {
      if (state === 'connected') {
        get().fetchScenarios();
      }
    });

    set({ bound: true });
  },

  fetchScenarios: async () => {
    set({ isLoading: true });
    try {
      const list = await sakuraClient.getScenarios();
      set({ scenarios: list, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  runScenario: async (id: string) => {
    set({ runningScenarioId: id });
    try {
      await sakuraClient.runScenario(id);
    } catch (e) {
      console.warn('[useScenariosStore] Failed to run scenario:', e);
      set({ runningScenarioId: null });
    }
  },
}));

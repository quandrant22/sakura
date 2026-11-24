/**
 * Shared state for Wake Word engine ("Сакура") and microphone arbitration.
 */

import { create } from 'zustand';

export type WakeStatus = 'off' | 'listening' | 'triggered' | 'unsupported' | 'denied' | 'error';

interface WakeControlState {
  wakeStatus: WakeStatus;
  micBusy: boolean;
  setWakeStatus: (status: WakeStatus) => void;
  setMicBusy: (busy: boolean) => void;
}

export const useWakeControlStore = create<WakeControlState>((set) => ({
  wakeStatus: 'off',
  micBusy: false,
  setWakeStatus: (wakeStatus) => set({ wakeStatus }),
  setMicBusy: (micBusy) => set({ micBusy }),
}));

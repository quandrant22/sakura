/**
 * Вынесенное высокочастотное состояние прогресса воспроизведения (positionMs / durationMs),
 * чтобы обновление времени раз в 400 мс не перерисовывало списки из 2000+ треков.
 */

import { create } from 'zustand';

interface MusicProgressState {
  positionMs: number;
  durationMs: number;
}

export const useMusicProgressStore = create<MusicProgressState>(() => ({
  positionMs: 0,
  durationMs: 0,
}));

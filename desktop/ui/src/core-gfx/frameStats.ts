// Пропущенные кадры ядра-графики: кадр «пропущен», если между отрисовками прошло больше слота
// целевой частоты (1000 / fps) — округлённое число слотов минус один. Сводка раз в periodMs
// (console.debug в dev-режиме или с ?corestats), накопленное — в window.__sakuraCoreFrames для стендов.

export interface FrameSummary { drawn: number; missed: number; pct: number }

declare global {
  interface Window { __sakuraCoreFrames?: FrameSummary }
}

export class FrameStats {
  private last = -1;
  private periodStart = -1;
  private drawn = 0;
  private missed = 0;
  private total: FrameSummary = { drawn: 0, missed: 0, pct: 0 };

  constructor(private report: (s: FrameSummary) => void, private periodMs = 10_000) {}

  /** Отрисован кадр в момент t (мс) при целевом слоте intervalMs. */
  frame(t: number, intervalMs: number) {
    if (this.periodStart < 0) this.periodStart = t;
    if (this.last >= 0) {
      const slots = Math.max(1, Math.round((t - this.last) / intervalMs));
      this.missed += slots - 1;
      this.total.missed += slots - 1;
    }
    this.last = t;
    this.drawn += 1;
    this.total.drawn += 1;
    this.total.pct = pct(this.total.drawn, this.total.missed);
    if (typeof window !== "undefined") window.__sakuraCoreFrames = { ...this.total };
    if (t - this.periodStart >= this.periodMs) {
      this.report({ drawn: this.drawn, missed: this.missed, pct: pct(this.drawn, this.missed) });
      this.drawn = 0;
      this.missed = 0;
      this.periodStart = t;
    }
  }

  /** Цикл остановлен (окно скрыто): пауза — не пропуск. */
  pause() {
    this.last = -1;
  }
}

const pct = (drawn: number, missed: number) => (drawn + missed ? Math.round((missed / (drawn + missed)) * 1000) / 10 : 0);

export function frameStatsEnabled(): boolean {
  try {
    if (new URLSearchParams(window.location.search).has("corestats")) return true;
    return Boolean(import.meta.env?.DEV) && import.meta.env?.MODE !== "test";
  } catch {
    return false;
  }
}

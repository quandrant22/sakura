// Чистая функция кадра ядра-графики: (время, состояние, уровень звука) → круги в
// координатах относительно центра основной капли. Рендер — SakuraCore.tsx.

export type CoreVisualState = "idle" | "listening" | "thinking" | "speaking" | "offline";

export const DROP_R = 45.5;
// Спутники (dx, dy, r) при полном раскрытии; силуэт ≈155x149.
export const SATELLITES: ReadonlyArray<readonly [number, number, number]> = [
  [33.7, -61.1, 33.7],
  [-61.1, -37.6, 26.6],
  [-28.2, -87.6, 15.9],
  [55, 25, 12],
  [-48, 30, 9],
];
// Фаза и скорость «бульканья» каждого спутника — чтобы они двигались вразнобой.
const WOBBLE: ReadonlyArray<readonly [number, number]> = [[0, 1], [1.9, 1.27], [3.7, 0.83], [5.1, 1.51], [2.6, 1.13]];

// viewBox: центр капли в (0,0); запас под кольца-волны.
export const VIEWBOX = { x: -130, y: -130, w: 260, h: 220 } as const;
export const MAX_RING_R = 84;

export const MERGE_PRESETS = {
  soft: { blur: 6, matrix: "22 -10" },
  tight: { blur: 4, matrix: "18 -7" },
  liquid: { blur: 8, matrix: "26 -12" },
} as const;
export type MergePreset = keyof typeof MERGE_PRESETS;

export interface Circle { cx: number; cy: number; r: number }
export interface Ring { r: number; opacity: number }
export interface CoreFrame { drop: Circle; satellites: Circle[]; rings: Ring[]; opacity: number }

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const finite = (v: number, d = 0) => (Number.isFinite(v) ? v : d);

interface Motion { base: number; amp: number; omega: number }
function motion(state: CoreVisualState, level: number): Motion {
  switch (state) {
    case "listening": return { base: 0.5, amp: 0.3, omega: 1.6 };
    case "thinking": return { base: 0.97, amp: 0.03, omega: 2.2 };
    case "speaking": return { base: 0.4 + 0.5 * level, amp: 0.08 + 0.25 * level, omega: 4 };
    case "offline": return { base: 0.3, amp: 0.02, omega: 0.3 };
    default: return { base: 0.55, amp: 0.35, omega: 1.1 };
  }
}

/** Кадр в момент t (секунды). level — уровень звука 0..1 (микрофон или озвучка). */
export function coreFrame(t: number, state: CoreVisualState, level: number): CoreFrame {
  t = finite(t);
  level = clamp(finite(level), 0, 1);
  const m = motion(state, level);

  const breathe = state === "offline" ? 1 : 1 + 0.025 * Math.sin(t * 0.8);
  const dropR = DROP_R * breathe;

  const satellites = SATELLITES.map(([dx, dy, r], i) => {
    const [phase, speed] = WOBBLE[i] ?? [0, 1];
    // Раскрытие 0 — спутник спрятан в капле, 1 — полностью выпучен.
    const e = clamp(m.base + m.amp * Math.sin(t * m.omega * speed + phase), 0, 1);
    return { cx: dx * e, cy: dy * e, r: r * (0.6 + 0.4 * e) };
  });

  const rings: Ring[] = [];
  if (state === "listening") {
    const reach = 12 + 26 * level;
    for (let k = 0; k < 2; k++) {
      const p = (((t * 0.7 + k / 2) % 1) + 1) % 1;
      rings.push({ r: Math.min(MAX_RING_R, DROP_R + reach * p), opacity: (1 - p) * (0.35 + 0.5 * level) });
    }
  }

  return { drop: { cx: 0, cy: 0, r: dropR }, satellites, rings, opacity: state === "offline" ? 0.45 : 1 };
}

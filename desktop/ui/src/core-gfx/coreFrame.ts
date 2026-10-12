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
// Фаза, скорость «бульканья» и направление орбиты (1 — по часовой) каждого спутника.
const WOBBLE: ReadonlyArray<readonly [number, number, number]> = [
  [0, 1, 1], [1.9, 1.27, -1], [3.7, 0.83, 1], [5.1, 1.51, -1], [2.6, 1.13, 1],
];
// Угловая скорость орбиты в состоянии «думает», рад/с.
const ORBIT_SPEED = 0.6;

// viewBox: центр капли в (0,0); квадрат 260 — с запасом под орбиту и кольца-волны.
// Диаметр капли 91 px при ширине 260 px — как в наброске.
export const VIEWBOX = { x: -130, y: -130, w: 260, h: 260 } as const;
export const MAX_RING_R = 84;

export const MERGE_PRESETS = {
  soft: { blur: 6, matrix: "22 -10" },
  tight: { blur: 4, matrix: "18 -7" },
  liquid: { blur: 8, matrix: "26 -12" },
} as const;
export type MergePreset = keyof typeof MERGE_PRESETS;

// «Подвижность ядра» из настроек: множитель амплитуды раскрытия.
export const MOBILITY = { low: 0.5, normal: 1, high: 1.3 } as const;
export type Mobility = keyof typeof MOBILITY;

export interface Circle { cx: number; cy: number; r: number }
export interface Ring { r: number; opacity: number }
export interface CoreFrame { drop: Circle; satellites: Circle[]; rings: Ring[]; opacity: number }

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const finite = (v: number, d = 0) => (Number.isFinite(v) ? v : d);

interface Motion { base: number; amp: number; omega: number }
function motion(state: CoreVisualState, level: number): Motion {
  switch (state) {
    case "listening": return { base: 0.5, amp: 0.3, omega: 1.6 };
    case "thinking": return { base: 0.7, amp: 0.25, omega: 1.4 };
    case "speaking": return { base: 0.4 + 0.5 * level, amp: 0.08 + 0.25 * level, omega: 4 };
    case "offline": return { base: 0.3, amp: 0.02, omega: 0.3 };
    default: return { base: 0.55, amp: 0.35, omega: 1.1 };
  }
}

/** Кадр в момент t (секунды). level — уровень звука 0..1 (микрофон или озвучка). */
export function coreFrame(t: number, state: CoreVisualState, level: number, mobility: Mobility = "normal"): CoreFrame {
  t = finite(t);
  level = clamp(finite(level), 0, 1);
  const raw = motion(state, level);
  // Нижняя граница раскрытия (base − amp) не меняется, амплитуда умножается на подвижность.
  const k = MOBILITY[mobility];
  const m = { ...raw, base: raw.base - raw.amp * (1 - k), amp: raw.amp * k };
  const orbit = state === "thinking" ? ORBIT_SPEED * t : 0;

  const breathe = state === "offline" ? 1 : 1 + 0.025 * Math.sin(t * 0.8);
  const dropR = DROP_R * breathe;

  const satellites = SATELLITES.map(([dx, dy, r], i) => {
    const [phase, speed, dir] = WOBBLE[i] ?? [0, 1, 1];
    // Раскрытие 0 — спутник спрятан в капле, 1 — полностью выпучен.
    const e = clamp(m.base + m.amp * Math.sin(t * m.omega * speed + phase), 0, 1);
    const a = orbit * dir, cos = Math.cos(a), sin = Math.sin(a);
    return { cx: (dx * cos - dy * sin) * e, cy: (dx * sin + dy * cos) * e, r: r * (0.6 + 0.4 * e) };
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

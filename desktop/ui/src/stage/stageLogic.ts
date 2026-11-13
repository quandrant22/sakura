// Сцена — прозрачный оверлей на «экране Сакуры» (окно ?view=stage). Чистая логика: что сейчас
// показывать (рисование, субтитры, всплывашки игр), когда прятать окно, перевод координат рисования.
// Отрисовка — Stage.tsx.

export interface InkShape {
  kind: "circle" | "box" | "arrow" | "line" | "path" | "text" | string;
  points: number[];
  text?: string;
  color?: string;
  width?: number;
}

export interface StageToast {
  id: number;
  title: string;
  text: string;
  /** game — реакция на игровое событие, info — обычное уведомление, warn — внимание. */
  tone: "game" | "info" | "warn";
  until: number;
}

export interface StageModel {
  ink: { shapes: InkShape[]; space: { w: number; h: number }; until: number } | null;
  subtitle: { text: string; until: number } | null;
  toasts: StageToast[];
  coreState: "idle" | "listening" | "thinking" | "speaking";
  gameMode: boolean;
  /** Показывать субтитры вне игры (в игре — всегда). */
  subtitlesAlways: boolean;
}

export const EMPTY_STAGE: StageModel = {
  ink: null, subtitle: null, toasts: [], coreState: "idle", gameMode: false, subtitlesAlways: false,
};

export const MAX_TOASTS = 3;
export const SUBTITLE_MIN_MS = 2500;
export const SUBTITLE_MAX_MS = 12_000;
export const TOAST_MS = 5000;

/** Сколько держать реплику: ~60 мс на символ (скорость чтения), в пределах 2.5–12 с. */
export function subtitleMs(text: string): number {
  return Math.max(SUBTITLE_MIN_MS, Math.min(SUBTITLE_MAX_MS, text.length * 60));
}

/** Убрать просроченное. */
export function prune(m: StageModel, now: number): StageModel {
  const ink = m.ink && m.ink.until > now ? m.ink : null;
  const subtitle = m.subtitle && m.subtitle.until > now ? m.subtitle : null;
  const toasts = m.toasts.filter((t) => t.until > now);
  if (ink === m.ink && subtitle === m.subtitle && toasts.length === m.toasts.length) return m;
  return { ...m, ink, subtitle, toasts };
}

/** Окно сцены нужно, только если на нём что-то есть (пустое окно поверх игры — лишняя задержка кадра). */
export function hasContent(m: StageModel, now: number): boolean {
  const p = prune(m, now);
  const coreVisible = p.gameMode && (p.coreState === "listening" || p.coreState === "speaking" || p.coreState === "thinking");
  return Boolean(p.ink?.shapes.length) || Boolean(p.subtitle) || p.toasts.length > 0 || coreVisible;
}

/** Рисование: duration 0 — до явной очистки (держим час), иначе — секунды. */
export function withInk(m: StageModel, shapes: InkShape[], space: { w: number; h: number } | undefined,
                        duration: number | undefined, now: number): StageModel {
  if (!shapes.length) return { ...m, ink: null };
  const ms = duration === 0 ? 3_600_000 : Math.max(1, duration ?? 10) * 1000;
  return { ...m, ink: { shapes, space: space && space.w > 0 && space.h > 0 ? space : { w: 0, h: 0 }, until: now + ms } };
}

export function withSubtitle(m: StageModel, text: string, now: number): StageModel {
  const t = text.trim();
  if (!t) return m;
  if (!m.gameMode && !m.subtitlesAlways) return m;
  return { ...m, subtitle: { text: t, until: now + subtitleMs(t) } };
}

let toastSeq = 0;
export function withToast(m: StageModel, title: string, text: string, tone: StageToast["tone"], now: number): StageModel {
  const toast: StageToast = { id: ++toastSeq, title, text, tone, until: now + TOAST_MS };
  return { ...m, toasts: [...prune(m, now).toasts, toast].slice(-MAX_TOASTS) };
}

/** Точки рисования (в пикселях снимка, который видела модель) → пиксели окна сцены. */
export function scalePoints(points: number[], space: { w: number; h: number }, view: { w: number; h: number }): number[] {
  if (!(space.w > 0 && space.h > 0)) return points;
  const kx = view.w / space.w, ky = view.h / space.h;
  return points.map((v, i) => (i % 2 === 0 ? v * kx : v * ky));
}

/** Наконечник стрелки: две короткие линии от конца под ±28°. */
export function arrowHead(x1: number, y1: number, x2: number, y2: number, size = 18): [number, number, number, number] {
  const a = Math.atan2(y2 - y1, x2 - x1);
  const d = (28 * Math.PI) / 180;
  return [x2 - size * Math.cos(a - d), y2 - size * Math.sin(a - d), x2 - size * Math.cos(a + d), y2 - size * Math.sin(a + d)];
}

/** Игровое событие ядра → подпись всплывашки. */
export const GAME_EVENT_TITLES: Record<string, string> = {
  hurt: "Ай!", flash: "Вспышка", dark: "…", death: "Повержен", victory: "Победа!", kill: "Есть!",
  multikill: "Серия!", round_win: "Раунд наш", round_loss: "Раунд их", bomb_planted: "Бомба", achievement: "Достижение",
  clip_saved: "Клип сохранён", level_up: "Новый уровень", objective: "Цель", low_hp: "Мало здоровья",
};

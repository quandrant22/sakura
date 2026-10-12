// Мини-окна «поверх всех» (видео 16:9, окно приложения — пропорции источника): пресеты размеров,
// минимум, привязка к углам рабочей области, сохранение позиции и размера между запусками.
import fs from "node:fs";
import path from "node:path";

export interface Rect { x: number; y: number; width: number; height: number }

export const VIDEO_ASPECT = 16 / 9;
export const MIN_WIDTH = 240;
export const PRESETS = { S: 320, M: 480, L: 640 } as const;
export type Preset = keyof typeof PRESETS;
/** Ближе этого к углу рабочей области — окно прилипает к углу. */
export const SNAP_PX = 24;
export const SNAP_MARGIN = 12;

export function presetSize(preset: Preset, aspect = VIDEO_ASPECT): { width: number; height: number } {
  const width = PRESETS[preset];
  return { width, height: Math.round(width / aspect) };
}

export function minSize(aspect = VIDEO_ASPECT): { width: number; height: number } {
  return { width: MIN_WIDTH, height: Math.round(MIN_WIDTH / aspect) };
}

/** Если окно у угла рабочей области (по обеим осям ближе SNAP_PX) — прижать к углу с отступом. */
export function snapToCorner(b: Rect, area: Rect, snap = SNAP_PX, margin = SNAP_MARGIN): Rect {
  const left = b.x - area.x, right = area.x + area.width - (b.x + b.width);
  const top = b.y - area.y, bottom = area.y + area.height - (b.y + b.height);
  const nearX = Math.min(left, right) <= snap, nearY = Math.min(top, bottom) <= snap;
  if (!nearX || !nearY) return b;
  return {
    ...b,
    x: left <= right ? area.x + margin : area.x + area.width - b.width - margin,
    y: top <= bottom ? area.y + margin : area.y + area.height - b.height - margin,
  };
}

/** Окно не должно уйти за пределы рабочей области (смена монитора, разрешения). */
export function clampToArea(b: Rect, area: Rect, aspect = VIDEO_ASPECT): Rect {
  const min = minSize(aspect);
  const width = Math.max(min.width, Math.min(b.width, area.width));
  const height = Math.round(width / aspect);
  return {
    width, height,
    x: Math.max(area.x, Math.min(b.x, area.x + area.width - width)),
    y: Math.max(area.y, Math.min(b.y, area.y + area.height - height)),
  };
}

/** Позиции мини-окон по ключу (video, window) в одном файле. */
export function readBounds(file: string, key: string): Rect | null {
  try {
    const all = JSON.parse(fs.readFileSync(file, "utf-8")) as Record<string, Rect>;
    const r = all[key];
    return r && [r.x, r.y, r.width, r.height].every((n) => typeof n === "number" && Number.isFinite(n)) ? r : null;
  } catch {
    return null;
  }
}

export function writeBounds(file: string, key: string, r: Rect): void {
  let all: Record<string, Rect> = {};
  try {
    all = JSON.parse(fs.readFileSync(file, "utf-8")) as Record<string, Rect>;
  } catch {
    all = {};
  }
  all[key] = { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) };
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(all), "utf-8");
}

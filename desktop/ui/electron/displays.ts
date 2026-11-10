// Мониторы и «экран Сакуры»: список дисплеев для настроек, выбор монитора для сцены (оверлея),
// рисования и захвата, сохранение выбора между запусками. Чистые функции — тесты без Electron.
import fs from "node:fs";
import path from "node:path";

export interface Rect { x: number; y: number; width: number; height: number }

/** То, что нужно знать о дисплее (подмножество Electron.Display). */
export interface DisplayLike {
  id: number;
  label?: string;
  bounds: Rect;
  workArea: Rect;
  scaleFactor: number;
  internal?: boolean;
}

export interface DisplayInfo {
  id: number;
  label: string;
  primary: boolean;
  /** Границы в логических пикселях (DIP) — для окон Electron. */
  bounds: Rect;
  /** Границы в физических пикселях — для захвата экрана ядром (PIL/mss). */
  physical: Rect;
  scaleFactor: number;
}

/** Подпись монитора: «Монитор 2 · 2560×1440 · основной». */
export function displayLabel(d: DisplayLike, index: number, primary: boolean, physical: Rect): string {
  const name = d.label && d.label.trim() ? d.label.trim() : `Монитор ${index + 1}`;
  return `${name} · ${physical.width}×${physical.height}${primary ? " · основной" : ""}`;
}

/** Физические границы: dipToScreenRect есть только в Windows; иначе — умножение на масштаб. */
export function toPhysical(d: DisplayLike, dipToScreen?: (r: Rect) => Rect): Rect {
  if (dipToScreen) {
    try {
      return dipToScreen(d.bounds);
    } catch {
      // упадём на расчёт ниже
    }
  }
  const k = d.scaleFactor > 0 ? d.scaleFactor : 1;
  return { x: Math.round(d.bounds.x * k), y: Math.round(d.bounds.y * k),
           width: Math.round(d.bounds.width * k), height: Math.round(d.bounds.height * k) };
}

export function describeDisplays(all: DisplayLike[], primaryId: number, dipToScreen?: (r: Rect) => Rect): DisplayInfo[] {
  // Слева направо, как на столе: так «Монитор 1» — левый.
  const sorted = [...all].sort((a, b) => a.bounds.x - b.bounds.x || a.bounds.y - b.bounds.y);
  return sorted.map((d, i) => {
    const physical = toPhysical(d, dipToScreen);
    const primary = d.id === primaryId;
    return { id: d.id, label: displayLabel(d, i, primary, physical), primary, bounds: d.bounds, physical,
             scaleFactor: d.scaleFactor };
  });
}

/** Выбранный монитор; пропал (отключили) или не выбран — основной. */
export function pickDisplay<T extends { id: number }>(all: T[], wantedId: number | null | undefined, primary: T): T {
  if (wantedId == null) return primary;
  return all.find((d) => d.id === wantedId) ?? primary;
}

// ── Сохранение выбора (stage.json в папке данных) ──

export interface StagePrefs { displayId: number | null; enabled: boolean }
export const DEFAULT_STAGE: StagePrefs = { displayId: null, enabled: true };

export function readStagePrefs(file: string): StagePrefs {
  try {
    const raw = JSON.parse(fs.readFileSync(file, "utf-8")) as Partial<StagePrefs>;
    return {
      displayId: typeof raw.displayId === "number" && Number.isFinite(raw.displayId) ? raw.displayId : null,
      enabled: typeof raw.enabled === "boolean" ? raw.enabled : true,
    };
  } catch {
    return { ...DEFAULT_STAGE };
  }
}

export function writeStagePrefs(file: string, prefs: StagePrefs): void {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(prefs), "utf-8");
  } catch {
    // нет прав на папку данных — выбор проживёт до перезапуска
  }
}

// ── Захват: какие источники разрешены ──

/** Окно (window:HWND:0) или монитор (screen:N:0) из desktopCapturer. */
export const CAPTURE_ID = /^(window|screen):\d+:\d+$/;

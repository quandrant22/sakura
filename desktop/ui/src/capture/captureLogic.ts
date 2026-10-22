// Чистая логика виджета «Окно приложения» (захват окна): режимы размера, частота кадров,
// чёрный кадр, чёрный список, подгонка виджета под пропорции окна. Отрисовка — AppWindowWidget.
import { fitRect } from "../media/videoFit";

export type CaptureMode = "fit" | "fill" | "actual" | "width";
export const CAPTURE_MODES: Record<CaptureMode, string> = { fit: "Вписать", fill: "Заполнить", actual: "100%", width: "По ширине" };

export const ZOOM = { min: 0.25, max: 4, step: 0.25 } as const;
export const FPS = { min: 1, max: 30, default: 10, small: 5, idle: 1 } as const;
/** Потолок разрешения захвата (WINDOW_CAPTURE_MAX). */
export const CAPTURE_MAX = { width: 1920, height: 1080 } as const;

export interface Rect { left: number; top: number; width: number; height: number }

/** Где рисовать кадр источника srcW×srcH в теле виджета boxW×boxH. scroll — нужна панорама/прокрутка. */
export function captureRect(boxW: number, boxH: number, srcW: number, srcH: number, mode: CaptureMode,
                            zoom = 1): Rect & { scroll: boolean } {
  if (!(srcW > 0 && srcH > 0 && boxW > 0 && boxH > 0)) return { left: 0, top: 0, width: 0, height: 0, scroll: false };
  const aspect = srcW / srcH;
  const z = Math.min(ZOOM.max, Math.max(ZOOM.min, zoom));
  if (mode === "actual") {
    const width = Math.round(srcW * z), height = Math.round(srcH * z);
    return { left: Math.max(0, Math.round((boxW - width) / 2)), top: Math.max(0, Math.round((boxH - height) / 2)),
             width, height, scroll: width > boxW || height > boxH };
  }
  if (mode === "width") {
    const width = Math.round(boxW * z), height = Math.round((boxW * z) / aspect);
    return { left: 0, top: 0, width, height, scroll: width > boxW || height > boxH };
  }
  const base = fitRect(boxW, boxH, aspect, mode);
  if (z === 1 || mode === "fill") return { ...base, scroll: false };
  const width = Math.round(base.width * z), height = Math.round(base.height * z);
  return { left: Math.round((boxW - width) / 2), top: Math.round((boxH - height) / 2), width, height,
           scroll: width > boxW || height > boxH };
}

/** Захват не выше потолка, с сохранением пропорций источника. */
export function captureSize(srcW: number, srcH: number, max = CAPTURE_MAX): { width: number; height: number } {
  const k = Math.min(1, max.width / srcW, max.height / srcH);
  return { width: Math.round(srcW * k), height: Math.round(srcH * k) };
}

/** Частота кадров: базовая 10 (1–30); маленький виджет — до 5; скрыт или идёт перетаскивание — 1. */
export function adaptiveFps(base: number, widgetWidth: number, hidden: boolean, interacting: boolean): number {
  const b = Math.min(FPS.max, Math.max(FPS.min, Math.round(base || FPS.default)));
  if (hidden || interacting) return FPS.idle;
  return widgetWidth < 320 ? Math.min(b, FPS.small) : b;
}

/** Кадр «чёрный» (защищённое окно отдаёт чёрный кадр; свёрнутое — тоже): средняя яркость ниже порога. */
export function isBlackFrame(rgba: Uint8ClampedArray, threshold = 8): boolean {
  let sum = 0, n = 0;
  for (let i = 0; i + 2 < rgba.length; i += 16) { // каждый 4-й пиксель — достаточно для решения
    sum += 0.2126 * (rgba[i] ?? 0) + 0.7152 * (rgba[i + 1] ?? 0) + 0.0722 * (rgba[i + 2] ?? 0);
    n++;
  }
  return n > 0 && sum / n < threshold;
}

export interface WindowSource { id: string; name: string }

/** Менеджеры паролей, банки и т.п. (WINDOW_BLOCKLIST) и окна самой Сакуры в выбор не попадают. */
export const DEFAULT_BLOCKLIST = ["keepass", "1password", "bitwarden", "lastpass", "dashlane", "enpass",
  "сбербанк", "сбербанк онлайн", "тинькофф", "т-банк", "альфа-банк", "втб онлайн", "credential", "пароль"];

export function filterSources(list: WindowSource[], blocklist: string[] = DEFAULT_BLOCKLIST): WindowSource[] {
  const block = blocklist.map((b) => b.trim().toLowerCase()).filter(Boolean);
  return list.filter((s) => {
    const n = s.name.toLowerCase();
    if (!n || n === "sakura" || n.startsWith("sakura ·")) return false;
    return !block.some((b) => n.includes(b));
  });
}

/** «Подогнать виджет под окно»: новая высота в строках сетки, чтобы тело виджета имело пропорции окна. */
export function fitWidgetRows(widgetWidthPx: number, aspect: number, rowHeight: number, marginY: number,
                              chromePx: number, minRows = 6): number {
  if (!(aspect > 0) || !(widgetWidthPx > 0)) return minRows;
  const wantPx = widgetWidthPx / aspect + chromePx; // тело + заголовок и панель
  // h строк занимают h*rowHeight + (h-1)*marginY пикселей
  return Math.max(minRows, Math.round((wantPx + marginY) / (rowHeight + marginY)));
}

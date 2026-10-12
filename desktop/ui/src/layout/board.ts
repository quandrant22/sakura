// Модель доски виджетов: сетка, реестр виджетов, раскладка по умолчанию и чистые операции над ней.
// Отрисовка — WidgetBoard.tsx (react-grid-layout).

export const GRID = {
  cols: 24,
  // 9.35, а не 10 из описания: с отступом 20 только так блоки встают в набросок (±3 px)
  // и раскладка по умолчанию (31 строка) помещается в 890 px без прокрутки. См. DECISIONS.md.
  rowHeight: 9.35,
  margin: [20, 20] as const,
  // Ширина доски в кадре 1440: уже неё раскладка масштабируется, а не сжимается в ноль.
  designWidth: 690,
};

export type WidgetId = "system" | "video" | "app" | "music";

export interface LayoutItem {
  i: WidgetId;
  x: number;
  y: number;
  w: number;
  h: number;
}

interface WidgetMeta {
  title: string;
  default: Omit<LayoutItem, "i">;
  minW: number;
  minH: number;
}

export const WIDGETS: Record<WidgetId, WidgetMeta> = {
  system: { title: "Система", default: { x: 0, y: 0, w: 9, h: 16 }, minW: 6, minH: 8 },
  video: { title: "Видео", default: { x: 9, y: 0, w: 15, h: 16 }, minW: 8, minH: 8 },
  app: { title: "Окно приложения", default: { x: 0, y: 16, w: 24, h: 11 }, minW: 8, minH: 6 },
  // Минимум панели Яндекс.Музыки 480x100 px при ширине доски 690: w17, h4.
  music: { title: "Музыка", default: { x: 0, y: 27, w: 24, h: 4 }, minW: 17, minH: 4 },
};

export const WIDGET_IDS = Object.keys(WIDGETS) as WidgetId[];

export const defaultLayout = (): LayoutItem[] => WIDGET_IDS.map((i) => ({ i, ...WIDGETS[i].default }));

const isWidget = (v: unknown): v is WidgetId => typeof v === "string" && v in WIDGETS;
const int = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? Math.round(v) : NaN);

/** Проверка сохранённой раскладки: неизвестные виджеты и мусор отбрасываются, размеры — в пределах сетки. */
export function sanitizeLayout(raw: unknown): LayoutItem[] | null {
  if (!Array.isArray(raw)) return null;
  const seen = new Set<WidgetId>();
  const out: LayoutItem[] = [];
  for (const it of raw) {
    if (!it || typeof it !== "object") continue;
    const o = it as Record<string, unknown>;
    if (!isWidget(o.i) || seen.has(o.i)) continue;
    const [x, y, w, h] = [int(o.x), int(o.y), int(o.w), int(o.h)];
    if ([x, y, w, h].some(Number.isNaN)) continue;
    const meta = WIDGETS[o.i];
    const cw = Math.min(GRID.cols, Math.max(meta.minW, w));
    out.push({ i: o.i, x: Math.min(GRID.cols - cw, Math.max(0, x)), y: Math.max(0, y), w: cw, h: Math.max(meta.minH, h) });
    seen.add(o.i);
  }
  return out;
}

/** Нижняя граница раскладки в строках. */
export const bottom = (layout: LayoutItem[]) => layout.reduce((m, it) => Math.max(m, it.y + it.h), 0);

/** Добавить виджет: на прежнее место по умолчанию, если оно свободно, иначе — под всеми. */
export function addWidget(layout: LayoutItem[], id: WidgetId): LayoutItem[] {
  if (layout.some((it) => it.i === id)) return layout;
  const d = WIDGETS[id].default;
  const overlaps = layout.some((it) => it.x < d.x + d.w && d.x < it.x + it.w && it.y < d.y + d.h && d.y < it.y + it.h);
  return [...layout, { i: id, ...d, y: overlaps ? bottom(layout) : d.y }];
}

export const removeWidget = (layout: LayoutItem[], id: WidgetId) => layout.filter((it) => it.i !== id);

export const hiddenWidgets = (layout: LayoutItem[]) => WIDGET_IDS.filter((id) => !layout.some((it) => it.i === id));

/** Пиксельный прямоугольник элемента при ширине доски width (для сверки с наброском и тестов). */
export function itemRect(it: Omit<LayoutItem, "i">, width = GRID.designWidth) {
  const [mx, my] = GRID.margin;
  const colW = (width - mx * (GRID.cols - 1)) / GRID.cols;
  return {
    left: it.x * (colW + mx),
    top: it.y * (GRID.rowHeight + my),
    width: it.w * colW + (it.w - 1) * mx,
    height: it.h * GRID.rowHeight + (it.h - 1) * my,
  };
}

/** Высота раскладки в пикселях (без масштаба). */
export const layoutHeight = (layout: LayoutItem[]) => {
  const rows = bottom(layout);
  return rows > 0 ? rows * GRID.rowHeight + (rows - 1) * GRID.margin[1] : 0;
};

/** Масштаб доски: при ширине уже designWidth раскладка рисуется в designWidth и уменьшается. */
export const boardScale = (width: number) => (width > 0 && width < GRID.designWidth ? width / GRID.designWidth : 1);

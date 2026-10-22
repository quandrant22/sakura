// Модель доски v2: страницы («рабочие столы»), у каждой — раскладка на три точки адаптивности,
// каталог виджетов, чистые операции (добавить, убрать, отменить, дублировать, закрепить, свернуть,
// сбросить, сдвинуть/изменить размер с клавиатуры), миграция с v1 и валидация.
// layout.json: { version: 2, active_page, pages: [{ id, name, breakpoints: { lg, md, sm }: [item] }] }

export type Breakpoint = "lg" | "md" | "sm";
export const BREAKPOINTS: Record<Breakpoint, number> = { lg: 640, md: 440, sm: 0 }; // ширина доски, px
export const COLS: Record<Breakpoint, number> = { lg: 24, md: 12, sm: 1 };
export const BP_ORDER: Breakpoint[] = ["lg", "md", "sm"];
export const ROW_HEIGHT = 9.35; // см. DECISIONS №9
export const MARGIN: [number, number] = [20, 20];
/** Свёрнутый виджет — только заголовок: 3 строки (3*9.35 + 2*20 ≈ 68 px). */
export const COLLAPSED_ROWS = 3;

export type WidgetType = "music" | "video" | "window" | "system" | "scenarios" | "today" | "server" | "notes"
  | "notifications" | "focus-timer" | "quick-actions";
export type Category = "media" | "system" | "assistant";
export type Size = "S" | "M" | "L";

export interface WidgetMeta {
  title: string;
  description: string;
  category: Category;
  /** Одна копия на страницу (музыка, видео, окно…). */
  singleton: boolean;
  /** Размеры для lg (24 колонки); на md и sm пересчитываются. */
  sizes: Record<Size, { w: number; h: number }>;
  min: { w: number; h: number };
  max?: { w: number; h: number };
}

export const CATALOG: Record<WidgetType, WidgetMeta> = {
  music: { title: "Музыка", description: "Панель Яндекс.Музыки или медиатека Сакуры", category: "media", singleton: true,
           sizes: { S: { w: 17, h: 4 }, M: { w: 24, h: 4 }, L: { w: 24, h: 12 } }, min: { w: 17, h: 4 } },
  video: { title: "Видео", description: "Файлы, потоки и YouTube", category: "media", singleton: true,
           sizes: { S: { w: 9, h: 12 }, M: { w: 15, h: 16 }, L: { w: 24, h: 22 } }, min: { w: 8, h: 8 } },
  window: { title: "Окно приложения", description: "Показ окна внутри Сакуры по вашему выбору", category: "media",
            singleton: true, sizes: { S: { w: 12, h: 9 }, M: { w: 24, h: 11 }, L: { w: 24, h: 18 } }, min: { w: 8, h: 6 } },
  system: { title: "Система", description: "CPU, RAM, GPU и устройства", category: "system", singleton: true,
            sizes: { S: { w: 6, h: 8 }, M: { w: 9, h: 16 }, L: { w: 12, h: 16 } }, min: { w: 6, h: 8 } },
  scenarios: { title: "Сценарии", description: "Быстрый запуск сценариев", category: "assistant", singleton: true,
               sizes: { S: { w: 6, h: 8 }, M: { w: 9, h: 12 }, L: { w: 12, h: 16 } }, min: { w: 6, h: 6 } },
  today: { title: "Сегодня", description: "Дата, время и настроение Сакуры", category: "assistant", singleton: true,
           sizes: { S: { w: 6, h: 6 }, M: { w: 8, h: 8 }, L: { w: 12, h: 10 } }, min: { w: 5, h: 5 } },
  server: { title: "Сервер", description: "Связь с ядром и сервером", category: "system", singleton: true,
            sizes: { S: { w: 6, h: 6 }, M: { w: 8, h: 8 }, L: { w: 12, h: 8 } }, min: { w: 5, h: 5 } },
  notes: { title: "Заметки", description: "Короткие заметки этого устройства", category: "assistant", singleton: false,
           sizes: { S: { w: 6, h: 8 }, M: { w: 8, h: 12 }, L: { w: 12, h: 16 } }, min: { w: 5, h: 6 } },
  notifications: { title: "Уведомления", description: "Лента уведомлений Сакуры", category: "assistant",
                   singleton: true, sizes: { S: { w: 6, h: 8 }, M: { w: 8, h: 12 }, L: { w: 12, h: 16 } },
                   min: { w: 5, h: 6 } },
  "focus-timer": { title: "Фокус-таймер", description: "Работа 25 минут, отдых 5", category: "assistant",
                   singleton: false, sizes: { S: { w: 6, h: 6 }, M: { w: 8, h: 8 }, L: { w: 10, h: 10 } },
                   min: { w: 5, h: 5 } },
  "quick-actions": { title: "Быстрые действия", description: "Скриншот, фокус, микрофон, игровой режим",
                     category: "system", singleton: true,
                     sizes: { S: { w: 6, h: 6 }, M: { w: 9, h: 8 }, L: { w: 12, h: 8 } }, min: { w: 5, h: 5 } },
};
export const WIDGET_TYPES = Object.keys(CATALOG) as WidgetType[];

export interface WidgetItem {
  id: string;
  type: WidgetType;
  x: number;
  y: number;
  w: number;
  h: number;
  locked?: boolean;
  collapsed?: boolean;
  settings?: Record<string, unknown>;
}
export type Layouts = Record<Breakpoint, WidgetItem[]>;
export interface Page { id: string; name: string; breakpoints: Layouts }
export interface Board { version: 2; active_page: string; pages: Page[] }

// ── геометрия ──────────────────────────────────────────────────────────
const hits = (a: Pick<WidgetItem, "x" | "y" | "w" | "h">, b: Pick<WidgetItem, "x" | "y" | "w" | "h">) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export const bottom = (items: WidgetItem[]) => items.reduce((m, it) => Math.max(m, it.y + it.h), 0);

/** Раздвинуть перекрытия: сверху вниз, мешающий опускается под соседа. */
export function resolveCollisions(items: WidgetItem[]): WidgetItem[] {
  const placed: WidgetItem[] = [];
  for (const it of [...items].sort((a, b) => a.y - b.y || a.x - b.x)) {
    const cur = { ...it };
    let hit = placed.find((p) => hits(cur, p));
    while (hit) {
      cur.y = hit.y + hit.h;
      hit = placed.find((p) => hits(cur, p));
    }
    placed.push(cur);
  }
  return items.map((it) => placed.find((p) => p.id === it.id)!);
}

/** Первая свободная позиция для w×h: построчно сверху, слева направо. */
export function firstFree(items: WidgetItem[], w: number, h: number, cols: number): { x: number; y: number } {
  const ww = Math.min(w, cols);
  for (let y = 0; y <= bottom(items); y++) {
    for (let x = 0; x + ww <= cols; x++) {
      if (!items.some((it) => hits({ x, y, w: ww, h }, it))) return { x, y };
    }
  }
  return { x: 0, y: bottom(items) };
}

/** Размер типа для точки адаптивности (sizes заданы для lg). */
export function sizeFor(type: WidgetType, size: Size, bp: Breakpoint): { w: number; h: number } {
  const meta = CATALOG[type];
  const base = meta.sizes[size];
  if (bp === "lg") return base;
  if (bp === "sm") return { w: 1, h: base.h };
  return { w: Math.max(Math.ceil(meta.min.w / 2), Math.ceil(base.w / 2)), h: base.h };
}

export function minFor(type: WidgetType, bp: Breakpoint): { w: number; h: number } {
  const m = CATALOG[type].min;
  return bp === "lg" ? m : bp === "sm" ? { w: 1, h: m.h } : { w: Math.min(COLS.md, Math.ceil(m.w / 2)), h: m.h };
}

/** Привести элемент к сетке точки: в пределах колонок, не меньше минимума. */
export function clampItem(it: WidgetItem, bp: Breakpoint): WidgetItem {
  const cols = COLS[bp];
  const min = minFor(it.type, bp);
  const max = CATALOG[it.type].max;
  let w = Math.min(cols, Math.max(min.w, Math.round(it.w)));
  let h = Math.max(it.collapsed ? COLLAPSED_ROWS : min.h, Math.round(it.h));
  if (max && bp === "lg") { w = Math.min(w, max.w); h = Math.min(h, max.h); }
  return { ...it, w, h, x: Math.min(cols - w, Math.max(0, Math.round(it.x))), y: Math.max(0, Math.round(it.y)) };
}

/** Раскладка md/sm из lg: md — колонки пополам, sm — столбиком в порядке «сверху вниз, слева направо». */
export function deriveLayout(lg: WidgetItem[], bp: Breakpoint): WidgetItem[] {
  if (bp === "lg") return lg;
  const order = [...lg].sort((a, b) => a.y - b.y || a.x - b.x);
  if (bp === "sm") {
    let y = 0;
    return order.map((it) => { const out = { ...it, x: 0, w: 1, y }; y += it.h; return out; });
  }
  return resolveCollisions(order.map((it) => clampItem({ ...it, x: Math.floor(it.x / 2), w: Math.ceil(it.w / 2) }, "md")));
}

// ── id ─────────────────────────────────────────────────────────────────
let seq = 0;
export function newId(type: string): string {
  seq += 1;
  return `${type}-${Date.now().toString(36)}${seq.toString(36)}`;
}

// ── раскладки по умолчанию и пресеты ────────────────────────────────────
type Spec = [WidgetType, number, number, number, number]; // type, x, y, w, h (lg)
const PRESET_SPECS: Record<string, Spec[]> = {
  // «Работа» — набросок владельца (см. board.test: совпадение ±10 px)
  work: [["system", 0, 0, 9, 16], ["video", 9, 0, 15, 16], ["window", 0, 16, 24, 11], ["music", 0, 27, 24, 4]],
  games: [["window", 0, 0, 16, 16], ["system", 16, 0, 8, 16], ["quick-actions", 0, 16, 12, 8],
          ["notifications", 12, 16, 12, 8], ["music", 0, 24, 24, 4]],
  media: [["video", 0, 0, 24, 22], ["music", 0, 22, 24, 4]],
  minimal: [["today", 0, 0, 8, 8], ["music", 0, 8, 24, 4]],
};
export const PRESETS: Record<string, string> = { minimal: "Минимум", work: "Работа", games: "Игры", media: "Медиа" };

export function presetLayouts(preset: keyof typeof PRESET_SPECS | string): Layouts {
  const specs = PRESET_SPECS[preset] ?? PRESET_SPECS.work!;
  const lg = specs.map(([type, x, y, w, h]) => ({ id: newIdStable(preset, type), type, x, y, w, h }));
  return { lg, md: deriveLayout(lg, "md"), sm: deriveLayout(lg, "sm") };
}

// Стабильные id для раскладок по умолчанию: удобно для тестов и сравнения с файлом.
const newIdStable = (preset: string, type: string) => `${type}-${preset}`;

export function defaultBoard(): Board {
  const pages: Page[] = [
    { id: "work", name: "Работа", breakpoints: presetLayouts("work") },
    { id: "games", name: "Игры", breakpoints: presetLayouts("games") },
    { id: "media", name: "Медиа", breakpoints: presetLayouts("media") },
  ];
  return { version: 2, active_page: "work", pages };
}

// ── миграция и валидация ─────────────────────────────────────────────────
const V1_TYPES: Record<string, WidgetType> = { system: "system", video: "video", app: "window", music: "music" };

/** v1 (prefs.layout: [{i, x, y, w, h}], одна страница, одна сетка) → v2: страница «Работа» + «Игры», «Медиа». */
export function migrateV1(layout: unknown): Board {
  const board = defaultBoard();
  if (!Array.isArray(layout)) return board;
  const lg: WidgetItem[] = [];
  for (const raw of layout) {
    const o = raw as Record<string, unknown> | null;
    const type = o && typeof o.i === "string" ? V1_TYPES[o.i] : undefined;
    if (!o || !type || lg.some((it) => it.type === type)) continue;
    lg.push(clampItem({ id: `${type}-work`, type, x: Number(o.x) || 0, y: Number(o.y) || 0,
                        w: Number(o.w) || 1, h: Number(o.h) || 1 }, "lg"));
  }
  const fixed = resolveCollisions(lg);
  board.pages[0] = { ...board.pages[0]!, breakpoints: { lg: fixed, md: deriveLayout(fixed, "md"), sm: deriveLayout(fixed, "sm") } };
  return board;
}

function validItem(raw: unknown, bp: Breakpoint, seen: Set<string>): WidgetItem | null {
  const o = raw as Record<string, unknown> | null;
  if (!o || typeof o !== "object") return null;
  const type = o.type as WidgetType;
  if (!(type in CATALOG)) return null; // неизвестные виджеты отбрасываются
  let id = typeof o.id === "string" && o.id ? o.id.slice(0, 64) : newId(type);
  if (seen.has(id)) id = newId(type);
  seen.add(id);
  const nums = ["x", "y", "w", "h"].map((k) => Number(o[k]));
  if (nums.some((n) => !Number.isFinite(n))) return null;
  const [x, y, w, h] = nums as [number, number, number, number];
  const item: WidgetItem = { id, type, x, y, w, h };
  if (o.locked === true) item.locked = true;
  if (o.collapsed === true) item.collapsed = true;
  if (o.settings && typeof o.settings === "object" && !Array.isArray(o.settings)) {
    const text = JSON.stringify(o.settings);
    if (text.length <= 20_000) item.settings = o.settings as Record<string, unknown>;
  }
  return clampItem(item, bp);
}

/** Валидация: неизвестное отбрасывается, singleton — одна копия, выход за сетку и перекрытия
 *  исправляются, недостающие точки адаптивности выводятся из lg, обязательные виджеты добавляются. */
export function validateBoard(raw: unknown, required: WidgetType[] = []): Board {
  const o = raw as Record<string, unknown> | null;
  if (!o || typeof o !== "object" || o.version !== 2 || !Array.isArray(o.pages)) return defaultBoard();
  const pages: Page[] = [];
  const pageIds = new Set<string>();
  for (const rp of o.pages.slice(0, 20)) {
    const p = rp as Record<string, unknown> | null;
    if (!p || typeof p !== "object") continue;
    let id = typeof p.id === "string" && p.id ? p.id.slice(0, 64) : newId("page");
    if (pageIds.has(id)) id = newId("page");
    pageIds.add(id);
    const name = (typeof p.name === "string" && p.name.trim() ? p.name.trim() : "Страница").slice(0, 40);
    const bps = (p.breakpoints ?? {}) as Record<string, unknown>;
    const seen = new Set<string>();
    const fix = (bp: Breakpoint, list: unknown): WidgetItem[] | null => {
      if (!Array.isArray(list)) return null;
      const out: WidgetItem[] = [];
      for (const r of list) {
        const it = validItem(r, bp, seen);
        if (!it) continue;
        if (CATALOG[it.type].singleton && out.some((x) => x.type === it.type)) continue;
        out.push(it);
      }
      return resolveCollisions(out);
    };
    let lg = fix("lg", bps.lg) ?? [];
    for (const t of required) {
      if (!lg.some((it) => it.type === t)) {
        const s = sizeFor(t, "M", "lg");
        lg = [...lg, { id: newId(t), type: t, ...firstFree(lg, s.w, s.h, COLS.lg), ...s }];
      }
    }
    seen.clear();
    lg.forEach((it) => seen.add(it.id));
    const sync = (bp: Breakpoint) => {
      const own = fix(bp, bps[bp]);
      const ids = new Set(lg.map((it) => it.id));
      // Точка без раскладки или с другим набором виджетов — пересчитывается из lg.
      if (!own || own.length !== lg.length || own.some((it) => !ids.has(it.id))) return deriveLayout(lg, bp);
      return own;
    };
    seen.clear();
    const md = sync("md");
    seen.clear();
    const sm = sync("sm");
    pages.push({ id, name, breakpoints: { lg, md, sm } });
  }
  if (!pages.length) return defaultBoard();
  const active = typeof o.active_page === "string" && pages.some((p) => p.id === o.active_page) ? o.active_page : pages[0]!.id;
  return { version: 2, active_page: active, pages };
}

// ── операции над страницей (во всех точках адаптивности сразу) ──────────
export function getPage(b: Board, pageId = b.active_page): Page {
  return b.pages.find((p) => p.id === pageId) ?? b.pages[0]!;
}

function mapPage(b: Board, pageId: string, fn: (p: Page) => Page): Board {
  return { ...b, pages: b.pages.map((p) => (p.id === pageId ? fn(p) : p)) };
}

function mapItems(p: Page, fn: (items: WidgetItem[], bp: Breakpoint) => WidgetItem[]): Page {
  return { ...p, breakpoints: { lg: fn(p.breakpoints.lg, "lg"), md: fn(p.breakpoints.md, "md"), sm: fn(p.breakpoints.sm, "sm") } };
}

export function canAdd(b: Board, type: WidgetType, pageId = b.active_page): boolean {
  return !CATALOG[type].singleton || !getPage(b, pageId).breakpoints.lg.some((it) => it.type === type);
}

/** Добавить виджет в первую свободную позицию каждой точки (или в указанную позицию на bp). */
export function addWidgetTo(b: Board, type: WidgetType, size: Size = "M",
                            at?: { bp: Breakpoint; x: number; y: number }, pageId = b.active_page): { board: Board; id: string | null } {
  if (!canAdd(b, type, pageId)) return { board: b, id: null };
  const id = newId(type);
  const board = mapPage(b, pageId, (p) => mapItems(p, (items, bp) => {
    const s = sizeFor(type, size, bp);
    const pos = at && at.bp === bp ? { x: at.x, y: at.y } : firstFree(items, s.w, s.h, COLS[bp]);
    return resolveCollisions([...items, clampItem({ id, type, ...pos, ...s }, bp)]);
  }));
  return { board, id };
}

export interface Removed { pageId: string; items: Record<Breakpoint, WidgetItem> }

export function removeWidgetFrom(b: Board, id: string, pageId = b.active_page): { board: Board; removed: Removed | null } {
  const page = getPage(b, pageId);
  const items = {} as Record<Breakpoint, WidgetItem>;
  for (const bp of BP_ORDER) {
    const it = page.breakpoints[bp].find((x) => x.id === id);
    if (!it) return { board: b, removed: null };
    items[bp] = it;
  }
  return { board: mapPage(b, pageId, (p) => mapItems(p, (list) => list.filter((x) => x.id !== id))),
           removed: { pageId, items } };
}

/** Отмена удаления: виджет возвращается на прежнее место (мешающие сдвигаются). */
export function restoreWidget(b: Board, r: Removed): Board {
  if (!b.pages.some((p) => p.id === r.pageId)) return b;
  return mapPage(b, r.pageId, (p) => mapItems(p, (list, bp) =>
    list.some((x) => x.id === r.items[bp].id) ? list : resolveCollisions([r.items[bp], ...list])));
}

export function duplicateWidget(b: Board, id: string, pageId = b.active_page): { board: Board; id: string | null } {
  const page = getPage(b, pageId);
  const src = page.breakpoints.lg.find((x) => x.id === id);
  if (!src || CATALOG[src.type].singleton) return { board: b, id: null };
  const copy = newId(src.type);
  return {
    id: copy,
    board: mapPage(b, pageId, (p) => mapItems(p, (list, bp) => {
      const s = list.find((x) => x.id === id)!;
      const pos = firstFree(list, s.w, s.h, COLS[bp]);
      return [...list, { ...s, id: copy, ...pos, locked: false, settings: s.settings ? { ...s.settings } : undefined }];
    })),
  };
}

export function patchWidget(b: Board, id: string, patch: Partial<Pick<WidgetItem, "locked" | "collapsed" | "settings">>,
                            pageId = b.active_page): Board {
  return mapPage(b, pageId, (p) => mapItems(p, (list, bp) => resolveCollisions(list.map((x) => {
    if (x.id !== id) return x;
    const next = { ...x, ...patch };
    // Свернуть до заголовка: высота запоминается (на каждой точке своя) и возвращается при разворачивании.
    if (patch.collapsed === true && !x.collapsed) {
      next.settings = { ...x.settings, expandedH: x.h };
      next.h = COLLAPSED_ROWS;
    }
    if (patch.collapsed === false && x.collapsed) next.h = Number(x.settings?.expandedH) || sizeFor(x.type, "M", bp).h;
    return clampItem(next, bp);
  }))));
}

/** «Сбросить виджет»: размер M и первая свободная позиция (на всех точках). */
export function resetWidget(b: Board, id: string, pageId = b.active_page): Board {
  return mapPage(b, pageId, (p) => mapItems(p, (list, bp) => {
    const it = list.find((x) => x.id === id);
    if (!it) return list;
    const rest = list.filter((x) => x.id !== id);
    const s = sizeFor(it.type, "M", bp);
    return [...rest, clampItem({ ...it, ...s, ...firstFree(rest, s.w, s.h, COLS[bp]), collapsed: false }, bp)];
  }));
}

/** «Сбросить раскладку страницы»: пресет по имени страницы (Работа/Игры/Медиа), иначе «Работа». */
export function resetPage(b: Board, pageId = b.active_page): Board {
  const page = getPage(b, pageId);
  const preset = Object.entries(PRESETS).find(([, n]) => n === page.name)?.[0] ?? "work";
  return mapPage(b, pageId, (p) => ({ ...p, breakpoints: presetLayouts(preset) }));
}

/** Alt+стрелки — сдвиг, Alt+Shift+стрелки — размер (на текущей точке адаптивности). */
export function nudgeWidget(b: Board, id: string, bp: Breakpoint, dx: number, dy: number, resize: boolean,
                            pageId = b.active_page): Board {
  return mapPage(b, pageId, (p) => ({
    ...p,
    breakpoints: {
      ...p.breakpoints,
      [bp]: resolveCollisions(p.breakpoints[bp].map((x) => {
        if (x.id !== id || x.locked) return x;
        return clampItem(resize ? { ...x, w: x.w + dx, h: x.h + dy } : { ...x, x: x.x + dx, y: x.y + dy }, bp);
      }).sort((a, c) => (a.id === id ? -1 : c.id === id ? 1 : 0))),
    },
  }));
}

/** Раскладка точки после перетаскивания/ресайза в сетке. */
export function setLayout(b: Board, bp: Breakpoint, items: Pick<WidgetItem, "id" | "x" | "y" | "w" | "h">[],
                          pageId = b.active_page): Board {
  return mapPage(b, pageId, (p) => ({
    ...p,
    breakpoints: {
      ...p.breakpoints,
      [bp]: p.breakpoints[bp].map((x) => {
        const n = items.find((i) => i.id === x.id);
        return n ? clampItem({ ...x, x: n.x, y: n.y, w: n.w, h: n.h }, bp) : x;
      }),
    },
  }));
}

// ── страницы ─────────────────────────────────────────────────────────────
export function addPage(b: Board, name: string, preset = "minimal"): Board {
  if (b.pages.length >= 9) return b; // Ctrl+1..9
  const id = newId("page");
  return { ...b, active_page: id, pages: [...b.pages, { id, name: name.trim().slice(0, 40) || "Страница", breakpoints: presetLayouts(preset) }] };
}

export function renamePage(b: Board, pageId: string, name: string): Board {
  const n = name.trim().slice(0, 40);
  return n ? mapPage(b, pageId, (p) => ({ ...p, name: n })) : b;
}

export function deletePage(b: Board, pageId: string): Board {
  if (b.pages.length <= 1) return b;
  const pages = b.pages.filter((p) => p.id !== pageId);
  return { ...b, pages, active_page: b.active_page === pageId ? pages[0]!.id : b.active_page };
}

export function movePage(b: Board, from: number, to: number): Board {
  if (from === to || from < 0 || to < 0 || from >= b.pages.length || to >= b.pages.length) return b;
  const pages = [...b.pages];
  const [p] = pages.splice(from, 1);
  pages.splice(to, 0, p!);
  return { ...b, pages };
}

export const setActivePage = (b: Board, pageId: string): Board =>
  b.pages.some((p) => p.id === pageId) ? { ...b, active_page: pageId } : b;

/** Страница «Игры» для автопереключения при запуске игры. */
export const gamesPage = (b: Board) => b.pages.find((p) => p.name.toLowerCase() === "игры" || p.id === "games");

/** Высота виджета в строках на всех точках адаптивности («Подогнать виджет под окно»). */
export function setWidgetHeight(b: Board, id: string, h: number, pageId = b.active_page): Board {
  return mapPage(b, pageId, (p) => mapItems(p, (list, bp) =>
    resolveCollisions(list.map((x) => (x.id === id ? clampItem({ ...x, h, collapsed: false }, bp) : x)))));
}

/** Пиксельный прямоугольник элемента lg при ширине доски width (сверка с наброском). */
export function itemRect(it: Pick<WidgetItem, "x" | "y" | "w" | "h">, width = 690) {
  const [mx, my] = MARGIN;
  const colW = (width - mx * (COLS.lg - 1)) / COLS.lg;
  return { left: it.x * (colW + mx), top: it.y * (ROW_HEIGHT + my),
           width: it.w * colW + (it.w - 1) * mx, height: it.h * ROW_HEIGHT + (it.h - 1) * my };
}

/** Высота раскладки в пикселях. */
export function layoutHeight(items: WidgetItem[]): number {
  const rows = bottom(items);
  return rows > 0 ? rows * ROW_HEIGHT + (rows - 1) * MARGIN[1] : 0;
}

/** Точка адаптивности по ширине доски. */
export function breakpointFor(width: number): Breakpoint {
  return width >= BREAKPOINTS.lg ? "lg" : width >= BREAKPOINTS.md ? "md" : "sm";
}

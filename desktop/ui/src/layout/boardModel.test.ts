import { describe, expect, test } from "vitest";

import {
  addPage, addWidgetTo, breakpointFor, itemRect, layoutHeight, type Board, BP_ORDER, CATALOG, COLLAPSED_ROWS, COLS, defaultBoard, deletePage, deriveLayout,
  duplicateWidget, firstFree, gamesPage, getPage, migrateV1, movePage, nudgeWidget, patchWidget, removeWidgetFrom,
  renamePage, resetPage, resetWidget, restoreWidget, setLayout, validateBoard, type WidgetItem,
} from "./boardModel";

const overlap = (items: WidgetItem[]) => items.some((a, i) => items.some((b, j) =>
  i !== j && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h));

const sane = (b: Board) => {
  for (const p of b.pages) for (const bp of BP_ORDER) {
    const items = p.breakpoints[bp];
    expect(overlap(items)).toBe(false);
    for (const it of items) expect(it.x + it.w).toBeLessThanOrEqual(COLS[bp]);
  }
};

// Блоки наброска (кадр 1440x1024) относительно левого верхнего угла доски (350, 104).
const SKETCH: Record<string, { left: number; top: number; width: number; height: number }> = {
  system: { left: 0, top: 0, width: 248, height: 450 },
  video: { left: 268, top: 0, width: 422, height: 450 },
  window: { left: 0, top: 470, width: 690, height: 300 },
  music: { left: 0, top: 790, width: 690, height: 100 },
};

describe("страница «Работа» совпадает с наброском", () => {
  test("±10 px при ширине доски 690", () => {
    for (const it of getPage(defaultBoard()).breakpoints.lg) {
      const r = itemRect(it);
      const sk = SKETCH[it.type]!;
      for (const k of ["left", "top", "width", "height"] as const) expect(Math.abs(r[k] - sk[k])).toBeLessThanOrEqual(10);
    }
  });

  test("помещается в 890 px без прокрутки; музыка не меньше 480×100", () => {
    const h = layoutHeight(getPage(defaultBoard()).breakpoints.lg);
    expect(h).toBeLessThanOrEqual(890);
    expect(h).toBeGreaterThan(880);
    const r = itemRect({ x: 0, y: 0, ...CATALOG.music.min });
    expect(r.width).toBeGreaterThanOrEqual(480);
    expect(r.height).toBeGreaterThanOrEqual(97);
  });

  test("точки адаптивности по ширине доски", () => {
    expect(breakpointFor(690)).toBe("lg");
    expect(breakpointFor(640)).toBe("lg");
    expect(breakpointFor(500)).toBe("md");
    expect(breakpointFor(439)).toBe("sm");
  });
});

describe("раскладка по умолчанию и точки адаптивности", () => {
  test("три страницы, «Работа» — набросок; md и sm без перекрытий", () => {
    const b = defaultBoard();
    expect(b.pages.map((p) => p.name)).toEqual(["Работа", "Игры", "Медиа"]);
    expect(getPage(b).breakpoints.lg.map((it) => [it.type, it.x, it.y, it.w, it.h])).toEqual([
      ["system", 0, 0, 9, 16], ["video", 9, 0, 15, 16], ["window", 0, 16, 24, 11], ["music", 0, 27, 24, 4]]);
    sane(b);
    const sm = getPage(b).breakpoints.sm;
    expect(sm.every((it) => it.x === 0 && it.w === 1)).toBe(true);
    expect(sm.map((it) => it.type)).toEqual(["system", "video", "window", "music"]);
  });

  test("md — колонки пополам", () => {
    const md = deriveLayout(getPage(defaultBoard()).breakpoints.lg, "md");
    expect(md.find((it) => it.type === "video")).toMatchObject({ x: 4, w: 8 });
    expect(overlap(md)).toBe(false);
  });
});

describe("миграция v1 → v2 и валидация", () => {
  test("v1 (system/video/app/music) переносится на страницу «Работа», app → window", () => {
    const b = migrateV1([{ i: "system", x: 15, y: 40, w: 9, h: 16 }, { i: "video", x: 0, y: 0, w: 15, h: 16 },
                         { i: "app", x: 0, y: 32, w: 24, h: 11 }, { i: "music", x: 0, y: 38, w: 24, h: 4 }]);
    expect(b.version).toBe(2);
    expect(getPage(b).breakpoints.lg.map((it) => it.type).sort()).toEqual(["music", "system", "video", "window"]);
    sane(b);
    expect(migrateV1("мусор")).toEqual(defaultBoard());
  });

  test("неизвестные отбрасываются, singleton один, выход за сетку и перекрытия исправляются", () => {
    const raw = { version: 2, active_page: "nope", pages: [{ id: "p", name: "Моя", breakpoints: { lg: [
      { id: "a", type: "music", x: 30, y: 0, w: 2, h: 1 },
      { id: "b", type: "music", x: 0, y: 0, w: 24, h: 4 },
      { id: "c", type: "evil", x: 0, y: 0, w: 1, h: 1 },
      { id: "d", type: "notes", x: 0, y: 0, w: 8, h: 8, settings: { text: "привет" } },
    ] } }] };
    const b = validateBoard(raw);
    const lg = getPage(b).breakpoints.lg;
    expect(lg.map((it) => it.type)).toEqual(["music", "notes"]);
    expect(lg[0]).toMatchObject({ w: 17, h: 4, x: 7 });
    expect(lg[1]!.settings).toEqual({ text: "привет" });
    expect(b.active_page).toBe("p");
    sane(b);
  });

  test("недостающие обязательные добавляются; мусор целиком → раскладка по умолчанию", () => {
    const b = validateBoard({ version: 2, pages: [{ id: "p", name: "X", breakpoints: { lg: [] } }] }, ["music"]);
    expect(getPage(b).breakpoints.lg.map((it) => it.type)).toEqual(["music"]);
    expect(validateBoard({ version: 1 })).toEqual(defaultBoard());
    expect(validateBoard(null)).toEqual(defaultBoard());
  });
});

describe("добавить, убрать, отменить", () => {
  test("добавление в первую свободную позицию на всех точках, singleton не повторяется", () => {
    const { board, id } = addWidgetTo(defaultBoard(), "notes", "S");
    expect(id).toBeTruthy();
    for (const bp of BP_ORDER) expect(getPage(board).breakpoints[bp].some((it) => it.id === id)).toBe(true);
    sane(board);
    expect(addWidgetTo(board, "music").id).toBeNull();
  });

  test("первая свободная позиция", () => {
    const items: WidgetItem[] = [{ id: "a", type: "notes", x: 0, y: 0, w: 12, h: 8 }];
    expect(firstFree(items, 12, 8, 24)).toEqual({ x: 12, y: 0 });
    expect(firstFree(items, 24, 8, 24)).toEqual({ x: 0, y: 8 });
  });

  test("удаление и отмена возвращают виджет на прежнее место", () => {
    const b0 = defaultBoard();
    const video = getPage(b0).breakpoints.lg.find((it) => it.type === "video")!;
    const { board, removed } = removeWidgetFrom(b0, video.id);
    expect(getPage(board).breakpoints.lg.some((it) => it.id === video.id)).toBe(false);
    const back = restoreWidget(board, removed!);
    expect(getPage(back).breakpoints.lg.find((it) => it.id === video.id)).toEqual(video);
    sane(back);
  });

  test("дублирование только не-singleton", () => {
    const { board, id } = addWidgetTo(defaultBoard(), "notes", "S");
    const dup = duplicateWidget(board, id!);
    expect(dup.id).toBeTruthy();
    expect(getPage(dup.board).breakpoints.lg.filter((it) => it.type === "notes")).toHaveLength(2);
    expect(duplicateWidget(board, "music-work").id).toBeNull();
  });
});

describe("закрепить, свернуть, сбросить, клавиатура", () => {
  test("свернуть до заголовка и развернуть обратно", () => {
    const b = patchWidget(defaultBoard(), "video-work", { collapsed: true });
    expect(getPage(b).breakpoints.lg.find((it) => it.id === "video-work")!.h).toBe(COLLAPSED_ROWS);
    const back = patchWidget(b, "video-work", { collapsed: false });
    expect(getPage(back).breakpoints.lg.find((it) => it.id === "video-work")!.h).toBe(16);
  });

  test("закреплённый не сдвигается с клавиатуры; обычный — сдвиг и размер", () => {
    let b = nudgeWidget(defaultBoard(), "music-work", "lg", 0, 2, false);
    expect(getPage(b).breakpoints.lg.find((it) => it.id === "music-work")!.y).toBe(29);
    b = nudgeWidget(b, "system-work", "lg", -1, 0, true);
    expect(getPage(b).breakpoints.lg.find((it) => it.id === "system-work")!.w).toBe(8);
    b = patchWidget(b, "system-work", { locked: true });
    const locked = nudgeWidget(b, "system-work", "lg", 3, 0, false);
    expect(getPage(locked).breakpoints.lg.find((it) => it.id === "system-work")!.x).toBe(0);
    sane(b);
  });

  test("сброс виджета и раскладки страницы", () => {
    let b = setLayout(defaultBoard(), "lg", [{ id: "video-work", x: 0, y: 40, w: 8, h: 8 }]);
    b = resetWidget(b, "video-work");
    expect(getPage(b).breakpoints.lg.find((it) => it.id === "video-work")).toMatchObject(CATALOG.video.sizes.M);
    expect(resetPage(b)).toEqual(defaultBoard());
  });
});

describe("страницы", () => {
  test("добавить, переименовать, переставить, удалить; последняя не удаляется", () => {
    let b = addPage(defaultBoard(), "Учёба", "work");
    expect(b.pages).toHaveLength(4);
    expect(getPage(b).name).toBe("Учёба");
    b = renamePage(b, b.active_page, "  Курс  ");
    expect(getPage(b).name).toBe("Курс");
    b = movePage(b, 3, 0);
    expect(b.pages[0]!.name).toBe("Курс");
    b = deletePage(b, b.pages[0]!.id);
    expect(b.pages.map((p) => p.name)).toEqual(["Работа", "Игры", "Медиа"]);
    let one: Board = { ...b, pages: [b.pages[0]!] };
    one = deletePage(one, one.pages[0]!.id);
    expect(one.pages).toHaveLength(1);
    expect(gamesPage(b)?.name).toBe("Игры");
  });
});

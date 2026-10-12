// Настройки интерфейса этого устройства: доска (страницы и раскладки, layout.json v2), тема, ширина
// чата, замок, подвижность ядра, медиа.
// Хранятся в %LOCALAPPDATA%\Sakura\layout.json по device_id (через preload-мост).
import { createStore, useStore } from "zustand";

import { bridge, type SakuraBridge } from "../bridge";
import { MERGE_PRESETS, MOBILITY, type MergePreset, type Mobility } from "../core-gfx/coreFrame";
import { CAPTURE_MODES, type CaptureMode, FPS, ZOOM } from "../capture/captureLogic";
import { type Board, defaultBoard, migrateV1, validateBoard } from "./boardModel";

export type Theme = "night" | "sketch";
export const THEMES: Record<Theme, string> = { night: "Сакура-ночь", sketch: "Как в наброске" };

export const CHAT = { default: 350, min: 320, maxFraction: 0.6, collapsed: 56 };

interface Persisted {
  theme: Theme;
  /** Доска v2: страницы, у каждой раскладки lg/md/sm. */
  board: Board;
  /** pack — авто-упаковка без перекрытий; free — свободно (виджет не вытесняет соседей). */
  boardMode: "pack" | "free";
  /** Запущена игра → страница «Игры». */
  autoGamePage: boolean;
  chatWidth: number;
  chatCollapsed: boolean;
  locked: boolean;
  mobility: Mobility;
  preset: MergePreset;
  /** Показывать в чате строки результатов команд («Громкость 70%»). */
  showCommandResults: boolean;
  /** Источник панели музыки: приложение Яндекс.Музыки (пульт) или медиатека Сакуры. */
  musicSource: MusicSource;
  /** Стиль панели: как в Яндекс.Музыке или в цветах Сакуры. */
  musicBarStyle: MusicBarStyle;
  /** Видео: вписать целиком (полосы) или заполнить с обрезкой (только локальное видео). */
  videoFit: "fit" | "fill";
  /** Показ окна: базовая частота кадров 1–30. */
  captureFps: number;
  /** Показ окна: режим и масштаб для каждого окна-источника (по названию). */
  captureViews: Record<string, { mode: CaptureMode; zoom: number }>;
}

export type MusicSource = "yandex" | "sakura";
export type MusicBarStyle = "yandex" | "sakura";
const MUSIC_SOURCES: Record<MusicSource, string> = { yandex: "Яндекс.Музыка", sakura: "Медиатека Сакуры" };
const BAR_STYLES: Record<MusicBarStyle, string> = { yandex: "Яндекс", sakura: "Сакура" };
export { BAR_STYLES, MUSIC_SOURCES };

export interface PrefsState extends Persisted {
  deviceId: string | null;
  loaded: boolean;
  /** Режим правки доски (не сохраняется). */
  editing: boolean;

  load(deviceId: string): Promise<void>;
  set<K extends keyof Persisted>(key: K, value: Persisted[K]): void;
  setEditing(on: boolean): void;
  /** Изменить доску чистой операцией из boardModel. */
  updateBoard(fn: (b: Board) => Board): void;
}

const DEFAULTS = (): Persisted => ({
  theme: "night",
  board: defaultBoard(),
  boardMode: "pack",
  autoGamePage: false,
  chatWidth: CHAT.default,
  chatCollapsed: false,
  locked: false,
  mobility: "normal",
  preset: "soft",
  showCommandResults: true,
  musicSource: "yandex",
  musicBarStyle: "yandex",
  videoFit: "fit",
  captureFps: FPS.default,
  captureViews: {},
});

const pick = <T extends string>(v: unknown, allowed: Record<T, unknown>, d: T): T =>
  typeof v === "string" && v in allowed ? (v as T) : d;

/** Сохранённая запись → настройки; всё неизвестное или испорченное заменяется значениями по умолчанию. */
export function parsePersisted(raw: Record<string, unknown> | null): Persisted {
  const d = DEFAULTS();
  if (!raw) return d;
  const w = raw.chatWidth;
  return {
    theme: pick(raw.theme, THEMES, d.theme),
    // v2 — проверка; старая запись (layout v1) — миграция; иначе раскладка по умолчанию.
    board: raw.board ? validateBoard(raw.board) : raw.layout ? migrateV1(raw.layout) : d.board,
    boardMode: raw.boardMode === "free" ? "free" : "pack",
    autoGamePage: raw.autoGamePage === true,
    chatWidth: typeof w === "number" && Number.isFinite(w) ? Math.max(CHAT.min, Math.round(w)) : d.chatWidth,
    chatCollapsed: raw.chatCollapsed === true,
    locked: raw.locked === true,
    mobility: pick(raw.mobility, MOBILITY, d.mobility),
    preset: pick(raw.preset, MERGE_PRESETS, d.preset),
    showCommandResults: raw.showCommandResults !== false,
    musicSource: pick(raw.musicSource, MUSIC_SOURCES, d.musicSource),
    musicBarStyle: pick(raw.musicBarStyle, BAR_STYLES, d.musicBarStyle),
    videoFit: raw.videoFit === "fill" ? "fill" : "fit",
    captureFps: typeof raw.captureFps === "number" ? Math.min(FPS.max, Math.max(FPS.min, Math.round(raw.captureFps))) : d.captureFps,
    captureViews: parseViews(raw.captureViews),
  };
}

function parseViews(raw: unknown): Persisted["captureViews"] {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Persisted["captureViews"] = {};
  for (const [k, v] of Object.entries(raw as Record<string, unknown>).slice(0, 50)) {
    const o = v as { mode?: unknown; zoom?: unknown } | null;
    if (!o || typeof o.mode !== "string" || !(o.mode in CAPTURE_MODES) || typeof o.zoom !== "number") continue;
    out[k.slice(0, 200)] = { mode: o.mode as CaptureMode, zoom: Math.min(ZOOM.max, Math.max(ZOOM.min, o.zoom)) };
  }
  return out;
}

const persisted = (s: PrefsState): Persisted => ({
  theme: s.theme, board: s.board, boardMode: s.boardMode, autoGamePage: s.autoGamePage, chatWidth: s.chatWidth, chatCollapsed: s.chatCollapsed,
  locked: s.locked, mobility: s.mobility, preset: s.preset, showCommandResults: s.showCommandResults,
  musicSource: s.musicSource, musicBarStyle: s.musicBarStyle, videoFit: s.videoFit,
  captureFps: s.captureFps, captureViews: s.captureViews,
});

export function createPrefsStore(api: () => SakuraBridge["layout"], saveDelayMs = 400) {
  const store = createStore<PrefsState>()((set, get) => ({
    ...DEFAULTS(),
    deviceId: null,
    loaded: false,
    editing: false,

    async load(deviceId) {
      let raw: Record<string, unknown> | null = null;
      try {
        raw = await api().get(deviceId);
      } catch {
        // Файл недоступен — работаем с раскладкой по умолчанию.
      }
      set({ ...parsePersisted(raw), deviceId, loaded: true });
    },
    set: (key, value) => set({ [key]: value } as Partial<PrefsState>),
    setEditing: (on) => set({ editing: on && !get().locked }),
    updateBoard: (fn) => {
      const next = fn(get().board);
      if (next !== get().board) set({ board: next });
    },
  }));

  // Сохранение с задержкой: перетаскивание и разделитель чата не пишут файл на каждый кадр.
  let timer: ReturnType<typeof setTimeout> | undefined;
  store.subscribe((s, prev) => {
    // Сама загрузка (prev.loaded = false) и несохраняемые поля (editing) запись не вызывают.
    if (!s.deviceId || !prev.loaded) return;
    if (JSON.stringify(persisted(s)) === JSON.stringify(persisted(prev))) return;
    clearTimeout(timer);
    const id = s.deviceId;
    timer = setTimeout(() => void api().set(id, { ...persisted(store.getState()) }).catch(() => {}), saveDelayMs);
  });
  return store;
}

export type PrefsStore = ReturnType<typeof createPrefsStore>;

export const prefsStore = createPrefsStore(() => bridge().layout);

export function usePrefs<T>(selector: (s: PrefsState) => T): T {
  return useStore(prefsStore, selector);
}

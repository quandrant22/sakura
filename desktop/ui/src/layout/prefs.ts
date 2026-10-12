// Настройки интерфейса этого устройства: раскладка доски, тема, ширина чата, замок, подвижность ядра.
// Хранятся в %LOCALAPPDATA%\Sakura\layout.json по device_id (через preload-мост).
import { createStore, useStore } from "zustand";

import { bridge, type SakuraBridge } from "../bridge";
import { MERGE_PRESETS, MOBILITY, type MergePreset, type Mobility } from "../core-gfx/coreFrame";
import { addWidget, defaultLayout, type LayoutItem, removeWidget, sanitizeLayout, type WidgetId } from "./board";

export type Theme = "night" | "sketch";
export const THEMES: Record<Theme, string> = { night: "Сакура-ночь", sketch: "Как в наброске" };

export const CHAT = { default: 350, min: 320, maxFraction: 0.6, collapsed: 56 };

interface Persisted {
  theme: Theme;
  layout: LayoutItem[];
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
  addWidget(id: WidgetId): void;
  removeWidget(id: WidgetId): void;
  resetLayout(): void;
}

const DEFAULTS = (): Persisted => ({
  theme: "night",
  layout: defaultLayout(),
  chatWidth: CHAT.default,
  chatCollapsed: false,
  locked: false,
  mobility: "normal",
  preset: "soft",
  showCommandResults: true,
  musicSource: "yandex",
  musicBarStyle: "yandex",
  videoFit: "fit",
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
    layout: sanitizeLayout(raw.layout) ?? d.layout,
    chatWidth: typeof w === "number" && Number.isFinite(w) ? Math.max(CHAT.min, Math.round(w)) : d.chatWidth,
    chatCollapsed: raw.chatCollapsed === true,
    locked: raw.locked === true,
    mobility: pick(raw.mobility, MOBILITY, d.mobility),
    preset: pick(raw.preset, MERGE_PRESETS, d.preset),
    showCommandResults: raw.showCommandResults !== false,
    musicSource: pick(raw.musicSource, MUSIC_SOURCES, d.musicSource),
    musicBarStyle: pick(raw.musicBarStyle, BAR_STYLES, d.musicBarStyle),
    videoFit: raw.videoFit === "fill" ? "fill" : "fit",
  };
}

const persisted = (s: PrefsState): Persisted => ({
  theme: s.theme, layout: s.layout, chatWidth: s.chatWidth, chatCollapsed: s.chatCollapsed,
  locked: s.locked, mobility: s.mobility, preset: s.preset, showCommandResults: s.showCommandResults,
  musicSource: s.musicSource, musicBarStyle: s.musicBarStyle, videoFit: s.videoFit,
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
    addWidget: (id) => set({ layout: addWidget(get().layout, id) }),
    removeWidget: (id) => set({ layout: removeWidget(get().layout, id) }),
    resetLayout: () => set({ layout: defaultLayout() }),
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

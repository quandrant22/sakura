// Доступ к preload-мосту. В браузере/тестах моста нет — возвращаем безопасные заглушки.
export interface CoreConnection {
  port: number;
  token: string;
}

export interface Rect { x: number; y: number; width: number; height: number }

/** Монитор (electron/displays.ts): bounds — логические пиксели, physical — физические (для ядра). */
export interface DisplayInfo {
  id: number;
  label: string;
  primary: boolean;
  bounds: Rect;
  physical: Rect;
  scaleFactor: number;
}

export interface CaptureSource {
  id: string;
  name: string;
  kind: "window" | "screen";
  /** Превью (data URL) — только для списка выбора. */
  thumb: string | null;
  /** Иконка приложения окна (data URL). */
  icon: string | null;
}

export type CoreProcessState = "idle" | "starting" | "running" | "restarting" | "failed" | "external" | "stopped";

export interface SakuraBridge {
  window: {
    minimize(): Promise<void>;
    toggleMaximize(): Promise<boolean>;
    close(): Promise<void>;
    isMaximized(): Promise<boolean>;
    onMaximized(cb: (maximized: boolean) => void): () => void;
  };
  version(): Promise<string>;
  /** layout.json: раскладка, тема и ширина чата по device_id. */
  layout: {
    get(deviceId: string): Promise<Record<string, unknown> | null>;
    set(deviceId: string, entry: Record<string, unknown>): Promise<boolean>;
    /** Сохранить раскладку в файл (диалог); false — отменено. */
    exportFile(json: string): Promise<boolean>;
    /** Выбрать файл раскладки (диалог); текст файла или null. */
    importFile(): Promise<string | null>;
  };
  /** Виджет в отдельном окне. */
  widgets: { popout(type: string, id: string): Promise<void> };
  openLogs(): Promise<string>;
  /** Сохранить переписку в файл (диалог); false — отменено. */
  exportChat(text: string): Promise<boolean>;
  core: {
    connection(): Promise<CoreConnection | null>;
    /** Состояние ядра, запущенного окном; null — ядро запущено отдельно. */
    state(): Promise<CoreProcessState | null>;
    onState(cb: (state: CoreProcessState) => void): () => void;
    openLog(): Promise<void>;
    /** Аварийная остановка по глобальной клавише (PANIC_HOTKEY). */
    onPanic(cb: () => void): () => void;
    /** «Говорить» по глобальной клавише (push-to-talk). */
    onTalk(cb: () => void): () => void;
    /** Сменить сочетание «говорить»; false — занято или неверно. */
    setTalkHotkey(combo: string): Promise<boolean>;
  };
  tray: {
    onAction(cb: (id: string) => void): () => void;
    setState(state: { mic?: boolean; game?: boolean; busy?: boolean }): Promise<void>;
  };
  autostart: { get(): Promise<boolean>; set(enabled: boolean): Promise<boolean> };
  /** Захват окна — только по явному выбору; кадры не пишутся на диск. */
  capture: {
    sources(): Promise<CaptureSource[]>;
    blocklist(): Promise<string[]>;
    select(id: string): Promise<boolean>;
    openMini(id: string, aspect: number): Promise<void>;
    closeMini(): Promise<void>;
    miniSelect(): Promise<void>;
    onMiniClosed(cb: () => void): () => void;
  };
  /** Мониторы. */
  displays: {
    list(): Promise<DisplayInfo[]>;
    onChanged(cb: () => void): () => void;
  };
  /** Сцена — прозрачный оверлей на «экране Сакуры» (рисование, субтитры, игровые реакции). */
  stage: {
    get(): Promise<{ displayId: number | null; enabled: boolean; current: number }>;
    setDisplay(id: number | null): Promise<DisplayInfo | null>;
    setEnabled(on: boolean): Promise<boolean>;
    /** Только из окна сцены: есть что показать — окно видно, нет — спрятано. */
    want(on: boolean): Promise<void>;
    display(): Promise<DisplayInfo | null>;
    onDisplay(cb: (d: DisplayInfo | null) => void): () => void;
  };
  media: {
    openMini(url: string): Promise<void>;
    closeMini(): Promise<void>;
    /** Размер мини-окна видео: S 320×180, M 480×270, L 640×360. */
    miniPreset(preset: "S" | "M" | "L"): Promise<void>;
    onMiniClosed(cb: () => void): () => void;
    setProxy(proxy: string): Promise<void>;
    chooseFolder(): Promise<string | null>;
  };
}

declare global {
  interface Window {
    sakura?: SakuraBridge;
  }
}

// Без Electron (браузер, тесты) раскладка живёт в памяти до перезагрузки страницы.
function memoryLayout(): SakuraBridge["layout"] {
  const mem = new Map<string, Record<string, unknown>>();
  return {
    get: async (id) => mem.get(id) ?? null,
    set: async (id, entry) => { mem.set(id, entry); return true; },
    exportFile: async () => false,
    importFile: async () => null,
  };
}

const fallback: SakuraBridge = {
  window: {
    minimize: async () => {},
    toggleMaximize: async () => false,
    close: async () => {},
    isMaximized: async () => false,
    onMaximized: () => () => {},
  },
  version: async () => "dev",
  layout: memoryLayout(),
  widgets: { popout: async () => {} },
  openLogs: async () => "",
  exportChat: async () => false,
  core: { connection: async () => null, state: async () => null, onState: () => () => {}, openLog: async () => {}, onPanic: () => () => {}, onTalk: () => () => {}, setTalkHotkey: async () => false },
  tray: { onAction: () => () => {}, setState: async () => {} },
  autostart: { get: async () => false, set: async (v) => v },
  capture: {
    sources: async () => [], blocklist: async () => [], select: async () => false, openMini: async () => {},
    closeMini: async () => {}, miniSelect: async () => {}, onMiniClosed: () => () => {},
  },
  displays: { list: async () => [], onChanged: () => () => {} },
  stage: {
    get: async () => ({ displayId: null, enabled: false, current: 0 }), setDisplay: async () => null,
    setEnabled: async (v) => v, want: async () => {}, display: async () => null, onDisplay: () => () => {},
  },
  media: { openMini: async () => {}, closeMini: async () => {}, miniPreset: async () => {}, onMiniClosed: () => () => {}, setProxy: async () => {}, chooseFolder: async () => null },
};

export const bridge = (): SakuraBridge => window.sakura ?? fallback;

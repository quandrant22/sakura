// Доступ к preload-мосту. В браузере/тестах моста нет — возвращаем безопасные заглушки.
export interface CoreConnection {
  port: number;
  token: string;
}

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
  core: { connection(): Promise<CoreConnection | null> };
  tray: {
    onAction(cb: (id: string) => void): () => void;
    setState(state: { mic?: boolean; game?: boolean; busy?: boolean }): Promise<void>;
  };
  autostart: { get(): Promise<boolean>; set(enabled: boolean): Promise<boolean> };
  /** Захват окна — только по явному выбору; кадры не пишутся на диск. */
  capture: {
    sources(): Promise<{ id: string; name: string }[]>;
    blocklist(): Promise<string[]>;
    select(id: string): Promise<boolean>;
    openMini(id: string, aspect: number): Promise<void>;
    closeMini(): Promise<void>;
    miniSelect(): Promise<void>;
    onMiniClosed(cb: () => void): () => void;
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
  core: { connection: async () => null },
  tray: { onAction: () => () => {}, setState: async () => {} },
  autostart: { get: async () => false, set: async (v) => v },
  capture: {
    sources: async () => [], blocklist: async () => [], select: async () => false, openMini: async () => {},
    closeMini: async () => {}, miniSelect: async () => {}, onMiniClosed: () => () => {},
  },
  media: { openMini: async () => {}, closeMini: async () => {}, miniPreset: async () => {}, onMiniClosed: () => () => {}, setProxy: async () => {}, chooseFolder: async () => null },
};

export const bridge = (): SakuraBridge => window.sakura ?? fallback;

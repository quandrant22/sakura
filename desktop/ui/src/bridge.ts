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
  };
  openLogs(): Promise<string>;
  core: { connection(): Promise<CoreConnection | null> };
  tray: {
    onAction(cb: (id: string) => void): () => void;
    setState(state: { mic?: boolean; game?: boolean }): Promise<void>;
  };
  autostart: { get(): Promise<boolean>; set(enabled: boolean): Promise<boolean> };
  media: {
    openMini(url: string): Promise<void>;
    closeMini(): Promise<void>;
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
  openLogs: async () => "",
  core: { connection: async () => null },
  tray: { onAction: () => () => {}, setState: async () => {} },
  autostart: { get: async () => false, set: async (v) => v },
  media: { openMini: async () => {}, closeMini: async () => {}, onMiniClosed: () => () => {}, setProxy: async () => {}, chooseFolder: async () => null },
};

export const bridge = (): SakuraBridge => window.sakura ?? fallback;

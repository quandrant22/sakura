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

const fallback: SakuraBridge = {
  window: {
    minimize: async () => {},
    toggleMaximize: async () => false,
    close: async () => {},
    isMaximized: async () => false,
    onMaximized: () => () => {},
  },
  version: async () => "dev",
  openLogs: async () => "",
  core: { connection: async () => null },
  tray: { onAction: () => () => {}, setState: async () => {} },
  autostart: { get: async () => false, set: async (v) => v },
  media: { openMini: async () => {}, closeMini: async () => {}, onMiniClosed: () => () => {}, setProxy: async () => {}, chooseFolder: async () => null },
};

export const bridge = (): SakuraBridge => window.sakura ?? fallback;

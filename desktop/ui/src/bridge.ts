// Доступ к preload-мосту. В браузере/тестах моста нет — возвращаем безопасные заглушки.
export interface SakuraBridge {
  window: {
    minimize(): Promise<void>;
    toggleMaximize(): Promise<boolean>;
    close(): Promise<void>;
    isMaximized(): Promise<boolean>;
    onMaximized(cb: (maximized: boolean) => void): () => void;
  };
  version(): Promise<string>;
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
};

export const bridge = (): SakuraBridge => window.sakura ?? fallback;

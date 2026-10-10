// Preload-мост: в окно попадает только этот узкий API (contextIsolation, sandbox).
import { contextBridge, ipcRenderer } from "electron";

const api = {
  window: {
    minimize: (): Promise<void> => ipcRenderer.invoke("window:minimize"),
    toggleMaximize: (): Promise<boolean> => ipcRenderer.invoke("window:toggle-maximize"),
    close: (): Promise<void> => ipcRenderer.invoke("window:close"),
    isMaximized: (): Promise<boolean> => ipcRenderer.invoke("window:is-maximized"),
    onMaximized: (cb: (maximized: boolean) => void): (() => void) => {
      const h = (_e: unknown, v: boolean) => cb(v);
      ipcRenderer.on("window:maximized", h);
      return () => ipcRenderer.removeListener("window:maximized", h);
    },
  },
  version: (): Promise<string> => ipcRenderer.invoke("app:version"),
  openLogs: (): Promise<string> => ipcRenderer.invoke("app:open-logs"),
  core: {
    connection: (): Promise<{ port: number; token: string } | null> => ipcRenderer.invoke("core:connection"),
  },
  tray: {
    onAction: (cb: (id: string) => void): (() => void) => {
      const h = (_e: unknown, id: string) => cb(id);
      ipcRenderer.on("tray:action", h);
      return () => ipcRenderer.removeListener("tray:action", h);
    },
    setState: (state: { mic?: boolean; game?: boolean }): Promise<void> => ipcRenderer.invoke("tray:state", state),
  },
  autostart: {
    get: (): Promise<boolean> => ipcRenderer.invoke("autostart:get"),
    set: (enabled: boolean): Promise<boolean> => ipcRenderer.invoke("autostart:set", enabled),
  },
  media: {
    openMini: (url: string): Promise<void> => ipcRenderer.invoke("media:mini-open", url),
    closeMini: (): Promise<void> => ipcRenderer.invoke("media:mini-close"),
    onMiniClosed: (cb: () => void): (() => void) => {
      const h = () => cb();
      ipcRenderer.on("media:mini-closed", h);
      return () => ipcRenderer.removeListener("media:mini-closed", h);
    },
    setProxy: (proxy: string): Promise<void> => ipcRenderer.invoke("media:proxy", proxy),
    chooseFolder: (): Promise<string | null> => ipcRenderer.invoke("media:choose-folder"),
  },
};

contextBridge.exposeInMainWorld("sakura", api);

export type SakuraBridge = typeof api;

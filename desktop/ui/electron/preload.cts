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
};

contextBridge.exposeInMainWorld("sakura", api);

export type SakuraBridge = typeof api;

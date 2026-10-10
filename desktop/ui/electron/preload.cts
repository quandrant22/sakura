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
};

contextBridge.exposeInMainWorld("sakura", api);

export type SakuraBridge = typeof api;

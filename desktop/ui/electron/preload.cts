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
  layout: {
    get: (deviceId: string): Promise<Record<string, unknown> | null> => ipcRenderer.invoke("layout:get", deviceId),
    set: (deviceId: string, entry: Record<string, unknown>): Promise<boolean> => ipcRenderer.invoke("layout:set", deviceId, entry),
    exportFile: (json: string): Promise<boolean> => ipcRenderer.invoke("layout:export", json),
    importFile: (): Promise<string | null> => ipcRenderer.invoke("layout:import"),
  },
  widgets: {
    popout: (type: string, id: string): Promise<void> => ipcRenderer.invoke("widget:popout", type, id),
  },
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
    setState: (state: { mic?: boolean; game?: boolean; busy?: boolean }): Promise<void> => ipcRenderer.invoke("tray:state", state),
  },
  autostart: {
    get: (): Promise<boolean> => ipcRenderer.invoke("autostart:get"),
    set: (enabled: boolean): Promise<boolean> => ipcRenderer.invoke("autostart:set", enabled),
  },
  capture: {
    sources: (): Promise<{ id: string; name: string }[]> => ipcRenderer.invoke("capture:sources"),
    blocklist: (): Promise<string[]> => ipcRenderer.invoke("capture:blocklist"),
    select: (id: string): Promise<boolean> => ipcRenderer.invoke("capture:select", id),
    openMini: (id: string, aspect: number): Promise<void> => ipcRenderer.invoke("capture:mini-open", id, aspect),
    closeMini: (): Promise<void> => ipcRenderer.invoke("capture:mini-close"),
    miniSelect: (): Promise<void> => ipcRenderer.invoke("capture:mini-select"),
    onMiniClosed: (cb: () => void): (() => void) => {
      const h = () => cb();
      ipcRenderer.on("capture:mini-closed", h);
      return () => ipcRenderer.removeListener("capture:mini-closed", h);
    },
  },
  media: {
    openMini: (url: string): Promise<void> => ipcRenderer.invoke("media:mini-open", url),
    closeMini: (): Promise<void> => ipcRenderer.invoke("media:mini-close"),
    miniPreset: (preset: "S" | "M" | "L"): Promise<void> => ipcRenderer.invoke("media:mini-preset", preset),
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

// Главный процесс Electron: одно окно без системной рамки, безопасные настройки.
import { BrowserWindow, app, ipcMain, screen, shell } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const devUrl = process.env.SAKURA_DEV_URL;

let win: BrowserWindow | null = null;

function createWindow(): void {
  // Базовый размер 1536x1024, но не больше рабочей области экрана (1080p с панелью задач).
  const area = screen.getPrimaryDisplay().workAreaSize;
  win = new BrowserWindow({
    width: Math.max(1180, Math.min(1536, area.width)),
    height: Math.max(760, Math.min(1024, area.height)),
    minWidth: 1180,
    minHeight: 760,
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    show: false,
    title: "Sakura",
    webPreferences: {
      preload: path.join(here, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      spellcheck: false,
    },
  });

  win.once("ready-to-show", () => win?.show());
  win.on("maximize", () => win?.webContents.send("window:maximized", true));
  win.on("unmaximize", () => win?.webContents.send("window:maximized", false));
  win.on("closed", () => {
    win = null;
  });

  // Никакой навигации и новых окон внутри приложения; внешние http(s)-ссылки — в браузер.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    if (!devUrl || !url.startsWith(devUrl)) e.preventDefault();
  });

  if (devUrl) void win.loadURL(devUrl);
  else void win.loadFile(path.join(here, "..", "dist", "index.html"));
}

ipcMain.handle("window:minimize", () => win?.minimize());
ipcMain.handle("window:toggle-maximize", () => {
  if (!win) return false;
  if (win.isMaximized()) win.unmaximize();
  else win.maximize();
  return win.isMaximized();
});
ipcMain.handle("window:close", () => win?.close());
ipcMain.handle("window:is-maximized", () => win?.isMaximized() ?? false);
ipcMain.handle("app:version", () => app.getVersion());

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  });
  app.whenReady().then(createWindow);
  app.on("window-all-closed", () => app.quit());
}

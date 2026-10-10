// Главный процесс Electron: одно окно без системной рамки, трей, безопасные настройки.
// С ядром (Python) общается только окно — по локальному API; main лишь читает
// файл с портом и токеном (ui.token) и отдаёт его окну через preload-мост.
import { BrowserWindow, Menu, Tray, app, dialog, ipcMain, nativeImage, screen, session, shell } from "electron";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { pacFor } from "./pac.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const devUrl = process.env.SAKURA_DEV_URL;
const dataDir = path.join(process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local"), "Sakura");
const tokenFile = process.env.SAKURA_UI_TOKEN ?? path.join(dataDir, "ui.token");

let win: BrowserWindow | null = null;
let miniWin: BrowserWindow | null = null;
let tray: Tray | null = null;
let quitting = false;
const trayState = { mic: true, game: false };

function loadPage(target: BrowserWindow, query = ""): Promise<void> {
  if (devUrl) return target.loadURL(devUrl + query);
  return target.loadFile(path.join(here, "..", "dist", "index.html"), { search: query.replace(/^\?/, "") });
}

function createWindow(): BrowserWindow {
  // Базовый размер 1536x1024, но не больше рабочей области экрана (1080p с панелью задач).
  const area = screen.getPrimaryDisplay().workAreaSize;
  const w = new BrowserWindow({
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

  w.on("maximize", () => w.webContents.send("window:maximized", true));
  w.on("unmaximize", () => w.webContents.send("window:maximized", false));
  // Крестик прячет окно в трей; выход — из меню трея.
  w.on("close", (e) => {
    if (!quitting) {
      e.preventDefault();
      w.hide();
    }
  });
  w.on("closed", () => {
    win = null;
  });

  // Никакой навигации и новых окон внутри приложения; внешние http(s)-ссылки — в браузер.
  w.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  w.webContents.on("will-navigate", (e, url) => {
    if (!devUrl || !url.startsWith(devUrl)) e.preventDefault();
  });
  return w;
}

function showWindow(): void {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function buildTrayMenu(): void {
  if (!tray) return;
  const send = (id: string) => win?.webContents.send("tray:action", id);
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Открыть", click: showWindow },
      { label: "Заглушить микрофон", type: "checkbox", checked: !trayState.mic, click: () => send("mic_toggle") },
      { label: "Игровой режим", type: "checkbox", checked: trayState.game, click: () => send("game_mode") },
      { type: "separator" },
      {
        label: "Выход",
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
}

function createTray(): void {
  const icon = nativeImage.createFromPath(path.join(here, "..", "electron", "assets", "tray.png"));
  tray = new Tray(icon);
  tray.setToolTip("Sakura");
  tray.on("click", showWindow);
  buildTrayMenu();
}

// ── IPC ──────────────────────────────────────────────────────────────
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
ipcMain.handle("app:open-logs", () => shell.openPath(path.join(dataDir, "logs")));
ipcMain.handle("core:connection", () => {
  try {
    const data = JSON.parse(fs.readFileSync(tokenFile, "utf-8")) as { port?: unknown; token?: unknown };
    if (typeof data.port === "number" && typeof data.token === "string") {
      return { port: data.port, token: data.token };
    }
  } catch {
    // ядро ещё не запущено — окно покажет «нет связи с ядром» и повторит попытку
  }
  return null;
});
ipcMain.handle("tray:state", (_e, state: { mic?: boolean; game?: boolean }) => {
  if (typeof state.mic === "boolean") trayState.mic = state.mic;
  if (typeof state.game === "boolean") trayState.game = state.game;
  buildTrayMenu();
});
// Автозапуск: Electron пишет в HKCU\...\Run текущего пользователя.
const loginArgs = app.isPackaged ? [] : [app.getAppPath()];
ipcMain.handle("autostart:get", () => app.getLoginItemSettings({ args: loginArgs }).openAtLogin);
ipcMain.handle("autostart:set", (_e, enabled: boolean) => {
  app.setLoginItemSettings({ openAtLogin: Boolean(enabled), path: process.execPath, args: loginArgs });
  return app.getLoginItemSettings({ args: loginArgs }).openAtLogin;
});

// ── Медиа: мини-окно YouTube и прокси только для плеера ──────────────
const LOCAL_PLAYER = /^http:\/\/127\.0\.0\.1:\d+\/youtube\/player\.html\?/;
ipcMain.handle("media:mini-open", (_e, url: string) => {
  if (typeof url !== "string" || !LOCAL_PLAYER.test(url)) return; // только страница нашего плеера
  if (!miniWin) {
    miniWin = new BrowserWindow({
      width: 480, height: 270, minWidth: 320, minHeight: 180, alwaysOnTop: true, title: "Sakura · видео",
      backgroundColor: "#000000", autoHideMenuBar: true,
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
    });
    miniWin.setAlwaysOnTop(true, "floating");
    miniWin.webContents.setWindowOpenHandler(({ url: u }) => {
      if (/^https?:\/\//.test(u)) void shell.openExternal(u);
      return { action: "deny" };
    });
    miniWin.webContents.on("will-navigate", (e) => e.preventDefault());
    miniWin.on("closed", () => {
      miniWin = null;
      win?.webContents.send("media:mini-closed");
    });
  }
  void miniWin.loadURL(url);
  miniWin.showInactive();
});
ipcMain.handle("media:mini-close", () => miniWin?.close());
ipcMain.handle("media:choose-folder", async () => {
  if (!win) return null;
  const r = await dialog.showOpenDialog(win, { properties: ["openDirectory"], title: "Папка медиатеки" });
  return r.canceled ? null : r.filePaths[0] ?? null;
});

// YOUTUBE_PROXY: PAC-скрипт — через прокси только домены YouTube (electron/pac.ts).
ipcMain.handle("media:proxy", async (_e, proxy: string) => {
  const pac = typeof proxy === "string" ? pacFor(proxy) : "";
  await session.defaultSession.setProxy(pac
    ? { pacScript: `data:application/x-ns-proxy-autoconfig;base64,${Buffer.from(pac).toString("base64")}` }
    : { mode: "direct" });
});

// ── Снимки экранов (desktop/ui/scripts/screens): SAKURA_SCREENSHOT_SPECS ──
interface ShotSpec {
  name: string;
  width: number;
  height: number;
  demo: string;
}

async function takeScreenshots(specs: ShotSpec[], outDir: string): Promise<void> {
  fs.mkdirSync(outDir, { recursive: true });
  const w = createWindow();
  w.setMinimumSize(800, 600);
  for (const spec of specs) {
    w.setContentSize(spec.width, spec.height);
    await loadPage(w, `?demo=${spec.demo}`); // demo уже содержит &screen=…
    w.showInactive();
    await new Promise((r) => setTimeout(r, 1500));
    const img = await w.webContents.capturePage();
    fs.writeFileSync(path.join(outDir, `${spec.name}.png`), img.toPNG());
    console.log(`screenshot ${spec.name}.png ${img.getSize().width}x${img.getSize().height}`);
  }
  quitting = true;
  app.quit();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", showWindow);
  app.whenReady().then(async () => {
    const specs = process.env.SAKURA_SCREENSHOT_SPECS;
    if (specs) {
      await takeScreenshots(JSON.parse(specs) as ShotSpec[], process.env.SAKURA_SCREENSHOT_DIR ?? ".");
      return;
    }
    win = createWindow();
    win.once("ready-to-show", () => win?.show());
    createTray();
    await loadPage(win);
  });
  app.on("before-quit", () => {
    quitting = true;
  });
  app.on("window-all-closed", () => {
    if (quitting) app.quit();
  });
}

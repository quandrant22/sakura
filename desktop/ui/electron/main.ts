// Главный процесс Electron: одно окно без системной рамки, трей, безопасные настройки.
// С ядром (Python) общается только окно — по локальному API; main лишь читает
// файл с портом и токеном (ui.token) и отдаёт его окну через preload-мост.
import {
  BrowserWindow, Menu, Tray, app, desktopCapturer, dialog, ipcMain, nativeImage, screen, session, shell,
} from "electron";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CoreSupervisor, coreAutostartEnabled } from "./coreProcess.js";
import { readLayout, writeLayout } from "./layoutFile.js";
import {
  clampToArea, minSize, type Preset, presetSize, readBounds, snapToCorner, VIDEO_ASPECT, writeBounds,
} from "./miniWindow.js";
import { pacFor } from "./pac.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const devUrl = process.env.SAKURA_DEV_URL;
const dataDir = path.join(process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local"), "Sakura");
const tokenFile = process.env.SAKURA_UI_TOKEN ?? path.join(dataDir, "ui.token");
const layoutFile = process.env.SAKURA_LAYOUT_FILE ?? path.join(dataDir, "layout.json");
const miniBoundsFile = path.join(dataDir, "mini_windows.json");
// Корень репозитория (здесь лежит пакет desktop): dist-electron → ui → desktop → корень.
const repoDir = process.env.SAKURA_REPO_DIR ?? path.join(here, "..", "..", "..");
let core: CoreSupervisor | null = null;

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
  // Базовый размер 1440x1024 (кадр наброска), но не больше рабочей области экрана.
  const area = screen.getPrimaryDisplay().workAreaSize;
  const w = new BrowserWindow({
    width: Math.max(1180, Math.min(1440, area.width)),
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
ipcMain.handle("layout:get", (_e, deviceId: unknown) => readLayout(layoutFile, deviceId));
ipcMain.handle("layout:set", (_e, deviceId: unknown, entry: unknown) => writeLayout(layoutFile, deviceId, entry));
ipcMain.handle("layout:export", async (_e, json: unknown) => {
  if (!win || typeof json !== "string" || json.length > 1_000_000) return false;
  const r = await dialog.showSaveDialog(win, { title: "Экспорт раскладки", defaultPath: "sakura-layout.json",
                                               filters: [{ name: "JSON", extensions: ["json"] }] });
  if (r.canceled || !r.filePath) return false;
  fs.writeFileSync(r.filePath, json, "utf-8");
  return true;
});
ipcMain.handle("layout:import", async () => {
  if (!win) return null;
  const r = await dialog.showOpenDialog(win, { title: "Импорт раскладки", properties: ["openFile"],
                                               filters: [{ name: "JSON", extensions: ["json"] }] });
  const file = r.canceled ? undefined : r.filePaths[0];
  if (!file || fs.statSync(file).size > 1_000_000) return null;
  return fs.readFileSync(file, "utf-8"); // разбор и проверка — в окне (validateBoard)
});

// «В отдельное окно»: виджет в своём окне (тот же интерфейс, ?view=widget).
const WIDGET_TYPES = new Set(["music", "video", "window", "system", "scenarios", "today", "server", "notes",
                              "notifications", "focus-timer", "quick-actions"]);
ipcMain.handle("widget:popout", (_e, type: unknown, id: unknown) => {
  if (typeof type !== "string" || !WIDGET_TYPES.has(type) || typeof id !== "string" || id.length > 64) return;
  const w = new BrowserWindow({
    width: 520, height: 420, minWidth: 320, minHeight: 200, title: "Sakura", backgroundColor: "#0a0610",
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(here, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  void loadPage(w, `?view=widget&type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}`);
});
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
// ── Захват окна (виджет «Окно приложения») — только по явному выбору пользователя ──
// Кадры не пишутся на диск и никуда не отправляются; getDisplayMedia получает ровно то окно,
// которое выбрано в интерфейсе (capture:select), иначе запрос отклоняется.
let pendingCaptureId: string | null = null;
let captureMini: BrowserWindow | null = null;
const CAPTURE_ID = /^window:\d+:\d+$/;

ipcMain.handle("capture:sources", async () => {
  const srcs = await desktopCapturer.getSources({ types: ["window"], thumbnailSize: { width: 0, height: 0 } });
  return srcs.map((s) => ({ id: s.id, name: s.name }));
});
ipcMain.handle("capture:blocklist", () => (process.env.WINDOW_BLOCKLIST ?? "").split(",").map((s) => s.trim()).filter(Boolean));
ipcMain.handle("capture:select", (_e, id: string) => {
  pendingCaptureId = typeof id === "string" && CAPTURE_ID.test(id) ? id : null;
  return pendingCaptureId !== null;
});

function installDisplayMediaHandler() {
  session.defaultSession.setDisplayMediaRequestHandler((_req, callback) => {
    const id = pendingCaptureId;
    pendingCaptureId = null;
    if (!id) return callback({});
    void desktopCapturer.getSources({ types: ["window"], thumbnailSize: { width: 0, height: 0 } }).then((srcs) => {
      const src = srcs.find((s) => s.id === id);
      callback(src ? { video: src } : {});
    });
  });
}

// Мини-окно захвата: поверх всех окон, красная рамка (её рисует страница), пропорции источника,
// позиция и размер запоминаются; в игровом режиме прячется.
function saveCaptureBounds() {
  if (captureMini) writeBounds(miniBoundsFile, "window", captureMini.getBounds());
}
ipcMain.handle("capture:mini-open", (_e, id: string, aspect: number) => {
  if (typeof id !== "string" || !CAPTURE_ID.test(id)) return;
  const a = Number.isFinite(aspect) && aspect > 0.2 && aspect < 5 ? aspect : VIDEO_ASPECT;
  captureMini?.close();
  const area = screen.getPrimaryDisplay().workArea;
  const size = presetSize("M", a);
  const saved = readBounds(miniBoundsFile, "window");
  const b = clampToArea(saved ?? { ...size, x: area.x + 24, y: area.y + area.height - size.height - 24 }, area, a);
  const min = minSize(a);
  captureMini = new BrowserWindow({
    ...b, minWidth: min.width, minHeight: min.height, frame: false, alwaysOnTop: true, title: "Sakura · окно",
    backgroundColor: "#000000", show: !trayState.game,
    webPreferences: { preload: path.join(here, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  captureMini.setAspectRatio(a);
  captureMini.setAlwaysOnTop(true, "floating");
  captureMini.on("moved", () => {
    if (!captureMini) return;
    const cur = captureMini.getBounds();
    const snapped = snapToCorner(cur, screen.getDisplayMatching(cur).workArea);
    if (snapped.x !== cur.x || snapped.y !== cur.y) captureMini.setBounds(snapped);
    saveCaptureBounds();
  });
  captureMini.on("resized", saveCaptureBounds);
  captureMini.webContents.on("before-input-event", (ev, input) => {
    if (input.type === "keyDown" && input.key === "Escape") { ev.preventDefault(); captureMini?.close(); }
  });
  captureMini.on("closed", () => {
    captureMini = null;
    win?.webContents.send("capture:mini-closed");
  });
  pendingCaptureId = id; // мини-окно само запросит getDisplayMedia этого окна
  void loadPage(captureMini, `?view=capture-mini&source=${encodeURIComponent(id)}`);
});
ipcMain.handle("capture:mini-close", () => captureMini?.close());
ipcMain.handle("capture:mini-select", (e) => {
  // Повторный запрос кадра из мини-окна (после перезагрузки страницы) — только для его же источника.
  if (captureMini && e.sender === captureMini.webContents) {
    const q = new URL(e.sender.getURL()).searchParams.get("source");
    pendingCaptureId = q && CAPTURE_ID.test(q) ? q : null;
  }
});

ipcMain.handle("tray:state", (_e, state: { mic?: boolean; game?: boolean }) => {
  if (typeof state.mic === "boolean") trayState.mic = state.mic;
  if (typeof state.game === "boolean") {
    trayState.game = state.game;
    // Игровой режим прячет мини-окно захвата, выход из него — возвращает.
    if (captureMini) { if (state.game) captureMini.hide(); else captureMini.showInactive(); }
  }
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
// «Окно поверх всех»: безрамочное, пропорции 16:9 (+16 px полосы перетаскивания над плеером),
// минимум 240×135, пресеты S/M/L, привязка к углам, позиция и размер запоминаются, Esc закрывает.
const MINI_BAR = 16;
function saveMiniBounds() {
  if (!miniWin) return;
  const b = miniWin.getBounds();
  writeBounds(miniBoundsFile, "video", { ...b, height: b.height - MINI_BAR });
}
ipcMain.handle("media:mini-open", (_e, url: string) => {
  if (typeof url !== "string" || !LOCAL_PLAYER.test(url)) return; // только страница нашего плеера
  if (!miniWin) {
    const area = screen.getPrimaryDisplay().workArea;
    const saved = readBounds(miniBoundsFile, "video");
    const size = presetSize("M");
    const b = clampToArea(saved ?? { ...size, x: area.x + area.width - size.width - 24, y: area.y + area.height - size.height - 24 },
                          area);
    const min = minSize();
    miniWin = new BrowserWindow({
      ...b, height: b.height + MINI_BAR, minWidth: min.width, minHeight: min.height + MINI_BAR,
      frame: false, alwaysOnTop: true, title: "Sakura · видео", backgroundColor: "#000000", autoHideMenuBar: true,
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
    });
    miniWin.setAspectRatio(VIDEO_ASPECT, { width: 0, height: MINI_BAR });
    miniWin.setAlwaysOnTop(true, "floating");
    miniWin.on("moved", () => {
      if (!miniWin) return;
      const cur = miniWin.getBounds();
      const snapped = snapToCorner(cur, screen.getDisplayMatching(cur).workArea);
      if (snapped.x !== cur.x || snapped.y !== cur.y) miniWin.setBounds(snapped);
      saveMiniBounds();
    });
    miniWin.on("resized", saveMiniBounds);
    miniWin.webContents.on("before-input-event", (ev, input) => {
      if (input.type === "keyDown" && input.key === "Escape") { ev.preventDefault(); miniWin?.close(); }
    });
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
  void miniWin.loadURL(url.includes("chrome=1") ? url : `${url}&chrome=1`);
  miniWin.showInactive();
});
ipcMain.handle("media:mini-close", () => miniWin?.close());
ipcMain.handle("media:mini-preset", (_e, preset: Preset) => {
  if (!miniWin || !["S", "M", "L"].includes(preset)) return;
  const b = miniWin.getBounds();
  const size = presetSize(preset);
  miniWin.setBounds({ ...b, width: size.width, height: size.height + MINI_BAR });
  saveMiniBounds();
});
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

// SAKURA_E2E — сквозные тесты Playwright рядом с рабочим окном: без запрета второго экземпляра.
if (!process.env.SAKURA_E2E && !app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", showWindow);
  app.whenReady().then(async () => {
    const specs = process.env.SAKURA_SCREENSHOT_SPECS;
    if (specs) {
      await takeScreenshots(JSON.parse(specs) as ShotSpec[], process.env.SAKURA_SCREENSHOT_DIR ?? ".");
      return;
    }
    // SAKURA_CORE_AUTOSTART=1 — ядро запускается вместе с окном (Python — SAKURA_PYTHON).
    if (coreAutostartEnabled(process.env)) {
      core = new CoreSupervisor({
        python: process.env.SAKURA_PYTHON ?? (process.platform === "win32" ? "python.exe" : "python3"),
        cwd: repoDir,
        logDir: path.join(dataDir, "logs"),
        tokenFile,
        log: (line) => console.log(`[core] ${line}`),
      });
      core.start();
      // Окно не ждёт ядро: до готовности оно само покажет «нет связи с ядром» и переподключится.
      void core.waitReady().then((ok) => console.log(`[core] ${ok ? "готово" : "не ответило вовремя"}`));
    }
    installDisplayMediaHandler();
    win = createWindow();
    win.once("ready-to-show", () => win?.show());
    createTray();
    await loadPage(win);
  });
  app.on("before-quit", () => {
    quitting = true;
    core?.stop();
  });
  app.on("window-all-closed", () => {
    if (quitting) app.quit();
  });
}

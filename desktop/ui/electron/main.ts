// Главный процесс Electron: одно окно без системной рамки, трей, безопасные настройки.
// С ядром (Python) общается только окно — по локальному API; main лишь читает
// файл с портом и токеном (ui.token) и отдаёт его окну через preload-мост.
import {
  BrowserWindow, Menu, Tray, app, desktopCapturer, dialog, globalShortcut, ipcMain, nativeImage, screen, session, shell,
} from "electron";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { coreAlready, type CoreState, CoreSupervisor, coreAutostartEnabled, pidAlive, readLockPid } from "./coreProcess.js";
import {
  CAPTURE_ID, describeDisplays, type DisplayInfo, pickDisplay, readStagePrefs, type StagePrefs, writeStagePrefs,
} from "./displays.js";
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
const stageFile = path.join(dataDir, "stage.json");
// Корень репозитория (здесь лежит пакет desktop): dist-electron → ui → desktop → корень.
const repoDir = process.env.SAKURA_REPO_DIR ?? path.join(here, "..", "..", "..");
let core: CoreSupervisor | null = null;
// Состояние ядра, запущенного окном (SAKURA_CORE_AUTOSTART); null — ядро запущено отдельно.
let coreState: CoreState | null = null;
const logDir = path.join(dataDir, "logs");
const appIcon = path.join(here, "..", "..", "assets", "sakura.ico");

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
    icon: fs.existsSync(appIcon) ? appIcon : undefined,
    webPreferences: {
      preload: path.join(here, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      spellcheck: false,
      webviewTag: true,
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
      ...(coreState === "failed"
        ? [{ label: "Ядро не запустилось: открыть журнал", click: openCoreLog }] : []),
      { type: "separator" },
      { label: "Выход", click: quitAll },
    ]),
  );
}

// «Говорить» (push-to-talk): глобальная клавиша → окно → listen_now; сочетание — Настройки → Голос.
const DEFAULT_TALK_HOTKEY = "Control+Alt+Space";
let talkHotkey: string | null = null;
function registerTalkHotkey(combo: string): boolean {
  if (talkHotkey) globalShortcut.unregister(talkHotkey);
  talkHotkey = null;
  try {
    if (combo && globalShortcut.register(combo, () => win?.webContents.send("control:talk"))) {
      talkHotkey = combo;
      return true;
    }
  } catch {
    // неверное сочетание — вернём false
  }
  return false;
}

function openCoreLog(): void {
  const log = path.join(logDir, "sakura.log");
  void shell.openPath(fs.existsSync(log) ? log : logDir);
}

function onCoreState(state: CoreState): void {
  coreState = state;
  win?.webContents.send("core:state", state);
  tray?.setToolTip(state === "failed" ? "Sakura — ядро не запустилось" : "Sakura");
  buildTrayMenu();
}

/** «Выход» из трея и `electron . --quit`: закрыть окно, ядро (деревом процессов) и всё остальное. */
function quitAll(): void {
  quitting = true;
  app.quit();
}

function createTray(): void {
  const iconPath = fs.existsSync(appIcon) ? appIcon : path.join(here, "..", "electron", "assets", "tray.png");
  const icon = nativeImage.createFromPath(iconPath);
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
ipcMain.handle("core:state", () => coreState);
ipcMain.handle("talk:set-hotkey", (_e, combo: unknown) => registerTalkHotkey(typeof combo === "string" ? combo : ""));
ipcMain.handle("core:open-log", () => openCoreLog());
ipcMain.handle("layout:get", (_e, deviceId: unknown) => readLayout(layoutFile, deviceId));
ipcMain.handle("layout:set", (_e, deviceId: unknown, entry: unknown) => writeLayout(layoutFile, deviceId, entry));
ipcMain.handle("chat:export", async (_e, text: unknown) => {
  if (!win || typeof text !== "string" || text.length > 20_000_000) return false;
  const r = await dialog.showSaveDialog(win, { title: "Экспорт переписки", defaultPath: "sakura-chat.txt",
                                               filters: [{ name: "Текст", extensions: ["txt"] }, { name: "JSON", extensions: ["json"] }] });
  if (r.canceled || !r.filePath) return false;
  fs.writeFileSync(r.filePath, text, "utf-8");
  return true;
});
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
const THUMB = { width: 320, height: 180 };

// Источники: окна (с превью и иконкой приложения) и мониторы целиком. Превью — только для списка выбора,
// никуда не сохраняются.
ipcMain.handle("capture:sources", async () => {
  const srcs = await desktopCapturer.getSources({ types: ["window", "screen"], thumbnailSize: THUMB, fetchWindowIcons: true });
  const displays = listDisplays();
  return srcs.map((s) => {
    const kind = s.id.startsWith("screen:") ? "screen" : "window";
    const disp = kind === "screen" ? displays.find((d) => String(d.id) === s.display_id) : undefined;
    return {
      id: s.id, kind,
      name: kind === "screen" ? (disp?.label ?? s.name) : s.name,
      thumb: s.thumbnail.isEmpty() ? null : s.thumbnail.toDataURL(),
      icon: s.appIcon && !s.appIcon.isEmpty() ? s.appIcon.resize({ width: 32, height: 32 }).toDataURL() : null,
    };
  });
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
    void desktopCapturer.getSources({ types: ["window", "screen"], thumbnailSize: { width: 0, height: 0 } }).then((srcs) => {
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

ipcMain.handle("tray:state", (_e, state: { mic?: boolean; game?: boolean; busy?: boolean }) => {
  // Индикатор в трее на время действия с компьютером (окна, клавиши, файлы…).
  if (typeof state.busy === "boolean") tray?.setToolTip(state.busy ? "Sakura — выполняю действие с компьютером…" : "Sakura");
  if (typeof state.mic === "boolean") trayState.mic = state.mic;
  if (typeof state.game === "boolean") {
    trayState.game = state.game;
    // Игровой режим прячет мини-окно захвата, выход из него — возвращает.
    if (captureMini) { if (state.game) captureMini.hide(); else captureMini.showInactive(); }
    // Сцена в игре держится поверх (игры поднимают себя наверх).
    if (state.game) applyStageVisibility(); else stopStageTopmost();
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

// ── Мониторы и сцена (оверлей поверх игр и экрана) ─────────────────────
// Сцена — прозрачное окно на весь выбранный монитор: рисование Сакуры (Ink), субтитры её реплик,
// игровые реакции и маленькое ядро. Клики проходят насквозь, фокус не забирает, в Alt+Tab и панели
// задач не видна. Показывается только когда есть что показать: пустое прозрачное окно поверх игры
// заставило бы Windows компоновать кадр игры (лишняя задержка).
// Поверх «настоящего» эксклюзивного полноэкранного режима (старые DX9/DX11 без оптимизаций
// полноэкранного режима) обычное окно не рисуется — для таких игр ядро предлагает включить оптимизации
// или оконный режим без рамки, а сцена переезжает на второй монитор (desktop/core/fullscreen.py).
let stagePrefs: StagePrefs = readStagePrefs(stageFile);
let stageWin: BrowserWindow | null = null;
let stageWanted = false; // страница сцены просит показать окно (есть содержимое)
let stageTopmostTimer: ReturnType<typeof setInterval> | null = null;

function listDisplays(): DisplayInfo[] {
  const dip = process.platform === "win32" ? (r: Electron.Rectangle) => screen.dipToScreenRect(null, r) : undefined;
  return describeDisplays(screen.getAllDisplays(), screen.getPrimaryDisplay().id, dip);
}

function stageDisplay(): Electron.Display {
  return pickDisplay(screen.getAllDisplays(), stagePrefs.displayId, screen.getPrimaryDisplay());
}

function placeStage(): void {
  if (!stageWin) return;
  stageWin.setBounds(stageDisplay().bounds);
}

function createStage(): void {
  if (stageWin || !stagePrefs.enabled) return;
  const d = stageDisplay();
  stageWin = new BrowserWindow({
    ...d.bounds, frame: false, transparent: true, backgroundColor: "#00000000", resizable: false, movable: false,
    minimizable: false, maximizable: false, fullscreenable: false, focusable: false, skipTaskbar: true,
    hasShadow: false, alwaysOnTop: true, show: false, title: "Sakura · сцена",
    ...(process.platform === "win32" ? { type: "toolbar" } : {}),
    webPreferences: { preload: path.join(here, "preload.cjs"), contextIsolation: true, nodeIntegration: false,
                      sandbox: true, backgroundThrottling: false },
  });
  stageWin.setIgnoreMouseEvents(true);
  stageWin.setAlwaysOnTop(true, "screen-saver");
  stageWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  stageWin.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  stageWin.webContents.on("will-navigate", (e) => e.preventDefault());
  stageWin.on("closed", () => {
    stageWin = null;
    stopStageTopmost();
  });
  void loadPage(stageWin, "?view=stage");
}

function destroyStage(): void {
  stopStageTopmost();
  stageWin?.destroy();
  stageWin = null;
}

/** Игры поднимают себя наверх; пока сцена видна в игре — раз в 1.5 с возвращаем её поверх, без фокуса. */
function startStageTopmost(): void {
  if (stageTopmostTimer) return;
  stageTopmostTimer = setInterval(() => {
    if (!stageWin || !stageWin.isVisible()) return;
    stageWin.setAlwaysOnTop(true, "screen-saver");
    stageWin.moveTop();
  }, 1500);
}
function stopStageTopmost(): void {
  if (stageTopmostTimer) clearInterval(stageTopmostTimer);
  stageTopmostTimer = null;
}

function applyStageVisibility(): void {
  if (!stageWin) return;
  if (stageWanted && stagePrefs.enabled) {
    if (!stageWin.isVisible()) stageWin.showInactive();
    stageWin.setAlwaysOnTop(true, "screen-saver");
    stageWin.moveTop();
    if (trayState.game) startStageTopmost();
  } else {
    stopStageTopmost();
    if (stageWin.isVisible()) stageWin.hide();
  }
}

ipcMain.handle("displays:list", () => listDisplays());
ipcMain.handle("stage:get", () => ({ ...stagePrefs, current: stageDisplay().id }));
ipcMain.handle("stage:set-display", (_e, id: unknown) => {
  stagePrefs = { ...stagePrefs, displayId: typeof id === "number" && Number.isFinite(id) ? id : null };
  writeStagePrefs(stageFile, stagePrefs);
  placeStage();
  const d = listDisplays().find((x) => x.id === stageDisplay().id) ?? null;
  stageWin?.webContents.send("stage:display", d);
  return d;
});
ipcMain.handle("stage:set-enabled", (_e, on: unknown) => {
  stagePrefs = { ...stagePrefs, enabled: Boolean(on) };
  writeStagePrefs(stageFile, stagePrefs);
  if (stagePrefs.enabled) createStage();
  else destroyStage();
  return stagePrefs.enabled;
});
ipcMain.handle("stage:want", (e, on: unknown) => {
  if (!stageWin || e.sender !== stageWin.webContents) return;
  stageWanted = Boolean(on);
  applyStageVisibility();
});
ipcMain.handle("stage:display", () => listDisplays().find((x) => x.id === stageDisplay().id) ?? null);
function watchDisplays(): void {
  const onChange = () => {
    placeStage();
    win?.webContents.send("displays:changed");
  };
  screen.on("display-added", onChange);
  screen.on("display-removed", onChange);
  screen.on("display-metrics-changed", onChange);
}

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

// SAKURA_E2E и снимки экранов (ядро не запускают) — рядом с рабочим окном: без запрета второго экземпляра.
if (!process.env.SAKURA_E2E && !process.env.SAKURA_SCREENSHOT_SPECS && !app.requestSingleInstanceLock()) {
  try {
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(path.join(logDir, "electron.log"), `[${new Date().toISOString()}] Single-instance lock rejected (another instance running)\n`);
  } catch {}
  app.quit();
} else {
  // Повторный запуск показывает окно; с --quit — тот же «Выход», что в трее (остановка из скриптов).
  app.on("second-instance", (_e, argv) => {
    try {
      fs.appendFileSync(path.join(logDir, "electron.log"), `[${new Date().toISOString()}] second-instance event: showing window\n`);
    } catch {}
    if (argv.includes("--quit")) {
      quitAll();
    } else {
      showWindow();
    }
  });
  app.whenReady().then(async () => {
    try {
      fs.mkdirSync(logDir, { recursive: true });
      fs.appendFileSync(path.join(logDir, "electron.log"), `[${new Date().toISOString()}] app.whenReady started\n`);
    } catch {}
    const specs = process.env.SAKURA_SCREENSHOT_SPECS;
    if (specs) {
      await takeScreenshots(JSON.parse(specs) as ShotSpec[], process.env.SAKURA_SCREENSHOT_DIR ?? ".");
      return;
    }
    // SAKURA_CORE_AUTOSTART=1 — ядро запускается вместе с окном (Python — SAKURA_PYTHON).
    if (coreAutostartEnabled(process.env)) {
      const lockFile = path.join(dataDir, "core.lock");
      core = new CoreSupervisor({
        // Только SAKURA_PYTHON (venv агента): запасной системный python запустил бы ядро без зависимостей.
        python: process.env.SAKURA_PYTHON ?? "",
        probeExisting: () => coreAlready(lockFile, tokenFile),
        lockOwnerAlive: () => pidAlive(readLockPid(lockFile)),
        cwd: repoDir,
        logDir,
        tokenFile,
        log: (line) => console.log(`[core] ${line}`),
        onState: onCoreState,
      });
      void core.launch();
      // Окно не ждёт ядро: до готовности оно само покажет «нет связи с ядром» и переподключится.
      void core.waitReady().then((ok) => console.log(`[core] ${ok ? "готово" : "не ответило вовремя"}`));
    }
    installDisplayMediaHandler();
    registerTalkHotkey(process.env.PTT_HOTKEY || DEFAULT_TALK_HOTKEY);
    // Аварийная остановка управления ПК: PANIC_HOTKEY (по умолчанию Ctrl+Alt+End) — из любого окна.
    const panicKey = process.env.PANIC_HOTKEY || "Control+Alt+End";
    try {
      if (!globalShortcut.register(panicKey, () => win?.webContents.send("control:panic"))) {
        console.log(`[panic] сочетание ${panicKey} занято другой программой`);
      }
    } catch {
      console.log(`[panic] неверное сочетание PANIC_HOTKEY: ${panicKey}`);
    }
    win = createWindow();
    win.webContents.on("did-fail-load", (_e, code, desc) => {
      try {
        fs.appendFileSync(path.join(logDir, "electron.log"), `[${new Date().toISOString()}] did-fail-load: ${code} ${desc}\n`);
      } catch {}
    });
    win.webContents.on("console-message", (_e, level, message) => {
      if (level >= 2) {
        try {
          fs.appendFileSync(path.join(logDir, "electron.log"), `[${new Date().toISOString()}] [console-${level}] ${message}\n`);
        } catch {}
      }
    });
    win.once("ready-to-show", () => {
      try {
        fs.appendFileSync(path.join(logDir, "electron.log"), `[${new Date().toISOString()}] win ready-to-show\n`);
      } catch {}
      win?.show();
    });
    // Страховка: если ready-to-show не вызвался за 2.5 сек, гарантированно показать окно
    setTimeout(() => {
      if (win && !win.isVisible()) {
        try {
          fs.appendFileSync(path.join(logDir, "electron.log"), `[${new Date().toISOString()}] fallback timeout: showing window\n`);
        } catch {}
        win.show();
      }
    }, 2500);

    createTray();
    watchDisplays();
    createStage();
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

import { X } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Group, Panel, Separator, usePanelRef } from "react-resizable-panels";

import { type CoreClient, WsCoreClient } from "./api/client";
import { DemoClient, type DemoMode } from "./api/demo";
import { BoardBar } from "./board/BoardBar";
import { WidgetBoard } from "./board/WidgetBoard";
import { bridge } from "./bridge";
import { Chat, ChatStrip } from "./components/Chat";
import { CoreFailedBanner } from "./components/CoreFailedBanner";
import { BrowserTaskBanner, ConfirmDialog, ControlBanner } from "./components/ControlSafety";
import { OfflineBanner } from "./components/OfflineBanner";
import { useTalkHotkey } from "./screens/VoiceSection";

function TalkHotkey() {
  useTalkHotkey();
  return null;
}
import { Memory } from "./screens/Memory";
import { Profile } from "./screens/Profile";
import { CoreCard, MenuCard, type Section, SECTION_ORDER } from "./components/LeftColumn";
import { TitleBar } from "./components/TitleBar";
import { CATALOG, gamesPage, getPage, patchWidget, setActivePage, type WidgetType } from "./layout/boardModel";
import { VIEWS } from "./board/registry";
import { CHAT, prefsStore, usePrefs } from "./layout/prefs";
import { MediaProvider } from "./media/MediaContext";
import { Devices } from "./screens/Devices";
import { Scenarios } from "./screens/Scenarios";
import { Settings } from "./screens/Settings";
import { createAppStore, StoreContext, useApp } from "./store";

const DEMO_MODES: DemoMode[] = ["normal", "empty", "offline", "unsupported"];

/** ?demo=normal|empty|offline|unsupported — данные из фикстур (снимки экранов, разработка). */
export function makeClient(search: string): CoreClient {
  const demo = new URLSearchParams(search).get("demo") as DemoMode | null;
  if (demo && DEMO_MODES.includes(demo)) return new DemoClient(demo);
  return new WsCoreClient(() => bridge().core.connection());
}

/** Если ядро не сообщило device_id, раскладка берётся под этим именем. */
const FALLBACK_DEVICE = "local";
const FALLBACK_AFTER_MS = 1500;

function Toast() {
  const toast = useApp((s) => s.toast);
  const dismiss = useApp((s) => s.dismissToast);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(dismiss, 3500);
    return () => clearTimeout(t);
  }, [toast, dismiss]);
  if (!toast) return null;
  return (
    <div role="alert" className={"fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-card border bg-panel2 px-4 py-2 text-sm text-ink shadow-soft " +
      (toast.level === "error" ? "border-accent" : "border-line")}>
      {toast.text}
      <button type="button" aria-label="Закрыть уведомление" onClick={dismiss} className="text-ink-dim hover:text-ink"><X size={14} /></button>
    </div>
  );
}

/** Выключение или перезагрузка через N секунд: обратный отсчёт и «Отмена» (shutdown /a). */
function PowerToast() {
  const power = useApp((s) => s.power);
  const cancel = useApp((s) => s.cancelPower);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!power) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [power]);
  if (!power) return null;
  const left = Math.max(0, Math.ceil((power.until - now) / 1000));
  return (
    <div role="alertdialog" aria-label="Выключение компьютера"
         className="fixed left-1/2 top-24 z-50 flex -translate-x-1/2 items-center gap-4 rounded-card border border-accent bg-panel2 px-5 py-3 text-sm text-ink shadow-soft">
      <span>{power.action === "restart" ? "Перезагрузка" : "Выключение"} через <b className="tabular-nums">{left}</b> с</span>
      <button type="button" onClick={() => void cancel()} autoFocus
              className="rounded-btn bg-accent-grad px-3 py-1.5 text-xs font-medium text-white">Отмена</button>
    </div>
  );
}

const SECTIONS: readonly Section[] = SECTION_ORDER;

// ?screen=devices|scenarios|memory|profile|settings — стартовый экран (снимки экранов, отладка).
function initialSection(): Section {
  const s = new URLSearchParams(window.location.search).get("screen") as Section | null;
  return s && SECTIONS.includes(s) ? s : "home";
}

function useWindowWidth() {
  const [w, setW] = useState(window.innerWidth);
  useEffect(() => {
    const on = () => setW(window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return w;
}

/** Раскладка этого устройства: грузим по device_id, без него — под FALLBACK_DEVICE. */
function usePrefsLoader() {
  const deviceId = useApp((s) => s.settings?.device_id);
  const theme = usePrefs((s) => s.theme);
  useEffect(() => {
    const p = prefsStore.getState();
    // ?theme=sketch — тема для снимков экранов (scripts/screens.mjs пишет во временный layout.json).
    const forced = new URLSearchParams(window.location.search).get("theme");
    const applyForced = () => { if (forced === "night" || forced === "sketch") prefsStore.getState().set("theme", forced); };
    if (deviceId && p.deviceId !== deviceId) void p.load(deviceId).then(applyForced);
    if (deviceId) return;
    const t = setTimeout(() => {
      if (!prefsStore.getState().loaded) void prefsStore.getState().load(FALLBACK_DEVICE).then(applyForced);
    }, FALLBACK_AFTER_MS);
    return () => clearTimeout(t);
  }, [deviceId]);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
}

function Workspace({ section, galleryOpen, onCloseGallery }: { section: Section; galleryOpen: boolean; onCloseGallery(): void }) {
  const winW = useWindowWidth();
  const chatRef = usePanelRef();
  const chatWidth = usePrefs((s) => s.chatWidth);
  const collapsed = usePrefs((s) => s.chatCollapsed);
  const setPref = usePrefs((s) => s.set);

  let screen;
  if (section === "settings") screen = <Settings />;
  else if (section === "devices") screen = <Devices />;
  else if (section === "scenarios") screen = <Scenarios />;
  else if (section === "memory") screen = <Memory />;
  else if (section === "profile") screen = <Profile />;
  else screen = <WidgetBoard galleryOpen={galleryOpen} onCloseGallery={onCloseGallery} />;

  const expand = () => {
    const p = chatRef.current;
    if (!p) return;
    p.expand();
    p.resize(Math.max(CHAT.min, chatWidth));
  };
  // Двойной клик по разделителю — ширина по умолчанию (350 px).
  const reset = () => {
    const p = chatRef.current;
    if (!p) return;
    if (p.isCollapsed()) p.expand();
    p.resize(CHAT.default);
  };

  return (
    <Group orientation="horizontal" className="min-w-0 flex-1">
      <Panel id="main" minSize={300} className="min-w-0">
        {screen}
      </Panel>
      <Separator disableDoubleClick onDoubleClick={reset} aria-label="Ширина чата" title="Потяните, чтобы изменить ширину чата; двойной клик — по умолчанию"
                 className="group flex w-[20px] items-stretch justify-center outline-none">
        <span className="my-6 w-[2px] rounded-full bg-transparent transition-colors group-hover:bg-accent/60 group-focus-visible:bg-accent group-data-[separator=active]:bg-accent" />
      </Separator>
      <Panel id="chat" panelRef={chatRef} defaultSize={collapsed ? CHAT.collapsed : chatWidth}
             minSize={CHAT.min} maxSize={Math.round(winW * CHAT.maxFraction)}
             collapsible collapsedSize={CHAT.collapsed} groupResizeBehavior="preserve-pixel-size"
             onResize={(size) => {
               const isCollapsed = size.inPixels <= CHAT.collapsed + 1;
               if (isCollapsed !== prefsStore.getState().chatCollapsed) setPref("chatCollapsed", isCollapsed);
               if (!isCollapsed) setPref("chatWidth", Math.round(size.inPixels));
             }}>
        {collapsed ? <ChatStrip onExpand={expand} /> : <Chat onCollapse={() => chatRef.current?.collapse()} />}
      </Panel>
    </Group>
  );
}

function Shell() {
  const [section, setSection] = useState<Section>(initialSection);
  const toggleMic = useApp((s) => s.toggleMic);
  const mic = useApp((s) => s.settings?.mic_enabled ?? true);
  const game = useApp((s) => s.gameMode);
  const setGameMode = useApp((s) => s.setGameMode);
  const loaded = usePrefs((s) => s.loaded);
  const setEditing = usePrefs((s) => s.setEditing);
  const updateBoard = usePrefs((s) => s.updateBoard);
  const autoGamePage = usePrefs((s) => s.autoGamePage);
  const [gallery, setGallery] = useState(false);
  usePrefsLoader();

  // Ctrl+1..9 — страница доски (на главной).
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.altKey || e.shiftKey || !/^[1-9]$/.test(e.key) || section !== "home") return;
      const page = prefsStore.getState().board.pages[Number(e.key) - 1];
      if (!page) return;
      e.preventDefault();
      updateBoard((b) => setActivePage(b, page.id));
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [section, updateBoard]);

  // Запущена игра (игровой режим) → страница «Игры», если включено в меню доски.
  useEffect(() => {
    if (!game || !autoGamePage) return;
    updateBoard((b) => { const p = gamesPage(b); return p ? setActivePage(b, p.id) : b; });
  }, [game, autoGamePage, updateBoard]);

  useEffect(() => bridge().tray.onAction((id) => {
    if (id === "mic_toggle") void toggleMic();
    if (id === "game_mode") void setGameMode(!game);
  }), [toggleMic, setGameMode, game]);
  const busy = useApp((s) => s.pcAction);
  useEffect(() => {
    void bridge().tray.setState({ mic, game, busy });
  }, [mic, game, busy]);

  const go = (s: Section) => {
    if (s !== "home") { setEditing(false); setGallery(false); }
    setSection(s);
  };

  // Alt+1…6 — разделы меню (клавиатурная навигация).
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.shiftKey || !/^[1-6]$/.test(e.key)) return;
      e.preventDefault();
      const target = SECTION_ORDER[Number(e.key) - 1];
      if (target) go(target);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg">
      <TitleBar center={section === "home" && loaded ? <BoardBar galleryOpen={gallery} onGallery={() => setGallery(!gallery)} /> : undefined} />
      <CoreFailedBanner />
      <OfflineBanner />
      <ControlBanner />
      <BrowserTaskBanner />
      <ConfirmDialog />
      <TalkHotkey />
      <div className="flex min-h-0 flex-1 gap-gap px-edge pb-edge pt-gap">
        <aside className="flex w-[300px] shrink-0 flex-col gap-gap">
          <CoreCard />
          <MenuCard section={section} onSection={go} />
        </aside>
        {/* Раскладка грузится по device_id — до этого чат и доска не монтируются, чтобы не прыгала ширина. */}
        {loaded ? <Workspace section={section} galleryOpen={gallery} onCloseGallery={() => setGallery(false)} />
          : <div className="flex-1" aria-busy="true" />}
      </div>
      <Toast />
      <PowerToast />
    </div>
  );
}

/** Сторы ядра и медиа — общие для главного окна и окна отдельного виджета. */
export function Providers({ client, children }: { client?: CoreClient; children: ReactNode }) {
  const core = useMemo(() => client ?? makeClient(window.location.search), [client]);
  const store = useMemo(() => createAppStore(core), [core]);
  useEffect(() => store.getState().init(), [store]);
  return (
    <StoreContext.Provider value={store}>
      <MediaProvider client={core}>{children}</MediaProvider>
    </StoreContext.Provider>
  );
}

/** «В отдельное окно»: один виджет на всё окно (?view=widget&type=…&id=…), настройки — в той же раскладке. */
function WidgetWindow({ type, id }: { type: WidgetType; id: string }) {
  usePrefsLoader();
  const board = usePrefs((s) => s.board);
  const loaded = usePrefs((s) => s.loaded);
  const update = usePrefs((s) => s.updateBoard);
  const item = board.pages.flatMap((p) => p.breakpoints.lg).find((it) => it.id === id)
    ?? { id, type, x: 0, y: 0, w: 1, h: 1 };
  const view = VIEWS[type];
  const page = board.pages.find((p) => p.breakpoints.lg.some((it) => it.id === id)) ?? getPage(board);
  useEffect(() => { document.title = `Sakura · ${CATALOG[type].title}`; }, [type]);
  if (!loaded) return <div className="h-full bg-bg" aria-busy="true" />;
  return (
    <div className="flex h-full flex-col bg-bg p-3">
      <section aria-label={CATALOG[type].title} className="flex min-h-0 flex-1 flex-col overflow-auto rounded-card bg-panel pt-3">
        <view.Component item={item}
                        setSettings={(patch) => update((b) => patchWidget(b, id, { settings: { ...item.settings, ...patch } }, page.id))} />
      </section>
    </div>
  );
}

export function WidgetWindowApp({ type, id }: { type: string; id: string }) {
  if (!(type in CATALOG)) return <div className="p-4 text-sm text-ink-dim">Неизвестный виджет</div>;
  return <Providers><WidgetWindow type={type as WidgetType} id={id} /></Providers>;
}

export default function App({ client }: { client?: CoreClient }) {
  return <Providers client={client}><Shell /></Providers>;
}

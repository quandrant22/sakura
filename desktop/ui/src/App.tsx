import { X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Group, Panel, Separator, usePanelRef } from "react-resizable-panels";

import { type CoreClient, WsCoreClient } from "./api/client";
import { DemoClient, type DemoMode } from "./api/demo";
import { WidgetBoard } from "./board/WidgetBoard";
import { bridge } from "./bridge";
import { Chat, ChatStrip } from "./components/Chat";
import { CoreCard, MenuCard, type Section } from "./components/LeftColumn";
import { TitleBar } from "./components/TitleBar";
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

function Placeholder({ title, phase }: { title: string; phase: number }) {
  return (
    <div className="grid h-full place-items-center rounded-card bg-panel text-sm text-ink-dim">
      {title}: экран появится в фазе {phase}
    </div>
  );
}

const SECTIONS: Section[] = ["home", "devices", "scenarios", "memory", "settings"];

// ?screen=devices|scenarios|memory|settings — стартовый экран (снимки экранов, отладка).
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

function Workspace({ section }: { section: Section }) {
  const winW = useWindowWidth();
  const chatRef = usePanelRef();
  const chatWidth = usePrefs((s) => s.chatWidth);
  const collapsed = usePrefs((s) => s.chatCollapsed);
  const setPref = usePrefs((s) => s.set);

  let screen;
  if (section === "settings") screen = <Settings />;
  else if (section === "devices") screen = <Devices />;
  else if (section === "scenarios") screen = <Scenarios />;
  else if (section === "memory") screen = <Placeholder title="Память" phase={5} />;
  else screen = <WidgetBoard />;

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
  usePrefsLoader();

  useEffect(() => bridge().tray.onAction((id) => {
    if (id === "mic_toggle") void toggleMic();
    if (id === "game_mode") void setGameMode(!game);
  }), [toggleMic, setGameMode, game]);
  useEffect(() => {
    void bridge().tray.setState({ mic, game });
  }, [mic, game]);

  const go = (s: Section) => {
    if (s !== "home") setEditing(false);
    setSection(s);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg">
      <TitleBar />
      <div className="flex min-h-0 flex-1 gap-gap px-edge pb-edge pt-gap">
        <aside className="flex w-[300px] shrink-0 flex-col gap-gap">
          <CoreCard />
          <MenuCard section={section} onSection={go} />
        </aside>
        {/* Раскладка грузится по device_id — до этого чат и доска не монтируются, чтобы не прыгала ширина. */}
        {loaded ? <Workspace section={section} /> : <div className="flex-1" aria-busy="true" />}
      </div>
      <Toast />
    </div>
  );
}

export default function App({ client }: { client?: CoreClient }) {
  const core = useMemo(() => client ?? makeClient(window.location.search), [client]);
  const store = useMemo(() => createAppStore(core), [core]);
  useEffect(() => store.getState().init(), [store]);
  return (
    <StoreContext.Provider value={store}>
      <MediaProvider client={core}>
        <Shell />
      </MediaProvider>
    </StoreContext.Provider>
  );
}

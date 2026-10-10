import { WifiOff, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { type CoreClient, WsCoreClient } from "./api/client";
import { DemoClient, type DemoMode } from "./api/demo";
import { bridge } from "./bridge";
import { type Section, Sidebar } from "./components/Sidebar";
import { type Tab, TitleBar } from "./components/TitleBar";
import { PlayerBar } from "./components/media/PlayerBar";
import { MediaProvider } from "./media/MediaContext";
import { Home } from "./screens/Home";
import { Media } from "./screens/Media";
import { Settings } from "./screens/Settings";
import { createAppStore, StoreContext, useApp } from "./store";

const DEMO_MODES: DemoMode[] = ["normal", "empty", "offline", "unsupported"];

/** ?demo=normal|empty|offline|unsupported — данные из фикстур (снимки экранов, разработка). */
export function makeClient(search: string): CoreClient {
  const demo = new URLSearchParams(search).get("demo") as DemoMode | null;
  if (demo && DEMO_MODES.includes(demo)) return new DemoClient(demo);
  return new WsCoreClient(() => bridge().core.connection());
}

const SECTION_TAB: Partial<Record<Section, Tab>> = { chat: "Главная", devices: "Устройства", scenarios: "Сценарии" };
const TAB_SECTION: Record<Tab, Section> = { Главная: "chat", Устройства: "devices", Сценарии: "scenarios", Настройки: "settings" };

function OfflineBanner() {
  const link = useApp((s) => s.link);
  const server = useApp((s) => s.server);
  const coreReady = useApp((s) => s.settings?.core_ready ?? true);
  let text = "";
  if (link !== "open") text = "Нет связи с ядром Сакуры — переподключаюсь…";
  else if (!coreReady) text = "Ядро запускается: загружаю распознавание речи…";
  else if (!server.online) text = "Нет связи с сервером";
  if (!text) return null;
  return (
    <div role="status" className="mx-5 mt-3 flex items-center gap-2 rounded-card border border-accent/30 bg-accent-soft px-4 py-2 text-sm text-ink">
      <WifiOff size={16} className="text-accent" /> {text}
    </div>
  );
}

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
    <div role="alert" className={"fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-card border px-4 py-2 text-sm shadow-soft " +
      (toast.level === "error" ? "border-accent bg-panel2 text-ink" : "border-line bg-panel2 text-ink")}>
      {toast.text}
      <button type="button" aria-label="Закрыть уведомление" onClick={dismiss} className="text-ink-dim hover:text-ink"><X size={14} /></button>
    </div>
  );
}

function Placeholder({ title, phase }: { title: string; phase: number }) {
  return (
    <div className="grid flex-1 place-items-center rounded-panel border border-line bg-panel text-sm text-ink-dim">
      {title}: экран появится в фазе {phase}
    </div>
  );
}

// ?screen=media|video|settings — стартовый экран (снимки экранов, отладка).
function initialScreen(): { section: Section; video: boolean } {
  const s = new URLSearchParams(window.location.search).get("screen");
  if (s === "media" || s === "video") return { section: "media", video: s === "video" };
  if (s === "settings") return { section: "settings", video: false };
  return { section: "chat", video: false };
}

function Shell() {
  const [init] = useState(initialScreen);
  // Раздел — единственный источник истины; подсвеченная вкладка заголовка выводится из него
  // (у «Медиа», «Памяти», «Профиля» своей вкладки нет — подсветки нет).
  const [section, setSection] = useState<Section>(init.section);
  const tab: Tab | null = section === "settings" ? "Настройки" : SECTION_TAB[section] ?? null;
  const toggleMic = useApp((s) => s.toggleMic);
  const mic = useApp((s) => s.settings?.mic_enabled ?? true);
  const game = useApp((s) => s.gameMode);
  const setGameMode = useApp((s) => s.setGameMode);

  useEffect(() => bridge().tray.onAction((id) => {
    if (id === "mic_toggle") void toggleMic();
    if (id === "game_mode") void setGameMode(!game);
  }), [toggleMic, setGameMode, game]);
  useEffect(() => {
    void bridge().tray.setState({ mic, game });
  }, [mic, game]);

  const go = (s: Section) => setSection(s);
  const goTab = (t: Tab) => setSection(TAB_SECTION[t]);

  let screen;
  if (section === "memory") screen = <Placeholder title="Память" phase={5} />;
  else if (section === "profile") screen = <Placeholder title="Профиль" phase={3} />;
  else if (section === "media") screen = <Media initial={init.video ? "video" : "music"} />;
  else if (section === "settings") screen = <Settings />;
  else if (section === "devices") screen = <Placeholder title="Устройства" phase={3} />;
  else if (section === "scenarios") screen = <Placeholder title="Сценарии" phase={4} />;
  else screen = <Home goDevices={() => go("devices")} goScenarios={() => go("scenarios")} goMedia={() => go("media")} />;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-win border border-line bg-bg shadow-soft">
      <TitleBar tab={tab} onTab={goTab} />
      <OfflineBanner />
      <div className="flex min-h-0 flex-1 gap-4 p-5">
        <Sidebar section={section} onSection={go} />
        {screen}
      </div>
      <PlayerBar />
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

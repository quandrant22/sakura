// Виджет «Окно приложения»: показ выбранного окна внутри Сакуры (desktopCapturer → getDisplayMedia).
// Только по явному действию; кадры не пишутся на диск и не уходят на сервер, кроме одного кадра
// по кнопке «Спросить про окно». Чёрный список (WINDOW_BLOCKLIST) и окна Сакуры не предлагаются.
import {
  AppWindow, ArrowLeft, ArrowRight, Globe, Home, Maximize2, MessageSquareText, Minus, Monitor, PictureInPicture2, Plus, RefreshCw, RotateCcw, Search, Square, X,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { bridge } from "../../bridge";
import {
  CAPTURE_MODES, type CaptureMode, captureRect, filterSources, fitWidgetRows, groupSources, matchSource, type WindowSource, ZOOM,
} from "../../capture/captureLogic";
import { useWindowCapture } from "../../capture/useWindowCapture";
import { MARGIN, ROW_HEIGHT, setWidgetHeight } from "../../layout/boardModel";
import { usePrefs } from "../../layout/prefs";
import { useMediaClient } from "../../media/MediaContext";
import { errorText } from "../../store";
import { useInteracting } from "../interaction";
import type { WidgetProps } from "./SmallWidgets";

const btn = "flex items-center gap-1 rounded-btn border border-line px-2 py-1 text-[11px] text-ink-dim hover:border-accent hover:text-ink disabled:opacity-40";

function useBox<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setBox({ w: e?.contentRect.width ?? 0, h: e?.contentRect.height ?? 0 }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, box] as const;
}

function useHidden() {
  const [hidden, setHidden] = useState(typeof document !== "undefined" && document.hidden);
  useEffect(() => {
    const on = () => setHidden(document.hidden);
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  return hidden;
}

/** Карточка источника в списке выбора: превью, иконка приложения, название. */
function SourceCard({ s, onPick }: { s: WindowSource; onPick(s: WindowSource): void }) {
  return (
    <button type="button" onClick={() => onPick(s)} title={s.name}
            className="group flex min-w-0 flex-col overflow-hidden rounded-btn border border-line bg-panel2/60 text-left transition hover:border-accent hover:shadow-glow">
      <div className="relative aspect-video w-full overflow-hidden bg-black/60">
        {s.thumb
          ? <img src={s.thumb} alt="" className="h-full w-full object-contain transition group-hover:scale-[1.02]" draggable={false} />
          : <div className="grid h-full place-items-center text-ink-dim">{s.kind === "screen" ? <Monitor size={22} /> : <AppWindow size={22} />}</div>}
      </div>
      <div className="flex min-w-0 items-center gap-1.5 px-2 py-1.5">
        {s.icon ? <img src={s.icon} alt="" className="h-4 w-4 shrink-0" draggable={false} />
          : s.kind === "screen" ? <Monitor size={14} className="shrink-0 text-accent" /> : null}
        <span className="truncate text-xs text-ink">{s.name}</span>
      </div>
    </button>
  );
}

function elapsed(since: number, now: number) {
  const s = Math.max(0, Math.floor((now - since) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function AppWindowWidget({ item }: Partial<WidgetProps>) {
  const client = useMediaClient();
  const [rootRef, root] = useBox<HTMLDivElement>();
  const [stageRef, stage] = useBox<HTMLDivElement>();
  const hidden = useHidden();
  const interacting = useInteracting();
  const baseFps = usePrefs((p) => p.captureFps);
  const views = usePrefs((p) => p.captureViews);
  const updateBoard = usePrefs((p) => p.updateBoard);
  const setPref = usePrefs((p) => p.set);
  const { stream, state, error, src, since, start: startCapture, stop, videoRef, onResize, grabFrame } =
    useWindowCapture({ baseFps, width: root.w, hidden, interacting });
  const [sources, setSources] = useState<WindowSource[] | null>(null);
  const [source, setSource] = useState<WindowSource | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [now, setNow] = useState(0);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [browserUrl, setBrowserUrl] = useState<string | null>(null);
  const [inputUrl, setInputUrl] = useState("");
  const webviewRef = useRef<any>(null);

  const openBrowser = (url: string) => {
    setBrowserUrl(url);
    setInputUrl(url);
    setSources(null);
  };

  const handleUrlSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    let target = inputUrl.trim();
    if (!target) return;
    if (!target.startsWith("http://") && !target.startsWith("https://")) {
      if (target.includes(".") && !target.includes(" ")) {
        target = "https://" + target;
      } else {
        target = `https://ya.ru/search/?text=${encodeURIComponent(target)}`;
      }
    }
    setBrowserUrl(target);
    setInputUrl(target);
  };

  useEffect(() => {
    const onOpen = (e: Event) => {
      const url = (e as CustomEvent<{ url?: string }>).detail?.url || "https://ya.ru";
      openBrowser(url);
    };
    window.addEventListener("sakura:open_browser", onOpen);
    return () => window.removeEventListener("sakura:open_browser", onOpen);
  }, []);

  const view = (source && views[source.name]) || { mode: "fit" as CaptureMode, zoom: 1 };
  const setView = (v: Partial<typeof view>) => {
    if (source) setPref("captureViews", { ...views, [source.name]: { ...view, ...v } });
  };

  // Поток — в <video> через callback-ref (без записи ref во время рендера).
  const attachVideo = (el: HTMLVideoElement | null) => {
    videoRef.current = el;
    if (el) {
      if (el.srcObject !== stream) el.srcObject = stream;
      if (stream) void el.play().catch(() => {});
      if (el.videoWidth > 0 && el.videoHeight > 0) onResize(el);
    }
  };
  useEffect(() => {
    if (state !== "live" && state !== "black") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [state]);

  const pick = async () => {
    setNote(null);
    setLoading(true);
    try {
      const [list, block] = await Promise.all([bridge().capture.sources(), bridge().capture.blocklist()]);
      setSources(filterSources(list, block.length ? block : undefined));
    } catch (e) {
      setNote(errorText(e));
    } finally {
      setLoading(false);
    }
  };
  const start = (s: WindowSource) => {
    setSource(s);
    setSources(null);
    setQuery("");
    void startCapture(s.id);
  };
  const ask = async () => {
    const image = grabFrame();
    if (!image) return;
    try {
      const r = await client.call<{ text?: string }>("window_ask", { image, question: `Что в окне «${source?.name}»?` });
      setNote(r?.text ?? "Отправлено");
    } catch (e) {
      setNote(errorText(e));
    }
  };
  // «Подогнать виджет под окно»: высота виджета под пропорции источника при текущей ширине.
  const fitWidget = () => {
    const aspect = src.width / src.height;
    const chrome = root.h - stage.h + 44; // заголовок виджета + панель
    const rows = fitWidgetRows(root.w, aspect, ROW_HEIGHT, MARGIN[1], chrome);
    if (item) updateBoard((b) => setWidgetHeight(b, item.id, rows));
  };

  const live = state === "live" || state === "black";
  const r = captureRect(stage.w, stage.h, src.width, src.height, view.mode, view.zoom);

  if (browserUrl) {
    return (
      <div ref={rootRef} className="flex min-h-0 flex-1 flex-col px-3 pb-3">
        <div className="mb-2 flex flex-wrap items-center gap-1.5" aria-label="Панель браузера">
          <button type="button" className={btn} onClick={() => webviewRef.current?.goBack?.()} title="Назад">
            <ArrowLeft size={12} />
          </button>
          <button type="button" className={btn} onClick={() => webviewRef.current?.goForward?.()} title="Вперёд">
            <ArrowRight size={12} />
          </button>
          <button type="button" className={btn} onClick={() => webviewRef.current?.reload?.()} title="Обновить">
            <RefreshCw size={12} />
          </button>
          <button type="button" className={btn} onClick={() => openBrowser("https://ya.ru")} title="На главную">
            <Home size={12} />
          </button>
          <form onSubmit={handleUrlSubmit} className="flex min-w-0 flex-1 items-center gap-1">
            <div className="flex min-w-0 flex-1 items-center gap-1.5 rounded-btn border border-line bg-panel2/60 px-2 py-1">
              <Globe size={13} className="text-accent" />
              <input
                aria-label="Адресная строка"
                value={inputUrl}
                onChange={(e) => setInputUrl(e.target.value)}
                placeholder="Введите адрес или поисковый запрос…"
                className="min-w-0 flex-1 bg-transparent text-xs text-ink outline-none placeholder:text-ink-dim"
              />
            </div>
            <button type="submit" className={btn}>Перейти</button>
          </form>
          <button type="button" className={btn} onClick={() => setBrowserUrl(null)} title="Закрыть браузер">
            <X size={12} />
          </button>
        </div>
        <div className="relative min-h-0 flex-1 overflow-hidden rounded-btn border border-line bg-white">
          <webview
            ref={webviewRef}
            src={browserUrl}
            className="h-full w-full border-none"
            allowpopups={true}
          />
        </div>
      </div>
    );
  }

  if (!live && state !== "starting") {
    return (
      <div ref={rootRef} className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-4 pb-4 text-sm">
        {state === "ended" && <div role="status" className="rounded-btn bg-panel2 px-3 py-2 text-ink-dim">Окно «{source?.name}» закрыто</div>}
        {error && <div role="alert" className="text-accent">{error}</div>}
        {!sources ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center text-ink-dim">
            <div className="flex items-center gap-2">
              <AppWindow size={26} className="text-accent" />
              <Globe size={26} className="text-accent/60" />
            </div>
            <span>Показать окно приложения или открыть браузер</span>
            <span className="text-xs">Всё работает прямо внутри виджета, не вылетая на весь экран</span>
            <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
              <button type="button" className={btn} onClick={() => void pick()} disabled={loading}><Maximize2 size={13} /> Выбрать окно или экран</button>
              <button type="button" className={btn + " border-accent/60 text-accent"} onClick={() => openBrowser("https://ya.ru")}><Globe size={13} /> Встроенный браузер</button>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-1.5 pt-1 text-xs">
              <span className="text-[11px] text-ink-dim">Быстрый запуск:</span>
              <button type="button" className="rounded-btn border border-line px-2 py-0.5 text-[11px] hover:border-accent hover:text-ink" onClick={() => openBrowser("https://ya.ru")}>Яндекс</button>
              <button type="button" className="rounded-btn border border-line px-2 py-0.5 text-[11px] hover:border-accent hover:text-ink" onClick={() => openBrowser("https://google.com")}>Google</button>
              <button type="button" className="rounded-btn border border-line px-2 py-0.5 text-[11px] hover:border-accent hover:text-ink" onClick={() => openBrowser("https://youtube.com")}>YouTube</button>
              <button type="button" className="rounded-btn border border-line px-2 py-0.5 text-[11px] hover:border-accent hover:text-ink" onClick={() => openBrowser("https://github.com")}>GitHub</button>
            </div>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-2">
            <div className="flex items-center gap-1.5">
              <label className="flex min-w-0 flex-1 items-center gap-1.5 rounded-btn border border-line bg-panel2/60 px-2 py-1">
                <Search size={13} className="text-ink-dim" />
                <input aria-label="Найти окно" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Найти окно…"
                       className="min-w-0 flex-1 bg-transparent text-xs text-ink outline-none placeholder:text-ink-dim" />
              </label>
              <button type="button" className={btn} onClick={() => void pick()} disabled={loading} aria-label="Обновить список">
                <RefreshCw size={12} className={loading ? "animate-spin" : ""} /></button>
              <button type="button" className={btn} onClick={() => { setSources(null); setQuery(""); }} aria-label="Отмена"><X size={12} /></button>
            </div>
            {(() => {
              const { windows, screens } = groupSources(sources);
              const shown = windows.filter((s) => matchSource(s, query));
              if (!windows.length && !screens.length) {
                return <div className="flex flex-1 items-center justify-center text-ink-dim">Нет окон для показа</div>;
              }
              return (
                <>
                  {screens.length > 0 && !query && (
                    <section aria-label="Экраны">
                      <div className="mb-1 text-[11px] uppercase tracking-wider text-ink-dim">Экраны</div>
                      <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2">
                        {screens.map((s) => <SourceCard key={s.id} s={s} onPick={start} />)}
                      </div>
                    </section>
                  )}
                  <section aria-label="Окна">
                    <div className="mb-1 text-[11px] uppercase tracking-wider text-ink-dim">Окна</div>
                    {shown.length === 0
                      ? <div className="py-4 text-center text-xs text-ink-dim">Ничего не найдено</div>
                      : <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2">
                          {shown.map((s) => <SourceCard key={s.id} s={s} onPick={start} />)}
                        </div>}
                  </section>
                </>
              );
            })()}
          </div>
        )}
      </div>
    );
  }

  return (
    <div ref={rootRef} className="flex min-h-0 flex-1 flex-col px-3 pb-3">
      <div className="mb-2 flex flex-wrap items-center gap-1.5" aria-label="Управление показом окна">
        <span className="flex items-center gap-1.5 text-[11px] text-accent" role="status" aria-label="Идёт показ">
          <span className="h-2 w-2 animate-pulse rounded-full bg-accent" /> идёт показ {elapsed(since, now || since)}
        </span>
        <span className="min-w-0 max-w-[30%] truncate text-xs text-ink-dim" title={source?.name}>{source?.name}</span>
        <div className="flex flex-wrap items-center gap-1" aria-label="Режим размера">
          {(Object.keys(CAPTURE_MODES) as CaptureMode[]).map((m) => (
            <button key={m} type="button" className={btn} aria-pressed={view.mode === m} onClick={() => setView({ mode: m })}>
              {CAPTURE_MODES[m]}</button>
          ))}
          <button type="button" className={btn} aria-label="Уменьшить" disabled={view.zoom <= ZOOM.min}
                  onClick={() => setView({ zoom: Math.max(ZOOM.min, view.zoom - ZOOM.step) })}><Minus size={12} /></button>
          <span className="w-9 text-center text-[11px] tabular-nums text-ink-dim">{Math.round(view.zoom * 100)}%</span>
          <button type="button" className={btn} aria-label="Увеличить" disabled={view.zoom >= ZOOM.max}
                  onClick={() => setView({ zoom: Math.min(ZOOM.max, view.zoom + ZOOM.step) })}><Plus size={12} /></button>
          <button type="button" className={btn} aria-label="Сбросить масштаб" onClick={() => setView({ zoom: 1 })}><RotateCcw size={12} /></button>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-1">
          {item && <button type="button" className={btn} onClick={fitWidget} disabled={!src.width}>Подогнать виджет</button>}
          <button type="button" className={btn} onClick={() => source && void bridge().capture.openMini(source.id, src.width / src.height)}>
            <PictureInPicture2 size={12} /> Поверх всех</button>
          <button type="button" className={btn} onClick={() => void ask()} title="Один кадр уйдёт на сервер для ответа">
            <MessageSquareText size={12} /> Спросить про окно</button>
          <button type="button" className={btn} onClick={() => stop()}><Square size={12} /> Стоп</button>
        </div>
      </div>
      {note && <div role="status" className="mb-1 truncate text-xs text-ink-dim" title={note}>{note}</div>}
      <div ref={stageRef} className={"relative min-h-0 flex-1 rounded-btn bg-black " + (r.scroll ? "overflow-auto" : "overflow-hidden")}>
        <video ref={attachVideo} autoPlay muted playsInline aria-label="Показ окна"
               onLoadedMetadata={(e) => onResize(e.currentTarget)}
               onPlay={(e) => onResize(e.currentTarget)}
               onPlaying={(e) => onResize(e.currentTarget)}
               onTimeUpdate={(e) => { if (!src.width && e.currentTarget.videoWidth > 0) onResize(e.currentTarget); }}
               onResize={(e) => onResize(e.currentTarget)}
               className={"absolute max-w-none " + (view.mode === "fill" ? "object-cover" : "object-contain")}
               style={src.width > 0 && src.height > 0 ? { left: r.left, top: r.top, width: r.width, height: r.height } : { inset: 0, width: "100%", height: "100%" }} />
        {state === "black" && (
          <div className="absolute inset-0 grid place-items-center bg-panel/90 text-center text-sm text-ink-dim" role="status">
            Окно свёрнуто или защищено от показа
          </div>
        )}
      </div>
    </div>
  );
}

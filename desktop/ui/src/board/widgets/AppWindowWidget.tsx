// Виджет «Окно приложения»: показ выбранного окна внутри Сакуры (desktopCapturer → getDisplayMedia).
// Только по явному действию; кадры не пишутся на диск и не уходят на сервер, кроме одного кадра
// по кнопке «Спросить про окно». Чёрный список (WINDOW_BLOCKLIST) и окна Сакуры не предлагаются.
import {
  AppWindow, Maximize2, MessageSquareText, Minus, PictureInPicture2, Plus, RotateCcw, Square,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { bridge } from "../../bridge";
import { CAPTURE_MODES, type CaptureMode, captureRect, filterSources, fitWidgetRows, type WindowSource, ZOOM } from "../../capture/captureLogic";
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

  const view = (source && views[source.name]) || { mode: "fit" as CaptureMode, zoom: 1 };
  const setView = (v: Partial<typeof view>) => {
    if (source) setPref("captureViews", { ...views, [source.name]: { ...view, ...v } });
  };

  // Поток — в <video> через callback-ref (без записи ref во время рендера).
  const attachVideo = (el: HTMLVideoElement | null) => {
    videoRef.current = el;
    if (el && el.srcObject !== stream) el.srcObject = stream;
  };
  useEffect(() => {
    if (state !== "live" && state !== "black") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [state]);

  const pick = async () => {
    setNote(null);
    const [list, block] = await Promise.all([bridge().capture.sources(), bridge().capture.blocklist()]);
    setSources(filterSources(list, block.length ? block : undefined));
  };
  const start = (s: WindowSource) => {
    setSource(s);
    setSources(null);
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

  if (!live && state !== "starting") {
    return (
      <div ref={rootRef} className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-4 pb-4 text-sm">
        {state === "ended" && <div role="status" className="rounded-btn bg-panel2 px-3 py-2 text-ink-dim">Окно «{source?.name}» закрыто</div>}
        {error && <div role="alert" className="text-accent">{error}</div>}
        {!sources ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center text-ink-dim">
            <AppWindow size={28} className="text-accent" />
            <span>Показать окно приложения внутри Сакуры</span>
            <span className="text-xs">Только по вашему действию, ничего не записывается</span>
            <button type="button" className={btn} onClick={() => void pick()}><Maximize2 size={13} /> Выбрать окно</button>
          </div>
        ) : sources.length === 0 ? (
          <div className="flex flex-1 items-center justify-center text-ink-dim">Нет окон для показа</div>
        ) : (
          <ul aria-label="Окна" className="flex flex-col gap-1">
            {sources.map((s) => (
              <li key={s.id}>
                <button type="button" onClick={() => start(s)}
                        className="w-full truncate rounded-btn px-3 py-1.5 text-left text-ink hover:bg-panel2">{s.name}</button>
              </li>
            ))}
          </ul>
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
               onResize={(e) => onResize(e.currentTarget)}
               className={"absolute max-w-none " + (view.mode === "fill" ? "object-cover" : "object-contain")}
               style={{ left: r.left, top: r.top, width: r.width, height: r.height }} />
        {state === "black" && (
          <div className="absolute inset-0 grid place-items-center bg-panel/90 text-center text-sm text-ink-dim" role="status">
            Окно свёрнуто или защищено от показа
          </div>
        )}
      </div>
    </div>
  );
}

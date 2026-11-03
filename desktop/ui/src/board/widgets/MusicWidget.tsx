// Виджет «Музыка»: нижняя панель 100 px. Источник — приложение Яндекс.Музыки (пульт через SMTC,
// по умолчанию) или медиатека Сакуры (встроенный плеер). Если виджет растянуть по высоте, под
// панелью медиатеки открывается сама медиатека. Источник и стиль — в меню «…».
import { Pause, Play, Repeat, Repeat1, Shuffle, SkipBack, SkipForward, Volume2, VolumeX } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";

import { Cover } from "../../components/media/Cover";
import { MusicView } from "../../components/media/MusicView";
import { BAR_STYLES, MUSIC_SOURCES, type MusicBarStyle, type MusicSource, usePrefs } from "../../layout/prefs";
import { useMusic } from "../../media/MediaContext";
import { fmtTime } from "../../media/types";
import { prevAction } from "./music/barLogic";
import { YandexBar } from "./music/YandexBar";

const iconBtn = "grid h-8 w-8 place-items-center rounded-full text-ink-dim transition-colors hover:text-ink disabled:opacity-40";
/** С какой высоты виджета показывать медиатеку под панелью. */
const LIBRARY_FROM_PX = 220;

function useHeight<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [h, setH] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setH(e?.contentRect.height ?? 0));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, h] as const;
}

/** Меню «…»: источник и стиль панели. */
function BarMenu({ onClose }: { onClose(): void }) {
  const source = usePrefs((p) => p.musicSource);
  const style = usePrefs((p) => p.musicBarStyle);
  const set = usePrefs((p) => p.set);
  const opt = (on: boolean) => "rounded-full px-2.5 py-1 text-xs " + (on ? "bg-accent-grad text-white" : "text-ink-dim hover:text-ink");
  return (
    <div role="menu" aria-label="Меню панели музыки" onMouseLeave={onClose}
         className="absolute right-2 top-1 z-10 flex flex-col gap-1 rounded-btn border border-line bg-panel2 p-2 shadow-soft">
      <div className="flex items-center gap-1">
        <span className="w-16 text-[11px] text-ink-dim">Источник</span>
        {(Object.keys(MUSIC_SOURCES) as MusicSource[]).map((k) => (
          <button key={k} type="button" role="menuitemradio" aria-checked={source === k} className={opt(source === k)}
                  onClick={() => { set("musicSource", k); onClose(); }}>{MUSIC_SOURCES[k]}</button>
        ))}
      </div>
      <div className="flex items-center gap-1">
        <span className="w-16 text-[11px] text-ink-dim">Стиль</span>
        {(Object.keys(BAR_STYLES) as MusicBarStyle[]).map((k) => (
          <button key={k} type="button" role="menuitemradio" aria-checked={style === k} className={opt(style === k)}
                  onClick={() => set("musicBarStyle", k)}>{BAR_STYLES[k]}</button>
        ))}
      </div>
    </div>
  );
}

/** Медиатека Сакуры — встроенный плеер. */
function LocalBar({ onMenu }: { onMenu(): void }) {
  const queue = useMusic((s) => s.queue);
  const status = useMusic((s) => s.status);
  const position = useMusic((s) => s.position);
  const duration = useMusic((s) => s.duration);
  const volume = useMusic((s) => s.volume);
  const muted = useMusic((s) => s.muted);
  const cover = useMusic((s) => s.cover);
  const error = useMusic((s) => s.error);
  const a = useMusic((s) => s);
  const t = queue.index >= 0 ? queue.items[queue.index] : undefined;
  const none = !t;

  return (
    <div className="flex h-[100px] shrink-0 items-center gap-3 py-[18px] pl-[18px] pr-4" aria-label="Мини-плеер">
      <Cover src={t?.cover ?? (t ? cover : null)} className="h-16 w-16 !rounded-[10px]" />
      <div className="w-32 min-w-0">
        <div className="truncate text-sm text-ink">{t?.title ?? "Ничего не играет"}</div>
        <div className="truncate text-xs text-ink-dim">{t ? error ?? (t.artist || "—") : "Выберите трек в медиатеке"}</div>
      </div>
      <div className="flex items-center gap-1">
        <button type="button" aria-label="Перемешать" aria-pressed={queue.shuffle} onClick={a.toggleShuffle}
                className={iconBtn + (queue.shuffle ? " text-accent" : "")}><Shuffle size={16} /></button>
        <button type="button" aria-label="Предыдущий" disabled={none}
                title="Клик — в начало трека (после 3 с) или предыдущий; двойной клик — предыдущий трек"
                onClick={(e) => void (prevAction(e.detail, position) === "restart" ? a.seek(0) : e.detail >= 2 ? a.prevTrack() : a.prev())}
                className={iconBtn}><SkipBack size={18} /></button>
        <button type="button" aria-label={status === "playing" ? "Пауза" : "Играть"} disabled={none} onClick={() => void a.toggle()}
                className="grid h-10 w-10 place-items-center rounded-full bg-accent-grad text-white shadow-glow disabled:opacity-40">
          {status === "playing" ? <Pause size={18} /> : <Play size={18} />}
        </button>
        <button type="button" aria-label="Следующий" disabled={none} onClick={() => void a.next()} className={iconBtn}><SkipForward size={18} /></button>
        <button type="button" aria-label="Повтор" aria-pressed={queue.repeat !== "off"} onClick={a.cycleRepeat}
                className={iconBtn + (queue.repeat !== "off" ? " text-accent" : "")}>
          {queue.repeat === "one" ? <Repeat1 size={16} /> : <Repeat size={16} />}
        </button>
      </div>
      <div className="flex min-w-[90px] flex-1 items-center gap-1.5 text-[11px] text-ink-dim">
        <span className="w-8 text-right tabular-nums">{fmtTime(position)}</span>
        <input type="range" aria-label="Позиция" min={0} max={duration || 0} step={0.5} disabled={none}
               value={Math.min(position, duration || 0)}
               onChange={(e) => a.seek(Number(e.target.value))} className="h-1 w-0 min-w-0 flex-1 accent-accent" />
        <span className="w-8 tabular-nums">{fmtTime(duration)}</span>
      </div>
      <div className="flex w-28 shrink-0 items-center gap-1">
        <button type="button" aria-label={muted ? "Включить звук" : "Выключить звук"} onClick={a.toggleMute} className={iconBtn}>
          {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
        </button>
        <input type="range" aria-label="Громкость" min={0} max={1} step={0.01} value={volume}
               onChange={(e) => a.setVolume(Number(e.target.value))} className="h-1 min-w-0 flex-1 accent-accent" />
      </div>
      <button type="button" aria-label="Меню панели" onClick={onMenu} className={iconBtn}>…</button>
    </div>
  );
}

export function MusicWidget() {
  const source = usePrefs((p) => p.musicSource);
  const [ref, height] = useHeight<HTMLDivElement>();
  const [menu, setMenu] = useState(false);
  const toggle = () => setMenu((m) => !m);

  return (
    <div ref={ref} className="relative flex h-full flex-col">
      {source === "yandex" ? (
        <div className="h-full min-h-0"><YandexBar onMenu={toggle} /></div>
      ) : (
        <>
          <LocalBar onMenu={toggle} />
          {height >= LIBRARY_FROM_PX && (
            <div className="flex min-h-0 flex-1 border-t border-line p-3 pl-0">
              <MusicView />
            </div>
          )}
        </>
      )}
      {menu && <BarMenu onClose={() => setMenu(false)} />}
    </div>
  );
}

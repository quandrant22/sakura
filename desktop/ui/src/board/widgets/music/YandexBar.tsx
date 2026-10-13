// Панель Яндекс.Музыки (режим remote): пульт приложения через ядро (SMTC, громкость сессии).
// Похожа на родной плеер: обложка 64×64, название, «…», кнопки с большой жёлтой «играть»,
// справа «Текст», настройки и громкость; фон — по цвету обложки; прогресс — по нижней кромке.
import {
  ExternalLink, Heart, HeartCrack, ListMusic, MoreHorizontal, Pause, Play, Repeat, Repeat1, Settings2, Shuffle,
  SkipBack, SkipForward, Volume2, VolumeX, X,
} from "lucide-react";
import { type MouseEvent, type PointerEvent, type ReactNode, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { usePrefs } from "../../../layout/prefs";
import { useMediaClient } from "../../../media/MediaContext";
import {
  type ControlResult, dominantColor, extrapolate, fmt, type Hint, hintFor, prevAction, type RemoteState, TOKEN_STEPS,
  visibleControls,
} from "./barLogic";

const POLL_MS = 2000;
const TICK_MS = 250;

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(690);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setW(e?.contentRect.width ?? 690));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/** Снимок пульта раз в 2 с (не в скрытом окне) + позиция каждые 250 мс между снимками. */
function useRemote() {
  const client = useMediaClient();
  const [st, setSt] = useState<RemoteState | null>(null);
  const [fetchedAt, setFetchedAt] = useState(0);
  const [now, setNow] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const r = await client.call<RemoteState>("media_ymremote", { op: "state" });
      if (r) { setSt(r); setFetchedAt(performance.now()); }
    } catch {
      setSt((s) => s ?? { status: "no_smtc" });
    }
  }, [client]);

  useEffect(() => {
    const first = setTimeout(() => void refresh(), 0);
    const poll = setInterval(() => { if (!document.hidden) void refresh(); }, POLL_MS);
    const tick = setInterval(() => { if (!document.hidden) setNow(performance.now()); }, TICK_MS);
    return () => { clearTimeout(first); clearInterval(poll); clearInterval(tick); };
  }, [refresh]);

  const position = extrapolate(st, fetchedAt ? Math.max(0, (now - fetchedAt) / 1000) : 0);
  return { st, position, refresh, client };
}

function useCoverColor(src: string | null | undefined) {
  const [color, setColor] = useState<string | null>(null);
  useEffect(() => {
    if (!src || typeof document === "undefined") return;
    const img = new Image();
    img.onload = () => {
      try {
        const c = document.createElement("canvas");
        c.width = c.height = 16;
        const ctx = c.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(img, 0, 0, 16, 16);
        const rgb = dominantColor(ctx.getImageData(0, 0, 16, 16).data);
        setColor(rgb ? `rgb(${rgb.join(" ")})` : null);
      } catch {
        setColor(null);
      }
    };
    img.src = src;
  }, [src]);
  return src ? color : null;
}

function IconBtn(p: { label: string; title?: string; onClick?(e: MouseEvent): void; disabled?: boolean; active?: boolean;
                      dim?: boolean; children: ReactNode }) {
  return (
    <button type="button" aria-label={p.label} title={p.title ?? p.label} aria-pressed={p.active} disabled={p.disabled}
            onClick={p.onClick}
            className={"grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors disabled:opacity-35 " +
              (p.dim ? "opacity-35 " : "") +
              (p.active ? "text-ym-yellow" : "text-ink-dim hover:text-ink")}>
      {p.children}
    </button>
  );
}

export function YandexBar({ onMenu }: { onMenu?(): void }) {
  const { st, position, refresh, client } = useRemote();
  const style = usePrefs((p) => p.musicBarStyle);
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hint, setHint] = useState<Hint | null>(null);
  const [help, setHelp] = useState(false);
  const [lyrics, setLyrics] = useState<string | null>(null);
  const [drag, setDrag] = useState<number | null>(null); // доля 0..1 во время перетаскивания
  const bg = useCoverColor(st?.cover);
  const show = visibleControls(width);
  const dur = st?.duration_s ?? 0;

  const control = async (op: string, value?: unknown, retried = false) => {
    try {
      const r = await client.call<ControlResult>("media_ymremote", { op, value });
      setHint(hintFor(r));
      if (r?.lyrics) setLyrics(r.lyrics);
      // Звук приложения ещё не появился (трек не играет) — один повтор через 2 с.
      if (r && !r.ok && r.retry_ms && !retried) setTimeout(() => void control(op, value, true), r.retry_ms);
    } catch (e) {
      setHint({ text: String((e as Error).message || e), warn: true });
    }
    void refresh();
  };
  /** Кнопка без токена не выключена: по клику — полная подсказка с «Как это сделать». */
  const needToken = (op: string) => (st?.can_like ? void control(op)
    : setHint({ text: st?.like_hint ?? "", warn: true, help: "token" }));

  const bubble = hint && (
    <div role="status" className={"absolute left-[94px] right-3 top-1.5 z-10 flex items-start gap-2 rounded-btn bg-panel2/95 px-3 py-1.5 text-xs leading-snug shadow-soft " +
                                   (hint.warn ? "text-warn" : "text-ink")}>
      <span className="min-w-0 flex-1 whitespace-normal break-words">{hint.text}</span>
      {hint.help === "token" && (
        <button type="button" onClick={() => setHelp(true)} className="shrink-0 rounded-full border border-warn/50 px-2 py-0.5 text-[11px]">
          Как это сделать
        </button>
      )}
      <button type="button" aria-label="Скрыть подсказку" onClick={() => setHint(null)} className="shrink-0 text-ink-dim hover:text-ink">
        <X size={13} />
      </button>
    </div>
  );
  const popups = (
    <>
      {help && (
        <div role="dialog" aria-label="Как подключить Яндекс.Музыку"
             className="absolute inset-x-3 bottom-2 top-2 z-20 overflow-auto rounded-btn bg-panel2 p-3 text-xs leading-relaxed text-ink shadow-soft">
          <div className="mb-1 flex items-center justify-between font-medium">Доступ к Яндекс.Музыке
            <button type="button" aria-label="Закрыть" onClick={() => setHelp(false)}><X size={14} /></button></div>
          <ol className="list-decimal pl-4">{TOKEN_STEPS.map((t) => <li key={t}>{t}</li>)}</ol>
        </div>
      )}
      {lyrics && (
        <div role="dialog" aria-label="Текст песни"
             className="absolute inset-x-3 bottom-2 top-2 z-20 overflow-auto whitespace-pre-wrap rounded-btn bg-panel2 p-3 text-xs leading-relaxed text-ink shadow-soft">
          <button type="button" aria-label="Закрыть текст" onClick={() => setLyrics(null)} className="float-right"><X size={14} /></button>
          {lyrics}
        </div>
      )}
    </>
  );

  // Прогресс по нижней кромке: клик и перетаскивание — перемотка (запрос — при отпускании).
  const fraction = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return r.width > 0 ? Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) : 0;
  };

  const yandex = style === "yandex";
  const background = yandex
    ? (bg ? `linear-gradient(90deg, ${bg}, rgb(var(--ym-bar)) 70%)` : "rgb(var(--ym-bar))")
    : undefined;

  if (!st || st.status !== "ok") {
    const text = !st ? "Подключаюсь к Яндекс.Музыке…" : st.status === "no_smtc" ? "Нет доступа к панели медиа Windows (SMTC)"
      : st.status === "not_running" ? "Яндекс.Музыка не запущена" : "Ничего не играет";
    return (
      <div ref={ref} className={"flex h-full items-center gap-4 px-4 " + (yandex ? "" : "bg-panel")}
           style={{ background }} aria-label="Яндекс.Музыка">
        <div className="grid h-16 w-16 shrink-0 place-items-center rounded-[10px] bg-panel2 text-ink-dim"><ListMusic size={24} /></div>
        <div className="min-w-0 flex-1 text-sm text-ink-dim">{text}</div>
        {bubble}
        {st && st.status !== "no_smtc" && (
          <button type="button" onClick={() => void control("open_app")}
                  className="flex shrink-0 items-center gap-1.5 rounded-full bg-ym-yellow px-3 py-1.5 text-xs font-medium text-ym-on">
            <ExternalLink size={13} /> Открыть Яндекс.Музыку
          </button>
        )}
        {onMenu && <IconBtn label="Меню панели" onClick={onMenu}><MoreHorizontal size={18} /></IconBtn>}
      </div>
    );
  }

  const pct = drag != null ? drag * 100 : dur > 0 ? Math.min(100, (position / dur) * 100) : 0;
  return (
    <div ref={ref} className={"relative flex h-full items-center gap-3 overflow-hidden pl-[18px] pr-3 " + (yandex ? "" : "bg-panel")}
         style={{ background }} aria-label="Яндекс.Музыка">
      {st.cover ? <img src={st.cover} alt="" className="h-16 w-16 shrink-0 rounded-[10px] object-cover" />
        : <div className="h-16 w-16 shrink-0 rounded-[10px] bg-panel2" />}
      <div className="min-w-0 w-36 shrink">
        <div className="truncate text-sm font-medium text-ink" title={st.title}>{st.title}</div>
        <div className="truncate text-xs text-ink-dim" title={st.artist}>{st.artist || "—"}</div>
      </div>
      {bubble}
      {popups}
      {onMenu && <IconBtn label="Меню панели" onClick={onMenu}><MoreHorizontal size={18} /></IconBtn>}

      <div className="mx-auto flex items-center gap-1">
        {show.rating && (
          <IconBtn label="Не нравится" title={st.can_like ? "Не нравится" : `Не нравится. ${st.like_hint}`}
                   dim={!st.can_like} onClick={() => needToken("dislike")}><HeartCrack size={17} /></IconBtn>
        )}
        {show.modes && (
          <IconBtn label="Перемешать" active={!!st.shuffle} onClick={() => void control("shuffle")}><Shuffle size={17} /></IconBtn>
        )}
        <IconBtn label="Предыдущий" title="Клик — в начало трека (после 3 с) или предыдущий; двойной клик — предыдущий трек"
                 onClick={(e) => void control(prevAction(e.detail, position))}><SkipBack size={19} /></IconBtn>
        <button type="button" aria-label={st.playing ? "Пауза" : "Играть"} onClick={() => void control("play_pause")}
                className={"grid h-11 w-11 shrink-0 place-items-center rounded-full " +
                  (yandex ? "bg-ym-yellow text-ym-on" : "bg-accent-grad text-white shadow-glow")}>
          {st.playing ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" />}
        </button>
        <IconBtn label="Следующий" onClick={() => void control("next")}><SkipForward size={19} /></IconBtn>
        {show.modes && (
          <IconBtn label="Повтор" active={!!st.repeat && st.repeat !== "none"} onClick={() => void control("repeat")}>
            {st.repeat === "track" ? <Repeat1 size={17} /> : <Repeat size={17} />}
          </IconBtn>
        )}
        {show.rating && (
          <IconBtn label={st.liked ? "Убрать лайк" : "Нравится"} active={!!st.liked}
                   title={st.can_like ? (st.liked ? "Убрать лайк" : "Нравится") : `Нравится. ${st.like_hint}`}
                   dim={!st.can_like} onClick={() => needToken("like")}>
            <Heart size={17} fill={st.liked ? "currentColor" : "none"} />
          </IconBtn>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {show.extras && (
          <>
            <button type="button" title={st.can_lyrics ? "Текст песни" : `Текст. ${st.like_hint}`}
                    className={"rounded-full px-2 py-1 text-xs text-ink-dim hover:text-ink " + (st.can_lyrics ? "" : "opacity-35")}
                    onClick={() => needToken("lyrics")}>Текст</button>
            <IconBtn label="Настройки панели" onClick={onMenu}><Settings2 size={16} /></IconBtn>
          </>
        )}
        <IconBtn label={st.volume === 0 ? "Включить звук" : "Выключить звук"} onClick={() => void control("mute")}
                 disabled={st.volume == null}>
          {st.volume === 0 ? <VolumeX size={17} /> : <Volume2 size={17} />}
        </IconBtn>
        {show.volume && st.volume != null && (
          <input type="range" aria-label="Громкость Яндекс.Музыки" min={0} max={100} step={1} value={st.volume}
                 onChange={(e) => void control("volume", Number(e.target.value))} className="h-1 w-24 accent-ym-yellow" />
        )}
      </div>

      <div className="absolute inset-x-0 bottom-0 h-[6px] cursor-pointer" role="slider" aria-label="Позиция"
           aria-valuemin={0} aria-valuemax={Math.round(dur)} aria-valuenow={Math.round(position)}
           aria-valuetext={`${fmt(position)} из ${fmt(dur)}`}
           onPointerDown={(e) => { e.currentTarget.setPointerCapture?.(e.pointerId); setDrag(fraction(e)); }}
           onPointerMove={(e) => { if (drag != null) setDrag(fraction(e)); }}
           onPointerUp={(e) => {
             e.currentTarget.releasePointerCapture?.(e.pointerId);
             if (drag != null && dur) void control("seek", fraction(e) * dur);
             setDrag(null);
           }}>
        <div className="absolute inset-x-0 bottom-0 h-[3px] bg-white/10" />
        <div className={"absolute bottom-0 left-0 h-[3px] " + (yandex ? "bg-ym-yellow" : "bg-accent")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

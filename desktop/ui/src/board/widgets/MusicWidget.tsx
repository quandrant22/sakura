// Виджет «Музыка»: нижняя панель 100 px (обложка 80x80, название, кнопки, прогресс, громкость).
// Если виджет растянуть по высоте — под панелью открывается медиатека.
// Яндекс.Музыка (remote/embedded), «Моя волна», лайки и эквалайзер — фаза 4.
import { Pause, Play, Repeat, Repeat1, Shuffle, SkipBack, SkipForward, Volume2, VolumeX } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";

import { Cover } from "../../components/media/Cover";
import { MusicView } from "../../components/media/MusicView";
import { useMusic } from "../../media/MediaContext";
import { fmtTime } from "../../media/types";

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

export function MusicWidget() {
  const queue = useMusic((s) => s.queue);
  const status = useMusic((s) => s.status);
  const position = useMusic((s) => s.position);
  const duration = useMusic((s) => s.duration);
  const volume = useMusic((s) => s.volume);
  const muted = useMusic((s) => s.muted);
  const cover = useMusic((s) => s.cover);
  const error = useMusic((s) => s.error);
  const a = useMusic((s) => s);
  const [ref, height] = useHeight<HTMLDivElement>();
  const t = queue.index >= 0 ? queue.items[queue.index] : undefined;
  const none = !t;

  return (
    <div ref={ref} className="flex h-full flex-col">
      <div className="flex h-[100px] shrink-0 items-center gap-3 py-[10px] pr-4" aria-label="Мини-плеер">
        <Cover src={t?.cover ?? (t ? cover : null)} className="h-20 w-20" />
        <div className="w-32 min-w-0">
          <div className="truncate text-sm text-ink">{t?.title ?? "Ничего не играет"}</div>
          <div className="truncate text-xs text-ink-dim">{t ? error ?? (t.artist || "—") : "Выберите трек в медиатеке"}</div>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" aria-label="Перемешать" aria-pressed={queue.shuffle} onClick={a.toggleShuffle}
                  className={iconBtn + (queue.shuffle ? " text-accent" : "")}><Shuffle size={16} /></button>
          <button type="button" aria-label="Предыдущий" disabled={none} onClick={() => void a.prev()} className={iconBtn}><SkipBack size={18} /></button>
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
      </div>
      {height >= LIBRARY_FROM_PX && (
        <div className="flex min-h-0 flex-1 border-t border-line p-3 pl-0">
          <MusicView />
        </div>
      )}
    </div>
  );
}

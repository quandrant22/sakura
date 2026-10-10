// Мини-плеер внизу окна: виден, пока в очереди есть треки.
import { Music2, Pause, Play, Repeat, Repeat1, Shuffle, SkipBack, SkipForward, Volume2, VolumeX } from "lucide-react";

import { useMusic } from "../../media/MediaContext";
import { fmtTime } from "../../media/types";

export function Cover({ src, className = "h-12 w-12" }: { src?: string | null; className?: string }) {
  return src ? (
    <img src={src} alt="" className={"shrink-0 rounded-card object-cover " + className} />
  ) : (
    <div className={"grid shrink-0 place-items-center rounded-card bg-gradient-to-br from-accent/40 to-[#3b2063] text-white/70 " + className}>
      <Music2 size={18} />
    </div>
  );
}

const iconBtn = "grid h-8 w-8 place-items-center rounded-full text-ink-dim transition-colors hover:text-ink";

export function PlayerBar() {
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
  if (!t) return null;

  return (
    <div className="mx-5 mb-4 flex items-center gap-4 rounded-panel border border-line bg-panel px-4 py-2.5 shadow-soft" aria-label="Мини-плеер">
      <Cover src={t.cover ?? cover} />
      <div className="w-56 min-w-0">
        <div className="truncate text-sm text-ink">{t.title}</div>
        <div className="truncate text-xs text-ink-dim">{error ?? (t.artist || "—")}</div>
      </div>
      <div className="flex items-center gap-1">
        <button type="button" aria-label="Перемешать" aria-pressed={queue.shuffle} onClick={a.toggleShuffle}
                className={iconBtn + (queue.shuffle ? " text-accent" : "")}><Shuffle size={16} /></button>
        <button type="button" aria-label="Предыдущий" onClick={() => void a.prev()} className={iconBtn}><SkipBack size={18} /></button>
        <button type="button" aria-label={status === "playing" ? "Пауза" : "Играть"} onClick={() => void a.toggle()}
                className="grid h-10 w-10 place-items-center rounded-full bg-accent text-white shadow-glow">
          {status === "playing" ? <Pause size={18} /> : <Play size={18} />}
        </button>
        <button type="button" aria-label="Следующий" onClick={() => void a.next()} className={iconBtn}><SkipForward size={18} /></button>
        <button type="button" aria-label="Повтор" aria-pressed={queue.repeat !== "off"} onClick={a.cycleRepeat}
                className={iconBtn + (queue.repeat !== "off" ? " text-accent" : "")}>
          {queue.repeat === "one" ? <Repeat1 size={16} /> : <Repeat size={16} />}
        </button>
      </div>
      <div className="flex flex-1 items-center gap-2 text-[11px] text-ink-dim">
        <span className="w-10 text-right tabular-nums">{fmtTime(position)}</span>
        <input type="range" aria-label="Позиция" min={0} max={duration || 0} step={0.5} value={Math.min(position, duration || 0)}
               onChange={(e) => a.seek(Number(e.target.value))} className="h-1 flex-1 accent-[#ff4d94]" />
        <span className="w-10 tabular-nums">{fmtTime(duration)}</span>
      </div>
      <div className="flex w-36 items-center gap-2">
        <button type="button" aria-label={muted ? "Включить звук" : "Выключить звук"} onClick={a.toggleMute} className={iconBtn}>
          {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
        </button>
        <input type="range" aria-label="Громкость" min={0} max={1} step={0.01} value={volume}
               onChange={(e) => a.setVolume(Number(e.target.value))} className="h-1 flex-1 accent-[#ff4d94]" />
      </div>
    </div>
  );
}

// Карточка «Сейчас играет» на главной: встроенная музыка или видео, иначе — внешнее приложение (SMTC).
import { Disc3, Pause, Play, SkipForward } from "lucide-react";
import { useEffect, useState } from "react";

import { useMediaClient, useMusic, useVideo } from "../../media/MediaContext";
import { Card } from "../ui";
import { Cover } from "./PlayerBar";

interface External { title: string; artist: string; status: string }

export function NowPlaying({ onOpen }: { onOpen(): void }) {
  const client = useMediaClient();
  const track = useMusic((s) => s.current());
  const status = useMusic((s) => s.status);
  const cover = useMusic((s) => s.cover);
  const toggle = useMusic((s) => s.toggle);
  const next = useMusic((s) => s.next);
  const video = useVideo((s) => (s.source && s.status !== "stopped" ? s.source : null));
  const [ext, setExt] = useState<External | null>(null);
  const builtin = (track && status !== "stopped") || video;

  useEffect(() => {
    if (builtin) return;
    let alive = true;
    const poll = () => client.call<{ track: External | null }>("media_external", { op: "now_playing" })
      .then((r) => alive && setExt(r?.track ?? null)).catch(() => alive && setExt(null));
    void poll();
    const t = setInterval(poll, 10_000);
    return () => { alive = false; clearInterval(t); };
  }, [client, builtin]);

  let body;
  if (video) {
    body = <div className="min-w-0"><div className="truncate text-sm text-ink">{video.title || "Видео"}</div>
      <div className="text-xs text-ink-dim">Видео · {video.kind === "youtube" ? "YouTube" : "файл"}</div></div>;
  } else if (track && status !== "stopped") {
    body = (
      <>
        <Cover src={track.cover ?? cover} className="h-11 w-11" />
        <div className="min-w-0 flex-1"><div className="truncate text-sm text-ink">{track.title}</div>
          <div className="truncate text-xs text-ink-dim">{track.artist || "—"}</div></div>
        <button type="button" aria-label={status === "playing" ? "Пауза" : "Играть"} onClick={() => void toggle()}
                className="grid h-8 w-8 place-items-center rounded-full bg-accent text-white">{status === "playing" ? <Pause size={14} /> : <Play size={14} />}</button>
        <button type="button" aria-label="Следующий" onClick={() => void next()} className="text-ink-dim hover:text-ink"><SkipForward size={16} /></button>
      </>
    );
  } else if (ext) {
    body = <div className="min-w-0"><div className="truncate text-sm text-ink">{ext.artist ? `${ext.artist} — ` : ""}{ext.title}</div>
      <div className="text-xs text-ink-dim">Играет во внешнем приложении · {ext.status}</div></div>;
  } else {
    body = <button type="button" onClick={onOpen} className="text-sm text-ink-dim hover:text-accent">Ничего не играет — открыть медиа</button>;
  }

  return (
    <Card title="Сейчас играет" icon={<Disc3 size={18} />}>
      <div className="flex items-center gap-3 px-4 pb-4">{body}</div>
    </Card>
  );
}

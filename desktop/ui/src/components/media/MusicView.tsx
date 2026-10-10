// Экран «Медиа → Музыка»: медиатека (Треки / Альбомы / Исполнители / Плейлисты,
// Яндекс.Музыка при MUSIC_YANDEX=1), поиск, сканирование, очередь с перетаскиванием.
import { GripVertical, ListMusic, ListPlus, Music2, RefreshCw, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { List, type RowComponentProps } from "react-window";

import { errorText } from "../../store";
import { useMediaClient, useMediaMeta, useMusic } from "../../media/MediaContext";
import { fmtTime, fromLibrary, type LibraryTrack, type Track } from "../../media/types";
import { EmptyState, ErrorState, Skeleton } from "../ui";
import { Cover } from "./PlayerBar";

type View = "tracks" | "albums" | "artists" | "playlists" | "yandex";
type Filter = { album?: string; artist?: string; playlist?: number; title?: string } | null;

interface AlbumRow { album: string; album_artist: string; tracks: number; year: number | null; cover: string | null }
interface ArtistRow { artist: string; tracks: number; albums: number }
interface PlaylistRow { id: number | string; name: string; tracks: number }

const VIEWS: { id: View; label: string }[] = [
  { id: "tracks", label: "Треки" }, { id: "albums", label: "Альбомы" },
  { id: "artists", label: "Исполнители" }, { id: "playlists", label: "Плейлисты" },
];

interface TrackRowProps {
  tracks: Track[];
  currentId: Track["id"] | undefined;
  onPlay(i: number): void;
  onNext(t: Track): void;
}

function TrackRow({ index, style, tracks, currentId, onPlay, onNext }: RowComponentProps<TrackRowProps>) {
  const t = tracks[index]!;
  const active = t.id === currentId;
  return (
    <div style={style} onDoubleClick={() => onPlay(index)} role="row" aria-selected={active}
         className={"group grid grid-cols-[36px_1fr_1fr_1fr_56px_32px] items-center gap-3 rounded-card px-3 text-sm " +
           (active ? "bg-accent-soft text-accent" : "text-ink hover:bg-white/5")}>
      <button type="button" aria-label={`Играть ${t.title}`} onClick={() => onPlay(index)}
              className="text-xs tabular-nums text-ink-dim group-hover:text-accent">{t.track_no ?? index + 1}</button>
      <span className="truncate">{t.title}</span>
      <span className="truncate text-ink-dim">{t.artist}</span>
      <span className="truncate text-ink-dim">{t.album}</span>
      <span className="text-right text-xs tabular-nums text-ink-dim">{fmtTime(t.duration)}</span>
      <button type="button" aria-label="Играть следующим" title="Играть следующим" onClick={() => onNext(t)}
              className="opacity-0 transition-opacity group-hover:opacity-100"><ListPlus size={15} /></button>
    </div>
  );
}

export function MusicView() {
  const client = useMediaClient();
  const settings = useMediaMeta((s) => s.settings);
  const scan = useMediaMeta((s) => s.scan);
  const version = useMediaMeta((s) => s.libraryVersion);
  const playTracks = useMusic((s) => s.playTracks);
  const playNext = useMusic((s) => s.playNext);
  const currentId = useMusic((s) => s.current()?.id);
  const [view, setView] = useState<View>("tracks");
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>(null);
  const [reload, setReload] = useState(0);
  // Результат привязан к ключу запроса: пока ключ не совпал — показываем загрузку
  // (без синхронного setState в эффекте).
  const reqKey = JSON.stringify({ view, q, filter, version, reload });
  const [res, setRes] = useState<{ key: string; rows?: unknown[]; error?: string } | null>(null);
  const rows = res?.key === reqKey ? (res.rows ?? null) : null;
  const error = res?.key === reqKey ? (res.error ?? null) : null;

  useEffect(() => {
    let alive = true;
    const load = async (): Promise<unknown[]> => {
      if (view === "yandex") {
        const r = q.trim()
          ? await client.call<{ items: Track[] }>("media_yandex", { op: "search", q })
          : await client.call<{ items: Track[] }>("media_yandex", { op: "liked" });
        return r.items;
      }
      if (filter?.playlist !== undefined) {
        const r = await client.call<{ items: LibraryTrack[] }>("media_playlist", { op: "tracks", id: filter.playlist });
        return r.items.map(fromLibrary);
      }
      if (view === "tracks" || filter) {
        const r = await client.call<{ items: LibraryTrack[] }>("media_library", {
          view: "tracks", q: q.trim() || undefined, album: filter?.album, artist: filter?.artist, limit: 50000 });
        return r.items.map(fromLibrary);
      }
      const r = await client.call<{ items: unknown[] }>("media_library", { view });
      return r.items;
    };
    load().then((r) => alive && setRes({ key: reqKey, rows: r ?? [] }))
      .catch((e) => alive && setRes({ key: reqKey, error: errorText(e) || String(e) }));
    return () => { alive = false; };
  }, [client, view, q, filter, version, reload, reqKey]);

  const showTracks = view === "tracks" || view === "yandex" || filter !== null;

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      <section className="flex min-h-0 flex-1 flex-col rounded-panel border border-line bg-panel shadow-soft">
        <header className="flex flex-wrap items-center gap-2 px-4 pt-4">
          {VIEWS.map((v) => (
            <button key={v.id} type="button" onClick={() => { setView(v.id); setFilter(null); }}
                    aria-current={view === v.id && !filter ? "page" : undefined}
                    className={"rounded-card px-3 py-1.5 text-sm " + (view === v.id && !filter ? "bg-accent-soft text-accent" : "text-ink-dim hover:text-ink")}>
              {v.label}
            </button>
          ))}
          {settings?.music_yandex && (
            <button type="button" onClick={() => { setView("yandex"); setFilter(null); }}
                    className={"flex items-center gap-1.5 rounded-card px-3 py-1.5 text-sm " + (view === "yandex" ? "bg-accent-soft text-accent" : "text-ink-dim hover:text-ink")}>
              Яндекс.Музыка
              <span className="rounded-full border border-amber-300/40 px-1.5 text-[10px] text-amber-200/80">{settings.yandex_note ?? "неофициальный доступ"}</span>
            </button>
          )}
          <div className="ml-auto flex items-center gap-2">
            <label className="flex items-center gap-2 rounded-card border border-line bg-panel2 px-2.5 py-1.5">
              <Search size={14} className="text-ink-dim" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск" aria-label="Поиск музыки"
                     className="w-44 bg-transparent text-sm text-ink outline-none placeholder:text-ink-dim" />
            </label>
            <button type="button" title="Пересканировать папки" aria-label="Пересканировать папки"
                    onClick={() => void client.call("media_scan")}
                    className="grid h-8 w-8 place-items-center rounded-card border border-line text-ink-dim hover:text-accent">
              <RefreshCw size={14} className={scan?.state === "running" ? "animate-spin" : ""} />
            </button>
          </div>
        </header>
        {scan?.state === "running" && (
          <div className="mx-4 mt-3 text-xs text-ink-dim" role="status">
            Сканирую: {scan.done ?? 0} из {scan.total ?? "?"}
            <div className="mt-1 h-1 rounded bg-white/5"><div className="h-1 rounded bg-accent" style={{ width: `${scan.total ? ((scan.done ?? 0) / scan.total) * 100 : 5}%` }} /></div>
          </div>
        )}
        {filter && (
          <div className="mx-4 mt-3 flex items-center gap-2 text-sm text-ink">
            {filter.title ?? filter.album ?? filter.artist}
            <button type="button" aria-label="Сбросить фильтр" onClick={() => setFilter(null)} className="text-ink-dim hover:text-ink"><X size={14} /></button>
          </div>
        )}

        <div className="mt-2 min-h-0 flex-1 px-2 pb-3">
          {error ? (
            <ErrorState text={error} onRetry={() => setReload((x) => x + 1)} />
          ) : rows === null ? (
            <Skeleton lines={6} />
          ) : rows.length === 0 ? (
            <EmptyState text={view === "yandex" ? "Ничего не найдено" : "Медиатека пуста. Добавьте папки с музыкой: Настройки → Медиа"} />
          ) : showTracks ? (
            <List rowComponent={TrackRow} rowCount={rows.length} rowHeight={40} className="h-full"
                  rowProps={{ tracks: rows as Track[], currentId, onPlay: (i) => void playTracks(rows as Track[], i), onNext: playNext }} />
          ) : view === "albums" ? (
            <div className="grid h-full grid-cols-[repeat(auto-fill,minmax(150px,1fr))] content-start gap-3 overflow-y-auto p-2">
              {(rows as AlbumRow[]).map((a) => (
                <button key={`${a.album_artist}|${a.album}`} type="button" onClick={() => setFilter({ album: a.album, title: a.album })}
                        className="rounded-card p-2 text-left hover:bg-white/5">
                  <Cover src={a.cover} className="aspect-square h-auto w-full" />
                  <div className="mt-2 truncate text-sm text-ink">{a.album}</div>
                  <div className="truncate text-xs text-ink-dim">{a.album_artist}{a.year ? ` · ${a.year}` : ""}</div>
                </button>
              ))}
            </div>
          ) : (
            <ul className="h-full overflow-y-auto">
              {(rows as (ArtistRow | PlaylistRow)[]).map((r) => {
                const isPl = "id" in r;
                const label = isPl ? r.name : r.artist;
                const sub = isPl ? `${r.tracks} треков` : `${r.albums} альб. · ${r.tracks} треков`;
                return (
                  <li key={isPl ? String(r.id) : r.artist}>
                    <button type="button" onClick={() => setFilter(isPl ? { playlist: Number(r.id), title: r.name } : { artist: r.artist, title: r.artist })}
                            className="flex w-full items-center gap-3 rounded-card px-3 py-2 text-left hover:bg-white/5">
                      <span className="grid h-9 w-9 place-items-center rounded-card bg-accent-soft text-accent">
                        {isPl ? <ListMusic size={16} /> : <Music2 size={16} />}
                      </span>
                      <span className="min-w-0 flex-1"><span className="block truncate text-sm text-ink">{label}</span>
                        <span className="block text-xs text-ink-dim">{sub}</span></span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </section>
      <QueuePanel />
    </div>
  );
}

function QueuePanel() {
  const queue = useMusic((s) => s.queue);
  const playAt = useMusic((s) => s.playAt);
  const move = useMusic((s) => s.move);
  const remove = useMusic((s) => s.remove);
  const [drag, setDrag] = useState<number | null>(null);
  return (
    <section className="flex w-[clamp(220px,20vw,300px)] shrink-0 flex-col rounded-panel border border-line bg-panel shadow-soft" aria-label="Очередь">
      <header className="px-4 pb-2 pt-4 text-sm font-semibold text-ink">Очередь <span className="font-normal text-ink-dim">{queue.items.length || ""}</span></header>
      {queue.items.length === 0 ? (
        <EmptyState text="Очередь пуста — дважды щёлкните по треку" />
      ) : (
        <ol className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {queue.items.map((t, i) => (
            <li key={`${t.id}-${i}`} draggable onDragStart={() => setDrag(i)} onDragOver={(e) => e.preventDefault()}
                onDrop={() => { if (drag !== null) move(drag, i); setDrag(null); }}
                className={"group flex items-center gap-2 rounded-card px-2 py-1.5 text-sm " + (i === queue.index ? "bg-accent-soft text-accent" : "text-ink hover:bg-white/5")}>
              <GripVertical size={14} className="shrink-0 cursor-grab text-ink-dim" aria-hidden="true" />
              <button type="button" onDoubleClick={() => void playAt(i)} onClick={(e) => e.detail === 0 && void playAt(i)}
                      className="min-w-0 flex-1 text-left" aria-label={`${t.title} — ${t.artist}`}>
                <span className="block truncate">{t.title}</span>
                <span className="block truncate text-xs text-ink-dim">{t.artist}</span>
              </button>
              <button type="button" aria-label="Убрать из очереди" onClick={() => remove(i)}
                      className="text-ink-dim opacity-0 hover:text-ink group-hover:opacity-100"><X size={14} /></button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

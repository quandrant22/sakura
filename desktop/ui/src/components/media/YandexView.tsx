// Экран Яндекс.Музыки: «Моя волна», «Мне нравится», плейлисты и поиск по всему каталогу.
// Двойной щелчок не нужен: щелчок по треку включает его, кнопки справа ставят в очередь.
import { ArrowLeft, Disc3, Heart, ListEnd, ListPlus, ListMusic, Mic2, Radio } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { errorText } from "../../store";
import { useMediaClient, useMusic } from "../../media/MediaContext";
import { fmtTime, type Track } from "../../media/types";
import { EmptyState, ErrorState, Skeleton } from "../ui";

interface Album { id: string; title: string; artist: string; year?: number | null }
interface Artist { id: string; name: string }
interface Playlist { id: string; name: string; tracks: number }
interface Found { tracks: Track[]; albums: Album[]; artists: Artist[]; playlists: Playlist[] }

/** Что открыто: главная, список плейлистов или треки выбранного альбома/исполнителя/плейлиста. */
type Open = { kind: "liked" | "playlists" } | { kind: "album" | "artist" | "playlist"; id: string; title: string };
type Data = { tracks?: Track[]; playlists?: Playlist[]; found?: Found };

const chip = "flex items-center gap-1.5 rounded-card border border-line px-3 py-1.5 text-sm text-ink hover:border-accent hover:text-accent";
const rowBtn = "grid h-7 w-7 shrink-0 place-items-center rounded-full text-ink-dim opacity-0 transition-opacity hover:text-accent focus:opacity-100 group-hover:opacity-100";

function TrackList({ tracks }: { tracks: Track[] }) {
  const playTracks = useMusic((s) => s.playTracks);
  const enqueue = useMusic((s) => s.enqueue);
  const currentId = useMusic((s) => s.current()?.id);
  return (
    <ul>
      {tracks.map((t, i) => (
        <li key={`${t.id}-${i}`} className={"group flex items-center gap-2 rounded-card px-2 text-sm " +
          (t.id === currentId ? "bg-accent-soft text-accent" : "text-ink hover:bg-white/5")}>
          <button type="button" onClick={() => void playTracks(tracks, i)} aria-label={`Играть ${t.title}`}
                  className="flex min-w-0 flex-1 items-center gap-3 py-1.5 text-left">
            {t.cover ? <img src={t.cover} alt="" loading="lazy" className="h-8 w-8 shrink-0 rounded" />
              : <span className="h-8 w-8 shrink-0 rounded bg-white/5" />}
            <span className="min-w-0 flex-1">
              <span className="block truncate">{t.title}</span>
              <span className="block truncate text-xs text-ink-dim">{t.artist}</span>
            </span>
            <span className="text-xs tabular-nums text-ink-dim">{fmtTime(t.duration)}</span>
          </button>
          <button type="button" className={rowBtn} title="Играть следующим" aria-label={`Играть следующим: ${t.title}`}
                  onClick={() => void enqueue([t], true)}><ListPlus size={15} /></button>
          <button type="button" className={rowBtn} title="В конец очереди" aria-label={`В конец очереди: ${t.title}`}
                  onClick={() => void enqueue([t])}><ListEnd size={15} /></button>
        </li>
      ))}
    </ul>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-4">
      <h3 className="mb-1 px-2 text-xs font-semibold uppercase tracking-wide text-ink-dim">{title}</h3>
      {children}
    </section>
  );
}

function Tile({ label, sub, icon, onClick }: { label: string; sub?: string; icon: ReactNode; onClick(): void }) {
  return (
    <li>
      <button type="button" onClick={onClick} className="flex w-full items-center gap-3 rounded-card px-2 py-1.5 text-left hover:bg-white/5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded bg-accent-soft text-accent">{icon}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-ink">{label}</span>
          {sub && <span className="block truncate text-xs text-ink-dim">{sub}</span>}
        </span>
      </button>
    </li>
  );
}

export function YandexView({ query, startOn }: { query: string; startOn?: "playlists" }) {
  const client = useMediaClient();
  const playStation = useMusic((s) => s.playStation);
  const playTracks = useMusic((s) => s.playTracks);
  const [open, setOpen] = useState<Open | null>(startOn === "playlists" ? { kind: "playlists" } : null);
  const [reload, setReload] = useState(0);
  // Поиск идёт в сеть: ждём, пока закончат печатать.
  const [q, setQ] = useState(query.trim());
  useEffect(() => {
    const t = setTimeout(() => setQ(query.trim()), 400);
    return () => clearTimeout(t);
  }, [query]);
  // Результат привязан к ключу запроса: пока ключ не совпал — показываем загрузку.
  const key = JSON.stringify({ q, open, reload });
  const [res, setRes] = useState<{ key: string; data?: Data; error?: string } | null>(null);
  const data = res?.key === key ? res.data ?? null : null;
  const error = res?.key === key ? res.error ?? null : null;

  useEffect(() => {
    let alive = true;
    const items = (payload: Record<string, unknown>) =>
      client.call<{ items: Track[] }>("media_yandex", payload).then((r) => ({ tracks: r.items }));
    const load = async (): Promise<Data> => {
      if (open?.kind === "liked") return items({ op: "liked" });
      if (open?.kind === "album" || open?.kind === "artist" || open?.kind === "playlist") return items({ op: open.kind, id: open.id });
      if (open?.kind === "playlists") {
        return { playlists: (await client.call<{ items: Playlist[] }>("media_yandex", { op: "playlists" })).items };
      }
      if (q) return { found: await client.call<Found>("media_yandex", { op: "search_all", q }) };
      return {};
    };
    load().then((d) => alive && setRes({ key, data: d }))
      .catch((e) => alive && setRes({ key, error: errorText(e) || String(e) }));
    return () => { alive = false; };
  }, [client, q, open, key]);

  const showPlaylist = (p: Playlist) => setOpen({ kind: "playlist", id: p.id, title: p.name });
  const title = open && "title" in open ? open.title : open?.kind === "liked" ? "Мне нравится" : open?.kind === "playlists" ? "Плейлисты" : null;

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto px-2">
      <div className="flex flex-wrap items-center gap-2 pt-1">
        {open ? (
          <button type="button" className={chip} onClick={() => setOpen(null)}><ArrowLeft size={14} /> Назад</button>
        ) : (
          <>
            <button type="button" className={chip} onClick={() => void playStation("user:onyourwave")}><Radio size={14} /> Моя волна</button>
            <button type="button" className={chip} onClick={() => setOpen({ kind: "liked" })}><Heart size={14} /> Мне нравится</button>
            <button type="button" className={chip} onClick={() => setOpen({ kind: "playlists" })}><ListMusic size={14} /> Плейлисты</button>
          </>
        )}
        {title && <span className="truncate text-sm font-semibold text-ink">{title}</span>}
        {data?.tracks?.length ? (
          <button type="button" className={chip + " ml-auto"} onClick={() => void playTracks(data.tracks!)}>Играть всё</button>
        ) : null}
      </div>

      {error ? <ErrorState text={error} onRetry={() => setReload((x) => x + 1)} />
        : !data ? <Skeleton lines={6} />
        : data.tracks ? (data.tracks.length ? <TrackList tracks={data.tracks} /> : <EmptyState text="Здесь пока пусто" />)
        : data.playlists ? (
          data.playlists.length ? (
            <ul>{data.playlists.map((p) => <Tile key={p.id} label={p.name} sub={`${p.tracks} треков`} icon={<ListMusic size={15} />} onClick={() => showPlaylist(p)} />)}</ul>
          ) : <EmptyState text="Плейлистов пока нет" />
        ) : data.found ? (
          data.found.tracks.length + data.found.albums.length + data.found.artists.length + data.found.playlists.length === 0
            ? <EmptyState text="Ничего не найдено" />
            : (
              <div>
                {data.found.tracks.length > 0 && <Section title="Треки"><TrackList tracks={data.found.tracks} /></Section>}
                {data.found.artists.length > 0 && <Section title="Исполнители"><ul>{data.found.artists.map((a) => (
                  <Tile key={a.id} label={a.name} icon={<Mic2 size={15} />} onClick={() => setOpen({ kind: "artist", id: a.id, title: a.name })} />))}</ul></Section>}
                {data.found.albums.length > 0 && <Section title="Альбомы"><ul>{data.found.albums.map((a) => (
                  <Tile key={a.id} label={a.title} sub={[a.artist, a.year].filter(Boolean).join(" · ")} icon={<Disc3 size={15} />}
                        onClick={() => setOpen({ kind: "album", id: a.id, title: a.title })} />))}</ul></Section>}
                {data.found.playlists.length > 0 && <Section title="Плейлисты"><ul>{data.found.playlists.map((p) => (
                  <Tile key={p.id} label={p.name} sub={`${p.tracks} треков`} icon={<ListMusic size={15} />} onClick={() => showPlaylist(p)} />))}</ul></Section>}
              </div>
            )
        ) : <EmptyState text="Найдите трек, альбом или исполнителя в поиске сверху" />}
    </div>
  );
}

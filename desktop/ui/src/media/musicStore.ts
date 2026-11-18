// Стор музыкального плеера: очередь, воспроизведение, команды голосом (media_command),
// отчёт ядру о состоянии (media_state → current_track для сервера), уровень звука.
import { createStore } from "zustand";

import type { CoreClient } from "../api/client";
import { CoreError } from "../api/types";
import type { AudioEngine } from "./audioEngine";
import * as Q from "./queue";
import { fromLibrary, type LibraryTrack, type PlayStatus, type Track, type YandexShow } from "./types";

const WAVE = "user:onyourwave";
/** Сколько треков станции должно оставаться впереди, прежде чем подгрузить следующую порцию. */
const STATION_LOW_WATER = 2;

interface StationBatch { items: Track[]; batch_id?: string | null }
interface YandexPlay { tracks: Track[]; station?: string | null; batch_id?: string | null; shuffle?: boolean }
interface YandexEnqueue { tracks: Track[]; next?: boolean }

export interface MusicState {
  queue: Q.Queue;
  status: PlayStatus;
  position: number;
  duration: number;
  volume: number;           // 0..1
  muted: boolean;
  crossfade: number;        // секунды
  sinkId: string;
  cover: string | null;
  error: string | null;
  /** Станция Яндекса, которая продолжает очередь сама («Моя волна», радио по треку). */
  station: { id: string; batchId: string | null } | null;
  /** Последняя команда Сакуры показать экран Яндекс.Музыки. */
  yandexShow: YandexShow | null;

  playTracks(tracks: Track[], start?: number): Promise<void>;
  playStation(station: string): Promise<void>;
  enqueue(tracks: Track[], next?: boolean): Promise<void>;
  setYandexShow(show: YandexShow | null): void;
  playAt(index: number): Promise<void>;
  toggle(): Promise<void>;
  next(auto?: boolean): Promise<void>;
  /** «Назад» как в обычных плеерах: дальше 3 с — в начало трека, иначе предыдущий. */
  prev(): Promise<void>;
  /** Всегда предыдущий трек (голосом «предыдущий трек», двойной клик). */
  prevTrack(): Promise<void>;
  seek(t: number): void;
  seekBy(d: number): void;
  setVolume(v: number): void;
  volumeBy(pct: number): void;
  toggleMute(): void;
  toggleShuffle(): void;
  cycleRepeat(): void;
  move(from: number, to: number): void;
  playNext(t: Track): void;
  remove(i: number): void;
  setCrossfade(s: number): void;
  setSinkId(id: string): Promise<void>;
  like(): Promise<void>;
  dislike(): Promise<void>;
  command(cmd: string, arg?: unknown): Promise<void>;
  current(): Track | null;
}

const REPORT_EVERY_MS = 5000;

export function createMusicStore(client: CoreClient, engine: AudioEngine) {
  let lastReport = 0;
  let nearEndArmed = true;
  let stationLoading = false;

  const store = createStore<MusicState>()((set, get) => {
    const current = () => {
      const q = get().queue;
      return q.index >= 0 ? q.items[q.index] ?? null : null;
    };

    async function srcFor(t: Track): Promise<{ src: string; cover: string | null }> {
      if (t.source === "yandex") {
        const r = await client.call<{ src: string }>("media_yandex", { op: "stream", id: t.id });
        return { src: r.src, cover: t.cover ?? null };
      }
      const r = await client.call<{ src: string; cover: string | null }>("media_urls", { track_id: t.id });
      return { src: r.src, cover: r.cover };
    }

    function report(newTrack = false) {
      const t = current();
      const s = get();
      lastReport = Date.now();
      void client.call("media_state", {
        player: "music", status: s.status, source: t?.source ?? "", title: t?.title ?? "",
        artist: t?.artist ?? "", album: t?.album ?? "", position: s.position, duration: s.duration,
        track_id: t && t.source === "local" ? t.id : null, new_track: newTrack,
        ym_id: t && t.source === "yandex" ? t.id : null,
      }).catch(() => {});
    }

    /** Станция учится на прослушиваниях; сбой отзыва не должен мешать музыке. */
    function feedback(event: "trackStarted" | "trackFinished" | "skip", t: Track | null, played = 0) {
      const st = get().station;
      if (!st || !t || t.source !== "yandex") return;
      void client.call("media_yandex", { op: "feedback", station: st.id, event, id: t.id, played,
                                         batch_id: st.batchId }).catch(() => {});
    }

    /** Впереди мало треков — подгрузить следующую порцию станции. */
    async function topUpStation() {
      const st = get().station;
      const q = get().queue;
      if (!st || stationLoading || q.items.length - 1 - q.index > STATION_LOW_WATER) return;
      stationLoading = true;
      try {
        const last = q.items[q.items.length - 1];
        const r = await client.call<StationBatch>("media_yandex", { op: "station", station: st.id, after: last?.id });
        if (get().station?.id !== st.id) return;   // пока ждали, включили другое
        const known = new Set(get().queue.items.map((t) => t.id));
        const fresh = (r.items ?? []).filter((t) => !known.has(t.id));
        if (fresh.length) set({ queue: Q.append(get().queue, fresh), station: { id: st.id, batchId: r.batch_id ?? st.batchId } });
        void preloadNext();
      } catch {
        // сеть вернётся — попробуем на следующем треке
      } finally {
        stationLoading = false;
      }
    }

    async function preloadNext() {
      const q = get().queue;
      const n = Q.nextIndex(q, true);
      const t = n >= 0 ? q.items[n] : undefined;
      if (!t || n === q.index) return engine.preload(null);
      try {
        engine.preload((await srcFor(t)).src);
      } catch {
        engine.preload(null);
      }
    }

    async function start(index: number, crossfade = 0) {
      const q = get().queue;
      const t = q.items[index];
      if (!t) return;
      set({ queue: { ...q, index }, error: null, position: 0, duration: t.duration ?? 0 });
      try {
        const { src, cover } = await srcFor(t);
        set({ cover });
        if (crossfade > 0 || get().status === "playing") await engine.switchTo(src, crossfade);
        else await engine.load(src);
        set({ status: "playing" });
        nearEndArmed = true;
        report(true);
        feedback("trackStarted", t);
        void preloadNext();
        void topUpStation();
      } catch (e) {
        const msg = e instanceof CoreError && e.code === "yandex_unavailable"
          ? `${e.message}. Используйте внешний плеер.` : e instanceof Error ? e.message : "Не удалось воспроизвести";
        set({ status: "stopped", error: msg });
        report();
      }
    }

    engine.onTime((position, duration) => {
      set({ position, duration: duration || get().duration });
      const s = get();
      // Плавный переход: стартуем следующий за crossfade секунд до конца.
      if (s.crossfade > 0 && nearEndArmed && duration > 0 && duration - position <= s.crossfade) {
        const n = Q.nextIndex(s.queue, true);
        if (n >= 0 && n !== s.queue.index) {
          nearEndArmed = false;
          feedback("trackFinished", current(), position);
          void start(n, s.crossfade);
        }
      }
      if (Date.now() - lastReport >= REPORT_EVERY_MS) report();
    });
    engine.onEnded(() => {
      if (get().crossfade > 0 && !nearEndArmed) return; // уже ушли на следующий
      void get().next(true);
    });
    engine.onError((message) => {
      set({ error: message });
      void get().next(true);
    });
    engine.onLevel((bars) => {
      if (get().status === "playing") void client.call("media_level", { bars }).catch(() => {});
    });

    return {
      queue: Q.emptyQueue(),
      status: "stopped",
      position: 0,
      duration: 0,
      volume: 0.8,
      muted: false,
      crossfade: 0,
      sinkId: "default",
      cover: null,
      error: null,
      station: null,
      yandexShow: null,

      current,

      async playTracks(tracks, startAt = 0) {
        set({ queue: Q.setItems(get().queue, tracks, startAt), station: null });
        await start(get().queue.index);
      },
      async playStation(station) {
        try {
          const r = await client.call<StationBatch>("media_yandex", { op: "station", station });
          if (!r.items?.length) return set({ error: "Станция пока пуста" });
          set({ queue: Q.setItems({ ...get().queue, shuffle: false }, r.items, 0),
                station: { id: station, batchId: r.batch_id ?? null } });
          await start(0);
        } catch (e) {
          set({ error: e instanceof Error ? e.message : "Станция недоступна" });
        }
      },
      async enqueue(tracks, next = false) {
        if (!tracks.length) return;
        if (get().queue.index < 0) return get().playTracks(tracks);
        if (next) {
          let q = get().queue;
          for (const t of [...tracks].reverse()) q = Q.playNext(q, t);
          set({ queue: q });
        } else {
          set({ queue: Q.append(get().queue, tracks) });
        }
        void preloadNext();
      },
      setYandexShow: (show) => set({ yandexShow: show }),
      playAt: (i) => start(i),

      async toggle() {
        const s = get();
        if (s.status === "playing") {
          engine.pause();
          set({ status: "paused" });
          report();
        } else if (s.queue.index >= 0) {
          if (s.status === "stopped") return start(s.queue.index);
          await engine.play();
          set({ status: "playing" });
          report();
        }
      },

      async next(auto = false) {
        feedback(auto ? "trackFinished" : "skip", current(), get().position);
        // Станция не кончается: порция могла не успеть подгрузиться к концу трека.
        if (Q.nextIndex(get().queue, auto) < 0 && get().station) await topUpStation();
        const n = Q.nextIndex(get().queue, auto);
        if (n < 0) {
          engine.pause();
          set({ status: "stopped", position: 0 });
          report();
          return;
        }
        if (auto && n === get().queue.index) {
          engine.seek(0);
          await engine.play();
          return;
        }
        await start(n);
      },

      async prev() {
        if (get().position > 3) return get().seek(0);
        return get().prevTrack();
      },

      async prevTrack() {
        const p = Q.prevIndex(get().queue);
        if (p >= 0) await start(p);
        else get().seek(0);
      },

      seek(t) {
        engine.seek(t);
        set({ position: t });
        report();
      },
      seekBy(d) {
        get().seek(Math.max(0, get().position + d));
      },
      setVolume(v) {
        const vol = Math.max(0, Math.min(1, v));
        engine.setVolume(vol);
        set({ volume: vol });
      },
      volumeBy(pct) {
        get().setVolume(get().volume + pct / 100);
      },
      toggleMute() {
        engine.setMuted(!get().muted);
        set({ muted: !get().muted });
      },
      toggleShuffle() {
        set({ queue: Q.setShuffle(get().queue, !get().queue.shuffle) });
        void preloadNext();
      },
      cycleRepeat() {
        set({ queue: { ...get().queue, repeat: Q.cycleRepeat(get().queue.repeat) } });
        void preloadNext();
      },
      move(from, to) {
        set({ queue: Q.move(get().queue, from, to) });
        void preloadNext();
      },
      playNext(t) {
        set({ queue: Q.playNext(get().queue, t) });
        void preloadNext();
      },
      remove(i) {
        const wasCurrent = i === get().queue.index;
        set({ queue: Q.removeAt(get().queue, i) });
        if (wasCurrent && get().queue.index >= 0 && get().status === "playing") void start(get().queue.index);
        else void preloadNext();
      },
      setCrossfade(s) {
        set({ crossfade: Math.max(0, Math.min(12, s)) });
      },
      async setSinkId(id) {
        await engine.setSinkId(id);
        set({ sinkId: id });
      },

      async like() {
        const t = current();
        if (!t) return;
        if (t.source === "yandex") await client.call("media_yandex", { op: "like", id: t.id, on: true });
        else await client.call("media_playlist", { op: "like", track_id: t.id });
      },
      async dislike() {
        const t = current();
        if (t?.source === "yandex") await client.call("media_yandex", { op: "like", id: t.id, on: false }).catch(() => {});
        await get().next();
      },

      async command(cmd, arg) {
        const s = get();
        switch (cmd) {
          case "toggle": return s.toggle();
          case "pause": if (s.status === "playing") return s.toggle(); return;
          case "next": return s.next();
          case "prev": return s.prev();
          case "prevTrack": return s.prevTrack();
          case "seek": return s.seek(Number(arg) || 0);
          case "seekBy": return s.seekBy(Number(arg) || 0);
          case "shuffle": return s.toggleShuffle();
          case "repeat": return s.cycleRepeat();
          case "mute": return s.toggleMute();
          case "volumeBy": return s.volumeBy(Number(arg) || 0);
          case "volumeSet": return s.setVolume((Number(arg) || 0) / 100);
          case "ym_play": {
            const a = arg as YandexPlay;
            const shuffle = !!a.shuffle;
            const startAt = shuffle ? Math.floor(Math.random() * a.tracks.length) : 0;
            set({ queue: Q.setItems({ ...get().queue, shuffle }, a.tracks, startAt),
                  station: a.station ? { id: a.station, batchId: a.batch_id ?? null } : null });
            return start(get().queue.index);
          }
          case "ym_enqueue": {
            const a = arg as YandexEnqueue;
            return s.enqueue(a.tracks, !!a.next);
          }
          case "ym_show": return s.setYandexShow(arg as YandexShow);
          case "queue_clear":
            set({ queue: Q.clearUpcoming(get().queue), station: null });
            return engine.preload(null);
          case "queue_remove": return s.remove(Number(arg));
          case "like": return s.like();
          case "dislike": return s.dislike();
          case "play_liked": {
            const pls = await client.call<{ items: { id: number; name: string }[] }>("media_library", { view: "playlists" });
            const fav = pls.items.find((p) => p.name === "Любимое");
            if (fav) {
              const r = await client.call<{ items: LibraryTrack[] }>("media_playlist", { op: "tracks", id: fav.id });
              if (r.items.length) return s.playTracks(r.items.map(fromLibrary));
            }
            const ym = await client.call<{ items: Track[] }>("media_yandex", { op: "liked" }).catch(() => ({ items: [] }));
            if (ym.items.length) return s.playTracks(ym.items);
            set({ error: "«Любимое» пока пусто" });
            return;
          }
          case "wave": return s.playStation(WAVE);
        }
      },
    };
  });

  // Ядру нужна очередь, чтобы Сакура могла ответить, что играет дальше и убрать трек по названию.
  store.subscribe((s, prev) => {
    if (s.queue.items === prev.queue.items && s.queue.index === prev.queue.index) return;
    void client.call("media_queue", { index: s.queue.index,
      items: s.queue.items.map((t) => ({ title: t.title, artist: t.artist })) }).catch(() => {});
  });
  return store;
}

export type MusicStore = ReturnType<typeof createMusicStore>;

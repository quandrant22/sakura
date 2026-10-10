// Стор видеоплеера. Сам <video>/iframe живёт в компоненте и регистрирует контроллер;
// стор держит источник и состояние, исполняет голосовые команды и сообщает ядру.
import { createStore } from "zustand";

import type { CoreClient } from "../api/client";
import type { PlayStatus } from "./types";

export interface Subtitle {
  index: number;
  label: string;
  src: string;
}

export type VideoSource =
  | { kind: "local"; trackId: number; title: string; src: string; subtitles: Subtitle[]; siblings: number[]; start: number }
  | { kind: "file" | "hls"; url: string; title: string; start: number }
  | { kind: "youtube"; videoId: string; playerUrl: string; title: string; start: number };

export interface VideoController {
  toggle(): void;
  pause(): void;
  seekBy(d: number): void;
  setRate(r: number): void;
  fullscreen(): void;
  setSubtitle(i: number): void;
  currentTime(): number;
}

export interface VideoState {
  source: VideoSource | null;
  status: PlayStatus;
  position: number;
  duration: number;
  rate: number;
  subtitle: number;           // -1 — выкл
  theater: boolean;
  mini: boolean;
  error: string | null;
  embedBlocked: boolean;      // YouTube 101/150 — встраивание запрещено

  open(src: VideoSource): void;
  close(): void;
  attach(c: VideoController | null): void;
  onPlayer(ev: { status?: PlayStatus; position?: number; duration?: number; title?: string }): void;
  onYoutubeError(code: number): void;
  onMediaError(message: string): void;
  setRate(r: number): void;
  cycleSubtitle(): void;
  setSubtitle(i: number): void;
  openNeighbour(step: 1 | -1): Promise<void>;
  setMini(on: boolean): void;
  command(cmd: string, arg?: unknown): Promise<void>;
}

export const RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
const clampRate = (r: number) => Math.max(0.5, Math.min(2, Math.round(r * 4) / 4));
const YT_ERRORS: Record<number, string> = {
  2: "Неверный адрес видео", 5: "Плеер YouTube не смог воспроизвести видео", 100: "Видео удалено или скрыто",
  101: "Автор запретил встраивание этого видео", 150: "Автор запретил встраивание этого видео",
  153: "YouTube не принял источник встраивания",
};

export function createVideoStore(client: CoreClient) {
  let ctl: VideoController | null = null;
  let lastReport = 0;

  const store = createStore<VideoState>()((set, get) => {
    const sourceKind = (s: VideoSource | null) => (s?.kind === "youtube" ? "youtube" : s?.kind === "local" ? "local" : "url");

    function report(force = false) {
      const s = get();
      if (!force && Date.now() - lastReport < 5000) return;
      lastReport = Date.now();
      void client.call("media_state", {
        player: "video", status: s.status, source: sourceKind(s.source), title: s.source?.title ?? "",
        position: s.position, duration: s.duration,
      }).catch(() => {});
      if (s.source?.kind === "local" && s.position > 0) {
        void client.call("media_position", { track_id: s.source.trackId, position: s.position }).catch(() => {});
      }
    }

    return {
      source: null, status: "stopped", position: 0, duration: 0, rate: 1, subtitle: -1,
      theater: false, mini: false, error: null, embedBlocked: false,

      open(source) {
        set({ source, status: "stopped", position: source.start, duration: 0, error: null, embedBlocked: false,
              subtitle: source.kind === "local" && source.subtitles.length ? 0 : -1 });
      },
      close() {
        report(true);
        set({ source: null, status: "stopped", position: 0, duration: 0, mini: false });
        report(true);
      },
      attach(c) {
        ctl = c;
      },
      onPlayer(ev) {
        const prev = get().status;
        set({
          ...(ev.status ? { status: ev.status } : {}),
          ...(ev.position != null ? { position: ev.position } : {}),
          ...(ev.duration ? { duration: ev.duration } : {}),
          ...(ev.title && get().source ? { source: { ...get().source!, title: ev.title } } : {}),
        });
        report(ev.status !== undefined && ev.status !== prev);
      },
      onYoutubeError(code) {
        set({ error: YT_ERRORS[code] ?? `Ошибка YouTube ${code}`, embedBlocked: code === 101 || code === 150 || code === 153,
              status: "stopped" });
        report(true);
      },
      onMediaError(message) {
        set({ error: message, status: "stopped" });
        report(true);
      },
      setRate(r) {
        const rate = clampRate(r);
        ctl?.setRate(rate);
        set({ rate });
      },
      setSubtitle(i) {
        ctl?.setSubtitle(i);
        set({ subtitle: i });
      },
      cycleSubtitle() {
        const s = get().source;
        const n = s?.kind === "local" ? s.subtitles.length : 0;
        if (!n) return;
        const next = get().subtitle + 1 >= n ? -1 : get().subtitle + 1;
        get().setSubtitle(next);
      },
      async openNeighbour(step) {
        const s = get().source;
        if (s?.kind !== "local") return;
        const i = s.siblings.indexOf(s.trackId) + step;
        const id = s.siblings[i];
        if (id === undefined) return;
        await openLocalVideo(client, store, id, s.title);
      },
      setMini(on) {
        set({ mini: on });
      },
      async command(cmd, arg) {
        switch (cmd) {
          case "toggle": return ctl?.toggle();
          case "pause": return ctl?.pause();
          case "seekBy": return ctl?.seekBy(Number(arg) || 0);
          case "rateBy": return get().setRate(get().rate + (Number(arg) || 0));
          case "next": return get().openNeighbour(1);
          case "prev": return get().openNeighbour(-1);
          case "fullscreen": return ctl?.fullscreen();
          case "subtitles": return get().cycleSubtitle();
          case "theater": return set({ theater: !get().theater });
          case "mini": return set({ mini: !get().mini });
        }
      },
    };
  });
  return store;
}

/** Открыть локальное видео из медиатеки: ссылки, субтитры, сохранённая позиция, соседи по папке. */
export async function openLocalVideo(client: CoreClient, store: VideoStore, trackId: number, fallbackTitle = "") {
  const r = await client.call<{ src: string; subtitles: Subtitle[]; position: number; siblings: number[] }>(
    "media_urls", { track_id: trackId });
  store.getState().open({ kind: "local", trackId, title: fallbackTitle, src: r.src, subtitles: r.subtitles,
                          siblings: r.siblings, start: r.position || 0 });
}

export type VideoStore = ReturnType<typeof createVideoStore>;

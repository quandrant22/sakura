// Контекст медиа: сторы плееров, звуковой движок, события ядра (media_command,
// audio_duck, media_settings, media_scan) и системные элементы Windows (mediaSession).
import { createContext, type ReactNode, useContext, useEffect, useMemo } from "react";
import { createStore, type StoreApi, useStore } from "zustand";

import type { CoreClient } from "../api/client";
import type { CoreEvent } from "../api/types";
import { bridge } from "../bridge";
import { type AudioEngine, HtmlAudioEngine } from "./audioEngine";
import { createMusicStore, type MusicState, type MusicStore } from "./musicStore";
import type { MediaCommand, MediaSettings } from "./types";
import { createVideoStore, type VideoState, type VideoStore } from "./videoStore";

export interface MediaMeta {
  settings: MediaSettings | null;
  scan: { state: string; done?: number; total?: number; added?: number; removed?: number } | null;
  duck: { music: number; video: number };
  libraryVersion: number;     // растёт после сканирования — списки перезагружаются
}

interface Ctx {
  client: CoreClient;
  music: MusicStore;
  video: VideoStore;
  meta: StoreApi<MediaMeta>;
}

const MediaCtx = createContext<Ctx | null>(null);

/** Без Web Audio (тесты, jsdom) — движок-заглушка. */
class NullEngine implements AudioEngine {
  async load() {}
  preload() {}
  async switchTo() {}
  async play() {}
  pause() {}
  seek() {}
  setVolume() {}
  setMuted() {}
  setDuck() {}
  async setSinkId() {}
  onTime() {}
  onEnded() {}
  onError() {}
  onLevel() {}
}

export function MediaProvider({ client, children }: { client: CoreClient; children: ReactNode }) {
  const ctx = useMemo<Ctx>(() => {
    const engine: AudioEngine = typeof AudioContext === "undefined" ? new NullEngine() : new HtmlAudioEngine();
    const meta = createStore<MediaMeta>()(() => ({ settings: null, scan: null, duck: { music: 1, video: 1 },
                                                   libraryVersion: 0 }));
    const music = createMusicStore(client, engine);
    const video = createVideoStore(client);
    client.onEvent((ev: CoreEvent) => {
      switch (ev.type) {
        case "media_command": {
          const c = ev as unknown as MediaCommand;
          if (c.player === "all") {
            if (music.getState().status === "playing") void music.getState().toggle();
            void video.getState().command("pause");
          } else if (c.player === "music") void music.getState().command(c.cmd, c.arg);
          else void video.getState().command(c.cmd, c.arg);
          break;
        }
        case "audio_duck": {
          const d = ev as unknown as { gains: { music: number; video: number }; ramp_ms: number };
          engine.setDuck(d.gains.music, d.ramp_ms);
          meta.setState({ duck: d.gains });
          break;
        }
        case "media_settings": {
          const s = (ev as unknown as { settings: MediaSettings }).settings;
          meta.setState({ settings: s });
          music.getState().setCrossfade(s.crossfade_s);
          void bridge().media.setProxy(s.youtube_proxy ?? "");
          break;
        }
        case "media_scan": {
          const s = ev as unknown as MediaMeta["scan"];
          meta.setState((m) => ({ scan: s, libraryVersion: s?.state === "done" ? m.libraryVersion + 1 : m.libraryVersion }));
          break;
        }
        case "game_mode":
          // Игровой режим прячет мини-окно видео.
          if ((ev as unknown as { on: boolean }).on) video.getState().setMini(false);
          break;
      }
    });
    return { client, music, video, meta };
  }, [client]);

  // Медиаклавиши и системная плашка Windows (SMTC) для встроенной музыки.
  useEffect(() => {
    const ms = typeof navigator !== "undefined" ? navigator.mediaSession : undefined;
    if (!ms) return;
    const m = ctx.music;
    ms.setActionHandler("play", () => void m.getState().toggle());
    ms.setActionHandler("pause", () => void m.getState().toggle());
    ms.setActionHandler("nexttrack", () => void m.getState().next());
    ms.setActionHandler("previoustrack", () => void m.getState().prev());
    ms.setActionHandler("seekto", (d) => d.seekTime != null && m.getState().seek(d.seekTime));
    return m.subscribe((s, prev) => {
      const t = s.current();
      if (t && (t !== prev.current() || s.cover !== prev.cover) && typeof MediaMetadata !== "undefined") {
        ms.metadata = new MediaMetadata({ title: t.title, artist: t.artist, album: t.album,
                                          artwork: s.cover ? [{ src: s.cover }] : [] });
      }
      if (s.status !== prev.status) ms.playbackState = s.status === "playing" ? "playing" : s.status === "paused" ? "paused" : "none";
    });
  }, [ctx]);

  return <MediaCtx.Provider value={ctx}>{children}</MediaCtx.Provider>;
}

function useCtx(): Ctx {
  const c = useContext(MediaCtx);
  if (!c) throw new Error("нет MediaProvider");
  return c;
}

export const useMediaClient = () => useCtx().client;
export const useMusic = <T,>(sel: (s: MusicState) => T): T => useStore(useCtx().music, sel);
export const useVideo = <T,>(sel: (s: VideoState) => T): T => useStore(useCtx().video, sel);
export const useMediaMeta = <T,>(sel: (s: MediaMeta) => T): T => useStore(useCtx().meta, sel);
export const useVideoStore = () => useCtx().video;
export const useMusicStore = () => useCtx().music;

// Типы медиа (desktop/docs/media.md).
export interface Track {
  id: number | string;          // число — медиатека; "ym:123" — Яндекс.Музыка
  source: "local" | "yandex";
  title: string;
  artist: string;
  album: string;
  duration: number | null;
  cover?: string | null;        // URL обложки (медиасервер или Яндекс)
  cover_hash?: string | null;
  track_no?: number | null;
}

export type PlayStatus = "stopped" | "playing" | "paused";
export type RepeatMode = "off" | "all" | "one";

export interface MediaCommand {
  player: "music" | "video" | "all";
  cmd: string;
  arg?: unknown;
}

export interface LibraryTrack {
  id: number;
  path: string;
  kind: "audio" | "video";
  title: string;
  artist: string;
  album: string;
  album_artist: string;
  track_no: number | null;
  year: number | null;
  duration: number | null;
  cover_hash: string | null;
  cover?: string | null;
}

export interface MediaSettings {
  music_folders: string[];
  video_folders: string[];
  crossfade_s: number;
  player_duck_pct: number;
  youtube_mode: "embedded" | "remote";
  youtube_proxy: string;
  music_yandex: boolean;
  yandex_note?: string;
  media_origin?: string | null;
}

export const fromLibrary = (t: LibraryTrack): Track => ({
  id: t.id, source: "local", title: t.title, artist: t.artist, album: t.album,
  duration: t.duration, cover_hash: t.cover_hash, cover: t.cover ?? null, track_no: t.track_no,
});

export function fmtTime(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return "–:––";
  const t = Math.max(0, Math.floor(s));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = String(t % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

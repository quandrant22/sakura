// Экран «Медиа → Видео»: локальные файлы (плейлист папки, позиция, субтитры), ссылки
// (.mp4/.webm/.m3u8 через hls.js), YouTube embedded (страница IFrame API с media_server).
// Поверх плеера YouTube ничего не рисуем, во фрейм youtube.com ничего не внедряем.
import { ExternalLink, Film, Globe, Maximize, MonitorUp, PictureInPicture2, Rows3, SkipBack, SkipForward,
         Subtitles, Undo2, Wifi } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { bridge } from "../../bridge";
import { errorText } from "../../store";
import { useMediaClient, useMediaMeta, useVideo, useVideoStore } from "../../media/MediaContext";
import { fmtTime, type LibraryTrack } from "../../media/types";
import { openLocalVideo, RATES } from "../../media/videoStore";
import { EmptyState, ErrorState, Skeleton } from "../ui";

type Check = Record<string, { ok: boolean; status?: number; error?: string }>;
const btn = "flex items-center gap-1.5 rounded-card border border-line px-2.5 py-1.5 text-xs text-ink-dim hover:border-accent hover:text-ink disabled:opacity-40";

function NativeVideo() {
  const store = useVideoStore();
  const source = useVideo((s) => s.source);
  const subtitle = useVideo((s) => s.subtitle);
  const duck = useMediaMeta((s) => s.duck.video);
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const v = ref.current;
    if (!v || !source || source.kind === "youtube") return;
    let hls: { destroy(): void } | null = null;
    const url = source.kind === "local" ? source.src : source.url;
    if (source.kind === "hls" && !v.canPlayType("application/vnd.apple.mpegurl")) {
      void import("hls.js").then(({ default: Hls }) => {
        if (!Hls.isSupported()) return store.getState().onMediaError("Поток HLS не поддерживается");
        const h = new Hls();
        h.on(Hls.Events.ERROR, (_e, d) => d.fatal && store.getState().onMediaError("Поток недоступен"));
        h.loadSource(url);
        h.attachMedia(v);
        hls = h;
      });
    } else {
      v.src = url;
    }
    v.currentTime = source.start || 0;
    void v.play().catch(() => {});
    store.getState().attach({
      toggle: () => (v.paused ? void v.play() : v.pause()),
      pause: () => v.pause(),
      seekBy: (d) => { v.currentTime = Math.max(0, v.currentTime + d); },
      setRate: (r) => { v.playbackRate = r; },
      fullscreen: () => (document.fullscreenElement ? void document.exitFullscreen() : void v.requestFullscreen()),
      setSubtitle: (i) => Array.from(v.textTracks).forEach((t, k) => { t.mode = k === i ? "showing" : "disabled"; }),
      currentTime: () => v.currentTime,
    });
    return () => {
      store.getState().attach(null);
      hls?.destroy();
      v.removeAttribute("src");
      v.load();
    };
  }, [source, store]);

  useEffect(() => {
    const v = ref.current;
    if (v) Array.from(v.textTracks).forEach((t, k) => { t.mode = k === subtitle ? "showing" : "disabled"; });
  }, [subtitle, source]);
  useEffect(() => {
    if (ref.current) ref.current.volume = Math.max(0, Math.min(1, duck));
  }, [duck]);

  // Мини-окно для локального видео и потоков — системная «картинка в картинке» (поверх всех окон).
  const mini = useVideo((s) => s.mini);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    const leave = () => store.getState().setMini(false);
    v.addEventListener("leavepictureinpicture", leave);
    if (mini && document.pictureInPictureElement !== v) void v.requestPictureInPicture?.().catch(() => store.getState().setMini(false));
    if (!mini && document.pictureInPictureElement) void document.exitPictureInPicture();
    return () => v.removeEventListener("leavepictureinpicture", leave);
  }, [mini, store]);

  const s = store.getState();
  return (
    <video ref={ref} controls className="h-full w-full bg-black" aria-label="Видео"
           onPlay={() => s.onPlayer({ status: "playing" })} onPause={() => s.onPlayer({ status: "paused" })}
           onEnded={() => { s.onPlayer({ status: "stopped" }); void s.openNeighbour(1); }}
           onTimeUpdate={(e) => s.onPlayer({ position: e.currentTarget.currentTime, duration: e.currentTarget.duration })}
           onError={(e) => {
             const code = e.currentTarget.error?.code;
             s.onMediaError(code === 4 ? "Этот формат не воспроизводится в окне" : "Не удалось воспроизвести видео");
           }}>
      {source?.kind === "local" && source.subtitles.map((t) => (
        <track key={t.index} kind="subtitles" src={t.src} label={t.label} default={t.index === 0} />
      ))}
    </video>
  );
}

function YoutubeFrame() {
  const store = useVideoStore();
  const source = useVideo((s) => s.source);
  const mini = useVideo((s) => s.mini);
  const duck = useMediaMeta((s) => s.duck.video);
  const frame = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    if (source?.kind !== "youtube") return;
    const post = (cmd: string, extra: Record<string, unknown> = {}) =>
      frame.current?.contentWindow?.postMessage({ target: "sakura-yt", cmd, ...extra }, new URL(source.playerUrl).origin);
    const onMsg = (ev: MessageEvent) => {
      if (ev.source !== frame.current?.contentWindow) return;
      const m = ev.data as { source?: string; event?: string; state?: number; time?: number; duration?: number; code?: number; title?: string };
      if (m?.source !== "sakura-yt") return;
      const st = store.getState();
      if (m.event === "error" && m.code != null) st.onYoutubeError(m.code);
      if (m.event === "time") st.onPlayer({ position: m.time });
      if (m.event === "state" || m.event === "ready") {
        // YT: 1 — играет, 2 — пауза, 0 — закончилось
        const status = m.state === 1 ? "playing" : m.state === 2 ? "paused" : m.state === 0 ? "stopped" : undefined;
        st.onPlayer({ status, position: m.time, duration: m.duration, title: m.title });
      }
    };
    window.addEventListener("message", onMsg);
    store.getState().attach({
      toggle: () => post("toggle"), pause: () => post("pause"), seekBy: (d) => post("seekBy", { delta: d }),
      setRate: (r) => post("rate", { rate: r }), setSubtitle: () => {}, currentTime: () => store.getState().position,
      fullscreen: () => (document.fullscreenElement ? void document.exitFullscreen() : void frame.current?.requestFullscreen()),
    });
    return () => {
      window.removeEventListener("message", onMsg);
      store.getState().attach(null);
    };
  }, [source, store]);

  useEffect(() => {
    if (source?.kind === "youtube") {
      frame.current?.contentWindow?.postMessage({ target: "sakura-yt", cmd: "volume", volume: Math.round(duck * 100) },
                                                new URL(source.playerUrl).origin);
    }
  }, [duck, source]);

  // Мини-окно YouTube — отдельное окно Electron поверх всех окон с той же страницей плеера.
  useEffect(() => {
    if (source?.kind !== "youtube") return;
    if (mini) {
      const pos = Math.floor(store.getState().position);
      frame.current?.contentWindow?.postMessage({ target: "sakura-yt", cmd: "pause" }, new URL(source.playerUrl).origin);
      void bridge().media.openMini(source.playerUrl.replace(/start=\d+/, `start=${pos}`));
    } else {
      void bridge().media.closeMini();
    }
  }, [mini, source, store]);
  useEffect(() => bridge().media.onMiniClosed(() => store.getState().setMini(false)), [store]);

  if (source?.kind !== "youtube") return null;
  return (
    <iframe ref={frame} title="YouTube" src={source.playerUrl} className="h-full w-full border-0 bg-black"
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin" />
  );
}

function Sources({ onError }: { onError(msg: string | null): void }) {
  const client = useMediaClient();
  const store = useVideoStore();
  const version = useMediaMeta((s) => s.libraryVersion);
  const ytMode = useMediaMeta((s) => s.settings?.youtube_mode ?? "embedded");
  const current = useVideo((s) => (s.source?.kind === "local" ? s.source.trackId : null));
  const [items, setItems] = useState<LibraryTrack[] | null>(null);
  const [url, setUrl] = useState("");

  useEffect(() => {
    client.call<{ items: LibraryTrack[] }>("media_library", { view: "tracks", kind: "video", limit: 5000 })
      .then((r) => setItems(r?.items ?? [])).catch(() => setItems([]));
  }, [client, version]);

  const openUrl = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const r = await client.call<{ kind: string; video_id?: string; player_url?: string; start?: number; url?: string }>(
        "media_open_url", { url });
      if (r.kind === "youtube" && ytMode === "remote") {
        // YOUTUBE_MODE=remote — видео открывается во вкладке браузера (команды идут через расширение).
        await client.call("media_youtube_to_browser", { video_id: r.video_id, time: r.start ?? 0 });
      } else if (r.kind === "youtube") store.getState().open({ kind: "youtube", videoId: r.video_id!, playerUrl: r.player_url!, title: "YouTube", start: r.start ?? 0 });
      else store.getState().open({ kind: r.kind as "file" | "hls", url: r.url!, title: url, start: 0 });
      onError(null);
    } catch (err) {
      onError(errorText(err) || String(err));
    }
  };

  const fromBrowser = async () => {
    try {
      const r = await client.call<{ video_id: string; player_url: string; start: number; title: string }>("media_youtube_from_browser");
      store.getState().open({ kind: "youtube", videoId: r.video_id, playerUrl: r.player_url, title: r.title, start: r.start });
      onError(null);
    } catch (err) {
      onError(errorText(err) || String(err));
    }
  };

  return (
    <aside className="flex w-[280px] shrink-0 flex-col gap-3">
      <form onSubmit={openUrl} className="rounded-panel border border-line bg-panel p-3">
        <div className="mb-2 flex items-center gap-1.5 text-xs text-ink-dim"><Globe size={13} /> Ссылка: YouTube, .mp4, .webm, .m3u8</div>
        <div className="flex gap-1.5">
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" aria-label="Ссылка на видео"
                 className="min-w-0 flex-1 rounded-lg border border-line bg-panel2 px-2 py-1.5 text-xs text-ink outline-none focus:border-accent" />
          <button type="submit" disabled={!url.trim()} className="rounded-lg bg-accent px-2.5 text-xs text-white disabled:opacity-40">Открыть</button>
        </div>
        <button type="button" onClick={() => void fromBrowser()} className={btn + " mt-2 w-full justify-center"}>
          <MonitorUp size={13} /> Взять видео из браузера
        </button>
      </form>
      <section className="flex min-h-0 flex-1 flex-col rounded-panel border border-line bg-panel">
        <header className="flex items-center gap-1.5 px-3 pb-1 pt-3 text-sm font-semibold text-ink"><Film size={15} className="text-accent" /> Видео из папок</header>
        {items === null ? <Skeleton lines={4} /> : items.length === 0 ? (
          <EmptyState text="Добавьте папки с видео: Настройки → Медиа" />
        ) : (
          <ul className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
            {items.map((v) => (
              <li key={v.id}>
                <button type="button" onClick={() => void openLocalVideo(client, store, v.id, v.title).catch((e) => onError(errorText(e)))}
                        className={"w-full truncate rounded-card px-2 py-1.5 text-left text-sm " + (current === v.id ? "bg-accent-soft text-accent" : "text-ink hover:bg-white/5")}>
                  {v.title}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </aside>
  );
}

function ConnectionCheck() {
  const client = useMediaClient();
  const [check, setCheck] = useState<Check | null>(null);
  useEffect(() => {
    client.call<Check>("media_youtube_check").then((r) => setCheck(r ?? null)).catch(() => setCheck(null));
  }, [client]);
  if (!check) return null;
  return (
    <div className="flex items-center gap-3 text-[11px] text-ink-dim" aria-label="Связь с YouTube">
      <Wifi size={12} />
      {Object.entries(check).map(([host, r]) => (
        <span key={host} className={r.ok ? "text-online" : "text-accent"}>{host} {r.ok ? "✓" : "✗"}</span>
      ))}
    </div>
  );
}

export function VideoView() {
  const client = useMediaClient();
  const store = useVideoStore();
  const source = useVideo((s) => s.source);
  const status = useVideo((s) => s.status);
  const position = useVideo((s) => s.position);
  const duration = useVideo((s) => s.duration);
  const rate = useVideo((s) => s.rate);
  const subtitle = useVideo((s) => s.subtitle);
  const theater = useVideo((s) => s.theater);
  const mini = useVideo((s) => s.mini);
  const error = useVideo((s) => s.error);
  const embedBlocked = useVideo((s) => s.embedBlocked);
  const [srcError, setSrcError] = useState<string | null>(null);
  const v = store.getState();
  const local = source?.kind === "local" ? source : null;
  const yt = source?.kind === "youtube" ? source : null;

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      {!theater && <Sources onError={setSrcError} />}
      <section className="flex min-h-0 flex-1 flex-col rounded-panel border border-line bg-panel p-3 shadow-soft">
        <div className="mb-2 flex items-center gap-2">
          <h2 className="truncate text-sm font-semibold text-ink">{source?.title || "Видео"}</h2>
          <span className="ml-auto"><ConnectionCheck /></span>
        </div>
        <div className="relative min-h-0 flex-1 overflow-hidden rounded-card bg-black">
          {!source ? (
            <EmptyState text="Выберите видео из папок, вставьте ссылку или возьмите видео из браузера" />
          ) : yt ? <YoutubeFrame /> : <NativeVideo />}
        </div>
        {(error || srcError) && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <ErrorState text={(error ?? srcError)!} />
            {embedBlocked && yt && (
              <button type="button" className={btn} onClick={() => void client.call("media_youtube_to_browser", { video_id: yt.videoId, time: position })}>
                <ExternalLink size={13} /> Открыть в браузере
              </button>
            )}
            {local && error && (
              <button type="button" className={btn} onClick={() => void client.call("media_open_external", { track_id: local.trackId })}>
                <ExternalLink size={13} /> Открыть во внешнем проигрывателе
              </button>
            )}
          </div>
        )}
        {source && (
          <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="Управление видео">
            <button type="button" className={btn} disabled={!local} onClick={() => void v.openNeighbour(-1)} aria-label="Предыдущий файл"><SkipBack size={13} /></button>
            <button type="button" className={btn} disabled={!local} onClick={() => void v.openNeighbour(1)} aria-label="Следующий файл"><SkipForward size={13} /></button>
            <span className="text-xs tabular-nums text-ink-dim">{fmtTime(position)} / {fmtTime(duration)} · {status === "playing" ? "играет" : status === "paused" ? "пауза" : "стоп"}</span>
            <label className="ml-2 flex items-center gap-1 text-xs text-ink-dim">Скорость
              <select value={rate} onChange={(e) => v.setRate(Number(e.target.value))} aria-label="Скорость"
                      className="rounded-lg border border-line bg-panel2 px-1.5 py-1 text-xs text-ink">
                {RATES.map((r) => <option key={r} value={r}>{r}×</option>)}
              </select>
            </label>
            {local && local.subtitles.length > 0 && (
              <label className="flex items-center gap-1 text-xs text-ink-dim"><Subtitles size={13} />
                <select value={subtitle} onChange={(e) => v.setSubtitle(Number(e.target.value))} aria-label="Субтитры"
                        className="rounded-lg border border-line bg-panel2 px-1.5 py-1 text-xs text-ink">
                  <option value={-1}>Выкл</option>
                  {local.subtitles.map((t) => <option key={t.index} value={t.index}>{t.label}</option>)}
                </select>
              </label>
            )}
            <div className="ml-auto flex items-center gap-2">
              {yt && (
                <button type="button" className={btn} onClick={() => { v.command("pause"); void client.call("media_youtube_to_browser", { video_id: yt.videoId, time: position }); }}>
                  <Undo2 size={13} /> Вернуть в браузер
                </button>
              )}
              <button type="button" className={btn} aria-pressed={theater} onClick={() => void v.command("theater")}><Rows3 size={13} /> Широкий</button>
              <button type="button" className={btn} aria-pressed={mini} onClick={() => v.setMini(!mini)}><PictureInPicture2 size={13} /> Мини-окно</button>
              <button type="button" className={btn} onClick={() => void v.command("fullscreen")}><Maximize size={13} /> Полный экран</button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

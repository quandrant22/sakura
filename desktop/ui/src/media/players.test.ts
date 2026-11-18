import { describe, expect, test, vi } from "vitest";

import type { CoreClient } from "../api/client";
import { CoreError } from "../api/types";
import type { AudioEngine } from "./audioEngine";
import { createMusicStore } from "./musicStore";
import type { Track } from "./types";
import { createVideoStore, openLocalVideo } from "./videoStore";

class FakeEngine implements AudioEngine {
  log: string[] = [];
  time: (p: number, d: number) => void = () => {};
  ended: () => void = () => {};
  async load(src: string) { this.log.push(`load ${src}`); }
  preload(src: string | null) { this.log.push(`preload ${src}`); }
  async switchTo(src: string, s: number) { this.log.push(`switch ${src} ${s}`); }
  async play() { this.log.push("play"); }
  pause() { this.log.push("pause"); }
  seek(t: number) { this.log.push(`seek ${t}`); }
  setVolume(v: number) { this.log.push(`vol ${v.toFixed(2)}`); }
  setMuted(m: boolean) { this.log.push(`mute ${m}`); }
  setDuck() {}
  async setSinkId(id: string) { this.log.push(`sink ${id}`); }
  onTime(cb: (p: number, d: number) => void) { this.time = cb; }
  onEnded(cb: () => void) { this.ended = cb; }
  onError() {}
  onLevel() {}
}

class FakeCore implements CoreClient {
  calls: { type: string; payload: Record<string, unknown> }[] = [];
  handlers: Record<string, (p: Record<string, unknown>) => unknown> = {
    media_urls: (p) => ({ src: `http://m/${p.track_id}`, cover: null, subtitles: [], position: 12, siblings: [7, 8, 9] }),
  };
  async call<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    this.calls.push({ type, payload });
    const h = this.handlers[type];
    return (h ? h(payload) : undefined) as T;
  }
  server<T>(): Promise<T> { return Promise.reject(new Error("no")); }
  onEvent() { return () => {}; }
  onLink() { return () => {}; }
  start() {}
  stop() {}
  states() { return this.calls.filter((c) => c.type === "media_state").map((c) => c.payload); }
}

const tr = (id: number): Track => ({ id, source: "local", title: `T${id}`, artist: "A", album: "LP", duration: 100 });

describe("музыкальный плеер", () => {
  test("играть список: загрузка, предзагрузка следующего, отчёт ядру", async () => {
    const core = new FakeCore();
    const eng = new FakeEngine();
    const m = createMusicStore(core, eng);
    await m.getState().playTracks([tr(1), tr(2), tr(3)], 0);
    await vi.waitFor(() => expect(eng.log).toContain("preload http://m/2"));
    expect(eng.log[0]).toBe("load http://m/1");
    expect(m.getState().status).toBe("playing");
    expect(core.states()[0]).toMatchObject({ player: "music", status: "playing", title: "T1", track_id: 1, new_track: true });
  });

  test("следующий без паузы, конец очереди, повтор одного", async () => {
    const core = new FakeCore();
    const eng = new FakeEngine();
    const m = createMusicStore(core, eng);
    await m.getState().playTracks([tr(1), tr(2)], 0);
    eng.ended();
    await vi.waitFor(() => expect(eng.log).toContain("switch http://m/2 0"));
    expect(m.getState().current()?.id).toBe(2);
    eng.ended();
    await vi.waitFor(() => expect(m.getState().status).toBe("stopped"));
    m.getState().cycleRepeat();
    m.getState().cycleRepeat(); // one
    await m.getState().playAt(1);
    eng.ended();
    await vi.waitFor(() => expect(eng.log.slice(-2)).toEqual(["seek 0", "play"]));
  });

  test("п. 7: prev — в начало после 3 с, prevTrack — всегда предыдущий, команды prevTrack/seek", async () => {
    const eng = new FakeEngine();
    const m = createMusicStore(new FakeCore(), eng);
    await m.getState().playTracks([tr(1), tr(2), tr(3)], 1);
    eng.time(10, 100);
    await m.getState().prev();
    expect(m.getState().current()?.id).toBe(2);           // 10 с — перемотка в начало
    expect(eng.log.at(-1)).toBe("seek 0");
    eng.time(1, 100);
    await m.getState().prev();
    expect(m.getState().current()?.id).toBe(1);           // 1 с — предыдущий
    await m.getState().playAt(2);
    eng.time(50, 100);
    await m.getState().command("prevTrack");
    expect(m.getState().current()?.id).toBe(2);           // голосом «предыдущий трек» — сразу предыдущий
    eng.time(40, 100);
    await m.getState().command("seek", 0);                 // «трек сначала»
    expect(m.getState().current()?.id).toBe(2);
    expect(eng.log.at(-1)).toBe("seek 0");
  });

  test("плавный переход стартует за crossfade секунд до конца", async () => {
    const core = new FakeCore();
    const eng = new FakeEngine();
    const m = createMusicStore(core, eng);
    m.getState().setCrossfade(3);
    await m.getState().playTracks([tr(1), tr(2)], 0);
    eng.time(96, 100);
    expect(m.getState().current()?.id).toBe(1);
    eng.time(97.5, 100);
    await vi.waitFor(() => expect(eng.log).toContain("switch http://m/2 3"));
    eng.ended(); // конец старого трека не переключает ещё раз
    expect(m.getState().current()?.id).toBe(2);
  });

  test("голосовые команды", async () => {
    const core = new FakeCore();
    const eng = new FakeEngine();
    const m = createMusicStore(core, eng);
    await m.getState().playTracks([tr(1), tr(2), tr(3)], 0);
    const c = m.getState().command;
    await c("toggle");
    expect(m.getState().status).toBe("paused");
    await c("toggle");
    expect(m.getState().status).toBe("playing");
    m.setState({ position: 50 });
    await c("seekBy", 10);
    expect(eng.log).toContain("seek 60");
    await c("volumeBy", -30);
    expect(m.getState().volume).toBeCloseTo(0.5);
    await c("mute");
    expect(m.getState().muted).toBe(true);
    await c("shuffle");
    expect(m.getState().queue.shuffle).toBe(true);
    await c("repeat");
    expect(m.getState().queue.repeat).toBe("all");
    await c("like");
    expect(core.calls.some((x) => x.type === "media_playlist" && x.payload.op === "like")).toBe(true);
    await c("next");
    expect(m.getState().current()?.id).not.toBe(1);
  });

  test("Яндекс недоступен — понятная ошибка", async () => {
    const core = new FakeCore();
    core.handlers.media_yandex = () => { throw new CoreError("yandex_unavailable", "Яндекс.Музыка: не удалось (ссылка на трек)"); };
    const m = createMusicStore(core, new FakeEngine());
    await m.getState().playTracks([{ ...tr(1), id: "ym:1", source: "yandex" }]);
    expect(m.getState().status).toBe("stopped");
    expect(m.getState().error).toContain("Используйте внешний плеер");
  });

  describe("Яндекс.Музыка", () => {
    const ym = (id: number): Track => ({ id: `ym:${id}`, source: "yandex", title: `Y${id}`, artist: "A", album: "", duration: 100 });
    const setup = () => {
      const core = new FakeCore();
      core.handlers.media_yandex = (p) => {
        if (p.op === "stream") return { src: `http://y/${p.id}` };
        if (p.op === "station") return { items: [ym(10), ym(11)], batch_id: "b2" };
        return { ok: true };
      };
      const eng = new FakeEngine();
      return { core, eng, m: createMusicStore(core, eng) };
    };
    const ops = (core: FakeCore, op: string) => core.calls.filter((c) => c.type === "media_yandex" && c.payload.op === op);

    test("станция подгружает следующую порцию сама и не повторяет треки", async () => {
      const { core, m } = setup();
      await m.getState().command("ym_play", { tracks: [ym(1)], station: "track:1", batch_id: "b1" });
      await vi.waitFor(() => expect(m.getState().queue.items.map((t) => t.id)).toEqual(["ym:1", "ym:10", "ym:11"]));
      expect(ops(core, "station")[0]!.payload).toMatchObject({ station: "track:1", after: "ym:1" });
      expect(m.getState().station).toEqual({ id: "track:1", batchId: "b2" });
    });

    test("отзывы станции: начало, пропуск, дослушал до конца", async () => {
      const { core, eng, m } = setup();
      await m.getState().command("ym_play", { tracks: [ym(1), ym(2), ym(3), ym(4), ym(5)], station: "user:onyourwave" });
      await m.getState().next();
      eng.ended();
      await vi.waitFor(() => expect(m.getState().current()?.id).toBe("ym:3"));
      expect(ops(core, "feedback").map((c) => c.payload.event)).toEqual(
        expect.arrayContaining(["trackStarted", "skip", "trackFinished"]));
    });

    test("обычный список выключает станцию", async () => {
      const { m } = setup();
      await m.getState().command("ym_play", { tracks: [ym(1)], station: "track:1" });
      await m.getState().playTracks([tr(1)]);
      expect(m.getState().station).toBeNull();
    });

    test("в очередь: в конец, следующим, а в пустую — сразу играть", async () => {
      const { m } = setup();
      await m.getState().command("ym_enqueue", { tracks: [ym(1)] });
      expect(m.getState().status).toBe("playing");
      await m.getState().command("ym_enqueue", { tracks: [ym(2)] });
      await m.getState().command("ym_enqueue", { tracks: [ym(3), ym(4)], next: true });
      expect(m.getState().queue.items.map((t) => t.id)).toEqual(["ym:1", "ym:3", "ym:4", "ym:2"]);
    });

    test("ядро знает очередь и текущий трек Яндекса", async () => {
      const { core, m } = setup();
      await m.getState().command("ym_play", { tracks: [ym(1), ym(2), ym(3), ym(4)] });
      expect(core.states().at(-1)).toMatchObject({ ym_id: "ym:1", track_id: null });
      const sent = core.calls.filter((c) => c.type === "media_queue").at(-1)!.payload;
      expect(sent).toMatchObject({ index: 0 });
      expect((sent.items as unknown[]).length).toBe(4);
    });

    test("лайк: состояние с сервера, переключение и откат при ошибке", async () => {
      const { core, m } = setup();
      const base = core.handlers.media_yandex!;
      core.handlers.media_yandex = (p) => (p.op === "likes" ? { ids: ["ym:1"] } : base(p));
      await m.getState().command("ym_play", { tracks: [ym(1), ym(2)] });
      await vi.waitFor(() => expect(m.getState().likedIds.has("ym:1")).toBe(true));
      await m.getState().toggleLike();
      expect(m.getState().likedIds.has("ym:1")).toBe(false);
      expect(ops(core, "unlike")).toHaveLength(1);
      core.handlers.media_yandex = () => { throw new Error("нет сети"); };
      await m.getState().toggleLike();
      expect(m.getState().likedIds.has("ym:1")).toBe(false);
      expect(m.getState().error).toBe("нет сети");
    });

    test("текст песни открывается на экране, без текста — понятная ошибка", async () => {
      const { core, m } = setup();
      await m.getState().command("ym_play", { tracks: [ym(1)] });
      core.handlers.media_yandex = (p) => (p.op === "lyrics" ? { text: "строка" } : { ok: true });
      await m.getState().showLyrics();
      expect(m.getState().yandexShow).toEqual({ view: "lyrics", title: "Y1", text: "строка" });
      core.handlers.media_yandex = () => ({ text: null });
      await m.getState().showLyrics();
      expect(m.getState().error).toBe("У этой песни нет текста");
    });

    test("станция при перемешивании считает оставшиеся треки по порядку игры", async () => {
      const { core, m } = setup();
      await m.getState().command("ym_play", { tracks: [ym(1), ym(2), ym(3), ym(4), ym(5), ym(6)], station: "s" });
      await vi.waitFor(() => expect(core.states().length).toBeGreaterThan(0));
      const before = ops(core, "station").length;
      m.setState({ queue: { ...m.getState().queue, shuffle: true, index: 5, order: [5, 0, 1, 2, 3, 4] } });
      await m.getState().playAt(5);
      expect(ops(core, "station").length).toBe(before);
    });

    test("очистить очередь, убрать трек, точная громкость", async () => {
      const { m } = setup();
      await m.getState().command("ym_play", { tracks: [ym(1), ym(2), ym(3)] });
      await m.getState().command("queue_remove", 2);
      expect(m.getState().queue.items.map((t) => t.id)).toEqual(["ym:1", "ym:2"]);
      await m.getState().command("queue_clear");
      expect(m.getState().queue.items.map((t) => t.id)).toEqual(["ym:1"]);
      await m.getState().command("volumeSet", 40);
      expect(m.getState().volume).toBeCloseTo(0.4);
    });
  });

  test("перетаскивание в очереди и «играть следующим»", async () => {
    const m = createMusicStore(new FakeCore(), new FakeEngine());
    await m.getState().playTracks([tr(1), tr(2), tr(3)], 0);
    m.getState().move(2, 0);
    expect(m.getState().queue.items.map((t) => t.id)).toEqual([3, 1, 2]);
    expect(m.getState().current()?.id).toBe(1);
    m.getState().playNext(tr(9));
    expect(m.getState().queue.items.map((t) => t.id)).toEqual([3, 1, 9, 2]);
  });
});

describe("видеоплеер", () => {
  const ctl = () => {
    const log: string[] = [];
    return { log, c: {
      toggle: () => log.push("toggle"), pause: () => log.push("pause"), seekBy: (d: number) => log.push(`seek ${d}`),
      setRate: (r: number) => log.push(`rate ${r}`), fullscreen: () => log.push("fs"),
      setSubtitle: (i: number) => log.push(`sub ${i}`), currentTime: () => 0,
    } };
  };

  test("локальное видео: позиция, субтитры, соседи, команды", async () => {
    const core = new FakeCore();
    core.handlers.media_urls = (p) => ({ src: `http://v/${p.track_id}`, position: 12, siblings: [7, 8, 9],
      subtitles: [{ index: 0, label: "a.ru.vtt", src: "s0" }, { index: 1, label: "a.en.srt", src: "s1" }] });
    const v = createVideoStore(core);
    const { log, c } = ctl();
    v.getState().attach(c);
    await openLocalVideo(core, v, 8, "Фильм");
    expect(v.getState().source).toMatchObject({ kind: "local", trackId: 8, start: 12 });
    expect(v.getState().subtitle).toBe(0);
    await v.getState().command("subtitles");
    await v.getState().command("subtitles");
    expect(v.getState().subtitle).toBe(-1);
    await v.getState().command("rateBy", 0.25);
    await v.getState().command("rateBy", 5);
    expect(v.getState().rate).toBe(2);
    await v.getState().command("seekBy", -10);
    await v.getState().command("toggle");
    await v.getState().command("theater");
    expect(v.getState().theater).toBe(true);
    expect(log).toEqual(["sub 1", "sub -1", "rate 1.25", "rate 2", "seek -10", "toggle"]);
    await v.getState().command("next");
    expect(v.getState().source).toMatchObject({ trackId: 9 });
  });

  test("ошибки YouTube 101/150 — встраивание запрещено", () => {
    const v = createVideoStore(new FakeCore());
    v.getState().open({ kind: "youtube", videoId: "dQw4w9WgXcQ", playerUrl: "http://127.0.0.1/p", title: "", start: 0 });
    v.getState().onYoutubeError(150);
    expect(v.getState().embedBlocked).toBe(true);
    expect(v.getState().error).toBe("Автор запретил встраивание этого видео");
    v.getState().onYoutubeError(5);
    expect(v.getState().embedBlocked).toBe(false);
  });

  test("отчёт ядру при смене статуса", () => {
    const core = new FakeCore();
    const v = createVideoStore(core);
    v.getState().open({ kind: "youtube", videoId: "dQw4w9WgXcQ", playerUrl: "p", title: "Клип", start: 0 });
    v.getState().onPlayer({ status: "playing", position: 3, duration: 200 });
    expect(core.states().at(-1)).toMatchObject({ player: "video", status: "playing", source: "youtube", title: "Клип" });
  });
});

// lib/capture.js: троттлинг захвата, деградация качества кадра, обрезка.
import { afterEach, describe, expect, test, vi } from "vitest";

import { loadLib } from "./helpers.js";

loadLib("lib/capture.js");
const C = globalThis.SakuraCapture;

afterEach(() => vi.useRealTimers());

describe("очередь захвата ≤ 2 вызовов/с", () => {
  test("5 запросов подряд — интервал ≥ 500 мс, порядок сохраняется", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const times = [];
    const capture = vi.fn(async (windowId) => { times.push([Date.now(), windowId]); return "data:" + windowId; });
    const q = C.createQueue({ capture });
    const all = Promise.all([1, 2, 3, 4, 5].map((w) => q(w, {})));
    await vi.advanceTimersByTimeAsync(5000);
    expect(await all).toEqual(["data:1", "data:2", "data:3", "data:4", "data:5"]);
    expect(times.map((t) => t[1])).toEqual([1, 2, 3, 4, 5]);
    expect(times.map((t) => t[0] - 10_000)).toEqual([0, 500, 1000, 1500, 2000]);
  });

  test("за любую секунду — не больше двух вызовов; ошибка не ломает очередь", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const times = [];
    let n = 0;
    const capture = vi.fn(async () => { times.push(Date.now()); n += 1; if (n === 2) throw new Error("лимит"); return "ok"; });
    const q = C.createQueue({ capture });
    const res = [1, 2, 3, 4].map((w) => q(w).catch((e) => e.message));
    await vi.advanceTimersByTimeAsync(3000);
    expect(await Promise.all(res)).toEqual(["ok", "лимит", "ok", "ok"]);
    for (const t of times) expect(times.filter((x) => x >= t && x < t + 1000).length).toBeLessThanOrEqual(2);
  });

  test("редкие вызовы не ждут", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const capture = vi.fn(async () => Date.now());
    const q = C.createQueue({ capture });
    expect(await q(1)).toBe(0);
    await vi.advanceTimersByTimeAsync(2000);
    const p = q(1);
    await vi.advanceTimersByTimeAsync(0);
    expect(await p).toBe(2000);
  });
});

// Кодек-заглушка: размер JPEG задаётся функцией от ширины и качества.
function codec(sizeFn, img = { width: 1920, height: 1080 }) {
  const calls = [];
  return {
    calls,
    decode: vi.fn(async () => ({ ...img, close: vi.fn() })),
    encode: vi.fn(async (_img, src, w, h, q) => { calls.push({ src, w, h, q }); return new Uint8Array(sizeFn(w, q)); }),
  };
}

describe("деградация качества кадра", () => {
  test("влезает сразу: ширина 1280, q60", async () => {
    const c = codec(() => 300 * 1024);
    const r = await C.compress("data:x", { codec: c });
    expect(c.calls.map((x) => [x.w, x.h, x.q])).toEqual([[1280, 720, 0.6]]);
    expect(r).toMatchObject({ mime: "image/jpeg", width: 1280, height: 720, quality: 60, over_limit: false, bytes: 300 * 1024 });
    expect(r.data_b64.length).toBe(Math.ceil((300 * 1024) / 3) * 4);
  });

  test("больше 400 КБ на q60 — q50", async () => {
    const c = codec((w, q) => (q > 0.55 ? 450 : 380) * 1024);
    const r = await C.compress("data:x", { codec: c });
    expect(c.calls.map((x) => [x.w, x.q])).toEqual([[1280, 0.6], [1280, 0.5]]);
    expect(r).toMatchObject({ width: 1280, quality: 50, over_limit: false });
  });

  test("и на q50 больше — ширина 1024", async () => {
    const c = codec((w) => (w > 1100 ? 500 : 350) * 1024);
    const r = await C.compress("data:x", { codec: c });
    expect(c.calls.map((x) => [x.w, x.h, x.q])).toEqual([[1280, 720, 0.6], [1280, 720, 0.5], [1024, 576, 0.5]]);
    expect(r).toMatchObject({ width: 1024, height: 576, quality: 50, over_limit: false });
  });

  test("не влезло и на последней ступени — отдаём с over_limit", async () => {
    const c = codec(() => 600 * 1024);
    const r = await C.compress("data:x", { codec: c });
    expect(c.calls).toHaveLength(3);
    expect(r.over_limit).toBe(true);
  });

  test("узкий кадр не растягивается", async () => {
    const c = codec(() => 1000, { width: 800, height: 600 });
    const r = await C.compress("data:x", { codec: c });
    expect([r.width, r.height]).toEqual([800, 600]);
  });

  test("обрезка: лимит 200 КБ", async () => {
    const c = codec((w, q) => (q > 0.55 ? 250 : 150) * 1024, { width: 1000, height: 800 });
    const r = await C.compress("data:x", { codec: c, crop: [100, 100, 200, 100], viewportWidth: 1000 });
    expect(r.quality).toBe(50);
    expect(C.LIMITS.crop).toBe(200 * 1024);
  });
});

describe("crop", () => {
  test("bbox + 16 px, масштаб кадра (devicePixelRatio 2)", () => {
    expect(C.cropRect([100, 200, 300, 50], 2048, 1536, 2)).toEqual({ x: 168, y: 368, w: 664, h: 164 });
  });

  test("у края кадра — обрезка по границам", () => {
    expect(C.cropRect([5, 5, 50, 50], 200, 100, 1)).toEqual({ x: 0, y: 0, w: 71, h: 71 });
    expect(C.cropRect([180, 80, 50, 50], 200, 100, 1)).toEqual({ x: 164, y: 64, w: 36, h: 36 });
  });

  test("элемент вне кадра — ошибка, а не пустой кадр", async () => {
    expect(C.cropRect([5000, 5000, 10, 10], 200, 100, 1)).toBeNull();
    const c = codec(() => 10);
    await expect(C.compress("data:x", { codec: c, crop: [5000, 5000, 10, 10], viewportWidth: 200 })).rejects.toThrow("вне кадра");
  });

  test("кадр обрезки кодируется из прямоугольника обрезки", async () => {
    const c = codec(() => 1000, { width: 2000, height: 1000 });
    const r = await C.compress("data:x", { codec: c, crop: [100, 100, 200, 100], viewportWidth: 1000 });
    expect(c.calls[0].src).toEqual({ x: 168, y: 168, w: 464, h: 264 });
    expect([r.width, r.height]).toEqual([464, 264]);
  });
});

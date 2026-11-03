import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { SakuraCore } from "./SakuraCore";

// Ручной rAF: кадры выдаются тестом, счётчик показывает, крутится ли цикл.
let queue: FrameRequestCallback[] = [];
let now = 0;
let hidden = false;
let reduced = false;

beforeEach(() => {
  queue = []; now = 0; hidden = false; reduced = false;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { queue.push(cb); return queue.length; });
  vi.stubGlobal("cancelAnimationFrame", () => { queue = []; });
  vi.spyOn(performance, "now").mockImplementation(() => now);
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  window.matchMedia = ((q: string) => ({
    matches: reduced && q.includes("reduce"), addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function frames(n: number, stepMs: number) {
  for (let i = 0; i < n; i++) {
    now += stepMs;
    const batch = queue; queue = [];
    batch.forEach((cb) => cb(now));
  }
}

const satX = (c: HTMLElement) => c.querySelectorAll("g circle")[1]!.getAttribute("cx");

test("атрибуты меняются без перерисовки React", () => {
  const { container } = render(<SakuraCore state="thinking" level={() => 0} />);
  const before = satX(container);
  act(() => frames(30, 16.7));
  expect(satX(container)).not.toBe(before);
});

test("idle — 30 fps: при rAF 60 кадр рисуется через раз", () => {
  const { container } = render(<SakuraCore state="idle" level={() => 0} />);
  const sat = container.querySelectorAll("g circle")[1]!;
  const set = vi.spyOn(sat, "setAttribute");
  act(() => frames(60, 1000 / 60));
  // 60 кадров rAF за секунду → около 30 отрисовок по 3 атрибута.
  expect(set.mock.calls.length / 3).toBeGreaterThanOrEqual(28);
  expect(set.mock.calls.length / 3).toBeLessThanOrEqual(32);
});

test("скрытое окно — цикл полностью остановлен, при показе возобновляется", () => {
  render(<SakuraCore state="speaking" level={() => 0.5} />);
  expect(queue.length).toBe(1);
  hidden = true;
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(queue.length).toBe(0);
  hidden = false;
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(queue.length).toBe(1);
});

test("reduced motion — статичный кадр без цикла", () => {
  reduced = true;
  render(<SakuraCore state="thinking" level={() => 1} />);
  expect(queue.length).toBe(0);
});

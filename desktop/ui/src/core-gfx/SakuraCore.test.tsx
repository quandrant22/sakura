import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { coreFrame } from "./coreFrame";
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

test("смена состояния: без скачка, время не сбрасывается, переход за 250 мс", () => {
  const { container, rerender } = render(<SakuraCore state="idle" level={() => 0} />);
  act(() => frames(60, 1000 / 60)); // секунда покоя
  const sat = () => {
    const el = container.querySelectorAll("g circle")[1]!;
    return [Number(el.getAttribute("cx")), Number(el.getAttribute("cy"))] as const;
  };
  const step = (a: readonly number[], b: readonly number[]) => Math.hypot(a[0]! - b[0]!, a[1]! - b[1]!);
  const before = sat();
  act(() => frames(1, 1000 / 60));
  const idleStep = step(before, sat());       // обычный шаг одного кадра
  const mid = sat();
  rerender(<SakuraCore state="thinking" level={() => 0} />);
  expect(sat()).toEqual(mid);                  // React не вернул атрибуты к кадру t=0
  act(() => frames(1, 1000 / 60));
  expect(step(mid, sat())).toBeLessThan(Math.max(1, idleStep * 2)); // первый кадр после смены — без скачка
  // Скачок без перехода был бы таким: кадр «думаю» в тот же момент против кадра покоя.
  const jump = step(mid, [coreFrame(now / 1000, "thinking", 0).satellites[0]!.cx, coreFrame(now / 1000, "thinking", 0).satellites[0]!.cy]);
  expect(jump).toBeGreaterThan(3);
  act(() => frames(18, 1000 / 60));            // > 250 мс — переход закончен
  // Время — от начала жизни ядра, а не от смены состояния.
  const want = coreFrame(now / 1000, "thinking", 0).satellites[0]!;
  const got = sat();
  expect(got[0]).toBeCloseTo(want.cx, 1);
  expect(got[1]).toBeCloseTo(want.cy, 1);
});

test("время не сбрасывается и после скрытия окна", () => {
  const { container } = render(<SakuraCore state="thinking" level={() => 0} />);
  act(() => frames(30, 1000 / 60));
  hidden = true;
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
  now += 5000;
  hidden = false;
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
  act(() => frames(1, 1000 / 60));
  const el = container.querySelectorAll("g circle")[1]!;
  expect(Number(el.getAttribute("cx"))).toBeCloseTo(coreFrame(now / 1000, "thinking", 0).satellites[0]!.cx, 1);
});

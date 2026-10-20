import { describe, expect, test } from "vitest";

import {
  applyPoll, belongsToTrack, dominantColor, extrapolate, fmt, mergeState, prevAction, visibleControls,
} from "./barLogic";

describe("панель музыки — логика", () => {
  test("позиция экстраполируется, пока играет, и не выходит за длительность", () => {
    const st = { status: "ok" as const, playing: true, position_s: 10, duration_s: 200, updated_age_s: 0.5 };
    expect(extrapolate(st, 0)).toBe(10.5);
    expect(extrapolate(st, 1.25)).toBe(11.75);
    expect(extrapolate({ ...st, playing: false }, 5)).toBe(10);
    expect(extrapolate({ ...st, position_s: 199 }, 5)).toBe(200);
    expect(extrapolate(null, 1)).toBe(0);
  });

  test("элементы скрываются по приоритету при узкой ширине", () => {
    expect(visibleControls(480)).toEqual({ modes: false, rating: false, volume: false, extras: false });
    expect(visibleControls(600)).toEqual({ modes: true, rating: false, volume: false, extras: false });
    expect(visibleControls(690)).toEqual({ modes: true, rating: true, volume: false, extras: false });
    expect(visibleControls(1000)).toEqual({ modes: true, rating: true, volume: true, extras: true });
  });

  test("доминирующий цвет обложки, прозрачные пиксели не считаются, затемнение", () => {
    const px = new Uint8ClampedArray([200, 100, 0, 255, 100, 100, 100, 255, 0, 0, 255, 0]);
    expect(dominantColor(px, 0)).toEqual([150, 100, 50]);
    expect(dominantColor(px, 0.5)).toEqual([75, 50, 25]);
    expect(dominantColor(new Uint8ClampedArray([1, 2, 3, 0]))).toBeNull();
  });

  test("«Предыдущий»: одинарный — в начало после 3 с, иначе назад; двойной — назад", () => {
    expect(prevAction(1, 10)).toBe("restart");
    expect(prevAction(1, 1)).toBe("prev");
    expect(prevAction(2, 0.2)).toBe("prev");
    expect(fmt(125)).toBe("2:05");
  });
});

describe("опрос и события музыки", () => {
  const A = { status: "ok" as const, title: "Старая", artist: "X", album: "", seq: 3, track_seq: 1, cover: "data:a", liked: true };
  const B = { status: "ok" as const, title: "Новая", artist: "Y", album: "", seq: 4, track_seq: 4 };

  test("устаревший ответ опроса (seq меньше) не применяется", () => {
    const now = mergeState(A, B);
    expect(applyPoll(now, { ...A, cover: undefined })).toBeNull();
    expect(applyPoll(now, { ...B, seq: 4, position_s: 12 })?.position_s).toBe(12); // тот же seq — свежая позиция
  });

  test("тот же трек сохраняет обложку и лайк, новый — сбрасывает", () => {
    const polled = applyPoll(A, { ...A, seq: 3, cover: undefined, liked: null })!;
    expect(polled.cover).toBe("data:a");
    expect(polled.liked).toBe(true);
    const next = mergeState(A, B);
    expect(next.cover).toBeNull();
    expect(next.liked).toBeNull();
  });

  test("обложка и лайк — только своему треку (по seq смены трека)", () => {
    const st = mergeState(A, { ...B, seq: 6, changed: "playback" } as typeof B);
    expect(belongsToTrack(st, 4)).toBe(true);   // пауза после смены трека — обложка всё ещё его
    expect(belongsToTrack(st, 1)).toBe(false);  // обложка прошлого трека опоздала — не ставим
  });
});

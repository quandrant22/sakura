import { describe, expect, test } from "vitest";

import {
  adaptiveFps, captureRect, captureSize, filterSources, fitWidgetRows, isBlackFrame,
} from "./captureLogic";

describe("окно приложения — размеры", () => {
  // Источник 1280×800 (16:10) в телах виджета 690×300 и 422×450.
  test("вписать: окно целиком по его пропорциям, letterbox", () => {
    expect(captureRect(690, 300, 1280, 800, "fit")).toEqual({ left: 105, top: 0, width: 480, height: 300, scroll: false });
    expect(captureRect(422, 450, 1280, 800, "fit")).toEqual({ left: 0, top: 94, width: 422, height: 263, scroll: false });
  });

  test("заполнить — покрывает тело, без прокрутки", () => {
    const r = captureRect(690, 300, 1280, 800, "fill");
    expect(r.width).toBeGreaterThanOrEqual(690);
    expect(r.height).toBeGreaterThanOrEqual(300);
    expect(r.scroll).toBe(false);
  });

  test("100% — реальный размер с прокруткой, масштаб ±", () => {
    expect(captureRect(690, 300, 1280, 800, "actual")).toEqual({ left: 0, top: 0, width: 1280, height: 800, scroll: true });
    expect(captureRect(690, 300, 400, 200, "actual")).toMatchObject({ left: 145, top: 50, scroll: false });
    expect(captureRect(690, 300, 1280, 800, "actual", 0.5)).toMatchObject({ width: 640, height: 400, scroll: true });
  });

  test("по ширине — ширина тела, вертикальная прокрутка", () => {
    expect(captureRect(690, 300, 1280, 800, "width")).toEqual({ left: 0, top: 0, width: 690, height: 431, scroll: true });
  });

  test("масштаб ограничен 0.25..4 и пустой источник", () => {
    expect(captureRect(690, 300, 1280, 800, "actual", 100).width).toBe(5120);
    expect(captureRect(690, 300, 0, 0, "fit").width).toBe(0);
  });
});

test("захват в разрешении источника с потолком 1920×1080, пропорции сохраняются", () => {
  expect(captureSize(1280, 800)).toEqual({ width: 1280, height: 800 });
  expect(captureSize(3840, 2160)).toEqual({ width: 1920, height: 1080 });
  expect(captureSize(2560, 1600)).toEqual({ width: 1728, height: 1080 });
});

test("частота кадров адаптивная", () => {
  expect(adaptiveFps(10, 690, false, false)).toBe(10);
  expect(adaptiveFps(10, 300, false, false)).toBe(5);
  expect(adaptiveFps(10, 690, true, false)).toBe(1);
  expect(adaptiveFps(10, 690, false, true)).toBe(1);
  expect(adaptiveFps(99, 690, false, false)).toBe(30);
});

test("чёрный кадр по яркости", () => {
  expect(isBlackFrame(new Uint8ClampedArray(64 * 4))).toBe(true);
  const bright = new Uint8ClampedArray(64 * 4).fill(200);
  expect(isBlackFrame(bright)).toBe(false);
});

test("чёрный список окон и окна самой Сакуры не показываются", () => {
  const list = [{ id: "1", name: "Блокнот" }, { id: "2", name: "KeePassXC — пароли" }, { id: "3", name: "Sakura" },
                { id: "4", name: "Сбербанк Онлайн" }, { id: "5", name: "Sakura · видео" }, { id: "6", name: "Steam" }];
  expect(filterSources(list).map((s) => s.name)).toEqual(["Блокнот", "Steam"]);
  expect(filterSources(list, ["steam"]).map((s) => s.name)).toContain("KeePassXC — пароли");
});

test("подогнать виджет под пропорции окна", () => {
  // ширина 690, окно 16:10, строка 9.35 + отступ 20, заголовок и панель 88 px
  const rows = fitWidgetRows(690, 1280 / 800, 9.35, 20, 88);
  const px = rows * 9.35 + (rows - 1) * 20 - 88;
  expect(Math.abs(px - 690 / 1.6)).toBeLessThan(30);
});

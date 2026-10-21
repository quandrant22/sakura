import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "vitest";

import { trayIconPath } from "./trayIcon";

// Как в собранном приложении: main.js лежит в dist-electron.
const distElectron = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "dist-electron");

test("значок трея есть в репозитории и найден по пути из dist-electron", () => {
  const ico = trayIconPath(distElectron, "win32");
  expect(path.basename(ico)).toBe("tray.ico");
  expect(fs.statSync(ico).size).toBeGreaterThan(100);
  const png = trayIconPath(distElectron, "linux");
  expect(path.basename(png)).toBe("tray.png");
  // tray.png — 16×16, tray@2x.png — 32×32 (заголовок PNG: ширина и высота в IHDR)
  for (const [name, size] of [["tray.png", 16], ["tray@2x.png", 32]] as const) {
    const buf = fs.readFileSync(path.join(path.dirname(png), name));
    expect(buf.readUInt32BE(16)).toBe(size);
    expect(buf.readUInt32BE(20)).toBe(size);
  }
});

test("нет файлов трея — значок приложения, а не пустая картинка", () => {
  const p = trayIconPath(distElectron, "win32", (f) => f.endsWith("sakura.ico"));
  expect(path.basename(p)).toBe("sakura.ico");
});

// Сквозная проверка доски виджетов в настоящем Electron (Playwright), на демо-данных:
// перетащить из галереи, переместить, изменить размер, убрать и отменить, перезапуск — раскладка
// сохранилась без перекрытий; во время перетаскивания iframe не перехватывает мышь.
// Запуск: npm run build && node scripts/e2e-board.mjs [папка снимков]  (по умолчанию C:/sakura-tmp/screens/board)
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { _electron as electron } from "playwright";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const shots = process.argv[2] ?? "C:/sakura-tmp/screens/board";
fs.mkdirSync(shots, { recursive: true });
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "sakura-e2e-"));
const layoutFile = path.join(tmp, "layout.json");
const env = { ...process.env, SAKURA_E2E: "1", SAKURA_LAYOUT_FILE: layoutFile,
              SAKURA_DEV_URL: `file:///${path.join(root, "dist", "index.html").replaceAll("\\", "/")}?demo=normal` };
delete env.ELECTRON_RUN_AS_NODE;

const results = [];
async function step(name, fn) {
  try {
    await fn();
    results.push(`OK   ${name}`);
  } catch (e) {
    results.push(`FAIL ${name}: ${e.message.split("\n")[0]}`);
  }
}

async function launch() {
  const app = await electron.launch({ args: [root], env });
  const page = await app.firstWindow();
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.setContentSize(1440, 1024));
  await page.getByLabel("Доска виджетов").waitFor();
  await page.waitForTimeout(800);
  return { app, page };
}

const region = (page, name) => page.getByRole("region", { name, exact: true });
async function boxes(page) {
  return page.$$eval(".react-grid-item", (els) => els.map((e) => {
    const r = e.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  }));
}
const overlaps = (bs) => bs.some((a, i) => bs.some((b, j) => i !== j &&
  a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1));

let { app, page } = await launch();

await step("галерея: перетаскивание «Заметки» на доску", async () => {
  await page.getByRole("button", { name: /Виджет/ }).click();
  await page.screenshot({ path: path.join(shots, "board_gallery.png") });
  await page.getByRole("listitem", { name: "Заметки" }).dragTo(page.getByLabel("Доска виджетов"), { targetPosition: { x: 300, y: 860 } });
  await region(page, "Заметки").waitFor({ timeout: 3000 });
  await page.getByLabel("Закрыть галерею").click();
});

await step("переместить виджет за заголовок", async () => {
  const head = region(page, "Система").locator("header");
  const before = await region(page, "Система").boundingBox();
  const hb = await head.boundingBox();
  await page.mouse.move(hb.x + 40, hb.y + 15);
  await page.mouse.down();
  // во время перетаскивания: класс is-interacting и iframe без событий мыши
  await page.mouse.move(hb.x + 120, hb.y + 300, { steps: 8 });
  const during = await page.evaluate(() => {
    const f = document.createElement("iframe");
    document.querySelector(".react-grid-item")?.appendChild(f);
    const pe = getComputedStyle(f).pointerEvents;
    f.remove();
    return { cls: document.body.classList.contains("is-interacting"), pe };
  });
  await page.mouse.move(hb.x + 140, hb.y + 320, { steps: 4 });
  await page.mouse.up();
  await page.waitForTimeout(400);
  const after = await region(page, "Система").boundingBox();
  assert.ok(during.cls, "нет is-interacting во время перетаскивания");
  assert.equal(during.pe, "none", "iframe ловит мышь во время перетаскивания");
  assert.ok(Math.abs(after.y - before.y) > 50 || Math.abs(after.x - before.x) > 50, "виджет не сдвинулся");
});

await step("изменить размер за угол", async () => {
  const item = page.locator(".react-grid-item", { has: region(page, "Видео") });
  const before = await item.boundingBox();
  await item.hover();
  const handle = item.locator(".react-resizable-handle-se");
  const hb = await handle.boundingBox();
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(hb.x - 120, hb.y - 80, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(400);
  const after = await item.boundingBox();
  assert.ok(after.width < before.width - 40, `ширина не уменьшилась: ${before.width} → ${after.width}`);
});

await step("убрать и отменить", async () => {
  await page.getByRole("button", { name: /^Правка/ }).click();
  await page.screenshot({ path: path.join(shots, "board_edit.png") });
  await page.getByLabel("Убрать виджет «Видео»").click();
  assert.equal(await region(page, "Видео").count(), 0);
  await page.getByRole("button", { name: "Отменить" }).click();
  await region(page, "Видео").waitFor({ timeout: 2000 });
  await page.getByRole("button", { name: /^Готово/ }).click();
});

await step("страницы: «Медиа» и обратно", async () => {
  await page.getByRole("button", { name: "Медиа", exact: true }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(shots, "board_pages.png") });
  await page.getByRole("button", { name: "Работа", exact: true }).click();
});

await page.waitForTimeout(800); // сохранение раскладки — с задержкой 400 мс
const saved = await boxes(page);
await app.close();

await step("перезапуск: раскладка сохранилась, без перекрытий", async () => {
  ({ app, page } = await launch());
  await region(page, "Заметки").waitFor({ timeout: 3000 });
  const now = await boxes(page);
  assert.equal(now.length, saved.length, "другое число виджетов");
  assert.ok(!overlaps(now), "виджеты перекрываются");
  await page.screenshot({ path: path.join(shots, "board_restart.png") });
});

await step("панель Яндекс.Музыки на демо-данных", async () => {
  await page.getByLabel("Яндекс.Музыка").waitFor({ timeout: 4000 });
  const bar = page.getByLabel("Яндекс.Музыка");
  await bar.screenshot({ path: path.join(shots, "music_yandex_bar.png") });
});

await app.close();
fs.rmSync(tmp, { recursive: true, force: true });
console.log(results.join("\n"));
process.exit(results.some((r) => r.startsWith("FAIL")) ? 1 : 0);

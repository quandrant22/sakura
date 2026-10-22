// Сверка каркаса с наброском владельца (кадр 1440x1024, допуск ±10 px).
// Запуск после npm run build:  electron scripts/compare-sketch.cjs [папка]  (по умолчанию C:/sakura-tmp/screens)
// Сохраняет: sketch.png — отрисованный набросок, frame.png — снимок приложения,
// overlay.png — снимок с контурами наброска, compare.json — расхождения по каждому блоку.
const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow } = require("electron");

const out = process.argv[2] ?? "C:/sakura-tmp/screens";
const W = 1440;
const H = 1024;
const TOLERANCE = 10;

// Блоки наброска: [имя, x, y, ширина, высота, селектор в приложении].
const BLOCKS = [
  ["верхняя панель", 0, 0, 1440, 84, "header.drag"],
  ["логотип", 30, 19, 300, 45, "header.drag > div:first-child"],
  ["свернуть", 1235, 19, 45, 45, '[aria-label="Свернуть"]'],
  ["развернуть", 1300, 19, 45, 45, '[aria-label="Развернуть"]'],
  ["закрыть", 1365, 19, 45, 45, '[aria-label="Закрыть"]'],
  ["карточка ядра", 30, 104, 300, 287, '[aria-label="Ядро Сакуры"]'],
  ["меню", 30, 411, 300, 583, 'nav[aria-label="Меню"]'],
  ["пункт меню 1", 50, 441, 260, 35, 'nav[aria-label="Меню"] button'],
  ["подвал меню", 50, 944, 260, 20, 'nav[aria-label="Меню"] > div:last-child'],
  ["система", 350, 104, 248, 450, 'section[aria-label="Система"]'],
  ["видео", 618, 104, 422, 450, 'section[aria-label="Видео"]'],
  ["окно приложения", 350, 574, 690, 300, 'section[aria-label="Окно приложения"]'],
  ["музыка", 350, 894, 690, 100, 'section[aria-label="Музыка"]'],
  ["чат", 1060, 104, 350, 890, 'section[aria-label="Чат"]'],
];
// Капля ядра в наброске: центр (179.5, 202.5), r 45.5.
const DROP = { cx: 179.5, cy: 202.5, r: 45.5 };

const sketchSvg = (outline) => {
  const style = outline ? 'fill="none" stroke="#00e5ff" stroke-width="2"' : "";
  const rects = BLOCKS.map(([, x, y, w, h], i) =>
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" ${i > 4 && i !== 7 && i !== 8 ? 'rx="20"' : ""} ${style}/>`).join("");
  const drop = outline
    ? `<circle cx="${DROP.cx}" cy="${DROP.cy}" r="${DROP.r}" ${style}/>`
    : `<circle cx="${DROP.cx}" cy="${DROP.cy}" r="${DROP.r}" fill="url(#g)"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">` +
    `<defs><radialGradient id="g" gradientUnits="userSpaceOnUse" gradientTransform="translate(158 185.5) rotate(54.9751) scale(71.437)">` +
    `<stop stop-color="#FF6AE3"/><stop offset="1" stop-color="#3E0074"/></radialGradient></defs>` +
    (outline ? "" : `<rect width="${W}" height="${H}" fill="white"/>`) + rects + drop + "</svg>";
};

const svgUrl = (svg) => "data:image/svg+xml;base64," + Buffer.from(svg).toString("base64");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function shot(win) {
  return (await win.webContents.capturePage()).toPNG();
}

app.whenReady().then(async () => {
  fs.mkdirSync(out, { recursive: true });
  const win = new BrowserWindow({ width: W, height: H, useContentSize: true, show: false, frame: false,
                                  webPreferences: { offscreen: false } });

  // 1. Набросок как есть.
  await win.loadURL(svgUrl(sketchSvg(false)));
  await wait(300);
  fs.writeFileSync(path.join(out, "sketch.png"), await shot(win));

  // 2. Приложение на демо-данных (собранный dist).
  await win.loadFile(path.join(__dirname, "..", "dist", "index.html"), { search: "demo=normal" });
  await wait(2500);
  const frame = await shot(win);
  fs.writeFileSync(path.join(out, "frame.png"), frame);

  const measured = await win.webContents.executeJavaScript(`(() => {
    const blocks = ${JSON.stringify(BLOCKS.map((b) => b[5]))}.map((sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return [r.x, r.y, r.width, r.height];
    });
    const drop = document.querySelector('[aria-label="Ядро Сакуры"] svg g circle');
    const d = drop ? drop.getBoundingClientRect() : null;
    return { blocks, drop: d ? [d.x + d.width / 2, d.y + d.height / 2] : null };
  })()`);

  const rows = BLOCKS.map(([name, x, y, w, h], i) => {
    const m = measured.blocks[i];
    if (!m) return { name, ok: false, missing: true };
    const delta = [m[0] - x, m[1] - y, m[2] - w, m[3] - h].map((v) => Math.round(v * 10) / 10);
    return { name, sketch: [x, y, w, h], app: m.map((v) => Math.round(v * 10) / 10), delta, ok: delta.every((v) => Math.abs(v) <= TOLERANCE) };
  });
  if (measured.drop) {
    const delta = [measured.drop[0] - DROP.cx, measured.drop[1] - DROP.cy].map((v) => Math.round(v * 10) / 10);
    rows.push({ name: "центр капли", sketch: [DROP.cx, DROP.cy], app: measured.drop.map((v) => Math.round(v * 10) / 10), delta,
                ok: delta.every((v) => Math.abs(v) <= TOLERANCE) });
  }

  // 3. Снимок с контурами наброска поверх.
  const html = `<body style="margin:0;width:${W}px;height:${H}px;position:relative">` +
    `<img src="data:image/png;base64,${frame.toString("base64")}" style="position:absolute;left:0;top:0;width:${W}px;height:${H}px">` +
    `<img src="${svgUrl(sketchSvg(true))}" style="position:absolute;left:0;top:0"></body>`;
  await win.loadURL("data:text/html;base64," + Buffer.from(html).toString("base64"));
  await wait(500);
  fs.writeFileSync(path.join(out, "overlay.png"), await shot(win));

  fs.writeFileSync(path.join(out, "compare.json"), JSON.stringify(rows, null, 1));
  for (const r of rows) console.log(`${r.ok ? "OK  " : "FAIL"} ${r.name.padEnd(16)} ${r.missing ? "не найден" : `Δ ${r.delta.join(" ")}`}`);
  const failed = rows.filter((r) => !r.ok).length;
  console.log(failed ? `расхождений больше ±${TOLERANCE} px: ${failed}` : `все блоки в пределах ±${TOLERANCE} px`);
  app.exit(failed ? 1 : 0);
});

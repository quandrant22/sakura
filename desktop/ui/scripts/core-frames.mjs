// Стенд ядра-графики в настоящем Electron на демо-данных (как e2e): главная с открытой доской,
// состояние ядра задаётся ?corestate=…, счётчик кадров — ?corestats (src/core-gfx/frameStats.ts).
// Печатает долю пропущенных кадров SakuraCore и CPU рендерера (% одного ядра).
// Запуск: npm run build && node scripts/core-frames.mjs [секунды] [состояния через запятую]
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { _electron as electron } from "playwright";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const seconds = Number(process.argv[2] ?? 20);
const states = (process.argv[3] ?? "idle,speaking,thinking").split(",");

async function measure(state) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "sakura-frames-"));
  const url = `file:///${path.join(root, "dist", "index.html").replaceAll("\\", "/")}?demo=normal&corestats=1&corestate=${state}`;
  const env = { ...process.env, SAKURA_E2E: "1", SAKURA_LAYOUT_FILE: path.join(tmp, "layout.json"), SAKURA_DEV_URL: url };
  delete env.ELECTRON_RUN_AS_NODE;
  const app = await electron.launch({ args: [root], env });
  const page = await app.firstWindow();
  await app.evaluate(({ BrowserWindow }) => {
    const w = BrowserWindow.getAllWindows()[0];
    w?.setContentSize(1440, 1024);
    w?.focus();
  });
  await page.getByLabel("Доска виджетов").waitFor();
  await page.waitForTimeout(2000);
  const pid = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.getOSProcessId());
  const cpu = () => app.evaluate(({ app: a }, p) => a.getAppMetrics().find((m) => m.pid === p)?.cpu.percentCPUUsage ?? NaN, pid);
  const f0 = await page.evaluate(() => window.__sakuraCoreFrames ?? { drawn: 0, missed: 0 });
  await cpu();
  const samples = [];
  for (let i = 0; i < seconds; i++) {
    await page.waitForTimeout(1000);
    samples.push(await cpu());
  }
  const f1 = await page.evaluate(() => window.__sakuraCoreFrames ?? { drawn: 0, missed: 0 });
  await app.close();
  fs.rmSync(tmp, { recursive: true, force: true });
  const drawn = f1.drawn - f0.drawn, missed = f1.missed - f0.missed;
  return { state, drawn, missed, pct: drawn + missed ? (100 * missed) / (drawn + missed) : 0,
           cpu: samples.reduce((a, b) => a + b, 0) / samples.length };
}

for (const s of states) {
  const m = await measure(s);
  console.log(`${m.state}: кадров ${m.drawn} за ${seconds} с, пропущено ${m.missed} (${m.pct.toFixed(1)}%), ` +
              `CPU рендерера ${m.cpu.toFixed(1)}% ядра`);
}

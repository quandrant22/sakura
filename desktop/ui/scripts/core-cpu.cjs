// Замер CPU рендерера с одной карточкой ядра: npx vite --host 127.0.0.1 --port 5175,
// затем npx electron scripts/core-cpu.cjs [секунды] [состояния через запятую]
const { app, BrowserWindow } = require("electron");

const seconds = Number(process.argv[2] ?? 30);
const states = (process.argv[3] ?? "idle,speaking").split(",");

async function measure(state) {
  const win = new BrowserWindow({ width: 400, height: 400, show: true, alwaysOnTop: true });
  await win.loadURL(`http://127.0.0.1:5175/preview-core.html?only=${state}`);
  await new Promise((r) => setTimeout(r, 3000));
  const pid = win.webContents.getOSProcessId();
  const cpu = () => app.getAppMetrics().find((m) => m.pid === pid)?.cpu.percentCPUUsage ?? NaN;
  // percentCPUUsage — загрузка с прошлого вызова; берём среднее посекундных замеров.
  cpu();
  const samples = [];
  for (let i = 0; i < seconds; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    samples.push(cpu());
  }
  const fps = await win.webContents.executeJavaScript(
    "new Promise(r=>{let n=0;const s=performance.now();const f=()=>{n++;performance.now()-s<1000?requestAnimationFrame(f):r(n)};requestAnimationFrame(f)})");
  win.destroy();
  return { avg: samples.reduce((a, b) => a + b, 0) / samples.length, fps };
}

app.whenReady().then(async () => {
  for (const s of states) {
    const m = await measure(s);
    console.log(`CPU ${s}: ${m.avg.toFixed(2)}% of one core over ${seconds}s (rAF ${m.fps}/s)`);
  }
  app.quit();
});

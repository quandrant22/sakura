// Снимок preview-core.html (ядро-графика, 5 состояний) для проверки владельцем.
// Запуск: npx vite --host 127.0.0.1 --port 5175, затем npx electron scripts/preview-core-shot.cjs [папка]
const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow } = require("electron");

const out = process.argv[2] ?? "C:/sakura-tmp/screens";

app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: 1640, height: 700, show: false });
  await win.loadURL("http://127.0.0.1:5175/preview-core.html");
  fs.mkdirSync(out, { recursive: true });
  for (const [t, name] of [[800, "a"], [1700, "b"]]) {
    await new Promise((r) => setTimeout(r, t));
    fs.writeFileSync(path.join(out, `preview-core-${name}.png`), (await win.capturePage()).toPNG());
  }
  app.quit();
});

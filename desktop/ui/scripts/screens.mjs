// Снимки экранов: npm run screens -- <папка>  (по умолчанию ./screens)
// Electron грузит собранный dist/ с ?demo=<режим>&screen=<экран>&theme=<тема> и сохраняет capturePage в PNG.
// SAKURA_SCREENS=home,settings,devices — какие экраны снимать (по умолчанию все).
// Раскладка пишется во временный layout.json — настоящий файл владельца не трогается.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");
const out = path.resolve(process.argv[2] ?? path.join(root, "screens"));
const wanted = (process.env.SAKURA_SCREENS ?? "home,settings,devices").split(",");

const sizes = [[1440, 1024], [1180, 760]];
const modes = [["normal", "norm"], ["empty", "empty"], ["offline", "offline"]];
// экран → (префикс файла, параметр screen, режимы, темы)
const screens = {
  home: ["home", "", modes, ["night", "sketch"]],
  settings: ["settings", "settings", [["normal", "norm"]], ["night"]],
  devices: ["devices", "devices", [["normal", "norm"]], ["night"]],
};
const specs = wanted.flatMap((key) => {
  const [prefix, screen, ms, themes] = screens[key];
  return sizes.flatMap(([w, h]) => ms.flatMap(([demo, label]) => themes.map((theme) => ({
    name: `${prefix}_${label}${theme === "night" ? "" : `_${theme}`}_${w}x${h}`, width: w, height: h,
    demo: `${demo}${screen ? `&screen=${screen}` : ""}&theme=${theme}` }))));
});

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "sakura-screens-"));
const electron = path.join(root, "node_modules", "electron", "dist", process.platform === "win32" ? "electron.exe" : "electron");
const env = {
  ...process.env,
  SAKURA_SCREENSHOT_SPECS: JSON.stringify(specs),
  SAKURA_SCREENSHOT_DIR: out,
  SAKURA_LAYOUT_FILE: path.join(tmp, "layout.json"),
};
delete env.ELECTRON_RUN_AS_NODE; // VS Code передаёт его дочерним процессам — Electron стал бы Node.
const r = spawnSync(electron, [root], { env, stdio: "inherit" });
fs.rmSync(tmp, { recursive: true, force: true });
process.exit(r.status ?? 1);

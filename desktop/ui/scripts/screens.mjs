// Снимки экранов: npm run screens -- <папка>  (по умолчанию ./screens)
// Electron грузит собранный dist/ с ?demo=<режим>&screen=<экран> и сохраняет capturePage в PNG.
// SAKURA_SCREENS=home,media,video,settings — какие экраны снимать (по умолчанию все).
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");
const out = path.resolve(process.argv[2] ?? path.join(root, "screens"));
const wanted = (process.env.SAKURA_SCREENS ?? "home,media,video,settings").split(",");

const sizes = [[1536, 1024], [1180, 760]];
const modes = [["normal", "norm"], ["empty", "empty"], ["offline", "offline"]];
// экран → (префикс файла, параметр screen, режимы)
const screens = {
  home: ["home", "", modes],
  media: ["media_music", "media", modes],
  video: ["media_video", "video", [["normal", "norm"], ["empty", "empty"]]],
  settings: ["media_settings", "settings", [["normal", "norm"]]],
};
const specs = wanted.flatMap((key) => {
  const [prefix, screen, ms] = screens[key];
  return sizes.flatMap(([w, h]) => ms.map(([demo, label]) => ({
    name: `${prefix}_${label}_${w}x${h}`, width: w, height: h,
    demo: screen ? `${demo}&screen=${screen}` : demo })));
});

const electron = path.join(root, "node_modules", "electron", "dist", process.platform === "win32" ? "electron.exe" : "electron");
const env = { ...process.env, SAKURA_SCREENSHOT_SPECS: JSON.stringify(specs), SAKURA_SCREENSHOT_DIR: out };
delete env.ELECTRON_RUN_AS_NODE; // VS Code передаёт его дочерним процессам — Electron стал бы Node.
const r = spawnSync(electron, [root], { env, stdio: "inherit" });
process.exit(r.status ?? 1);

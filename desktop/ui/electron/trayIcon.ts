// Значок в трее: electron/assets/tray.ico на Windows (16–48 px), tray.png (+ tray@2x.png) — на других системах.
// Пути — от dist-electron (собранный main.js) к electron/assets; файла нет — значок приложения, иначе
// Tray получил бы пустую картинку и значок пропал бы из трея (живая проверка 21.10).
import fs from "node:fs";
import path from "node:path";

export function trayIconPath(here: string, platform: NodeJS.Platform = process.platform,
                             exists: (p: string) => boolean = (p) => fs.existsSync(p)): string {
  const assets = path.join(here, "..", "electron", "assets");
  const candidates = [
    ...(platform === "win32" ? [path.join(assets, "tray.ico")] : []),
    path.join(assets, "tray.png"),
    path.join(here, "..", "..", "assets", "sakura.ico"),
  ];
  return candidates.find(exists) ?? candidates[candidates.length - 1]!;
}

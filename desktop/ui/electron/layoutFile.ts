// %LOCALAPPDATA%\Sakura\layout.json — раскладка доски, тема и ширина чата по device_id.
// Формат: { "<device_id>": { ...настройки интерфейса } }. Запись атомарная (tmp + rename).
import fs from "node:fs";
import path from "node:path";

const DEVICE_RE = /^[\w.-]{1,64}$/;
const MAX_BYTES = 256 * 1024;

export type LayoutEntry = Record<string, unknown>;

// Копия повреждённого файла — одна за сеанс (до первой записи файл читается многократно).
const backedUp = new Set<string>();

function readAll(file: string): Record<string, LayoutEntry> {
  let text: string;
  try {
    text = fs.readFileSync(file, "utf-8");
  } catch {
    return {}; // файла ещё нет
  }
  try {
    const data: unknown = JSON.parse(text);
    if (data && typeof data === "object" && !Array.isArray(data)) return data as Record<string, LayoutEntry>;
  } catch {
    // разобрать не удалось — ниже копия
  }
  // Повреждённый файл не теряется: копия рядом, дальше — раскладка по умолчанию.
  if (!backedUp.has(file)) {
    backedUp.add(file);
    try {
      fs.copyFileSync(file, `${file}.corrupt-${Date.now()}.json`);
    } catch {
      // копия необязательна
    }
  }
  return {};
}

export function readLayout(file: string, deviceId: unknown): LayoutEntry | null {
  if (typeof deviceId !== "string" || !DEVICE_RE.test(deviceId)) return null;
  const entry = readAll(file)[deviceId];
  return entry && typeof entry === "object" && !Array.isArray(entry) ? entry : null;
}

export function writeLayout(file: string, deviceId: unknown, entry: unknown): boolean {
  if (typeof deviceId !== "string" || !DEVICE_RE.test(deviceId)) return false;
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) return false;
  const all = readAll(file);
  all[deviceId] = entry as LayoutEntry;
  const text = JSON.stringify(all, null, 1);
  if (Buffer.byteLength(text) > MAX_BYTES) return false;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, text, "utf-8");
  fs.renameSync(tmp, file);
  return true;
}

// %LOCALAPPDATA%\Sakura\layout.json — раскладка доски, тема и ширина чата по device_id.
// Формат: { "<device_id>": { ...настройки интерфейса } }. Запись атомарная (tmp + rename).
import fs from "node:fs";
import path from "node:path";

const DEVICE_RE = /^[\w.-]{1,64}$/;
const MAX_BYTES = 256 * 1024;

export type LayoutEntry = Record<string, unknown>;

function readAll(file: string): Record<string, LayoutEntry> {
  try {
    const data: unknown = JSON.parse(fs.readFileSync(file, "utf-8"));
    return data && typeof data === "object" && !Array.isArray(data) ? (data as Record<string, LayoutEntry>) : {};
  } catch {
    // Нет файла или он повреждён — начинаем с чистого листа, старый файл не трогаем до записи.
    return {};
  }
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

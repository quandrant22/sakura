// Настройки: «Сеть», «Звук», «Язык», «Расширение», «Игровой режим», «Диагностика» (журнал), «Обновление».
import { Download, FileText, FolderOpen, RefreshCw } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { bridge } from "../bridge";
import { useMediaClient } from "../media/MediaContext";
import { errorText, useApp } from "../store";

const input = "rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent";
const btn = "flex items-center gap-1 rounded-full border border-line px-3 py-1 text-xs text-ink-dim hover:text-ink disabled:opacity-40";

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[220px_1fr] items-start gap-4 border-b border-line py-3 last:border-0">
      <div><div className="text-sm text-ink">{label}</div>{hint && <div className="mt-0.5 text-xs text-ink-dim">{hint}</div>}</div>
      <div className="min-w-0 text-sm text-ink">{children}</div>
    </div>
  );
}

export function NetworkSection() {
  const s = useApp((x) => x.settings);
  const server = useApp((x) => x.server);
  return (
    <div className="px-4 pb-2">
      <Row label="Сервер" hint="Адрес из .env (VPS_WS_URL); токен не показывается">
        {s?.offline ? "Без сервера (SAKURA_OFFLINE)" : String(s?.server_url ?? "—")}
        <span className={"ml-2 text-xs " + (server.online ? "text-online" : "text-warn")}>
          {server.connecting ? "подключение…" : server.online ? `на связи, протокол v${server.proto ?? "?"}` : "нет связи"}</span>
      </Row>
      <Row label="Транспорт" hint="SERVER_TRANSPORT: ws, wss или noise (DECISIONS №43)">
        {String(s?.server_transport ?? "ws")}{s?.cert_pinned ? " · сертификат закреплён" : ""}
        {s?.server_transport === "ws" && <span className="ml-2 text-xs text-warn">без шифрования</span>}
      </Row>
    </div>
  );
}

interface AudioDev { id: number; name: string; default: boolean }

export function SoundSection() {
  const client = useMediaClient();
  const s = useApp((x) => x.settings);
  const [devs, setDevs] = useState<{ inputs: AudioDev[]; outputs: AudioDev[] } | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    let alive = true;
    client.call<{ inputs: AudioDev[]; outputs: AudioDev[] }>("list_audio_devices").then(
      (r) => { if (alive) setDevs(r); }, (e: unknown) => { if (alive) setMsg(errorText(e)); });
    return () => { alive = false; };
  }, [client]);
  const set = (key: string, value: unknown) =>
    client.call("settings_set", { key, value }).then(() => setMsg("Сохранено. Применится после перезапуска ядра."),
                                                      (e: unknown) => setMsg(errorText(e)));
  const select = (key: "input_device" | "output_device", list: AudioDev[] | undefined, label: string) => (
    <select aria-label={label} className={input + " max-w-full"} value={String(s?.[key] ?? "")}
            onChange={(e) => void set(key, e.target.value === "" ? null : Number(e.target.value))}>
      <option value="">По умолчанию Windows</option>
      {list?.map((d) => <option key={d.id} value={d.id}>{d.name}{d.default ? " (по умолчанию)" : ""}</option>)}
    </select>
  );
  return (
    <div className="px-4 pb-2">
      <Row label="Микрофон" hint="Откуда Сакура слушает">{select("input_device", devs?.inputs, "Микрофон")}</Row>
      <Row label="Вывод голоса" hint="Устройство вывода музыки и видео — в разделе «Медиа»">{select("output_device", devs?.outputs, "Вывод голоса")}</Row>
      {msg && <div className="py-2 text-xs text-ink-dim">{msg}</div>}
    </div>
  );
}

export function LanguageSection() {
  const client = useMediaClient();
  const lang = useApp((x) => x.settings?.language ?? "ru");
  return (
    <div className="px-4 pb-2">
      <Row label="Язык интерфейса" hint="Language">
        <select aria-label="Язык интерфейса" value={String(lang)} className={input}
                onChange={(e) => void client.call("settings_set", { key: "language", value: e.target.value })}>
          <option value="ru">Русский</option>
          <option value="en">English</option>
        </select>
      </Row>
    </div>
  );
}

export function ExtensionSection() {
  const s = useApp((x) => x.settings);
  return (
    <div className="px-4 pb-2">
      <Row label="Расширение браузера" hint="Управление вкладками и YouTube">
        <span className={s?.extension_connected ? "text-online" : "text-warn"}>
          {s?.extension_connected ? "● подключено" : "○ не подключено"}</span>
        <div className="mt-1 text-xs text-ink-dim">
          Opera GX / Chrome: «Расширения» → режим разработчика → «Загрузить распакованное» → C:\sakura-dev\desktop\extension (версия 3.1.0)
        </div>
      </Row>
    </div>
  );
}

export function GameModeSection() {
  const client = useMediaClient();
  const on = useApp((x) => x.gameMode);
  return (
    <div className="px-4 pb-2">
      <Row label="Игровой режим" hint="Сакура тише и не перехватывает экран; включается сам при запуске игр из списка">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={on} className="accent-accent"
                 onChange={(e) => void client.call("game_mode", { on: e.target.checked })} /> Включён</label>
      </Row>
    </div>
  );
}

/** «Канал: защищён / нет» и версия протокола для Диагностики. */
export function channelLine(diag: Record<string, unknown>): string {
  const ch = (diag.channel ?? {}) as { transport?: string | null; secure?: boolean };
  const server = (diag.server ?? {}) as { online?: boolean; proto?: number | null };
  const secure = ch.secure ? "защищён" : "не защищён";
  const t = ch.transport ?? (server.online ? "ws" : "нет связи");
  return `${secure} (${t})${server.proto ? `, протокол v${server.proto}` : ""}`;
}

export function DiagnosticsSection() {
  const client = useMediaClient();
  const [diag, setDiag] = useState<Record<string, unknown> | null>(null);
  const [lines, setLines] = useState<string[] | null>(null);
  const [msg, setMsg] = useState("");
  const loadDiag = async () => { try { setDiag(await client.call("diagnostics")); } catch (e) { setMsg(errorText(e)); } };
  const loadLog = async () => {
    try { setLines((await client.call<{ lines: string[] }>("logs_tail", { n: 200 })).lines); } catch (e) { setMsg(errorText(e)); }
  };
  const report = async () => {
    try {
      const r = await client.call<{ path: string }>("problem_report");
      setMsg(`Отчёт сохранён: ${r.path} — журналы и версии без токенов и без содержимого разговоров`);
    } catch (e) { setMsg(errorText(e)); }
  };
  const music = diag?.music as { count?: number; p50?: number; p95?: number } | undefined;
  return (
    <div className="px-4 pb-3">
      <div className="flex flex-wrap gap-2 py-2">
        <button type="button" className={btn} onClick={() => void loadDiag()}><RefreshCw size={13} /> Проверить</button>
        <button type="button" className={btn} onClick={() => void loadLog()}><FileText size={13} /> Журнал</button>
        <button type="button" className={btn} onClick={() => void bridge().openLogs()}><FolderOpen size={13} /> Папка журналов</button>
        <button type="button" className={btn} onClick={() => void report()}><FileText size={13} /> Отчёт о проблеме</button>
      </div>
      {diag && (
        <dl aria-label="Диагностика" className="grid grid-cols-[180px_1fr] gap-y-1 text-xs">
          <dt className="text-ink-dim">Устройство</dt><dd className="text-ink">{String(diag.device_id)}</dd>
          <dt className="text-ink-dim">Ядро</dt><dd className="text-ink">pid {String(diag.pid)}, Python {String(diag.python)}</dd>
          <dt className="text-ink-dim">Система</dt><dd className="text-ink">{String(diag.os)}</dd>
          <dt className="text-ink-dim">Канал</dt>
          <dd className="text-ink">{channelLine(diag)}</dd>
          <dt className="text-ink-dim">Трек: событие → окно</dt>
          <dd className="text-ink">{music?.count ? `p50 ${music.p50} мс, p95 ${music.p95} мс (${music.count})` : "замеров пока нет"}</dd>
        </dl>
      )}
      {lines && (
        <pre aria-label="Журнал ядра" className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-btn bg-panel2 p-2 text-[11px] leading-snug text-ink-dim">
          {lines.join("\n") || "журнал пуст"}
        </pre>
      )}
      {msg && <div role="status" className="mt-1 break-all text-xs text-ink">{msg}</div>}
    </div>
  );
}

export function UpdateSection() {
  const client = useMediaClient();
  const [st, setSt] = useState<{ branch: string; behind: number; ahead: number; dirty: boolean; news?: string[] } | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const check = async () => {
    setBusy(true);
    try { setSt(await client.call("update_status")); setMsg(""); } catch (e) { setMsg(errorText(e)); }
    setBusy(false);
  };
  const pull = async () => {
    setBusy(true);
    try { setMsg((await client.call<{ detail: string }>("update_pull")).detail); } catch (e) { setMsg(errorText(e)); }
    setBusy(false);
    void check();
  };
  return (
    <div className="px-4 pb-3">
      <div className="flex flex-wrap items-center gap-2 py-2 text-xs">
        <button type="button" disabled={busy} className={btn} onClick={() => void check()}><RefreshCw size={13} /> Проверить обновления</button>
        {st && st.behind > 0 && !st.dirty && (
          <button type="button" disabled={busy} className={btn} onClick={() => void pull()}><Download size={13} /> Обновить ({st.behind})</button>
        )}
        {st && <span aria-label="Состояние обновления" className="text-ink-dim">
          ветка {st.branch}: {st.behind ? `доступно коммитов: ${st.behind}` : "обновлений нет"}{st.dirty ? " · есть локальные изменения — обновление по кнопке недоступно" : ""}
        </span>}
      </div>
      {st?.news && st.news.length > 0 && (
        <ul aria-label="Что нового" className="mb-2 list-disc pl-5 text-xs text-ink">
          {st.news.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
      <div className="text-xs text-ink-dim">Если новая версия не соберётся или не запустится, Сакура вернёт прежнюю. Только перемотка вперёд (git pull --ff-only); после обновления перезапустите Сакуру.</div>
      {msg && <div role="status" className="mt-1 text-xs text-ink">{msg}</div>}
    </div>
  );
}

// Настройки → «Безопасность»: защищённый канал securechannel/1 (Noise). Статус канала, отпечатки ключей,
// «Подключить это устройство» (8 слов или QR из файла/буфера), список устройств сервера, «Сбросить ключи».
// Ключи не показываются — только отпечатки; QR распознаётся в окне (jsQR), в ядро уходит текст ссылки.
import jsQR from "jsqr";
import { ClipboardPaste, FileImage, KeyRound, Link2, ShieldCheck, ShieldOff, Trash2 } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { useMediaClient } from "../media/MediaContext";
import { errorText } from "../store";

interface Keys { device_key: boolean; device_fp: string | null; storage: string | null; paired: boolean;
                 server_fp: string | null; device_id: string | null }
interface Channel { transport: string | null; secure: boolean; reason?: string | null; age_s?: number; rekeys?: number;
                    proto?: number | null }
export interface SecureStatus { keys: Keys; channel: Channel; mode: string; pinned: boolean }
/** Устройство реестра канала (ответ secure_devices, PROTOCOL.md сервера §10.3). */
export interface SecureDevice { device_id: string; name?: string | null; fingerprint: string; paired_at?: number | null;
                                last_seen?: number | null; online: boolean; secure_now: boolean; revoked: boolean; current: boolean }

const dateText = (ts: number) => new Date(ts * 1000).toLocaleString().slice(0, 17);

const btn = "flex items-center gap-1 rounded-full border border-line px-3 py-1 text-xs text-ink-dim hover:text-ink disabled:opacity-40";

/** Состояние канала понятным языком. */
export function channelText(st: SecureStatus): { text: string; ok: boolean; hint: string } {
  const c = st.channel;
  if (c.transport === "noise" && c.secure) {
    return { text: "Зашифровано", ok: true, hint: "Сакура и сервер общаются по защищённому каналу Noise" };
  }
  if (c.transport === "wss") return { text: "Зашифровано (TLS)", ok: true, hint: "Соединение wss:// с проверкой сертификата" };
  if (c.transport === "ws" && st.mode === "noise") {
    return { text: "Не защищено", ok: false, hint: `Защищённый канал недоступен: ${c.reason ?? "причина неизвестна"}. Связь идёт без шифрования.` };
  }
  if (c.transport === "ws") {
    return { text: "Не защищено", ok: false, hint: "Обычный ws://: включите VPN или подключите устройство ниже и выберите режим noise" };
  }
  return { text: "Нет связи", ok: false, hint: c.reason ?? "Сакура ещё не подключилась к серверу" };
}

/** Текст QR из картинки (файл или буфер обмена). */
export async function qrFromBlob(blob: Blob): Promise<string | null> {
  const bmp = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bmp.width;
  canvas.height = bmp.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(bmp, 0, 0);
  const img = ctx.getImageData(0, 0, bmp.width, bmp.height);
  return jsQR(img.data, img.width, img.height)?.data ?? null;
}

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[220px_1fr] items-start gap-4 border-b border-line py-3 last:border-0">
      <div><div className="text-sm text-ink">{label}</div>{hint && <div className="mt-0.5 text-xs text-ink-dim">{hint}</div>}</div>
      <div className="min-w-0 text-sm text-ink">{children}</div>
    </div>
  );
}

export function SecuritySection() {
  const client = useMediaClient();
  const [st, setSt] = useState<SecureStatus | null>(null);
  const [words, setWords] = useState("");
  const [msg, setMsg] = useState<{ text: string; warn: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [devices, setDevices] = useState<SecureDevice[] | string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    client.call<SecureStatus>("secure_status").then(
      (r) => { if (alive) setSt(r); },
      (e: unknown) => { if (alive) setMsg({ text: errorText(e), warn: true }); });
    return () => { alive = false; };
  }, [client, tick]);

  const pair = async (payload: Record<string, unknown>) => {
    setBusy(true);
    setMsg({ text: "Подключаю устройство…", warn: false });
    try {
      const r = await client.call<{ server_fp: string; device_fp: string }>("secure_pair", payload);
      setMsg({ text: `Готово. Отпечаток сервера ${r.server_fp} — сверьте с Telegram. Перезапустите ядро, чтобы включить канал.`, warn: false });
      setWords("");
    } catch (e) {
      setMsg({ text: errorText(e), warn: true });
    }
    setBusy(false);
    setTick((t) => t + 1);
  };
  const fromImage = async (blob: Blob | null | undefined) => {
    if (!blob) { setMsg({ text: "Картинка с QR не найдена", warn: true }); return; }
    const text = await qrFromBlob(blob).catch(() => null);
    if (!text) { setMsg({ text: "На картинке не нашёлся QR — попробуйте ввести 8 слов", warn: true }); return; }
    await pair({ uri: text });
  };
  const fromClipboard = async () => {
    try {
      for (const item of await navigator.clipboard.read()) {
        const type = item.types.find((t) => t.startsWith("image/"));
        if (type) { await fromImage(await item.getType(type)); return; }
        if (item.types.includes("text/plain")) {
          const text = await (await item.getType("text/plain")).text();
          if (text.startsWith("sakura-pair://")) { await pair({ uri: text.trim() }); return; }
        }
      }
      setMsg({ text: "В буфере обмена нет QR или ссылки sakura-pair://", warn: true });
    } catch {
      setMsg({ text: "Нет доступа к буферу обмена — загрузите картинку файлом", warn: true });
    }
  };
  const reset = async () => {
    setConfirmReset(false);
    try { await client.call("secure_reset"); setMsg({ text: "Ключи сброшены. Устройство нужно подключить заново.", warn: false }); }
    catch (e) { setMsg({ text: errorText(e), warn: true }); }
    setTick((t) => t + 1);
  };
  const loadDevices = async () => {
    try { const r = await client.call<{ devices?: SecureDevice[] }>("secure_devices"); setDevices(r.devices ?? []); }
    catch (e) { setDevices(errorText(e)); }
  };

  const ch = st ? channelText(st) : null;
  return (
    <div className="px-4 pb-3">
      <Row label="Канал до сервера" hint="Режим: SERVER_TRANSPORT (ws, noise, noise-only)">
        {ch && (
          <div aria-label="Состояние канала">
            <div className={"flex items-center gap-1.5 " + (ch.ok ? "text-online" : "text-warn")}>
              {ch.ok ? <ShieldCheck size={15} /> : <ShieldOff size={15} />} {ch.text}
              <span className="text-xs text-ink-dim">· режим {st?.mode}{st?.channel.proto ? ` · протокол v${st.channel.proto}` : ""}</span>
            </div>
            <div className="mt-0.5 text-xs text-ink-dim">{ch.hint}</div>
            {st?.channel.transport === "noise" && (
              <div className="mt-0.5 text-xs text-ink-dim">сеанс {Math.round(st.channel.age_s ?? 0)} с, смен ключа: {st.channel.rekeys ?? 0}</div>
            )}
          </div>
        )}
      </Row>
      <Row label="Ключи" hint="Только отпечатки; сами ключи хранятся в Windows (DPAPI) и не показываются">
        <div className="space-y-0.5 text-xs">
          <div>Это устройство: <span className="font-mono">{st?.keys.device_fp ?? "ключа ещё нет"}</span>
            {st?.keys.storage === "dpapi" ? " · защищён Windows" : st?.keys.storage === "file" ? " · файл только для пользователя" : ""}</div>
          <div>Сервер: <span className="font-mono">{st?.keys.server_fp ?? "не подключено"}</span>{st?.pinned ? " · закреплён" : ""}</div>
          {st?.keys.device_id && <div>Имя на сервере: {st.keys.device_id}</div>}
        </div>
      </Row>
      <Row label="Подключить это устройство" hint="В Telegram: /pair — придут QR и 8 слов (действуют 10 минут)">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void pair({ words }); }}>
          <input value={words} onChange={(e) => setWords(e.target.value)} aria-label="8 слов" placeholder="лес кот мост …"
                 className="flex-1 rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent" />
          <button type="submit" disabled={busy || words.trim().split(/\s+/).length < 8} className={btn}><KeyRound size={13} /> Подключить</button>
        </form>
        <div className="mt-2 flex flex-wrap gap-2">
          <label className={btn + " cursor-pointer"}><FileImage size={13} /> QR из файла
            <input type="file" accept="image/*" aria-label="QR из файла" className="hidden"
                   onChange={(e) => void fromImage(e.target.files?.[0])} /></label>
          <button type="button" disabled={busy} onClick={() => void fromClipboard()} className={btn}><ClipboardPaste size={13} /> QR из буфера</button>
        </div>
      </Row>
      <Row label="Устройства" hint="Какие устройства подключены к серверу">
        <button type="button" onClick={() => void loadDevices()} className={btn}><Link2 size={13} /> Показать</button>
        {typeof devices === "string" && <div className="mt-1 text-xs text-ink-dim">{devices}</div>}
        {Array.isArray(devices) && (devices.length === 0 ? <div className="mt-1 text-xs text-ink-dim">устройств нет</div> : (
          <ul aria-label="Устройства канала" className="mt-1 space-y-1 text-xs">
            {devices.map((d) => (
              <li key={d.device_id} aria-current={d.current || undefined} className={d.revoked ? "text-ink-dim line-through" : "text-ink"}>
                <span className={"mr-1.5 inline-block h-2 w-2 rounded-full " + (d.online ? "bg-online" : "bg-ink-dim")} />
                {d.name || d.device_id} <span className="text-ink-dim">({d.device_id})</span>
                {d.current && <span className="ml-1 text-accent">· это устройство</span>}
                <div className="pl-3.5 text-ink-dim">
                  <span className="font-mono">{d.fingerprint}</span>
                  {" · "}{d.revoked ? "отозвано" : d.secure_now ? "защищено сейчас" : d.online ? "онлайн без защиты" : "не в сети"}
                  {d.paired_at ? ` · подключено ${dateText(d.paired_at)}` : ""}
                  {d.last_seen ? ` · был ${dateText(d.last_seen)}` : ""}
                </div>
              </li>
            ))}
          </ul>
        ))}
      </Row>
      <Row label="Сбросить ключи" hint="Удалит ключ устройства и данные подключения; потом — заново /pair">
        {confirmReset ? (
          <span className="flex items-center gap-2 text-xs text-warn">Точно сбросить?
            <button type="button" onClick={() => void reset()} className="underline">Да</button>
            <button type="button" onClick={() => setConfirmReset(false)} className="text-ink-dim underline">Нет</button></span>
        ) : <button type="button" onClick={() => setConfirmReset(true)} className={btn}><Trash2 size={13} /> Сбросить</button>}
      </Row>
      {msg && <div role="status" className={"mt-2 text-xs " + (msg.warn ? "text-warn" : "text-ink")}>{msg.text}</div>}
    </div>
  );
}

// Настройки → «Секреты»: поля только для записи. Показывается лишь «задан / не задан»;
// значение не хранится в состоянии React или store (неуправляемое поле, очищается сразу после
// отправки), не логируется и маскируется (type=password) — не видно и на скриншотах.
import { KeyRound, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useMediaClient } from "../media/MediaContext";
import { errorText } from "../store";

export const SECRETS: { key: string; label: string; hint: string }[] = [
  { key: "WS_TOKEN", label: "Токен сервера (WS_TOKEN)", hint: "Без него Сакура не подключится к серверу" },
  { key: "YANDEX_MUSIC_TOKEN", label: "Токен Яндекс.Музыки", hint: "Лайки, дизлайки и текст песни в панели музыки" },
];

interface SecretsStatus { env_file: string | null; exists: boolean; keys: Record<string, boolean> }

function SecretField({ k, label, hint, isSet, onSaved }: {
  k: string; label: string; hint: string; isSet: boolean | undefined; onSaved(keys: Record<string, boolean>): void;
}) {
  const client = useMediaClient();
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    const el = ref.current;
    const value = el?.value ?? "";
    if (el) el.value = ""; // значение не задерживается в окне ни на миг дольше отправки
    if (!value.trim()) { setErr("Введите значение"); return; }
    setBusy(true);
    try {
      const r = await client.call<{ keys: Record<string, boolean> }>("secrets_set", { key: k, value });
      setErr(null);
      onSaved(r.keys);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-[220px_1fr] items-start gap-4 border-b border-line py-3 last:border-0">
      <div>
        <div className="text-sm text-ink">{label}</div>
        <div className="mt-0.5 text-xs text-ink-dim">{hint}</div>
      </div>
      <div className="min-w-0 space-y-1.5">
        <div className={"text-xs " + (isSet ? "text-online" : "text-warn")} aria-label={`${k}: ${isSet ? "задан" : "не задан"}`}>
          {isSet == null ? "…" : isSet ? "● задан" : "○ не задан"}
        </div>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <input ref={ref} type="password" autoComplete="off" spellCheck={false} aria-label={`Новое значение ${k}`}
                 placeholder={isSet ? "заменить значение" : "вставьте значение"}
                 className="flex-1 rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent" />
          <button type="submit" disabled={busy}
                  className="flex items-center gap-1 rounded-lg border border-line px-3 text-xs text-ink-dim hover:text-ink disabled:opacity-40">
            <KeyRound size={14} /> Сохранить
          </button>
        </form>
        {err && <div role="alert" className="text-xs text-warn">{err}</div>}
      </div>
    </div>
  );
}

export function SecretsSection() {
  const client = useMediaClient();
  const [st, setSt] = useState<SecretsStatus | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [restarting, setRestarting] = useState(false);

  useEffect(() => {
    let alive = true;
    client.call<SecretsStatus>("secrets_status").then(
      (r) => { if (alive) { setSt(r); setFailed(null); } },
      (e: unknown) => { if (alive) setFailed(errorText(e)); },
    );
    return () => { alive = false; };
  }, [client]);

  const restart = async () => {
    setRestarting(true);
    try { await client.call("core_restart"); } catch { /* ядро закрывается — ответа может не быть */ }
  };

  if (failed) return <div className="p-4 text-sm text-ink-dim">Нет связи с ядром Сакуры: {failed}</div>;
  return (
    <div className="px-4 pb-2">
      <div className="py-2 text-xs text-ink-dim">
        Значения записываются в {st?.env_file ?? "файл .env"} и нигде не показываются. Перед записью делается копия .env.bak.
      </div>
      {SECRETS.map((s) => (
        <SecretField key={s.key} k={s.key} label={s.label} hint={s.hint} isSet={st?.keys[s.key]}
                     onSaved={(keys) => { setSt((x) => (x ? { ...x, keys } : x)); setSaved(true); }} />
      ))}
      {saved && (
        <div role="status" className="mt-2 flex items-center gap-3 rounded-btn bg-panel2 px-3 py-2 text-xs text-ink">
          <span className="flex-1">Сохранено. Новое значение заработает после перезапуска ядра.</span>
          <button type="button" disabled={restarting} onClick={() => void restart()}
                  className="flex items-center gap-1 rounded-full border border-line px-3 py-1 hover:border-accent disabled:opacity-40">
            <RotateCw size={13} /> {restarting ? "Перезапускаю…" : "Перезапустить ядро"}
          </button>
        </div>
      )}
    </div>
  );
}

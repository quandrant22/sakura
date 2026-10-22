// Настройки → «Приложения»: параметры запуска из белого списка. Сейчас — Яндекс.Музыка:
// «Поддержка кнопок окна» (--force-renderer-accessibility) и перезапуск с ней.
import { RotateCw } from "lucide-react";
import { useEffect, useState } from "react";

import { useMediaClient } from "../media/MediaContext";
import { errorText } from "../store";

interface AppState {
  running: boolean; with_flag: boolean; store: boolean; exe_found: boolean; a11y: boolean | null;
  enabled: boolean; args: string[];
}

export function appStatusText(s: AppState): string {
  if (!s.exe_found) return "Приложение не найдено";
  if (s.store) return "Версия из Microsoft Store — параметры запуска не поддерживаются";
  if (!s.running) return "Не запущено";
  if (!s.with_flag) return "Запущено без ключа — кнопки окна недоступны";
  return s.a11y ? "Кнопки окна доступны" : "Запущено с ключом, но кнопки окна пока не видны";
}

export function AppsSection() {
  const client = useMediaClient();
  const [st, setSt] = useState<AppState | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    client.call<{ yandex_music: AppState }>("apps_state").then(
      (r) => { if (alive) setSt(r.yandex_music); },
      (e: unknown) => { if (alive) setMsg(errorText(e)); },
    );
    return () => { alive = false; };
  }, [client, tick]);

  const toggle = async (on: boolean) => {
    try { await client.call("settings_set", { key: "music_accessibility", value: on }); } catch (e) { setMsg(errorText(e)); }
    setTick((t) => t + 1);
  };
  const restart = async () => {
    setBusy(true);
    setMsg("Перезапускаю Яндекс.Музыку…");
    try {
      const r = await client.call<{ ok: boolean; detail: string }>("app_restart", { app: "yandex_music" });
      setMsg(r.detail);
    } catch (e) {
      setMsg(errorText(e));
    }
    setBusy(false);
    setTick((t) => t + 1);
  };

  return (
    <div className="px-4 pb-2">
      <div className="grid grid-cols-[220px_1fr] items-start gap-4 py-3">
        <div>
          <div className="text-sm text-ink">Яндекс.Музыка</div>
          <div className="mt-0.5 text-xs text-ink-dim">Параметры: {st?.args.length ? st.args.join(" ") : "нет"}</div>
        </div>
        <div className="space-y-2 text-sm">
          <label className="flex items-center gap-2 text-ink">
            <input type="checkbox" checked={st?.enabled ?? true} onChange={(e) => void toggle(e.target.checked)} className="accent-accent" />
            Поддержка кнопок окна
          </label>
          <div className="text-xs text-ink-dim">
            Сакура сможет нажимать «Перемешать», «Повтор» и «Моя волна» в окне приложения. Параметры задаются только здесь —
            не голосом и не с сервера.
          </div>
          <div role="status" aria-label="Состояние Яндекс.Музыки" className={"text-xs " + (st?.with_flag && st.a11y ? "text-online" : "text-warn")}>
            {st ? appStatusText(st) : "…"}
          </div>
          {st && st.enabled && !st.store && st.exe_found && !(st.with_flag && st.a11y) && (
            <button type="button" disabled={busy} onClick={() => void restart()}
                    className="flex items-center gap-1 rounded-full border border-line px-3 py-1 text-xs text-ink-dim hover:text-ink disabled:opacity-40">
              <RotateCw size={13} /> Перезапустить с поддержкой кнопок
            </button>
          )}
          {msg && <div className="text-xs text-ink-dim">{msg}</div>}
        </div>
      </div>
    </div>
  );
}

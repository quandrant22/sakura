// Настройки → «Голос»: чувствительность слова «Сакура», клавиша «говорить» (push-to-talk), таблица замен.
import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { bridge } from "../bridge";
import { useMediaClient } from "../media/MediaContext";
import { errorText, useApp } from "../store";

const input = "rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent";
export const DEFAULT_TALK = "Control+Alt+Space";
const SENS: Record<string, string> = { auto: "Авто — по шуму в комнате", low: "Низкая — только чёткое «Сакура» (шумно)",
                                       normal: "Обычная", high: "Высокая — быстрее, но чаще ложные срабатывания" };

/** Подключение клавиши «говорить» к окну: глобальная клавиша → listen_now. */
export function useTalkHotkey() {
  const listen = useApp((s) => s.listenNow);
  const combo = useApp((s) => (s.settings?.hotkey_talk as string | undefined) || DEFAULT_TALK);
  useEffect(() => bridge().core.onTalk(() => void listen()), [listen]);
  useEffect(() => { void bridge().core.setTalkHotkey(combo); }, [combo]);
}

export function VoiceSection() {
  const client = useMediaClient();
  const s = useApp((x) => x.settings);
  const [rows, setRows] = useState<[string, string][]>([]);
  const [msg, setMsg] = useState("");
  const [loaded, setLoaded] = useState(false);
  if (!loaded && s) {
    setRows(((s.stt_replacements as [string, string][] | undefined) ?? []).map((r) => [r[0], r[1]]));
    setLoaded(true);
  }
  const set = async (key: string, value: unknown, done = "Сохранено") => {
    try { await client.call("settings_set", { key, value }); setMsg(done); } catch (e) { setMsg(errorText(e)); }
  };
  const setHotkey = async (combo: string) => {
    const ok = await bridge().core.setTalkHotkey(combo);
    if (!ok && combo) { setMsg(`Сочетание ${combo} занято или неверно`); return; }
    await set("hotkey_talk", combo);
  };
  return (
    <div className="px-4 pb-3 text-sm">
      <div className="grid grid-cols-[220px_1fr] items-start gap-4 border-b border-line py-3">
        <div><div className="text-ink">Чувствительность «Сакура»</div><div className="text-xs text-ink-dim">Авто подстраивается под шум</div></div>
        <select aria-label="Чувствительность слова Сакура" className={input} value={String(s?.wake_sensitivity ?? "auto")}
                onChange={(e) => void set("wake_sensitivity", e.target.value)}>
          {Object.entries(SENS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <div className="grid grid-cols-[220px_1fr] items-start gap-4 border-b border-line py-3">
        <div><div className="text-ink">Клавиша «говорить»</div><div className="text-xs text-ink-dim">Слушать без слова «Сакура», из любого окна</div></div>
        <input aria-label="Клавиша говорить" className={input} defaultValue={String(s?.hotkey_talk ?? DEFAULT_TALK)}
               placeholder={DEFAULT_TALK} onBlur={(e) => void setHotkey(e.target.value.trim())} />
      </div>
      <div className="grid grid-cols-[220px_1fr] items-start gap-4 py-3">
        <div><div className="text-ink">Замены распознанного</div><div className="text-xs text-ink-dim">Например «вал хейм» → «Valheim»</div></div>
        <div className="space-y-1.5">
          {rows.map((r, i) => (
            <div key={i} className="flex gap-2">
              <input aria-label={`Распознано ${i + 1}`} value={r[0]} className={input + " flex-1"}
                     onChange={(e) => setRows(rows.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))} />
              <input aria-label={`Заменить на ${i + 1}`} value={r[1]} className={input + " flex-1"}
                     onChange={(e) => setRows(rows.map((x, j) => (j === i ? [x[0], e.target.value] : x)))} />
              <button type="button" aria-label="Убрать замену" onClick={() => setRows(rows.filter((_, j) => j !== i))}
                      className="text-ink-dim hover:text-warn"><X size={14} /></button>
            </div>
          ))}
          <div className="flex gap-2">
            <button type="button" onClick={() => setRows([...rows, ["", ""]])}
                    className="flex items-center gap-1 rounded-full border border-line px-3 py-1 text-xs text-ink-dim hover:text-ink"><Plus size={13} /> Добавить</button>
            <button type="button" onClick={() => void set("stt_replacements", rows.filter((r) => r[0].trim()), "Замены сохранены")}
                    className="rounded-full border border-line px-3 py-1 text-xs text-ink-dim hover:text-ink">Сохранить замены</button>
          </div>
        </div>
      </div>
      {msg && <div role="status" className="text-xs text-ink-dim">{msg}</div>}
    </div>
  );
}

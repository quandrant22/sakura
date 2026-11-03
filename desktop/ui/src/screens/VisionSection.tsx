// Настройки → «Зрение»: разрешить Сакуре самой поглядывать на экран и свой список приватных окон.
// Кадр по прямой просьбе («глянь на экран») работает и без разрешения; приватные окна не снимаются никогда.
import { useState } from "react";

import { useMediaClient } from "../media/MediaContext";
import { errorText, useApp } from "../store";

const input = "rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent";

/** Строки списка → чистый список без пустых и повторов. */
export function parsePrivate(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(/[\n,;]+/)) {
    const v = raw.trim();
    if (v && !out.some((x) => x.toLowerCase() === v.toLowerCase())) out.push(v);
  }
  return out.slice(0, 100);
}

export function VisionSection() {
  const client = useMediaClient();
  const s = useApp((x) => x.settings);
  const allowed = Boolean(s?.vision_glance_allowed);
  const [draft, setDraft] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const saved = ((s?.vision_private as string[] | undefined) ?? []).join("\n");
  const set = async (key: string, value: unknown) => {
    try { await client.call("settings_set", { key, value }); setMsg("Сохранено"); } catch (e) { setMsg(errorText(e)); }
  };
  return (
    <div className="px-4 pb-3 text-sm">
      <div className="grid grid-cols-[220px_1fr] items-start gap-4 border-b border-line py-3">
        <div>
          <div className="text-ink">Поглядывать на экран</div>
          <div className="text-xs text-ink-dim">Изредка, сама, с короткой репликой. По просьбе «глянь на экран» смотрит всегда</div>
        </div>
        <div className="space-y-1">
          <label className="flex items-center gap-2 text-ink">
            <input type="checkbox" checked={allowed} aria-label="Разрешить Сакуре поглядывать" className="accent-accent"
                   onChange={(e) => void set("vision_glance_allowed", e.target.checked)} /> Разрешить</label>
          <div className="text-xs text-ink-dim">
            Включить сам взгляд нужно ещё и голосом: «поглядывай на экран». Каждый взгляд виден уведомлением.
          </div>
        </div>
      </div>
      <div className="grid grid-cols-[220px_1fr] items-start gap-4 py-3">
        <div>
          <div className="text-ink">Приватные окна</div>
          <div className="text-xs text-ink-dim">Часть заголовка или имя программы, по одному в строке. Менеджеры паролей, банки и инкогнито — всегда</div>
        </div>
        <div className="space-y-1.5">
          <textarea aria-label="Приватные окна" rows={4} className={input + " w-full"} placeholder={"telegram.exe\nЛичная переписка"}
                    value={draft ?? saved} onChange={(e) => setDraft(e.target.value)} />
          <button type="button" disabled={draft === null}
                  onClick={() => { void set("vision_private", parsePrivate(draft ?? "")); setDraft(null); }}
                  className="rounded-full border border-line px-3 py-1 text-xs text-ink-dim hover:text-ink disabled:opacity-40">
            Сохранить список</button>
          {msg && <div role="status" className="text-xs text-ink-dim">{msg}</div>}
        </div>
      </div>
    </div>
  );
}

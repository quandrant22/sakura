// Экран «Память»: что Сакура помнит о пользователе — категории, поиск, правка, удаление с подтверждением.
// Данные — с сервера (memory_list/search/update/delete); сервер без поддержки — «Сервер не поддерживает».
import { Brain, Check, Pencil, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CoreError } from "../api/types";
import { Card } from "../components/ui";
import { useMediaClient } from "../media/MediaContext";
import { errorText } from "../store";

export interface MemoryItem { id: string; category: string; text: string; ts: number }
interface MemoryReply { items: MemoryItem[]; total: number; counts: Record<string, number> }

const CATEGORY: Record<string, string> = { preferences: "Предпочтения", facts: "Факты", bookmarks: "Закладки" };

export function Memory() {
  const client = useMediaClient();
  const [data, setData] = useState<MemoryReply | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error" | "unsupported">("loading");
  const [error, setError] = useState("");
  const [cat, setCat] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const request = useCallback(async (msg: Record<string, unknown> & { type: string }) => {
    try {
      const r = await client.server<MemoryReply>(msg);
      setState("ready");
      return r;
    } catch (e) {
      const unsupported = e instanceof CoreError && (e.code === "unsupported" || e.code === "unknown_type");
      setState(unsupported ? "unsupported" : "error");
      setError(unsupported ? "Сервер не поддерживает «Память»" : errorText(e));
      return null;
    }
  }, [client]);

  useEffect(() => {
    let alive = true;
    const msg = q.trim() ? { type: "memory_search", q: q.trim() } : { type: "memory_list", ...(cat ? { category: cat } : {}) };
    client.server<MemoryReply>(msg).then(
      (r) => { if (alive) { setData(r); setState("ready"); } },
      (e: unknown) => {
        if (!alive) return;
        const unsupported = e instanceof CoreError && (e.code === "unsupported" || e.code === "unknown_type");
        setState(unsupported ? "unsupported" : "error");
        setError(unsupported ? "Сервер не поддерживает «Память»" : errorText(e));
      },
    );
    return () => { alive = false; };
  }, [client, cat, q, tick]);

  const save = async () => {
    if (!editing) return;
    await request({ type: "memory_update", id: editing.id, text: editing.text });
    setEditing(null);
    setTick((t) => t + 1);
  };
  const remove = async (id: string) => {
    await request({ type: "memory_delete", id });
    setConfirm(null);
    setTick((t) => t + 1);
  };

  return (
    <Card title="Память" icon={<Brain size={18} />} className="h-full min-h-0">
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-4 pb-4">
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex flex-1 items-center gap-2 rounded-lg border border-line bg-panel2 px-2.5 py-1.5">
            <Search size={14} className="text-ink-dim" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск по памяти" aria-label="Поиск по памяти"
                   className="flex-1 bg-transparent text-sm text-ink outline-none" />
          </label>
          {[null, ...Object.keys(data?.counts ?? {})].map((c) => (
            <button key={c ?? "all"} type="button" onClick={() => setCat(c)} aria-pressed={cat === c}
                    className={"rounded-full px-3 py-1 text-xs " + (cat === c ? "bg-accent/20 text-ink" : "text-ink-dim hover:text-ink")}>
              {c ? `${CATEGORY[c] ?? c} · ${data?.counts[c]}` : "Все"}
            </button>
          ))}
        </div>
        {state === "loading" && <div className="text-sm text-ink-dim">Загрузка…</div>}
        {(state === "error" || state === "unsupported") && (
          <div role="alert" className="text-sm text-warn">{error}
            {state === "error" && <button type="button" onClick={() => setTick((t) => t + 1)} className="ml-2 underline">Повторить</button>}
          </div>
        )}
        {state === "ready" && data && data.items.length === 0 && <div className="text-sm text-ink-dim">Ничего не найдено</div>}
        <ul aria-label="Записи памяти" className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
          {state === "ready" && data?.items.map((m) => (
            <li key={m.id} className="flex items-start gap-2 rounded-btn bg-panel2 px-3 py-2 text-sm">
              <span className="mt-0.5 shrink-0 rounded-full bg-panel px-2 py-0.5 text-[11px] text-ink-dim">{CATEGORY[m.category] ?? m.category}</span>
              {editing?.id === m.id ? (
                <input autoFocus value={editing.text} onChange={(e) => setEditing({ id: m.id, text: e.target.value })}
                       onKeyDown={(e) => { if (e.key === "Enter") void save(); if (e.key === "Escape") setEditing(null); }}
                       aria-label="Текст записи" className="flex-1 rounded border border-line bg-panel px-2 py-0.5 text-ink outline-none" />
              ) : <span className="flex-1 text-ink">{m.text}</span>}
              {editing?.id === m.id ? (
                <>
                  <button type="button" aria-label="Сохранить" onClick={() => void save()} className="text-online"><Check size={15} /></button>
                  <button type="button" aria-label="Отмена" onClick={() => setEditing(null)} className="text-ink-dim"><X size={15} /></button>
                </>
              ) : confirm === m.id ? (
                <span className="flex items-center gap-2 text-xs text-warn">Удалить?
                  <button type="button" onClick={() => void remove(m.id)} className="underline">Да</button>
                  <button type="button" onClick={() => setConfirm(null)} className="text-ink-dim underline">Нет</button>
                </span>
              ) : (
                <>
                  <button type="button" aria-label={`Изменить: ${m.text}`} onClick={() => setEditing({ id: m.id, text: m.text })}
                          className="text-ink-dim hover:text-ink"><Pencil size={14} /></button>
                  <button type="button" aria-label={`Удалить: ${m.text}`} onClick={() => setConfirm(m.id)}
                          className="text-ink-dim hover:text-warn"><Trash2 size={14} /></button>
                </>
              )}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

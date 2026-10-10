import { CheckCheck, Clock3, MessageCircle, MoreHorizontal, Plus, Send } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import type { Message } from "../api/types";
import { useApp } from "../store";
import { CharacterArt } from "./CharacterArt";
import { Card, EmptyState, Loadable, timeHM } from "./ui";

function Bubble({ m }: { m: Message }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[78%] rounded-panel rounded-br-md bg-panel2 px-4 py-2.5 text-sm text-ink">
          {/* Текст как есть: абзацы, списки, эмодзи; markdown не интерпретируем. */}
          <p className="whitespace-pre-wrap break-words">{m.text}</p>
          <div className="mt-1 flex items-center justify-end gap-1 text-[11px] text-ink-dim">
            {timeHM(m.ts)}
            {m.pending ? <Clock3 size={12} aria-label="отправляется" /> : <CheckCheck size={14} className="text-accent" aria-label="доставлено" />}
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-end gap-2">
      <CharacterArt className="h-8 w-8 shrink-0 rounded-full" fade={false} />
      <div className="max-w-[78%] rounded-panel rounded-bl-md border border-line bg-panel px-4 py-2.5 text-sm text-ink">
        <div className="mb-0.5 text-xs font-semibold text-accent">{m.role === "system" ? "Система" : "Sakura"}</div>
        <p className="whitespace-pre-wrap break-words">{m.text}</p>
        <div className="mt-1 text-right text-[11px] text-ink-dim">{timeHM(m.ts)}</div>
      </div>
    </div>
  );
}

export function Chat() {
  const chat = useApp((s) => s.chat);
  const prompts = useApp((s) => s.settings?.quick_prompts ?? []);
  const sendText = useApp((s) => s.sendText);
  const loadHistory = useApp((s) => s.loadHistory);
  const coreState = useApp((s) => s.coreState);
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.data.length]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!text.trim()) return;
    void sendText(text);
    setText("");
  };

  return (
    <Card title="Чат" icon={<MessageCircle size={18} />} className="h-full"
          action={coreState !== "idle" && <span className="text-xs text-accent">{STATE_LABEL[coreState]}</span>}>
      <div ref={listRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-2" aria-live="polite">
        <Loadable status={chat.status} error={chat.error} onRetry={() => void loadHistory()} lines={5}>
          {chat.data.length === 0 ? (
            <EmptyState text="Здесь будет ваша переписка. Напишите или скажите «Сакура…»" />
          ) : (
            chat.data.map((m) => <Bubble key={m.id} m={m} />)
          )}
        </Loadable>
      </div>

      <form onSubmit={submit} className="mx-4 mt-2 flex items-center gap-2 rounded-panel border border-line bg-panel2 p-1.5">
        <button type="button" disabled title="Вложения — скоро" aria-label="Вложения"
                className="grid h-9 w-9 place-items-center rounded-full text-ink-dim opacity-50">
          <Plus size={18} />
        </button>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Написать сообщение…"
               aria-label="Сообщение" className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-dim" />
        <button type="submit" aria-label="Отправить" disabled={!text.trim()}
                className="grid h-9 w-9 place-items-center rounded-full bg-accent text-white shadow-glow transition-opacity disabled:opacity-40">
          <Send size={16} />
        </button>
      </form>

      <div className="flex flex-wrap gap-2 px-4 pb-4 pt-3">
        {prompts.map((p) => (
          <button key={p} type="button" onClick={() => void sendText(p)}
                  className="rounded-full border border-line px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-accent hover:text-ink">
            {p}
          </button>
        ))}
        <button type="button" aria-label="Ещё подсказки" title="Подсказки настраиваются в Настройках"
                className="rounded-full border border-line px-2.5 py-1.5 text-ink-dim hover:text-ink">
          <MoreHorizontal size={14} />
        </button>
      </div>
    </Card>
  );
}

const STATE_LABEL = { idle: "", listening: "слушаю…", thinking: "думаю…", speaking: "говорю…" } as const;

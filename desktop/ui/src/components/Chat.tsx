// Чат справа на всю высоту. Markdown не интерпретируется — текст как есть.
import { CheckCheck, Clock3, Mic, MicOff, PanelRightClose, PanelRightOpen, Send } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import type { Message } from "../api/types";
import { useApp } from "../store";
import { SakuraLogo } from "./SakuraLogo";
import { EmptyState, Loadable, timeHM } from "./ui";

export const DEFAULT_PROMPTS = ["Что у меня сегодня?", "Погода", "Включи музыку"];

const STATE_LABEL = { idle: "", listening: "слушаю…", thinking: "думаю…", speaking: "говорю…" } as const;

function Bubble({ m }: { m: Message }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-card rounded-br-md bg-panel2 px-4 py-2.5 text-sm text-ink">
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
      <SakuraLogo size={26} className="mb-1 shrink-0" />
      <div className="max-w-[85%] rounded-card rounded-bl-md border border-line px-4 py-2.5 text-sm text-ink">
        <div className="mb-0.5 text-xs font-semibold text-accent">{m.role === "system" ? "Система" : "Sakura"}</div>
        <p className="whitespace-pre-wrap break-words">{m.text}</p>
        <div className="mt-1 text-right text-[11px] text-ink-dim">{timeHM(m.ts)}</div>
      </div>
    </div>
  );
}

export function Chat({ onCollapse }: { onCollapse(): void }) {
  const chat = useApp((s) => s.chat);
  const saved = useApp((s) => s.settings?.quick_prompts);
  const prompts = saved?.length ? saved : DEFAULT_PROMPTS;
  const sendText = useApp((s) => s.sendText);
  const loadHistory = useApp((s) => s.loadHistory);
  const coreState = useApp((s) => s.coreState);
  const mic = useApp((s) => s.settings?.mic_enabled ?? true);
  const listenNow = useApp((s) => s.listenNow);
  const toggleMic = useApp((s) => s.toggleMic);
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
    <section aria-label="Чат" className="flex h-full min-w-0 flex-col rounded-card bg-panel">
      <header className="flex h-14 shrink-0 items-center gap-2 px-5">
        <h2 className="text-sm font-semibold text-ink">Чат</h2>
        {coreState !== "idle" && <span className="text-xs text-accent">{STATE_LABEL[coreState]}</span>}
        <button type="button" onClick={onCollapse} aria-label="Свернуть чат" title="Свернуть чат"
                className="ml-auto grid h-8 w-8 place-items-center rounded-btn text-ink-dim hover:bg-panel2 hover:text-ink">
          <PanelRightClose size={16} />
        </button>
      </header>

      <div ref={listRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-2" aria-live="polite">
        <Loadable status={chat.status} error={chat.error} onRetry={() => void loadHistory()} lines={5}>
          {chat.data.length === 0 ? (
            <EmptyState text="Здесь будет ваша переписка. Напишите или скажите «Сакура…»" />
          ) : (
            chat.data.map((m) => <Bubble key={m.id} m={m} />)
          )}
        </Loadable>
      </div>

      <div className="flex flex-wrap gap-2 px-4 pt-3">
        {prompts.map((p) => (
          <button key={p} type="button" onClick={() => void sendText(p)}
                  className="rounded-full border border-line px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-accent hover:text-ink">
            {p}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="m-4 flex items-center gap-2 rounded-card border border-line bg-panel2 p-1.5">
        <button type="button" onClick={() => void (mic ? listenNow() : toggleMic())}
                aria-label={mic ? "Говорить" : "Включить микрофон"} title={mic ? "Говорить сейчас" : "Микрофон выключен — включить"}
                className={"grid h-9 w-9 shrink-0 place-items-center rounded-full transition-colors " +
                  (coreState === "listening" ? "bg-accent-grad text-white shadow-glow" : "text-ink-dim hover:text-ink")}>
          {mic ? <Mic size={18} /> : <MicOff size={18} className="text-accent" />}
        </button>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Написать сообщение…"
               aria-label="Сообщение" className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-dim" />
        <button type="submit" aria-label="Отправить" disabled={!text.trim()}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-accent-grad text-white shadow-glow transition-opacity disabled:opacity-40">
          <Send size={16} />
        </button>
      </form>
    </section>
  );
}

/** Свёрнутый чат — узкая полоса с кнопкой «развернуть». */
export function ChatStrip({ onExpand }: { onExpand(): void }) {
  const unread = useApp((s) => s.coreState !== "idle");
  return (
    <section aria-label="Чат свёрнут" className="flex h-full flex-col items-center rounded-card bg-panel py-4">
      <button type="button" onClick={onExpand} aria-label="Развернуть чат" title="Развернуть чат"
              className="grid h-9 w-9 place-items-center rounded-btn text-ink-dim hover:bg-panel2 hover:text-ink">
        <PanelRightOpen size={18} />
      </button>
      {unread && <span className="mt-3 h-2 w-2 rounded-full bg-accent" aria-hidden="true" />}
    </section>
  );
}

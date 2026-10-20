// Чат справа на всю высоту. Markdown не интерпретируется — текст как есть.
import { CheckCheck, Clock3, Download, Mic, MicOff, PanelRightClose, PanelRightOpen, Search, Send, Trash2, Volume2, Zap } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import type { Message } from "../api/types";
import { bridge } from "../bridge";
import { usePrefs } from "../layout/prefs";
import { errorText, useApp } from "../store";
import { SakuraLogo } from "./SakuraLogo";
import { EmptyState, Loadable, timeHM } from "./ui";

export const DEFAULT_PROMPTS = ["Что у меня сегодня?", "Погода", "Включи музыку"];

const STATE_LABEL = { idle: "", listening: "слушаю…", thinking: "думаю…", speaking: "говорю…" } as const;

const SOURCE_LABEL: Record<NonNullable<Message["source"]>, string> = {
  mic: "микрофон", ui: "окно", e2e: "проверка", api: "API", server: "", system: "система",
};

/** Метка источника: сразу видно, сказано ли голосом, набрано в окне, в Telegram или отправлено проверкой. */
export function sourceLabel(m: Message): string {
  if (m.role === "system") return "система";
  if (m.channel === "telegram") return "Telegram";
  if (m.source) return SOURCE_LABEL[m.source];
  return m.role === "user" && m.channel === "voice" ? "микрофон" : "";
}

/** Цветная метка вида ответа. */
export function kindChip(m: Message): { text: string; tone: "accent" | "dim" | "error" } | null {
  switch (m.kind) {
    case "ack": case "template": return { text: "быстрый ответ", tone: "dim" };
    case "error": return { text: "ошибка", tone: "error" };
    case "proactive": return { text: "проактивно", tone: "accent" };
    case "command": return { text: "команда", tone: "dim" };
    case "confirm": return { text: "вопрос", tone: "accent" };
    default: return null;
  }
}

function Chip({ m }: { m: Message }) {
  const c = kindChip(m);
  if (!c) return null;
  const tone = c.tone === "error" ? "border-accent text-accent" : c.tone === "accent" ? "bg-accent-soft text-accent border-transparent"
    : "border-line text-ink-dim";
  return <span className={"rounded-full border px-1.5 py-px text-[10px] " + tone}>{c.text}</span>;
}

/** Результат команды — приглушённой строкой «действие», без пузыря. */
function ActionLine({ m }: { m: Message }) {
  return (
    <div className={"flex items-center gap-2 pl-9 text-xs " + (m.kind === "error" ? "text-accent" : "text-ink-dim")} role="note">
      <Zap size={12} className="shrink-0" />
      <span className="min-w-0 flex-1 truncate" title={m.text}>{m.text}</span>
      <Chip m={m} />
      <span className="text-[11px]">{timeHM(m.ts)}</span>
    </div>
  );
}

/** Удаление сообщения из истории: значок при наведении → «Удалить?» Да/Нет. */
function DeleteControl({ m, onDelete }: { m: Message; onDelete?(id: string): void }) {
  const [ask, setAsk] = useState(false);
  if (!onDelete || m.pending || m.id.startsWith("local-")) return null;
  return ask ? (
    <span className="ml-2 inline-flex items-center gap-1 text-warn">Удалить?
      <button type="button" onClick={() => { setAsk(false); onDelete(m.id); }} className="underline">Да</button>
      <button type="button" onClick={() => setAsk(false)} className="text-ink-dim underline">Нет</button></span>
  ) : (
    <button type="button" aria-label="Удалить сообщение" onClick={() => setAsk(true)}
            className="ml-1 opacity-0 transition-opacity hover:text-warn group-hover:opacity-100"><Trash2 size={11} /></button>
  );
}

/** Вопрос сервера «Да или нет?»: ответ уходит обычным текстом «да»/«нет», как если бы его сказали. */
function ConfirmButtons({ onAnswer }: { onAnswer(text: "да" | "нет"): void }) {
  return (
    <div className="mt-2 flex gap-2" role="group" aria-label="Ответ на вопрос">
      <button type="button" onClick={() => onAnswer("да")}
              className="rounded-full bg-accent-grad px-4 py-1 text-xs font-medium text-white">Да</button>
      <button type="button" onClick={() => onAnswer("нет")}
              className="rounded-full border border-line px-4 py-1 text-xs text-ink-dim hover:text-ink">Нет</button>
    </div>
  );
}

/** Кнопки — только у последнего вопроса, на который ещё не ответили (после него нет реплики пользователя). */
export function openQuestionId(msgs: Message[]): string | null {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i]!;
    if (m.role === "user") return null;
    if (m.kind === "confirm") return m.id;
  }
  return null;
}

function Bubble({ m, onDelete, onAnswer }: { m: Message; onDelete?(id: string): void; onAnswer?(text: "да" | "нет"): void }) {
  const label = sourceLabel(m);
  if (m.role === "system" && (m.kind === "command" || m.kind === "error")) return <ActionLine m={m} />;
  if (m.role === "user") {
    return (
      <div className="group flex justify-end">
        <div className="max-w-[85%] rounded-card rounded-br-md bg-panel2 px-4 py-2.5 text-sm text-ink">
          <p className="whitespace-pre-wrap break-words">{m.text}</p>
          <div className="mt-1 flex items-center justify-end gap-1 text-[11px] text-ink-dim">
            {label && <span className={m.source === "e2e" ? "text-accent" : ""} aria-label={`источник: ${label}`}>{label} ·</span>}
            {timeHM(m.ts)}
            {m.pending ? <Clock3 size={12} aria-label="отправляется" /> : <CheckCheck size={14} className="text-accent" aria-label="доставлено" />}
            <DeleteControl m={m} onDelete={onDelete} />
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="group flex items-end gap-2">
      <SakuraLogo size={26} className="mb-1 shrink-0" />
      <div className="max-w-[85%] rounded-card rounded-bl-md border border-line px-4 py-2.5 text-sm text-ink">
        <div className="mb-0.5 flex items-center gap-1.5 text-xs font-semibold text-accent">
          {m.role === "system" ? "Система" : "Sakura"} <Chip m={m} />
        </div>
        {m.kind === "voice_only" ? (
          <p className="flex items-center gap-1.5 italic text-ink-dim"><Volume2 size={14} /> {m.text}</p>
        ) : (
          <p className="whitespace-pre-wrap break-words">{m.text}</p>
        )}
        {onAnswer && <ConfirmButtons onAnswer={onAnswer} />}
        <div className="mt-1 text-right text-[11px] text-ink-dim">{label && `${label} · `}{timeHM(m.ts)}
          <DeleteControl m={m} onDelete={onDelete} /></div>
      </div>
    </div>
  );
}

export function Chat({ onCollapse }: { onCollapse(): void }) {
  const chat = useApp((s) => s.chat);
  const showCommands = usePrefs((p) => p.showCommandResults);
  const saved = useApp((s) => s.settings?.quick_prompts);
  const prompts = saved?.length ? saved : DEFAULT_PROMPTS;
  const sendText = useApp((s) => s.sendText);
  const loadHistory = useApp((s) => s.loadHistory);
  const noHistory = useApp((s) => s.historyUnsupported);
  const coreState = useApp((s) => s.coreState);
  const mic = useApp((s) => s.settings?.mic_enabled ?? true);
  const listenNow = useApp((s) => s.listenNow);
  const toggleMic = useApp((s) => s.toggleMic);
  const chatMore = useApp((s) => s.chatMore);
  const loadOlder = useApp((s) => s.loadOlder);
  const searchHistory = useApp((s) => s.searchHistory);
  const deleteMessage = useApp((s) => s.deleteMessage);
  const question = openQuestionId(chat.data);
  const [text, setText] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Message[] | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const runSearch = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!query.trim()) { setFound(null); return; }
    try { setFound(await searchHistory(query.trim())); setNote(null); } catch (err) { setNote(errorText(err)); }
  };
  const remove = async (id: string) => {
    try { await deleteMessage(id); setFound((f) => f?.filter((m) => m.id !== id) ?? null); } catch (err) { setNote(errorText(err)); }
  };
  const older = async () => {
    try { await loadOlder(); } catch (err) { setNote(errorText(err)); }
  };
  const exportChat = async () => {
    const lines = chat.data.map((m) => `[${new Date(m.ts * 1000).toLocaleString()}] ${m.role === "user" ? "Вы" : m.role === "system" ? "Система" : "Sakura"}: ${m.text}`);
    const ok = await bridge().exportChat(lines.join("\n"));
    setNote(ok ? "Переписка сохранена в файл" : null);
  };
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
        <button type="button" onClick={() => { setSearchOpen(!searchOpen); setFound(null); }} aria-label="Поиск по переписке"
                title="Поиск по переписке" className="ml-auto grid h-8 w-8 place-items-center rounded-btn text-ink-dim hover:bg-panel2 hover:text-ink">
          <Search size={15} />
        </button>
        <button type="button" onClick={() => void exportChat()} aria-label="Экспорт переписки" title="Сохранить переписку в файл"
                className="grid h-8 w-8 place-items-center rounded-btn text-ink-dim hover:bg-panel2 hover:text-ink">
          <Download size={15} />
        </button>
        <button type="button" onClick={onCollapse} aria-label="Свернуть чат" title="Свернуть чат"
                className="grid h-8 w-8 place-items-center rounded-btn text-ink-dim hover:bg-panel2 hover:text-ink">
          <PanelRightClose size={16} />
        </button>
      </header>

      {searchOpen && (
        <form onSubmit={(e) => void runSearch(e)} className="mx-4 mb-1 flex gap-2">
          <input value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Искать в переписке" placeholder="Искать в переписке…"
                 autoFocus className="min-w-0 flex-1 rounded-lg border border-line bg-panel2 px-2.5 py-1 text-xs text-ink outline-none focus:border-accent" />
          <button type="submit" className="rounded-full border border-line px-3 text-xs text-ink-dim hover:text-ink">Найти</button>
        </form>
      )}
      {note && <div role="status" className="mx-4 mb-1 text-xs text-ink-dim">{note}</div>}
      {noHistory && (
        <div className="mx-4 mb-1 rounded-btn bg-panel2 px-3 py-1.5 text-xs text-ink-dim">
          История переписки: сервер не поддерживает — видны сообщения с момента запуска
        </div>
      )}
      <div ref={listRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-2" aria-live="polite">
        {found ? (
          <div aria-label="Результаты поиска" className="flex flex-col gap-3">
            <div className="text-xs text-ink-dim">Найдено: {found.length}</div>
            {found.map((m) => <Bubble key={m.id} m={m} onDelete={(id) => void remove(id)} />)}
          </div>
        ) : (
        <Loadable status={chat.status} error={chat.error} onRetry={() => void loadHistory()} lines={5}>
          {chatMore && !noHistory && (
            <button type="button" onClick={() => void older()} className="self-center rounded-full border border-line px-3 py-1 text-xs text-ink-dim hover:text-ink">
              Загрузить раньше
            </button>
          )}
          {chat.data.length === 0 ? (
            <EmptyState text="Здесь будет ваша переписка. Напишите или скажите «Сакура…»" />
          ) : (
            chat.data.filter((m) => showCommands || m.kind !== "command").map((m) => (
              <Bubble key={m.id} m={m} onDelete={noHistory ? undefined : (id) => void remove(id)}
                      onAnswer={m.id === question ? (t) => void sendText(t) : undefined} />))
          )}
        </Loadable>
        )}
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

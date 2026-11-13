// Небольшие виджеты каталога: сценарии, сегодня, сервер, заметки, уведомления, фокус-таймер,
// быстрые действия. Каждый получает свой элемент доски и может хранить настройки в нём (settings).
import { Camera, Eraser, Eye, Film, Gamepad2, Mic, MicOff, Pause, PhoneCall, Play, RotateCcw, Target, Volume2, Workflow } from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState, Loadable, modeLabel, timeHM, toneLabel } from "../../components/ui";
import type { WidgetItem } from "../../layout/boardModel";
import { useApp } from "../../store";

export interface WidgetProps {
  item: WidgetItem;
  setSettings(patch: Record<string, unknown>): void;
}

const body = "flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-4 pb-4 text-sm";
const chip = "flex items-center gap-2 rounded-xl border border-white/[0.08] bg-panel2/70 px-3 py-2 text-xs font-medium text-ink-dim hover:border-accent/60 hover:text-ink hover:bg-accent/10 hover:shadow-[0_0_14px_rgba(255,106,227,0.25)] transition-all duration-200 active:scale-95 backdrop-blur-md";
const activeChip = "flex items-center gap-2 rounded-xl border border-accent bg-accent/20 px-3 py-2 text-xs font-semibold text-accent shadow-[0_0_16px_rgba(255,106,227,0.35)] transition-all duration-200 active:scale-95 backdrop-blur-md";

export function ScenariosWidget() {
  const scenarios = useApp((s) => s.scenarios);
  const load = useApp((s) => s.loadScenarios);
  const run = useApp((s) => s.quickAction);
  return (
    <div className={body}>
      <Loadable status={scenarios.status} error={scenarios.error} onRetry={() => void load()} lines={3}>
        {scenarios.data.length === 0 ? <EmptyState text="Сценариев пока нет" /> : (
          <ul className="flex flex-col gap-1">
            {scenarios.data.map((sc) => (
              <li key={sc.id ?? sc.name} className="flex items-center gap-2 rounded-btn bg-panel2 px-3 py-1.5">
                <Workflow size={14} className="shrink-0 text-accent" />
                <span className="min-w-0 flex-1 truncate text-ink" title={sc.name}>{sc.name}</span>
                <button type="button" aria-label={`Запустить «${sc.name}»`} disabled={!sc.id}
                        onClick={() => sc.id && void run("run_scenario", sc.id)}
                        className="grid h-7 w-7 place-items-center rounded-full text-ink-dim hover:text-accent disabled:opacity-40">
                  <Play size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Loadable>
    </div>
  );
}

function useClock(intervalMs = 1000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function TodayWidget() {
  const now = useClock(30_000);
  const status = useApp((s) => s.status);
  return (
    <div className={body}>
      <div className="text-3xl font-semibold tabular-nums text-ink">{timeHM(now.getTime() / 1000)}</div>
      <div className="text-ink-dim">{now.toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" })}</div>
      {status.status === "ready" && status.data && (
        <div className="mt-1 text-xs text-ink-dim">
          {toneLabel(status.data.tone)} · {modeLabel(status.data.mode)}
          {status.data.quote && <p className="mt-1 italic text-ink">«{status.data.quote}»</p>}
        </div>
      )}
      {status.status === "unsupported" && <div className="text-xs text-ink-dim">Настроение: сервер не поддерживает</div>}
    </div>
  );
}

export function ServerWidget() {
  const link = useApp((s) => s.link);
  const server = useApp((s) => s.server);
  const device = useApp((s) => s.settings?.device_id);
  const coreReady = useApp((s) => s.settings?.core_ready ?? false);
  const row = (k: string, v: string, ok: boolean) => (
    <div className="flex items-center gap-2">
      <span className={"h-2 w-2 rounded-full " + (ok ? "bg-online" : "bg-ink-dim")} />
      <span className="text-ink-dim">{k}</span>
      <span className="ml-auto text-ink">{v}</span>
    </div>
  );
  return (
    <div className={body}>
      {row("Ядро", link === "open" ? (coreReady ? "на связи" : "запускается") : "нет связи", link === "open" && coreReady)}
      {row("Сервер", server.online ? `на связи, протокол v${server.proto ?? "?"}` : "нет связи", server.online)}
      {device && <div className="text-xs text-ink-dim">Устройство: {device}</div>}
    </div>
  );
}

export function NotesWidget({ item, setSettings }: WidgetProps) {
  const [text, setText] = useState(String(item.settings?.text ?? ""));
  // Заметка хранится в layout.json в настройках этого виджета (с задержкой — не на каждую букву).
  useEffect(() => {
    if (text === (item.settings?.text ?? "")) return;
    const t = setTimeout(() => setSettings({ text }), 500);
    return () => clearTimeout(t);
  }, [text, item.settings?.text, setSettings]);
  return (
    <div className="flex min-h-0 flex-1 px-3 pb-3">
      <textarea value={text} onChange={(e) => setText(e.target.value.slice(0, 10_000))} aria-label="Заметка"
                placeholder="Заметка…" spellCheck
                className="min-h-0 flex-1 resize-none rounded-btn border border-line bg-panel2 p-3 text-sm text-ink outline-none focus:border-accent" />
    </div>
  );
}

export function NotificationsWidget() {
  const items = useApp((s) => s.notifications);
  return (
    <div className={body}>
      {items.length === 0 ? <EmptyState text="Уведомлений пока нет" /> : (
        <ul className="flex flex-col gap-2">
          {items.map((n, i) => {
            const isDiscord = n.text.toLowerCase().includes("discord");
            return (
              <li key={`${n.ts}-${i}`} className={`rounded-xl border p-2.5 backdrop-blur-sm transition-all duration-200 shadow-soft ${
                isDiscord
                  ? "border-[#5865F2]/40 bg-[#5865F2]/10 hover:border-[#5865F2]/70 shadow-[0_0_12px_rgba(88,101,242,0.15)]"
                  : n.level === "info"
                    ? "border-white/[0.06] bg-panel2/60 hover:border-accent/40"
                    : "border-accent/50 bg-accent/10 hover:border-accent"
              }`}>
                <div className="flex items-center justify-between gap-2 mb-1">
                  <div className="flex items-center gap-1.5">
                    {isDiscord && <span className="h-1.5 w-1.5 rounded-full bg-[#5865F2] shadow-[0_0_6px_#5865F2]" />}
                    <span className="text-[10px] font-mono text-ink-dim">{timeHM(n.ts)}</span>
                  </div>
                  {isDiscord && (
                    <span className="rounded bg-[#5865F2]/20 px-1.5 py-0.5 text-[9px] font-medium text-[#7983f5]">
                      Discord Call
                    </span>
                  )}
                </div>
                <div className={n.level === "info" ? "text-xs text-ink/90 font-normal leading-relaxed" : "text-xs text-accent font-medium leading-relaxed"}>
                  {n.text}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** Фокус-таймер: работа/отдых, минуты — в настройках виджета. */
export function FocusTimerWidget({ item }: WidgetProps) {
  const work = Number(item.settings?.work) || 25;
  const rest = Number(item.settings?.rest) || 5;
  const [phase, setPhase] = useState<"work" | "rest">("work");
  const [left, setLeft] = useState(work * 60);
  const [running, setRunning] = useState(false);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setLeft((s) => {
      if (s > 1) return s - 1;
      const next = phase === "work" ? "rest" : "work";
      setPhase(next);
      return (next === "work" ? work : rest) * 60;
    }), 1000);
    return () => clearInterval(t);
  }, [running, phase, work, rest]);
  const reset = () => { setRunning(false); setPhase("work"); setLeft(work * 60); };
  return (
    <div className={body + " items-center justify-center"}>
      <div className="text-xs text-ink-dim">{phase === "work" ? "Работа" : "Отдых"}</div>
      <div className="text-3xl font-semibold tabular-nums text-ink" role="timer">
        {String(Math.floor(left / 60)).padStart(2, "0")}:{String(left % 60).padStart(2, "0")}
      </div>
      <div className="flex gap-2">
        <button type="button" className={chip} onClick={() => setRunning(!running)} aria-label={running ? "Пауза таймера" : "Старт таймера"}>
          {running ? <Pause size={13} /> : <Play size={13} />} {running ? "Пауза" : "Старт"}
        </button>
        <button type="button" className={chip} onClick={reset} aria-label="Сбросить таймер"><RotateCcw size={13} /></button>
      </div>
    </div>
  );
}

export function QuickActionsWidget() {
  const quick = useApp((s) => s.quickAction);
  const mic = useApp((s) => s.settings?.mic_enabled ?? true);
  const toggleMic = useApp((s) => s.toggleMic);
  const game = useApp((s) => s.gameMode);
  const setGame = useApp((s) => s.setGameMode);
  const listen = useApp((s) => s.listenNow);
  return (
    <div className="flex min-h-0 flex-1 flex-wrap content-start gap-2 overflow-y-auto px-4 pb-4">
      <button type="button" className={chip} onClick={() => void listen()}><Volume2 size={13} className="text-accent" /> Говорить</button>
      <button type="button" className={chip} onClick={() => void quick("screenshot")}><Camera size={13} className="text-accent" /> Скриншот</button>
      <button type="button" className={chip} onClick={() => void quick("clip_that")}><Film size={13} className="text-accent" /> Клип 30с</button>
      <button type="button" className={chip} onClick={() => void quick("clear_ink")}><Eraser size={13} className="text-accent" /> Чернила</button>
      <button type="button" className={chip} onClick={() => void quick("toggle_call_mode")}><PhoneCall size={13} className="text-accent" /> Звонок</button>
      <button type="button" className={chip} onClick={() => void quick("toggle_watch_along")}><Eye size={13} className="text-accent" /> Вместе</button>
      <button type="button" className={chip} onClick={() => void quick("focus_mode")}><Target size={13} className="text-accent" /> Фокус</button>
      <button type="button" className={!mic ? activeChip : chip} aria-pressed={!mic} onClick={() => void toggleMic()}>
        {mic ? <Mic size={13} /> : <MicOff size={13} className="text-accent" />} {mic ? "Микрофон вкл." : "Микрофон выкл."}
      </button>
      <button type="button" className={game ? activeChip : chip} aria-pressed={game} onClick={() => void setGame(!game)}>
        <Gamepad2 size={13} className={game ? "text-accent" : ""} /> Игровой режим
      </button>
    </div>
  );
}

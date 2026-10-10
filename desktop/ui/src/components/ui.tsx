// Общие кирпичики интерфейса: карточка, скелетоны, состояния пусто/ошибка/не поддерживается.
import { AlertTriangle, CloudOff, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

import type { LoadStatus } from "../store";

export function Card(props: { title?: ReactNode; icon?: ReactNode; action?: ReactNode; className?: string;
                              children: ReactNode }) {
  return (
    <section className={"flex min-h-0 flex-col rounded-panel border border-line bg-panel shadow-soft " + (props.className ?? "")}>
      {props.title && (
        <header className="flex items-center gap-2 px-4 pb-2 pt-4">
          {props.icon && <span className="text-accent">{props.icon}</span>}
          <h2 className="text-sm font-semibold text-ink">{props.title}</h2>
          {props.action && <div className="ml-auto">{props.action}</div>}
        </header>
      )}
      {props.children}
    </section>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-3 p-4" aria-busy="true" aria-label="Загрузка">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="h-4 animate-pulse rounded-lg bg-white/5" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({ text, action }: { text: string; action?: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-ink-dim">
      <span>{text}</span>
      {action}
    </div>
  );
}

export function ErrorState({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-ink-dim">
      <AlertTriangle size={20} className="text-accent" />
      <span>{text}</span>
      {onRetry && (
        <button type="button" onClick={onRetry}
                className="flex items-center gap-1 rounded-card border border-line px-3 py-1.5 text-ink hover:border-accent">
          <RotateCw size={14} /> Повторить
        </button>
      )}
    </div>
  );
}

export function Unsupported() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center text-sm text-ink-dim">
      <CloudOff size={20} />
      <span>Сервер не поддерживает</span>
    </div>
  );
}

/** Выбор состояния по статусу загрузки: скелетон / ошибка / не поддерживается / содержимое. */
export function Loadable(props: { status: LoadStatus; error?: string; onRetry?: () => void; lines?: number;
                                  children: ReactNode }) {
  if (props.status === "loading" || props.status === "idle") return <Skeleton lines={props.lines} />;
  if (props.status === "unsupported") return <Unsupported />;
  if (props.status === "error") return <ErrorState text={props.error ?? "Ошибка"} onRetry={props.onRetry} />;
  return <>{props.children}</>;
}

export function timeHM(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function agoText(ts: number, now = Date.now() / 1000): string {
  const s = Math.max(0, now - ts);
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return `${Math.floor(s / 86400)} дн назад`;
}

const TONES: Record<string, string> = {
  calm: "Спокойное", cheerful: "Весёлое", warm: "Тёплое", playful: "Игривое",
  serious: "Серьёзное", sad: "Грустное", tender: "Нежное", excited: "Воодушевлённое",
};
const MODES: Record<string, string> = { normal: "Обычный", game: "Игровой", focus: "Фокус", night: "Ночной" };

export const toneLabel = (t: string) => TONES[t] ?? (t ? t.charAt(0).toUpperCase() + t.slice(1) : "—");
export const modeLabel = (m: string) => MODES[m] ?? (m || "—");

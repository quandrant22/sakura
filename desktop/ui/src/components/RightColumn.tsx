import { AppWindow, Camera, Focus, Gauge, Heart, Play, Zap } from "lucide-react";
import { type ReactNode, useState } from "react";

import { useApp } from "../store";
import { CharacterArt } from "./CharacterArt";
import { Card, Loadable, modeLabel, toneLabel } from "./ui";

export function SakuraCard() {
  const status = useApp((s) => s.status);
  return (
    <section className="relative overflow-hidden rounded-panel border border-line shadow-soft">
      <CharacterArt className="h-44" />
      <div className="absolute inset-x-0 bottom-0 p-4">
        <div className="text-xs text-ink-dim">Сейчас рядом</div>
        <div className="text-base font-semibold text-accent">Sakura</div>
        <p className="mt-1 line-clamp-2 text-xs italic text-ink">
          {status.data?.quote ? `«${status.data.quote}»` : "Хорошего дня ♡"}
        </p>
      </div>
    </section>
  );
}

function ActionButton(props: { icon: ReactNode; label: string; onClick(): void; expanded?: boolean }) {
  return (
    <button type="button" onClick={props.onClick} aria-expanded={props.expanded}
            className="flex w-full items-center gap-3 rounded-card px-3 py-2.5 text-left text-sm text-ink transition-colors hover:bg-white/5">
      <span className="grid h-8 w-8 place-items-center rounded-card bg-accent-soft text-accent">{props.icon}</span>
      {props.label}
    </button>
  );
}

function Picker({ items, onPick, empty }: { items: string[] | null; onPick(v: string): void; empty: string }) {
  if (items === null) return <div className="px-4 py-2 text-xs text-ink-dim">Загрузка…</div>;
  if (items.length === 0) return <div className="px-4 py-2 text-xs text-ink-dim">{empty}</div>;
  return (
    <ul className="mx-2 mb-2 max-h-40 overflow-y-auto rounded-card border border-line bg-panel2 py-1" role="listbox">
      {items.map((it) => (
        <li key={it}>
          <button type="button" role="option" aria-selected={false} onClick={() => onPick(it)}
                  className="w-full px-3 py-1.5 text-left text-xs text-ink hover:bg-white/5">{it}</button>
        </li>
      ))}
    </ul>
  );
}

export function QuickActions() {
  const quickAction = useApp((s) => s.quickAction);
  const listApps = useApp((s) => s.listApps);
  const scenarios = useApp((s) => s.scenarios.data);
  const [open, setOpen] = useState<"apps" | "scenarios" | null>(null);
  const [apps, setApps] = useState<string[] | null>(null);

  const toggleApps = () => {
    if (open === "apps") return setOpen(null);
    setOpen("apps");
    setApps(null);
    listApps().then(setApps).catch(() => setApps([]));
  };

  return (
    <Card title="Быстрые действия" icon={<Zap size={18} />}>
      <div className="px-2 pb-2">
        <ActionButton icon={<Camera size={16} />} label="Сделать скриншот" onClick={() => void quickAction("screenshot")} />
        <ActionButton icon={<AppWindow size={16} />} label="Открыть приложение" onClick={toggleApps} expanded={open === "apps"} />
        {open === "apps" && (
          <Picker items={apps} empty="Приложения не найдены" onPick={(a) => { setOpen(null); void quickAction("open_app", a); }} />
        )}
        <ActionButton icon={<Focus size={16} />} label="Включить режим фокуса" onClick={() => void quickAction("focus_mode")} />
        <ActionButton icon={<Play size={16} />} label="Запустить сценарий" expanded={open === "scenarios"}
                      onClick={() => setOpen(open === "scenarios" ? null : "scenarios")} />
        {open === "scenarios" && (
          <Picker items={scenarios.map((s) => s.name)} empty="Сценариев пока нет"
                  onPick={(name) => {
                    setOpen(null);
                    const sc = scenarios.find((s) => s.name === name);
                    if (sc?.id) void quickAction("run_scenario", sc.id);
                  }} />
        )}
      </div>
    </Card>
  );
}

export function StatusCard() {
  const status = useApp((s) => s.status);
  const gameMode = useApp((s) => s.gameMode);
  const loadStatus = useApp((s) => s.loadStatus);
  const row = (label: string, value: string) => (
    <div className="flex items-center justify-between py-1.5 text-sm">
      <span className="text-ink-dim">{label}</span>
      <span className="text-ink">{value}</span>
    </div>
  );
  return (
    <Card title="Статус" icon={<Gauge size={18} />}>
      <div className="px-4 pb-3">
        <Loadable status={status.status} error={status.error} onRetry={() => void loadStatus()} lines={3}>
          {row("Настроение", toneLabel(status.data?.tone ?? ""))}
          {row("Режим", gameMode ? "Игровой" : modeLabel(status.data?.mode ?? "normal"))}
          {row("Контекст", status.data?.context || "—")}
        </Loadable>
      </div>
    </Card>
  );
}

export function Mascot() {
  return (
    <div className="flex items-center gap-3 rounded-panel border border-line bg-panel p-3 shadow-soft">
      <CharacterArt className="h-14 w-14 shrink-0 rounded-full" fade={false} />
      <p className="text-xs text-ink-dim">
        Я всегда рядом. Даже когда ты просто молчишь <Heart size={11} className="inline text-accent" fill="currentColor" />
      </p>
    </div>
  );
}

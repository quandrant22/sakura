import { ArrowRight, Plus, Sparkles, Workflow } from "lucide-react";
import { useState } from "react";

import { useApp } from "../store";
import { Card, ErrorState, Skeleton, Unsupported } from "./ui";

export const CONDITION_TYPES = [
  { id: "phrase", label: "Скажу фразу" },
  { id: "time", label: "Время" },
  { id: "device_connected", label: "Устройство подключилось" },
  { id: "device_disconnected", label: "Устройство отключилось" },
  { id: "app_started", label: "Запущено приложение" },
] as const;

export const ACTION_TYPES = [
  { id: "action", label: "Действие" },
  { id: "pause", label: "Пауза" },
  { id: "telegram", label: "Сообщение в Telegram" },
  { id: "notify", label: "Уведомление" },
] as const;

const labelOf = (list: readonly { id: string; label: string }[], id: string) =>
  list.find((x) => x.id === id)?.label ?? id;

interface Pair {
  cond: string;
  condValue: string;
  act: string;
  actValue: string;
}

const field = "min-w-0 rounded-lg border border-line bg-panel2 px-2 py-1.5 text-xs text-ink outline-none focus:border-accent";

function PairRow({ pair, onChange, disabled = false }: { pair: Pair; onChange?(p: Pair): void; disabled?: boolean }) {
  const set = (patch: Partial<Pair>) => onChange?.({ ...pair, ...patch });
  return (
    <div className={"space-y-1.5 " + (disabled ? "opacity-60" : "")}>
      <div className="grid grid-cols-[34px_1fr_1fr] items-center gap-1.5">
        <span className="text-xs text-ink-dim">Если</span>
        <select aria-label="Тип условия" value={pair.cond} disabled={disabled} onChange={(e) => set({ cond: e.target.value })} className={field}>
          {CONDITION_TYPES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>
        <input aria-label="Значение условия" value={pair.condValue} disabled={disabled} onChange={(e) => set({ condValue: e.target.value })}
               placeholder="значение" className={field} />
      </div>
      <div className="grid grid-cols-[34px_1fr_1fr_28px] items-center gap-1.5">
        <span className="text-xs text-ink-dim">То</span>
        <select aria-label="Тип действия" value={pair.act} disabled={disabled} onChange={(e) => set({ act: e.target.value })} className={field}>
          {ACTION_TYPES.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select>
        <input aria-label="Значение действия" value={pair.actValue} disabled={disabled} onChange={(e) => set({ actValue: e.target.value })}
               placeholder="значение" className={field} />
        <button type="button" aria-label="Добавить действие" disabled={disabled}
                className="grid h-7 w-7 place-items-center rounded-lg border border-line text-ink-dim hover:text-accent">
          <Plus size={14} />
        </button>
      </div>
    </div>
  );
}

const EXAMPLE: Pair = { cond: "time", condValue: "22:00–07:00", act: "action", actValue: "Не беспокоить на телефоне" };

export function ScenarioBuilder({ onOpen }: { onOpen(): void }) {
  const preview = useApp((s) => s.preview);
  const previewScenario = useApp((s) => s.previewScenario);
  const [name, setName] = useState("");
  const [pairs, setPairs] = useState<Pair[]>([{ cond: "phrase", condValue: "", act: "action", actValue: "" }]);
  const [phrase, setPhrase] = useState("");

  return (
    <Card title="Создание сценария" icon={<Workflow size={18} />}
          action={
            <button type="button" onClick={onOpen}
                    className="flex items-center gap-1 whitespace-nowrap rounded-card bg-accent px-2.5 py-1 text-xs text-white shadow-glow">
              <Plus size={14} /> Новый сценарий
            </button>
          }>
      <div className="space-y-3 overflow-y-auto px-4 pb-4">
        <input aria-label="Название сценария" value={name} onChange={(e) => setName(e.target.value)}
               placeholder="Например: Режим сна" className={field + " w-full py-2 text-sm"} />
        {pairs.map((p, i) => (
          <PairRow key={i} pair={p} onChange={(np) => setPairs(pairs.map((x, j) => (j === i ? np : x)))} />
        ))}
        <div className="text-xs text-ink-dim">И так далее…</div>
        <PairRow pair={EXAMPLE} disabled />
        <button type="button" onClick={() => setPairs([...pairs, { cond: "time", condValue: "", act: "action", actValue: "" }])}
                className="flex items-center gap-1 text-xs text-accent hover:underline">
          <Plus size={14} /> Добавить условие
        </button>

        <div className="border-t border-line pt-3">
          <div className="mb-1.5 flex items-center gap-1 text-xs text-ink-dim"><Sparkles size={12} /> Или опишите словами</div>
          <form className="flex gap-1.5" onSubmit={(e) => { e.preventDefault(); void previewScenario(phrase); }}>
            <input aria-label="Сценарий словами" value={phrase} onChange={(e) => setPhrase(e.target.value)}
                   placeholder="Создай сценарий: вечером включай тишину" className={field + " flex-1"} />
            <button type="submit" disabled={!phrase.trim()}
                    className="rounded-lg bg-accent-soft px-2.5 text-xs text-accent disabled:opacity-40">Предпросмотр</button>
          </form>
          {preview.status === "loading" && <Skeleton lines={2} />}
          {preview.status === "unsupported" && <Unsupported />}
          {preview.status === "error" && <ErrorState text={preview.error ?? "Ошибка"} onRetry={() => void previewScenario(phrase)} />}
          {preview.status === "ready" && preview.data && (
            <div className="mt-2 rounded-card border border-line bg-panel2 p-3 text-xs" aria-label="Предпросмотр сценария">
              <div className="mb-1 font-semibold text-ink">{preview.data.scenario.name}</div>
              {preview.data.scenario.conditions.map((c, i) => (
                <div key={`c${i}`} className="text-ink-dim">Если {labelOf(CONDITION_TYPES, c.type).toLowerCase()}: <span className="text-ink">{c.value}</span></div>
              ))}
              {preview.data.scenario.actions.map((a, i) => (
                <div key={`a${i}`} className="flex items-center gap-1 text-ink-dim"><ArrowRight size={12} /> {labelOf(ACTION_TYPES, a.type)}: <span className="text-ink">{a.value}</span></div>
              ))}
              {preview.data.warnings.map((w) => <div key={w} className="mt-1 text-amber-300/80">{w}</div>)}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

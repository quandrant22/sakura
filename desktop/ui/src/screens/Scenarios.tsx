// Экран «Сценарии»: список с сервера и создание (конструктор «Если … То …», из фразы).
// Сохранение, запуск и правка — фаза 5.
import { Play, Trash2, Workflow } from "lucide-react";
import { useState } from "react";

import { ScenarioBuilder } from "../components/ScenarioBuilder";
import { Card, EmptyState, Loadable } from "../components/ui";
import { errorText, useApp } from "../store";

export function Scenarios() {
  const scenarios = useApp((s) => s.scenarios);
  const load = useApp((s) => s.loadScenarios);
  const run = useApp((s) => s.runScenario);
  const remove = useApp((s) => s.deleteScenario);
  const log = useApp((s) => s.scenarioLog);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const act = async (fn: () => Promise<void>) => { try { await fn(); setNote(null); } catch (e) { setNote(errorText(e)); } };
  return (
    <div className="flex h-full min-h-0 gap-gap">
      <Card title="Сценарии" icon={<Workflow size={18} />} className="min-h-0 flex-1">
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
          <Loadable status={scenarios.status} error={scenarios.error} onRetry={() => void load()}>
            {scenarios.data.length === 0 ? (
              <EmptyState text="Сценариев пока нет" />
            ) : (
              <ul className="flex flex-col gap-2">
                {scenarios.data.map((sc) => (
                  <li key={sc.id ?? sc.name} className="flex items-center gap-2 rounded-btn bg-panel2 px-3 py-2 text-sm">
                    <span className={"h-2 w-2 rounded-full " + (sc.enabled ? "bg-online" : "bg-ink-dim")} />
                    <span className="truncate text-ink">{sc.name}</span>
                    <span className="ml-auto text-xs text-ink-dim">{sc.enabled ? "включён" : "выключен"}</span>
                    {sc.id && (confirm === sc.id ? (
                      <span className="flex items-center gap-1 text-xs text-warn">Удалить?
                        <button type="button" onClick={() => { setConfirm(null); void act(() => remove(sc.id as string)); }} className="underline">Да</button>
                        <button type="button" onClick={() => setConfirm(null)} className="text-ink-dim underline">Нет</button></span>
                    ) : (
                      <>
                        <button type="button" aria-label={`Запустить: ${sc.name}`} onClick={() => void act(() => run(sc.id as string))}
                                className="text-ink-dim hover:text-accent"><Play size={14} /></button>
                        <button type="button" aria-label={`Удалить: ${sc.name}`} onClick={() => setConfirm(sc.id as string)}
                                className="text-ink-dim hover:text-warn"><Trash2 size={14} /></button>
                      </>
                    ))}
                  </li>
                ))}
              </ul>
            )}
          </Loadable>
          {note && <div role="alert" className="mt-2 text-xs text-warn">{note}</div>}
          {log.length > 0 && (
            <div className="mt-4">
              <div className="mb-1 text-xs font-medium text-ink">Журнал запусков</div>
              <ul aria-label="Журнал запусков" className="flex flex-col gap-0.5 text-xs text-ink-dim">
                {[...log].reverse().slice(0, 30).map((e, i) => (
                  <li key={`${e.run_id}-${e.step}-${i}`}>
                    {new Date(e.ts * 1000).toLocaleTimeString().slice(0, 8)} · {e.run_id} · {e.status === "started" ? "запущен"
                      : e.status === "done" ? "завершён" : `шаг ${e.step + 1}: ${e.status}${e.detail ? ` (${e.detail})` : ""}`}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Card>
      <div className="min-h-0 w-[420px] shrink-0 overflow-y-auto">
        <ScenarioBuilder />
      </div>
    </div>
  );
}

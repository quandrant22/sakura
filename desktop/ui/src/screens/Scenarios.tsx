// Экран «Сценарии»: список с сервера и создание (конструктор «Если … То …», из фразы).
// Сохранение, запуск и правка — фаза 5.
import { Workflow } from "lucide-react";

import { ScenarioBuilder } from "../components/ScenarioBuilder";
import { Card, EmptyState, Loadable } from "../components/ui";
import { useApp } from "../store";

export function Scenarios() {
  const scenarios = useApp((s) => s.scenarios);
  const load = useApp((s) => s.loadScenarios);
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
                  </li>
                ))}
              </ul>
            )}
          </Loadable>
        </div>
      </Card>
      <div className="min-h-0 w-[420px] shrink-0 overflow-y-auto">
        <ScenarioBuilder />
      </div>
    </div>
  );
}

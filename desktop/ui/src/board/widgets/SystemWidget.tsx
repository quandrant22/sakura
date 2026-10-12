// Виджет «Система»: загрузка CPU/RAM/GPU этого ПК и состояние остальных устройств.
import type { Device } from "../../api/types";
import { EmptyState, Loadable } from "../../components/ui";
import { useApp } from "../../store";

function Meter({ label, value }: { label: string; value: number | null | undefined }) {
  const v = value == null ? null : Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-ink-dim">{label}</span>
        <span className="tabular-nums text-ink">{v == null ? "—" : `${v}%`}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-panel2" role="meter" aria-label={label}
           aria-valuemin={0} aria-valuemax={100} aria-valuenow={v ?? undefined}>
        <div className="h-full rounded-full bg-accent-grad transition-[width]" style={{ width: `${v ?? 0}%` }} />
      </div>
    </div>
  );
}

function DeviceLine({ d }: { d: Device }) {
  return (
    <li className="flex items-center gap-2 text-xs">
      <span className={"h-2 w-2 shrink-0 rounded-full " + (d.online ? "bg-online" : "bg-ink-dim")} />
      <span className="truncate text-ink">{d.name}</span>
      <span className="ml-auto shrink-0 text-ink-dim">
        {d.online ? (d.stats?.battery != null ? `${d.stats.battery}%` : "онлайн") : "офлайн"}
      </span>
    </li>
  );
}

export function SystemWidget() {
  const devices = useApp((s) => s.devices);
  const me = useApp((s) => s.settings?.device_id);
  const loadDevices = useApp((s) => s.loadDevices);
  const self = devices.data.find((d) => d.id === me);
  const others = devices.data.filter((d) => d.id !== me);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4">
      <Loadable status={devices.status} error={devices.error} onRetry={() => void loadDevices()} lines={4}>
        <div className="flex flex-col gap-3">
          <Meter label="CPU" value={self?.stats.cpu} />
          <Meter label="RAM" value={self?.stats.ram} />
          <Meter label="GPU" value={self?.stats.gpu} />
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-ink-dim">Устройства</div>
          {others.length === 0 ? (
            <EmptyState text="Других устройств нет" />
          ) : (
            <ul className="flex flex-col gap-2">{others.map((d) => <DeviceLine key={d.id} d={d} />)}</ul>
          )}
        </div>
      </Loadable>
    </div>
  );
}

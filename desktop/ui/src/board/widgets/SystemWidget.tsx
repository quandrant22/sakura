// Виджет «Система»: загрузка CPU/RAM/GPU этого ПК и состояние остальных устройств.
import type { Device } from "../../api/types";
import { EmptyState, Loadable } from "../../components/ui";
import { useApp } from "../../store";

/** Цвет нагрузки: спокойно — акцент, высокая (≥85 %) — предупреждение. */
export function loadTone(v: number | null): string {
  if (v == null) return "rgb(var(--ink-dim))";
  return v >= 85 ? "rgb(var(--warn))" : "rgb(var(--accent))";
}

function Meter({ label, value }: { label: string; value: number | null | undefined }) {
  const v = value == null ? null : Math.max(0, Math.min(100, Math.round(value)));
  const tone = loadTone(v);
  return (
    <div className="grid grid-cols-[38px_1fr_42px] items-center gap-3 py-1">
      <span className="text-[11px] font-semibold tracking-wider text-ink-dim">{label}</span>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]" role="meter" aria-label={label}
           aria-valuemin={0} aria-valuemax={100} aria-valuenow={v ?? undefined}>
        <div className="h-full rounded-full transition-[width,background] duration-500"
             style={{ width: `${v ?? 0}%`, background: `linear-gradient(90deg, rgb(var(--accent-deep)), ${tone})`,
                      boxShadow: `0 0 10px ${v != null && v >= 85 ? "rgba(255,184,77,.45)" : "var(--accent-soft)"}` }} />
      </div>
      <span className="text-right font-mono text-xs tabular-nums text-ink">{v == null ? "—" : `${v}%`}</span>
    </div>
  );
}

function DeviceLine({ d }: { d: Device }) {
  return (
    <li className="flex items-center gap-2.5 rounded-btn bg-white/[0.03] px-3 py-2 text-xs transition-colors hover:bg-white/[0.06]">
      <span className={"h-2 w-2 shrink-0 rounded-full " + (d.online ? "bg-online shadow-[0_0_6px_rgba(0,255,160,0.5)]" : "bg-ink-dim")} />
      <span className="truncate text-ink font-medium">{d.name}</span>
      <span className="ml-auto shrink-0 font-mono text-ink-dim">
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
        <div className="flex flex-col rounded-btn bg-white/[0.03] px-3 py-2">
          <Meter label="CPU" value={self?.stats.cpu} />
          <Meter label="RAM" value={self?.stats.ram} />
          <Meter label="GPU" value={self?.stats.gpu} />
        </div>
        <div>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-dim">Устройства</div>
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

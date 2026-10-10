import { BatteryCharging, BatteryMedium, ChevronRight, Cpu, Headphones, Laptop, Monitor, Smartphone, Tablet, Wifi } from "lucide-react";

import type { Device } from "../api/types";
import { useApp } from "../store";
import { agoText, Card, EmptyState, Loadable } from "./ui";

const KIND_ICON = { pc: Laptop, phone: Smartphone, tablet: Tablet, headphones: Headphones, other: Monitor } as const;
const KIND_LABEL = { pc: "ПК", phone: "телефон", tablet: "планшет", headphones: "наушники", other: "устройство" } as const;

function Metric({ label, value }: { label: string; value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  return (
    <span className="whitespace-nowrap">
      {label} <span className="text-ink">{Math.round(value)}%</span>
    </span>
  );
}

export function DeviceRow({ d, thisDevice }: { d: Device; thisDevice: boolean }) {
  const Icon = KIND_ICON[d.kind] ?? Monitor;
  const s = d.stats ?? {};
  return (
    <li className="flex items-center gap-3 rounded-card px-2 py-2.5 hover:bg-white/5">
      <span className={"grid h-9 w-9 shrink-0 place-items-center rounded-card " + (d.online ? "bg-accent-soft text-accent" : "bg-white/5 text-ink-dim")}>
        <Icon size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-ink">
          {d.name} <span className="text-ink-dim">({KIND_LABEL[d.kind] ?? d.kind})</span>
          {d.focus && <span className="ml-1 text-[10px] uppercase tracking-wide text-accent">в фокусе</span>}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-ink-dim">
          <span className="flex items-center gap-1">
            <span className={"h-1.5 w-1.5 rounded-full " + (d.online ? "bg-online" : "bg-ink-dim")} />
            {d.online ? "Онлайн" : "Офлайн"}
          </span>
          {d.online && thisDevice && (
            <>
              <Metric label="CPU" value={s.cpu} />
              <Metric label="RAM" value={s.ram} />
              <Metric label="GPU" value={s.gpu} />
            </>
          )}
          {d.online && d.kind === "phone" && (
            <>
              {s.battery != null && (
                <span className="flex items-center gap-1">
                  {s.charging ? <BatteryCharging size={12} /> : <BatteryMedium size={12} />}
                  <span className="text-ink">{s.battery}%</span>
                </span>
              )}
              {s.wifi && (
                <span className="flex items-center gap-1"><Wifi size={12} /> {s.wifi}</span>
              )}
              {s.signal != null && <span>Сеть {s.signal}/4</span>}
            </>
          )}
          {!d.online && <span>Последняя активность: {agoText(d.last_seen)}</span>}
        </div>
      </div>
      <ChevronRight size={16} className="text-ink-dim" />
    </li>
  );
}

export function DevicesCard({ onAll }: { onAll(): void }) {
  const devices = useApp((s) => s.devices);
  const me = useApp((s) => s.settings?.device_id);
  const loadDevices = useApp((s) => s.loadDevices);
  return (
    <Card title="Устройства" icon={<Cpu size={18} />}
          action={
            <button type="button" onClick={onAll} className="flex items-center text-xs text-ink-dim hover:text-accent">
              Все устройства <ChevronRight size={14} />
            </button>
          }>
      <div className="px-2 pb-3">
        <Loadable status={devices.status} error={devices.error} onRetry={() => void loadDevices()}>
          {devices.data.length === 0 ? (
            <EmptyState text="Пока нет подключённых устройств" />
          ) : (
            <ul>{devices.data.map((d) => <DeviceRow key={d.id} d={d} thisDevice={d.id === me} />)}</ul>
          )}
        </Loadable>
      </div>
    </Card>
  );
}

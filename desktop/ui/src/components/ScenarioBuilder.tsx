// Конструктор сценария: «Когда» (условия, любое из них) → «Что сделать» (шаги по порядку).
// Команды — из реестра сервера (scenario_catalog), сохранение — scenario_save.
import {
  AlertTriangle, AppWindow, ChevronDown, ChevronUp, Clock, Mic, Monitor, Plug, Plus, Save, Search, Unplug, X,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import type { CatalogAction, Device, Scenario, ScenarioStep } from "../api/types";
import { errorText, useApp } from "../store";
import { ACTION_TYPES, CONDITION_TYPES, DAYS, WEEKDAYS, WEEKEND } from "./scenarioText";

const field = "min-w-0 rounded-lg border border-line bg-panel2 px-2 py-1.5 text-xs text-ink outline-none focus:border-accent";
const iconBtn = "grid h-7 w-7 shrink-0 place-items-center rounded-lg text-ink-dim hover:bg-white/5 hover:text-accent disabled:opacity-30";

const COND_ICONS: Record<string, ReactNode> = {
  phrase: <Mic size={14} />, time: <Clock size={14} />, device_connected: <Plug size={14} />,
  device_disconnected: <Unplug size={14} />, app_started: <AppWindow size={14} />,
};

/** Старый формат «id:параметр» → value + arg. */
export function normalizeAction(a: ScenarioStep): ScenarioStep {
  if (a.type === "action" && a.value.includes(":") && !a.arg) {
    const i = a.value.indexOf(":");
    return { ...a, value: a.value.slice(0, i), arg: a.value.slice(i + 1) };
  }
  return a;
}

/** Выбор команды Сакуры: поиск по названию и описанию, группы. */
export function ActionPicker({ value, catalog, onPick }: { value: string; catalog: CatalogAction[];
                                                            onPick(id: string): void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", off);
    return () => document.removeEventListener("mousedown", off);
  }, [open]);
  const current = catalog.find((x) => x.id === value);
  const groups = useMemo(() => {
    const t = q.trim().toLowerCase();
    const hits = catalog.filter((x) => !t || `${x.title} ${x.desc} ${x.group}`.toLowerCase().includes(t));
    const out = new Map<string, CatalogAction[]>();
    for (const x of hits) out.set(x.group, [...(out.get(x.group) ?? []), x]);
    return [...out.entries()];
  }, [catalog, q]);
  return (
    <div ref={box} className="relative min-w-0 flex-1">
      <button type="button" aria-label="Команда" aria-expanded={open} onClick={() => setOpen(!open)}
              className={field + " flex w-full items-center gap-1 text-left"}>
        <span className={"min-w-0 flex-1 truncate " + (current ? "text-ink" : "text-ink-dim")}>
          {current ? current.title : value ? `${value} (нет на сервере)` : "Выбери команду…"}
        </span>
        <ChevronDown size={12} className="shrink-0 text-ink-dim" />
      </button>
      {open && (
        <div className="absolute left-0 right-0 z-20 mt-1 rounded-card border border-line bg-panel p-2 shadow-xl">
          <div className="mb-1.5 flex items-center gap-1 rounded-lg border border-line bg-panel2 px-2">
            <Search size={12} className="text-ink-dim" />
            <input autoFocus aria-label="Поиск команды" value={q} onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}
                   placeholder="музыка, громкость, чайник…" className="w-full bg-transparent py-1.5 text-xs text-ink outline-none" />
          </div>
          <div role="listbox" aria-label="Команды" className="max-h-64 overflow-y-auto">
            {groups.length === 0 && <div className="p-2 text-xs text-ink-dim">Ничего не нашлось</div>}
            {groups.map(([g, items]) => (
              <div key={g}>
                <div className="sticky top-0 bg-panel px-1 pb-0.5 pt-1.5 text-[10px] uppercase tracking-wide text-ink-dim">{g}</div>
                {items.map((x) => (
                  <button key={x.id} type="button" role="option" aria-selected={x.id === value} title={x.desc}
                          onClick={() => { onPick(x.id); setOpen(false); setQ(""); }}
                          className={"flex w-full items-center gap-1 rounded-md px-2 py-1 text-left text-xs hover:bg-accent-soft " +
                                     (x.id === value ? "text-accent" : "text-ink")}>
                    <span className="min-w-0 flex-1 truncate">{x.title}</span>
                    {x.confirm && <AlertTriangle size={11} className="shrink-0 text-warn" />}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function DayChips({ days, onChange }: { days: number[]; onChange(d: number[]): void }) {
  const set = new Set(days.length ? days : [0, 1, 2, 3, 4, 5, 6]);
  const toggle = (d: number) => {
    const next = new Set(set);
    if (next.has(d)) next.delete(d); else next.add(d);
    const arr = [...next].sort((a, b) => a - b);
    onChange(arr.length === 7 ? [] : arr.length ? arr : [d]);
  };
  const preset = "rounded-md px-1.5 py-0.5 text-[10px] text-ink-dim hover:text-accent";
  return (
    <div className="flex flex-wrap items-center gap-1">
      {DAYS.map((label, d) => (
        <button key={label} type="button" aria-pressed={set.has(d)} aria-label={`День: ${label}`} onClick={() => toggle(d)}
                className={"h-6 w-7 rounded-md border text-[10px] " +
                           (set.has(d) ? "border-accent bg-accent-soft text-accent" : "border-line text-ink-dim")}>
          {label}
        </button>
      ))}
      <button type="button" className={preset} onClick={() => onChange(WEEKDAYS)}>будни</button>
      <button type="button" className={preset} onClick={() => onChange(WEEKEND)}>выходные</button>
      <button type="button" className={preset} onClick={() => onChange([])}>все</button>
    </div>
  );
}

function ConditionRow({ c, devices, apps, onChange, onRemove }: {
  c: ScenarioStep; devices: Device[]; apps: string[]; onChange(c: ScenarioStep): void; onRemove(): void;
}) {
  const meta = CONDITION_TYPES.find((x) => x.id === c.type);
  const setType = (type: string) => onChange(type === "time" ? { type, value: "08:00" } : { type, value: "" });
  return (
    <div className="space-y-1.5 rounded-card border border-line bg-panel2/60 p-2">
      <div className="flex items-center gap-1.5">
        <span className="text-accent">{COND_ICONS[c.type]}</span>
        <select aria-label="Тип условия" value={c.type} onChange={(e) => setType(e.target.value)} className={field + " flex-1"}>
          {CONDITION_TYPES.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
        </select>
        <button type="button" aria-label="Убрать условие" onClick={onRemove} className={iconBtn}><X size={14} /></button>
      </div>
      {c.type === "phrase" && (
        <input aria-label="Фраза" value={c.value} onChange={(e) => onChange({ ...c, value: e.target.value })}
               placeholder="например: доброе утро" className={field + " w-full"} />
      )}
      {c.type === "time" && (
        <div className="space-y-1.5">
          <input aria-label="Время" type="time" value={c.value.split("-")[0]}
                 onChange={(e) => onChange({ ...c, value: e.target.value })} className={field + " w-28"} />
          <DayChips days={c.days ?? []} onChange={(d) => onChange({ ...c, days: d.length ? d : undefined })} />
        </div>
      )}
      {(c.type === "device_connected" || c.type === "device_disconnected") && (
        <select aria-label="Устройство" value={c.value} onChange={(e) => onChange({ ...c, value: e.target.value })}
                className={field + " w-full"}>
          <option value="">Любое устройство</option>
          {devices.map((d) => <option key={d.id} value={d.id}>{d.name}{d.online ? " · онлайн" : ""}</option>)}
          {c.value && !devices.some((d) => d.id === c.value) && <option value={c.value}>{c.value}</option>}
        </select>
      )}
      {c.type === "app_started" && (
        <>
          <input aria-label="Приложение" list="scenario-apps" value={c.value}
                 onChange={(e) => onChange({ ...c, value: e.target.value })}
                 placeholder="Steam, Discord, Valorant…" className={field + " w-full"} />
          <datalist id="scenario-apps">{apps.map((a) => <option key={a} value={a} />)}</datalist>
        </>
      )}
      {meta && <div className="text-[10px] text-ink-dim">{meta.hint}</div>}
    </div>
  );
}

function ActionRow({ a, i, count, catalog, onChange, onMove, onRemove }: {
  a: ScenarioStep; i: number; count: number; catalog: CatalogAction[];
  onChange(a: ScenarioStep): void; onMove(dir: -1 | 1): void; onRemove(): void;
}) {
  const cmd = a.type === "action" ? catalog.find((x) => x.id === a.value) : undefined;
  const setType = (type: string) => onChange(type === "pause" ? { type, value: "5" } : { type, value: "" });
  return (
    <div className="space-y-1.5 rounded-card border border-line bg-panel2/60 p-2">
      <div className="flex items-center gap-1.5">
        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-accent-soft text-[10px] text-accent">{i + 1}</span>
        <select aria-label="Тип действия" value={a.type} onChange={(e) => setType(e.target.value)} className={field + " w-48"}>
          {ACTION_TYPES.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
        </select>
        <div className="ml-auto flex">
          <button type="button" aria-label="Выше" disabled={i === 0} onClick={() => onMove(-1)} className={iconBtn}><ChevronUp size={14} /></button>
          <button type="button" aria-label="Ниже" disabled={i === count - 1} onClick={() => onMove(1)} className={iconBtn}><ChevronDown size={14} /></button>
          <button type="button" aria-label="Убрать действие" onClick={onRemove} className={iconBtn}><X size={14} /></button>
        </div>
      </div>
      {a.type === "action" && (
        <>
          <ActionPicker value={a.value} catalog={catalog}
                        onPick={(id) => onChange({ type: "action", value: id, ...(a.arg ? { arg: a.arg } : {}) })} />
          {cmd?.param && (
            <input aria-label="Параметр" value={a.arg ?? ""} onChange={(e) => onChange({ ...a, arg: e.target.value })}
                   placeholder={cmd.param.hint + (cmd.param.required ? "" : " (необязательно)")} className={field + " w-full"} />
          )}
          {cmd && (cmd.confirm || cmd.device) && (
            <div className="flex flex-wrap gap-2 text-[10px]">
              {cmd.confirm && <span className="flex items-center gap-1 text-warn"><AlertTriangle size={11} /> опасное: только кнопкой ▶ с подтверждением</span>}
              {cmd.device && <span className="flex items-center gap-1 text-ink-dim"><Monitor size={11} /> выполнит компьютер</span>}
            </div>
          )}
        </>
      )}
      {a.type === "pause" && (
        <label className="flex items-center gap-2 text-xs text-ink-dim">
          <input aria-label="Секунд" type="number" min={1} max={60} value={a.value}
                 onChange={(e) => onChange({ ...a, value: e.target.value })} className={field + " w-20"} />
          секунд (до 60)
        </label>
      )}
      {(a.type === "telegram" || a.type === "notify") && (
        <textarea aria-label="Текст" rows={2} value={a.value} onChange={(e) => onChange({ ...a, value: e.target.value })}
                  placeholder={a.type === "telegram" ? "Что прислать тебе в Telegram" : "Что Сакура скажет и покажет"}
                  className={field + " w-full resize-none"} />
      )}
    </div>
  );
}

/** Проверка до отправки: понятные сообщения прямо в форме (сервер проверит ещё раз). */
export function localProblems(sc: Scenario, catalog: CatalogAction[]): string[] {
  const out: string[] = [];
  if (!sc.name.trim()) out.push("Впиши название");
  if (!sc.actions.length) out.push("Добавь хотя бы одно действие");
  sc.conditions.forEach((c, i) => {
    if ((c.type === "phrase" || c.type === "app_started") && !c.value.trim()) out.push(`Условие ${i + 1}: заполни поле`);
    if (c.type === "time" && !/^\d{2}:\d{2}/.test(c.value)) out.push(`Условие ${i + 1}: укажи время`);
  });
  sc.actions.forEach((a, i) => {
    if (a.type === "action") {
      const cmd = catalog.find((x) => x.id === a.value);
      if (!a.value) out.push(`Действие ${i + 1}: выбери команду`);
      else if (catalog.length && !cmd) out.push(`Действие ${i + 1}: такой команды нет на сервере`);
      else if (cmd?.param?.required && !a.arg?.trim()) out.push(`Действие ${i + 1}: ${cmd.param.hint.toLowerCase()}`);
    } else if (a.type === "pause") {
      const n = Number(a.value);
      if (!(n >= 1 && n <= 60)) out.push(`Действие ${i + 1}: пауза от 1 до 60 секунд`);
    } else if (!a.value.trim()) out.push(`Действие ${i + 1}: впиши текст`);
  });
  return out;
}

export function ScenarioBuilder({ draft, hints = [], onSaved, onCancel }: {
  draft: Scenario; hints?: string[]; onSaved(s: Scenario, warnings: string[], run: boolean): void; onCancel(): void;
}) {
  const catalog = useApp((s) => s.catalog);
  const loadCatalog = useApp((s) => s.loadCatalog);
  const devices = useApp((s) => s.devices);
  const loadDevices = useApp((s) => s.loadDevices);
  const listApps = useApp((s) => s.listApps);
  const save = useApp((s) => s.saveScenario);
  const [sc, setSc] = useState<Scenario>(() => ({ ...draft, actions: draft.actions.map(normalizeAction) }));
  const [error, setError] = useState<string | null>(null);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [apps, setApps] = useState<string[]>([]);

  useEffect(() => {
    if (catalog.status === "idle") void loadCatalog();
    if (devices.status === "idle") void loadDevices();
    listApps().then((a) => setApps(Array.isArray(a) ? a : [])).catch(() => setApps([]));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const cat = catalog.data;
  const problems = localProblems(sc, cat);
  const setCond = (i: number, c: ScenarioStep) => setSc({ ...sc, conditions: sc.conditions.map((x, j) => (j === i ? c : x)) });
  const setAct = (i: number, a: ScenarioStep) => setSc({ ...sc, actions: sc.actions.map((x, j) => (j === i ? a : x)) });
  const move = (i: number, dir: -1 | 1) => {
    const next = [...sc.actions];
    const a = next[i], b = next[i + dir];
    if (!a || !b) return;
    next[i] = b;
    next[i + dir] = a;
    setSc({ ...sc, actions: next });
  };

  async function submit(run: boolean) {
    setTried(true);
    if (problems.length) return;
    setBusy(true);
    setError(null);
    try {
      const body: Scenario = {
        ...sc, name: sc.name.trim(),
        conditions: sc.conditions.map((c) => (c.type === "time"
          ? { type: c.type, value: c.value, ...(c.days?.length ? { days: c.days } : {}) }
          : { type: c.type, value: c.value.trim() })),
        actions: sc.actions.map((a) => (a.type === "action"
          ? { type: "action", value: a.value, ...(a.arg?.trim() ? { arg: a.arg.trim() } : {}) }
          : { type: a.type, value: a.value.trim() })),
      };
      const r = await save(body);
      onSaved(r.scenario, r.warnings, run);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 px-4 pb-4">
      {hints.length > 0 && (
        <ul aria-label="Подсказки" className="space-y-0.5 rounded-card border border-amber-300/20 bg-amber-300/5 p-2 text-[11px] text-amber-200/90">
          {hints.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}
      <div className="flex items-center gap-2">
        <input aria-label="Название сценария" value={sc.name} onChange={(e) => setSc({ ...sc, name: e.target.value })}
               placeholder="Например: Доброе утро" maxLength={60} className={field + " flex-1 py-2 text-sm"} />
        <label className="flex items-center gap-1 text-xs text-ink-dim">
          <input type="checkbox" aria-label="Включён" checked={sc.enabled} onChange={(e) => setSc({ ...sc, enabled: e.target.checked })}
                 className="accent-[rgb(var(--accent))]" />
          включён
        </label>
      </div>

      <section aria-label="Когда запускать" className="space-y-1.5">
        <div className="text-xs font-semibold text-ink">Когда запускать</div>
        {sc.conditions.length === 0 && (
          <div className="text-[11px] text-ink-dim">Без условий — кнопкой ▶ или голосом: «запусти сценарий {sc.name || "…"}»</div>
        )}
        {sc.conditions.map((c, i) => (
          <ConditionRow key={i} c={c} devices={devices.data} apps={apps} onChange={(nc) => setCond(i, nc)}
                        onRemove={() => setSc({ ...sc, conditions: sc.conditions.filter((_, j) => j !== i) })} />
        ))}
        {sc.conditions.length > 1 && <div className="text-[10px] text-ink-dim">Сработает любое из условий</div>}
        <button type="button" disabled={sc.conditions.length >= 10}
                onClick={() => setSc({ ...sc, conditions: [...sc.conditions, { type: "phrase", value: "" }] })}
                className="flex items-center gap-1 text-xs text-accent hover:underline disabled:opacity-40">
          <Plus size={14} /> Добавить условие
        </button>
      </section>

      <section aria-label="Что сделать" className="space-y-1.5">
        <div className="text-xs font-semibold text-ink">Что сделать</div>
        {catalog.status === "error" && <div className="text-[11px] text-warn">Список команд не загрузился: {catalog.error}</div>}
        {catalog.status === "unsupported" && <div className="text-[11px] text-warn">Сервер ещё не отдаёт список команд — обнови сервер</div>}
        {sc.actions.map((a, i) => (
          <ActionRow key={i} a={a} i={i} count={sc.actions.length} catalog={cat} onChange={(na) => setAct(i, na)}
                     onMove={(d) => move(i, d)} onRemove={() => setSc({ ...sc, actions: sc.actions.filter((_, j) => j !== i) })} />
        ))}
        <button type="button" disabled={sc.actions.length >= 20}
                onClick={() => setSc({ ...sc, actions: [...sc.actions, { type: "action", value: "" }] })}
                className="flex items-center gap-1 text-xs text-accent hover:underline disabled:opacity-40">
          <Plus size={14} /> Добавить действие
        </button>
      </section>

      {tried && problems.length > 0 && (
        <ul role="alert" aria-label="Что поправить" className="space-y-0.5 text-[11px] text-warn">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
      {error && <div role="alert" className="text-[11px] text-warn">{error}</div>}
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <button type="button" disabled={busy} onClick={() => void submit(false)}
                className="flex items-center gap-1 rounded-btn bg-accent px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
          <Save size={14} /> Сохранить
        </button>
        <button type="button" disabled={busy} onClick={() => void submit(true)}
                className="rounded-btn border border-line px-3 py-1.5 text-xs text-ink hover:border-accent disabled:opacity-50">
          Сохранить и запустить
        </button>
        <button type="button" onClick={onCancel} className="ml-auto text-xs text-ink-dim hover:text-ink">Отмена</button>
      </div>
    </div>
  );
}

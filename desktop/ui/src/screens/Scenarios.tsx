// Экран «Сценарии»: список (вкл/выкл, запуск, правка, удаление, итог последнего запуска),
// журнал запусков и редактор справа: с нуля, из шаблона или из фразы.
import { AlertTriangle, CircleCheck, CircleX, Pencil, Play, Plus, SkipForward, Sparkles, Trash2, Workflow } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Scenario } from "../api/types";
import { CoreError } from "../api/types";
import { ScenarioBuilder } from "../components/ScenarioBuilder";
import { actionText, conditionText, emptyScenario, TEMPLATES } from "../components/scenarioText";
import { agoText, Card, EmptyState, Loadable, timeHM } from "../components/ui";
import { errorText, useApp } from "../store";

const field = "min-w-0 rounded-lg border border-line bg-panel2 px-2 py-1.5 text-xs text-ink outline-none focus:border-accent";

function Switch({ on, label, onChange }: { on: boolean; label: string; onChange(v: boolean): void }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
            className={"relative h-4 w-7 shrink-0 rounded-full transition-colors " + (on ? "bg-accent" : "bg-white/15")}>
      <span className={"absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all " + (on ? "left-3.5" : "left-0.5")} />
    </button>
  );
}

function LastRun({ sc }: { sc: Scenario }) {
  if (!sc.last_run) return null;
  const when = agoText(sc.last_run);
  if (sc.last_status === "error") {
    return <span className="flex items-center gap-1 text-warn" title={sc.last_detail}><CircleX size={11} /> ошибка {when}</span>;
  }
  if (sc.last_status === "skipped") {
    return <span className="flex items-center gap-1 text-ink-dim" title={sc.last_detail}><SkipForward size={11} /> пропущен {when}: {sc.last_detail}</span>;
  }
  return <span className="flex items-center gap-1 text-online"><CircleCheck size={11} /> выполнен {when}{sc.run_count ? ` · ${sc.run_count} раз` : ""}</span>;
}

type Editing = { draft: Scenario; hints: string[]; key: number };

export function Scenarios() {
  const scenarios = useApp((s) => s.scenarios);
  const load = useApp((s) => s.loadScenarios);
  const run = useApp((s) => s.runScenario);
  const remove = useApp((s) => s.deleteScenario);
  const toggle = useApp((s) => s.toggleScenario);
  const log = useApp((s) => s.scenarioLog);
  const catalog = useApp((s) => s.catalog);
  const loadCatalog = useApp((s) => s.loadCatalog);
  const devices = useApp((s) => s.devices);
  const preview = useApp((s) => s.preview);
  const previewScenario = useApp((s) => s.previewScenario);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [danger, setDanger] = useState<{ id: string; text: string } | null>(null);
  const [note, setNote] = useState<{ text: string; warn: boolean } | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [phrase, setPhrase] = useState("");
  const [seq, setSeq] = useState(1);

  useEffect(() => { if (catalog.status === "idle") void loadCatalog(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // «Собрать» из фразы → черновик сразу в редактор (с подсказками сервера).
  // Черновик, собранный до открытия экрана, повторно не открываем.
  const seenPreview = useRef(preview.data);
  useEffect(() => {
    if (preview.status === "ready" && preview.data && preview.data !== seenPreview.current) {
      seenPreview.current = preview.data;
      open(preview.data.scenario, preview.data.warnings);
    }
  }, [preview]); // eslint-disable-line react-hooks/exhaustive-deps

  function open(draft: Scenario, hints: string[] = []) {
    setEditing({ draft: structuredClone(draft), hints, key: seq });
    setSeq(seq + 1);
    setNote(null);
  }

  async function act(fn: () => Promise<void>) {
    try { await fn(); setNote(null); } catch (e) { setNote({ text: errorText(e), warn: true }); }
  }

  async function start(id: string, sure = false) {
    try {
      await run(id, sure);
      setDanger(null);
    } catch (e) {
      if (e instanceof CoreError && e.code === "confirm_required") setDanger({ id, text: e.message });
      else setNote({ text: errorText(e), warn: true });
    }
  }

  const cat = catalog.data;
  const runs = [...log].reverse().slice(0, 40);
  const quickStart = (
    <Card title="Создать сценарий" icon={<Sparkles size={18} />}>
      <div className="space-y-3 px-4 pb-4">
        <div>
          <div className="mb-1.5 text-xs text-ink-dim">Опиши словами — соберу черновик</div>
          <form className="flex gap-1.5" onSubmit={(e) => { e.preventDefault(); void previewScenario(phrase); }}>
            <input aria-label="Сценарий словами" value={phrase} onChange={(e) => setPhrase(e.target.value)}
                   placeholder="по будням в 7:30 включи мою волну и скажи доброе утро" className={field + " flex-1"} />
            <button type="submit" disabled={!phrase.trim() || preview.status === "loading"}
                    className="rounded-lg bg-accent-soft px-2.5 text-xs text-accent disabled:opacity-40">Собрать</button>
          </form>
          {preview.status === "error" && <div role="alert" className="mt-1 text-[11px] text-warn">{preview.error}</div>}
          {preview.status === "unsupported" && <div className="mt-1 text-[11px] text-warn">Сервер не поддерживает</div>}
          <div className="mt-1 text-[10px] text-ink-dim">
            Понимаю время («в 7:30», «по будням», «вечером»), «когда скажу …», «когда открою Steam»,
            «когда подключится телефон», паузы и «напиши мне в телеграм …»
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-ink-dim">Шаблоны:</span>
          {TEMPLATES.map((t) => (
            <button key={t.title} type="button" onClick={() => open(t.scenario)}
                    className="rounded-full border border-line px-2.5 py-1 text-xs text-ink hover:border-accent hover:text-accent">
              {t.title}
            </button>
          ))}
          <button type="button" onClick={() => open(emptyScenario())}
                  className="flex items-center gap-1 rounded-full border border-dashed border-line px-2.5 py-1 text-xs text-ink-dim hover:border-accent hover:text-accent">
            <Plus size={12} /> Собрать с нуля
          </button>
        </div>
      </div>
    </Card>
  );

  if (editing) {
    return (
      <div className="h-full min-h-0 overflow-y-auto">
        <Card title={editing.draft.id ? "Изменение сценария" : "Новый сценарий"} icon={<Workflow size={18} />}
              action={<button type="button" onClick={() => setEditing(null)} className="text-xs text-ink-dim hover:text-accent">← К списку</button>}>
          <ScenarioBuilder key={editing.key} draft={editing.draft} hints={editing.hints}
                           onCancel={() => setEditing(null)}
                           onSaved={(s, warnings, andRun) => {
                             setEditing(null);
                             setNote({ text: [`Сохранено: «${s.name}»`, ...warnings].join(". "), warn: false });
                             if (andRun && s.id) void start(s.id);
                           }} />
        </Card>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-gap overflow-y-auto">
      <Card title="Сценарии" icon={<Workflow size={18} />}
            action={
              <button type="button" onClick={() => open(emptyScenario())}
                      className="flex items-center gap-1 rounded-btn bg-accent-soft px-2.5 py-1 text-xs text-accent hover:brightness-110">
                <Plus size={14} /> Новый
              </button>
            }>
        <div className="px-4 pb-4">
            <Loadable status={scenarios.status} error={scenarios.error} onRetry={() => void load()}>
              {scenarios.data.length === 0 ? (
                <EmptyState text="Сценариев пока нет — начни с шаблона ниже или опиши словами" />
              ) : (
                <ul className="flex flex-col gap-2">
                  {scenarios.data.map((sc) => (
                    <li key={sc.id ?? sc.name}
                        className="rounded-card bg-panel2 px-3 py-2 text-sm">
                      <div className="flex items-center gap-2">
                        {sc.id && <Switch on={sc.enabled} label={`Включён: ${sc.name}`}
                                          onChange={(v) => void act(() => toggle(sc.id as string, v))} />}
                        <span className={"truncate font-medium " + (sc.enabled ? "text-ink" : "text-ink-dim")}>{sc.name}</span>
                        {sc.builtin && <span className="rounded bg-white/5 px-1 text-[10px] text-ink-dim">встроенный</span>}
                        {sc.id && (confirm === sc.id ? (
                          <span className="ml-auto flex items-center gap-1 text-xs text-warn">Удалить?
                            <button type="button" onClick={() => { setConfirm(null); void act(() => remove(sc.id as string)); }} className="underline">Да</button>
                            <button type="button" onClick={() => setConfirm(null)} className="text-ink-dim underline">Нет</button></span>
                        ) : (
                          <span className="ml-auto flex items-center gap-2">
                            <button type="button" aria-label={`Запустить: ${sc.name}`} onClick={() => void start(sc.id as string)}
                                    className="text-ink-dim hover:text-accent"><Play size={14} /></button>
                            <button type="button" aria-label={`Изменить: ${sc.name}`} onClick={() => open(sc)}
                                    className="text-ink-dim hover:text-accent"><Pencil size={14} /></button>
                            {!sc.builtin && (
                              <button type="button" aria-label={`Удалить: ${sc.name}`} onClick={() => setConfirm(sc.id as string)}
                                      className="text-ink-dim hover:text-warn"><Trash2 size={14} /></button>
                            )}
                          </span>
                        ))}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
                        {sc.conditions.length === 0
                          ? <span className="rounded bg-white/5 px-1.5 text-ink-dim">кнопкой или «запусти сценарий {sc.name}»</span>
                          : sc.conditions.map((c, i) => (
                            <span key={i} className="rounded bg-accent-soft px-1.5 text-accent">{conditionText(c, devices.data)}</span>))}
                      </div>
                      <div className="mt-1 truncate text-[11px] text-ink-dim" title={sc.actions.map((a) => actionText(a, cat)).join(" → ")}>
                        {sc.actions.map((a) => actionText(a, cat)).join(" → ")}
                      </div>
                      <div className="mt-1 text-[11px]"><LastRun sc={sc} /></div>
                      {danger?.id === sc.id && (
                        <div role="alert" className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-warn/40 bg-warn/10 p-2 text-xs text-warn">
                          <AlertTriangle size={14} /> Есть опасные действия. Запустить?
                          <button type="button" onClick={() => void start(sc.id as string, true)} className="underline">Запустить</button>
                          <button type="button" onClick={() => setDanger(null)} className="text-ink-dim underline">Отмена</button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Loadable>
          {note && <div role="alert" className={"mt-2 text-xs " + (note.warn ? "text-warn" : "text-online")}>{note.text}</div>}
        </div>
      </Card>
      {quickStart}
      {runs.length > 0 && (
        <Card title="Журнал запусков">
          <ul className="max-h-56 overflow-y-auto px-4 pb-3 text-xs text-ink-dim">
            {runs.map((e, i) => (
              <li key={`${e.run_id}-${e.step}-${i}`} className={e.status === "error" ? "text-warn" : ""}>
                {timeHM(e.ts)} · {e.status === "started"
                  ? `${e.name ?? e.detail}${e.trigger ? ` (${e.trigger})` : ""} — запущен`
                  : e.status === "done" ? (e.detail || "завершён")
                  : `шаг ${e.step + 1}: ${e.status === "ok" ? "готово" : e.status === "error" ? "ошибка" : e.status}${e.detail ? ` — ${e.detail}` : ""}`}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

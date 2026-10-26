// Безопасность управления ПК: баннер «Сакура управляет компьютером» со «Стоп», «Управление приостановлено»
// с «Возобновить», окно «Разрешить?» для опасных действий и центр действий (колокол в верхней панели).
import { Bell, Globe, OctagonX, Play, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { bridge } from "../bridge";
import { useMediaClient } from "../media/MediaContext";
import { errorText, useApp } from "../store";

export function ControlBanner() {
  const busy = useApp((s) => s.pcAction);
  const paused = useApp((s) => s.controlPaused);
  const panic = useApp((s) => s.panic);
  useEffect(() => bridge().core.onPanic(() => void panic(true)), [panic]);
  if (paused) {
    return (
      <div role="alert" className="flex items-center gap-2 border-b border-warn/40 bg-warn/10 px-4 py-1.5 text-xs text-warn">
        <OctagonX size={14} /> Управление компьютером остановлено аварийной кнопкой.
        <button type="button" onClick={() => void panic(false)} className="ml-auto flex items-center gap-1 rounded-full border border-warn/50 px-3 py-0.5">
          <Play size={12} /> Возобновить</button>
      </div>
    );
  }
  if (!busy) return null;
  return (
    <div aria-live="polite" aria-label="Сакура управляет компьютером"
         className="flex items-center gap-2 border-b border-accent/40 bg-accent/10 px-4 py-1.5 text-xs text-ink">
      <ShieldAlert size={14} className="text-accent" /> Сакура управляет компьютером…
      <button type="button" onClick={() => void panic(true)} title="Аварийная остановка (Ctrl+Alt+End)"
              className="ml-auto flex items-center gap-1 rounded-full bg-warn/20 px-3 py-0.5 text-warn">
        <OctagonX size={12} /> Стоп</button>
    </div>
  );
}

/** Задача агента браузера: «работает в окне агента» или пауза (капча, вход) с кнопкой «Готово». */
export function BrowserTaskBanner() {
  const task = useApp((s) => s.browserTask);
  const resume = useApp((s) => s.resumeBrowser);
  if (!task) return null;
  if (task.state === "paused") {
    return (
      <div role="alert" aria-label="Задача в браузере ждёт"
           className="flex items-center gap-2 border-b border-warn/40 bg-warn/10 px-4 py-1.5 text-xs text-warn">
        <Globe size={14} /> Задача в браузере ждёт вас{task.text ? `: ${task.text}` : ""}. Сделайте нужное в окне агента.
        <button type="button" onClick={() => void resume(task.task_id)}
                className="ml-auto flex items-center gap-1 rounded-full border border-warn/50 px-3 py-0.5">
          <Play size={12} /> Готово</button>
      </div>
    );
  }
  return (
    <div aria-live="polite" aria-label="Сакура работает в браузере"
         className="flex items-center gap-2 border-b border-accent/40 bg-accent/10 px-4 py-1.5 text-xs text-ink">
      <Globe size={14} className="text-accent" /> Сакура выполняет задачу в отдельном окне браузера…
    </div>
  );
}

export function ConfirmDialog() {
  const confirms = useApp((s) => s.confirms);
  const answer = useApp((s) => s.answerConfirm);
  const c = confirms[0];
  if (!c) return null;
  return (
    <div role="dialog" aria-label="Разрешить действие?" className="fixed inset-0 z-50 grid place-items-center bg-black/50">
      <div className="w-[420px] rounded-card bg-panel p-5 shadow-soft">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium text-ink"><ShieldAlert size={16} className="text-warn" /> Разрешить?</div>
        <div className="mb-4 break-words text-sm text-ink">{c.label}</div>
        <div className="mb-4 text-xs text-ink-dim">Без ответа за минуту действие будет отменено.</div>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={() => void answer(c.id, false)} className="rounded-full border border-line px-4 py-1.5 text-sm text-ink-dim hover:text-ink">Нет</button>
          <button type="button" onClick={() => void answer(c.id, true)} className="rounded-full bg-warn/80 px-4 py-1.5 text-sm text-black">Да, выполнить</button>
        </div>
      </div>
    </div>
  );
}

interface Recent { action: string; status: string; ts: number }

const STATUS: Record<string, string> = { done: "выполнено", noop: "без изменений", failed: "ошибка", unsupported: "отказ" };

/** Центр действий: что Сакура сделала (20 последних, без содержимого), что ждёт подтверждения, связь, обновления. */
export function ActionCenter() {
  const client = useMediaClient();
  const confirms = useApp((s) => s.confirms);
  const link = useApp((s) => s.link);
  const online = useApp((s) => s.server.online);
  const offlineMode = useApp((s) => Boolean(s.settings?.offline));
  const answer = useApp((s) => s.answerConfirm);
  const [open, setOpen] = useState(false);
  const [recent, setRecent] = useState<Recent[]>([]);
  const [update, setUpdate] = useState<{ behind: number } | null>(null);
  const [err, setErr] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    client.call<{ actions: Recent[] }>("actions_recent").then(
      (r) => { if (alive) setRecent(r.actions); }, (e: unknown) => { if (alive) setErr(errorText(e)); });
    client.call<{ behind: number }>("update_status").then((r) => { if (alive) setUpdate(r); }, () => {});
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("mousedown", close);
    return () => { alive = false; window.removeEventListener("mousedown", close); };
  }, [client, open]);

  const connectionProblem = link !== "open" ? "Нет связи с ядром" : !online && !offlineMode ? "Нет связи с сервером" : null;
  const badge = confirms.length + (connectionProblem ? 1 : 0);
  return (
    <div ref={ref} className="no-drag relative">
      <button type="button" aria-label="Центр действий" title="Центр действий" onClick={() => setOpen(!open)}
              className="relative grid h-[45px] w-[45px] place-items-center rounded-btn bg-panel text-ink-dim hover:bg-panel2 hover:text-ink">
        <Bell size={18} />
        {badge > 0 && <span className="absolute right-2 top-2 grid h-4 min-w-4 place-items-center rounded-full bg-warn px-1 text-[10px] text-black">{badge}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label="Центр действий" className="absolute right-0 top-[52px] z-40 w-[360px] rounded-card bg-panel p-4 text-xs shadow-soft">
          {confirms.length > 0 && (
            <section className="mb-3">
              <div className="mb-1 font-medium text-warn">Ждёт подтверждения</div>
              {confirms.map((c) => (
                <div key={c.id} className="flex items-center gap-2 py-1 text-ink">
                  <span className="flex-1 break-words">{c.label}</span>
                  <button type="button" onClick={() => void answer(c.id, true)} className="underline">Да</button>
                  <button type="button" onClick={() => void answer(c.id, false)} className="text-ink-dim underline">Нет</button>
                </div>
              ))}
            </section>
          )}
          {connectionProblem && <div className="mb-3 text-warn">{connectionProblem}</div>}
          {update && update.behind > 0 && <div className="mb-3 text-ink">Доступно обновление: {update.behind} коммит(ов) — Настройки → Обновление</div>}
          <div className="mb-1 font-medium text-ink">Последние действия</div>
          {err && <div className="text-warn">{err}</div>}
          {recent.length === 0 && !err && <div className="text-ink-dim">Сакура ещё ничего не делала с компьютером</div>}
          <ul aria-label="Последние действия" className="max-h-64 overflow-y-auto">
            {recent.map((r) => (
              <li key={`${r.ts}-${r.action}`} className="flex justify-between gap-2 border-b border-line py-1 last:border-0">
                <span className="text-ink">{r.action}</span>
                <span className={r.status === "done" ? "text-online" : r.status === "noop" ? "text-ink-dim" : "text-warn"}>
                  {STATUS[r.status] ?? r.status} · {new Date(r.ts * 1000).toLocaleTimeString().slice(0, 5)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

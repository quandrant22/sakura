// Настройки → «Экран и сцена»: на каком мониторе Сакура смотрит, рисует и показывается поверх игр.
// Выбор живёт в двух местах: main (куда ставить окно сцены, stage.json) и ядро (какой монитор снимать —
// настройка target_display в физических пикселях).
import { Crosshair, Monitor } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { bridge, type DisplayInfo } from "../bridge";
import { useMediaClient } from "../media/MediaContext";
import { errorText, useApp } from "../store";

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[220px_1fr] items-start gap-4 border-b border-line py-3 last:border-0">
      <div><div className="text-sm text-ink">{label}</div>{hint && <div className="mt-0.5 text-xs text-ink-dim">{hint}</div>}</div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

const btn = "flex items-center gap-1.5 rounded-btn border border-line px-3 py-1.5 text-xs text-ink-dim hover:border-accent hover:text-ink";

/** Значение настройки ядра target_display для монитора. */
export function targetFor(d: DisplayInfo): Record<string, unknown> {
  return { id: d.id, label: d.label, ...d.physical };
}

/** Мини-схема мониторов: прямоугольники в пропорциях стола, выбранный — акцентом. */
function DisplayMap({ list, current, onPick }: { list: DisplayInfo[]; current: number | null; onPick(d: DisplayInfo): void }) {
  if (!list.length) return null;
  const minX = Math.min(...list.map((d) => d.bounds.x)), minY = Math.min(...list.map((d) => d.bounds.y));
  const maxX = Math.max(...list.map((d) => d.bounds.x + d.bounds.width));
  const maxY = Math.max(...list.map((d) => d.bounds.y + d.bounds.height));
  const W = 320, k = W / Math.max(1, maxX - minX), H = Math.max(60, (maxY - minY) * k);
  return (
    <div className="relative mt-3" style={{ width: W, height: H }} aria-label="Схема мониторов">
      {list.map((d, i) => {
        const on = d.id === current;
        return (
          <button key={d.id} type="button" onClick={() => onPick(d)} aria-pressed={on} title={d.label}
                  className={"absolute grid place-items-center rounded-lg border text-xs transition " +
                    (on ? "border-accent bg-accent/15 text-ink shadow-glow" : "border-white/[0.12] bg-panel2 text-ink-dim hover:border-accent/60")}
                  style={{ left: (d.bounds.x - minX) * k + 2, top: (d.bounds.y - minY) * k + 2,
                           width: d.bounds.width * k - 4, height: d.bounds.height * k - 4 }}>
            <span className="flex items-center gap-1"><Monitor size={13} /> {i + 1}{d.primary ? " ★" : ""}</span>
          </button>
        );
      })}
    </div>
  );
}

export function ScreenSection() {
  const client = useMediaClient();
  const settings = useApp((s) => s.settings);
  const [list, setList] = useState<DisplayInfo[]>([]);
  const [current, setCurrent] = useState<number | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const refresh = () => Promise.all([bridge().displays.list(), bridge().stage.get()]).then(([ds, st]) => {
      if (!alive) return;
      setList(ds);
      setCurrent(st.current || st.displayId || ds.find((d) => d.primary)?.id || null);
      setEnabled(st.enabled);
    }, () => {});
    void refresh();
    const off = bridge().displays.onChanged(() => void refresh());
    return () => { alive = false; off(); };
  }, []);

  const pick = async (d: DisplayInfo) => {
    setMsg(null);
    try {
      await bridge().stage.setDisplay(d.id);
      await client.call("settings_set", { key: "target_display", value: targetFor(d) });
      setCurrent(d.id);
      setMsg(`Сакура теперь на «${d.label}»`);
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  const toggleStage = async (on: boolean) => {
    setEnabled(await bridge().stage.setEnabled(on));
    void client.call("settings_set", { key: "stage_enabled", value: on }).catch(() => {});
  };
  const test = async () => {
    try { await client.call("ink_test"); setMsg("Смотри на выбранный монитор — обвела центр на 4 секунды"); }
    catch (e) { setMsg(errorText(e)); }
  };

  return (
    <div className="px-4 pb-2">
      <Row label="Экран Сакуры" hint="Здесь она смотрит на экран (зрение, «скажи, когда…», игры), рисует и показывает субтитры">
        {list.length === 0 ? (
          <div className="text-xs text-ink-dim">Мониторы видны только в приложении Сакуры</div>
        ) : (
          <>
            <select aria-label="Экран Сакуры" value={current ?? ""} onChange={(e) => {
              const d = list.find((x) => x.id === Number(e.target.value));
              if (d) void pick(d);
            }}>
              {list.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
            </select>
            <DisplayMap list={list} current={current} onPick={(d) => void pick(d)} />
          </>
        )}
      </Row>
      <Row label="Сцена поверх экрана" hint="Прозрачный слой: рисование, субтитры и реакции в играх. Клики проходят насквозь">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-ink">
            <input type="checkbox" checked={enabled} onChange={(e) => void toggleStage(e.target.checked)} /> Включена
          </label>
          <button type="button" className={btn} onClick={() => void test()} disabled={!enabled}><Crosshair size={13} /> Проверить</button>
        </div>
      </Row>
      <Row label="Субтитры вне игр" hint="В игре её реплики видны всегда; здесь — и на обычном рабочем столе">
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" checked={Boolean(settings?.stage_subtitles_always)}
                 onChange={(e) => void client.call("settings_set", { key: "stage_subtitles_always", value: e.target.checked })} /> Показывать
        </label>
      </Row>
      {msg && <div role="status" className="py-2 text-xs text-ink-dim">{msg}</div>}
    </div>
  );
}

// Настройки → «Игры»: текущая сессия и уровень присутствия Сакуры, уровни по играм, «это игра / не игра»,
// игровые API (CS2/Dota 2 — файл GSI по кнопке; LoL — сам), автоклипы, приглушение игры, полноэкранный режим.
import { Gamepad2, Plug, Plus, Wrench, X } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";

import { useMediaClient } from "../media/MediaContext";
import { errorText, useApp } from "../store";

export type Level = "silent" | "reactions" | "commentator" | "coop";
export const LEVELS: { id: Level; name: string; hint: string }[] = [
  { id: "silent", name: "Молчит", hint: "только всплывашки и итоги" },
  { id: "reactions", name: "Реакции", hint: "победы, серии, достижения" },
  { id: "commentator", name: "Комментатор", hint: "чаще и на больше событий" },
  { id: "coop", name: "Напарник", hint: "рядом на всё заметное" },
];

interface Session { active: boolean; game?: string; key?: string; level?: Level; reason?: string; minutes?: number;
                    stats?: Record<string, number> }
interface GamesState {
  session: Session;
  presence: Record<string, Level>;
  presence_default: Level;
  games: string[];
  not_games: string[];
  gsi: { game: string; title: string; found: boolean; installed: boolean }[];
  global_fso_disabled: boolean;
}
interface Hint { exclusive: boolean; fix: "game" | "global" | null; text: string; game?: string; path?: string }

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[220px_1fr] items-start gap-4 border-b border-line py-3 last:border-0">
      <div><div className="text-sm text-ink">{label}</div>{hint && <div className="mt-0.5 text-xs text-ink-dim">{hint}</div>}</div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

const btn = "flex items-center gap-1.5 rounded-btn border border-line px-3 py-1.5 text-xs text-ink-dim hover:border-accent hover:text-ink disabled:opacity-40";

/** Переключатель уровня: четыре сегмента, активный — градиентом акцента. */
export function LevelSwitch({ value, onChange, label }: { value: Level; onChange(l: Level): void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-btn bg-panel2 p-0.5">
      {LEVELS.map((l) => (
        <button key={l.id} type="button" role="radio" aria-checked={value === l.id} title={l.hint}
                onClick={() => onChange(l.id)}
                className={"rounded-[10px] px-3 py-1 text-xs transition " +
                  (value === l.id ? "bg-accent-grad text-white shadow-glow" : "text-ink-dim hover:text-ink")}>
          {l.name}
        </button>
      ))}
    </div>
  );
}

function ExeList({ items, onRemove, label }: { items: string[]; onRemove(x: string): void; label: string }) {
  if (!items.length) return <div className="text-xs text-ink-dim">Пусто</div>;
  return (
    <div className="flex flex-wrap gap-1.5" aria-label={label}>
      {items.map((x) => (
        <span key={x} className="flex items-center gap-1 rounded-full bg-panel2 px-2.5 py-1 text-xs text-ink">
          {x}
          <button type="button" aria-label={`Убрать ${x}`} onClick={() => onRemove(x)} className="text-ink-dim hover:text-accent"><X size={12} /></button>
        </span>
      ))}
    </div>
  );
}

export function GamesSection() {
  const client = useMediaClient();
  const settings = useApp((s) => s.settings);
  const gameMode = useApp((s) => s.gameMode);
  const [st, setSt] = useState<GamesState | null>(null);
  const [hint, setHint] = useState<Hint | null>(null);
  const [exe, setExe] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => client.call<GamesState>("games_state").then((r) => setSt(r ?? null), (e: unknown) => setMsg(errorText(e))),
                           [client]);
  useEffect(() => {
    let alive = true;
    client.call<GamesState>("games_state").then((r) => { if (alive) setSt(r ?? null); },
                                                (e: unknown) => { if (alive) setMsg(errorText(e)); });
    const off = client.onEvent((ev) => {
      const e = ev as { type: string } & Record<string, unknown>;
      if (e.type === "game_session") void load();
      if (e.type === "fullscreen_hint") setHint(e as unknown as Hint);
    });
    return () => { alive = false; off(); };
  }, [client, load]);

  const run = async (type: string, payload: Record<string, unknown>, ok?: string) => {
    setMsg(null);
    try {
      const r = await client.call<{ detail?: string }>(type, payload);
      setMsg(r?.detail ?? ok ?? "Готово");
      await load();
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  const setDefault = (l: Level) => run("settings_set", { key: "game_presence_default", value: l }, "Сохранено");
  const setLevel = (key: string, l: Level) => run("game_presence_set", { key, level: l }, "Сохранено");
  const removeLevel = (key: string) => {
    const per = Object.fromEntries(Object.entries(st?.presence ?? {}).filter(([k]) => k !== key));
    return run("settings_set", { key: "game_presence", value: per }, "Убрано");
  };
  const mark = (isGame: boolean) => {
    const name = exe.trim().toLowerCase();
    if (!name) return;
    setExe("");
    void run("game_mark", { exe: name.endsWith(".exe") ? name : `${name}.exe`, is_game: isGame }, "Запомнила");
  };
  const unlist = (key: "game_processes" | "game_not_processes", x: string) =>
    run("settings_set", { key, value: (key === "game_processes" ? st?.games : st?.not_games)?.filter((g) => g !== x) ?? [] }, "Убрано");

  const s = st?.session;
  return (
    <div className="px-4 pb-2">
      <Row label="Сейчас" hint="Игру Сакура узнаёт сама — по процессу: Steam, Epic, GOG, Riot, Battle.net, VK Play, эмуляторы">
        {s?.active ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-sm text-ink">
              <Gamepad2 size={16} className="text-accent" /> <b>{s.game}</b>
              <span className="text-xs text-ink-dim">· {s.minutes} мин · {s.reason}</span>
            </div>
            <LevelSwitch label="Присутствие в этой игре" value={s.level ?? "reactions"} onChange={(l) => s.key && void setLevel(s.key, l)} />
            {s.stats && (
              <div className="text-xs text-ink-dim">
                убийств {s.stats.kills ?? 0} · смертей {s.stats.deaths ?? 0} · побед {s.stats.wins ?? 0} · клипов {s.stats.clips ?? 0}
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-3 text-sm text-ink-dim">
            Не играешь
            <label className="flex items-center gap-2 text-ink">
              <input type="checkbox" checked={gameMode} onChange={(e) => void client.call("game_mode", { on: e.target.checked })} />
              Игровой режим вручную
            </label>
          </div>
        )}
      </Row>

      {hint?.exclusive && (
        <div role="alert" className="my-2 rounded-btn border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-ink">
          <div>{hint.text}</div>
          {hint.fix && (
            <button type="button" className={btn + " mt-2"}
                    onClick={() => void run("fullscreen_fix", hint.fix === "global" ? { scope: "global" } : { scope: "game", path: hint.path })}>
              <Wrench size={13} /> Включить оптимизации полноэкранного режима
            </button>
          )}
        </div>
      )}

      <Row label="По умолчанию" hint="Для игр, где уровень не выбран">
        <LevelSwitch label="Присутствие по умолчанию" value={st?.presence_default ?? "reactions"} onChange={(l) => void setDefault(l)} />
      </Row>

      {st && Object.keys(st.presence).length > 0 && (
        <Row label="По играм">
          <div className="flex flex-col gap-2">
            {Object.entries(st.presence).map(([key, l]) => (
              <div key={key} className="flex flex-wrap items-center gap-2">
                <span className="w-44 truncate text-xs text-ink" title={key}>{key}</span>
                <LevelSwitch label={`Присутствие: ${key}`} value={l} onChange={(nl) => void setLevel(key, nl)} />
                <button type="button" aria-label={`Сбросить ${key}`} className="text-ink-dim hover:text-accent" onClick={() => void removeLevel(key)}><X size={13} /></button>
              </div>
            ))}
          </div>
        </Row>
      )}

      <Row label="Это игра / не игра" hint="Имя exe: если Сакура не узнала игру или приняла программу за игру">
        <div className="flex flex-col gap-2">
          <div className="flex gap-2">
            <input aria-label="Имя exe" value={exe} onChange={(e) => setExe(e.target.value)} placeholder="game.exe"
                   className="w-48 rounded-btn border border-line bg-panel2 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent" />
            <button type="button" className={btn} onClick={() => mark(true)} disabled={!exe.trim()}><Plus size={13} /> Игра</button>
            <button type="button" className={btn} onClick={() => mark(false)} disabled={!exe.trim()}><X size={13} /> Не игра</button>
          </div>
          <div className="text-xs text-ink-dim">Игры:</div>
          <ExeList label="Игры" items={st?.games ?? []} onRemove={(x) => void unlist("game_processes", x)} />
          <div className="text-xs text-ink-dim">Не игры:</div>
          <ExeList label="Не игры" items={st?.not_games ?? []} onRemove={(x) => void unlist("game_not_processes", x)} />
        </div>
      </Row>

      <Row label="Точные события" hint="Официальные API игр: Сакура знает убийства, раунды и победы без разглядывания экрана">
        <div className="flex flex-col gap-2 text-sm">
          {(st?.gsi ?? []).map((g) => (
            <div key={g.game} className="flex items-center gap-3">
              <span className="w-40 text-ink">{g.title}</span>
              {g.installed ? <span className="text-xs text-online">подключено</span>
                : g.found ? <button type="button" className={btn} onClick={() => void run("gsi_install", { game: g.game })}><Plug size={13} /> Подключить</button>
                  : <span className="text-xs text-ink-dim">не найдена в Steam</span>}
            </div>
          ))}
          <div className="flex items-center gap-3"><span className="w-40 text-ink">League of Legends</span><span className="text-xs text-ink-dim">само, во время матча</span></div>
          <div className="text-xs text-ink-dim">Остальные игры — по экрану (урон, вспышки, затемнение) и достижениям Steam.</div>
        </div>
      </Row>

      <Row label="Клипы и звук">
        <div className="flex flex-col gap-2 text-sm text-ink">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={settings?.game_autoclip !== false}
                   onChange={(e) => void client.call("settings_set", { key: "game_autoclip", value: e.target.checked })} />
            Сохранять клип при победе, эйсе и серии (последние 20 с)
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={settings?.game_duck !== false}
                   onChange={(e) => void client.call("settings_set", { key: "game_duck", value: e.target.checked })} />
            Приглушать игру, пока Сакура говорит
          </label>
        </div>
      </Row>

      {st?.global_fso_disabled && !hint?.exclusive && (
        <Row label="Полноэкранный режим" hint="Оптимизации выключены для всех игр — поверх полноэкранных игр Сакуру не видно">
          <button type="button" className={btn} onClick={() => void run("fullscreen_fix", { scope: "global" })}><Wrench size={13} /> Включить</button>
        </Row>
      )}

      {msg && <div role="status" className="py-2 text-xs text-ink-dim">{msg}</div>}
    </div>
  );
}

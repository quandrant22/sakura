// Левая колонка 300 px (фиксированная): карточка ядра 300x287 и меню.
import {
  Brain, Cpu, Home, LayoutGrid, Lock, MicOff, Plus, RotateCcw, Settings as SettingsIcon, Unlock, Workflow,
} from "lucide-react";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import { bridge } from "../bridge";
import type { CoreVisualState } from "../core-gfx/coreFrame";
import { SakuraCore } from "../core-gfx/SakuraCore";
import { hiddenWidgets, WIDGETS } from "../layout/board";
import { usePrefs } from "../layout/prefs";
import { useApp } from "../store";

export type Section = "home" | "devices" | "scenarios" | "memory" | "settings";

const MENU: { id: Section; label: string; icon: typeof Home }[] = [
  { id: "home", label: "Главная", icon: Home },
  { id: "devices", label: "Устройства", icon: Cpu },
  { id: "scenarios", label: "Сценарии", icon: Workflow },
  { id: "memory", label: "Память", icon: Brain },
  { id: "settings", label: "Настройки", icon: SettingsIcon },
];

const STATUS: Record<CoreVisualState, string> = {
  idle: "Онлайн", listening: "Слушаю", thinking: "Думаю", speaking: "Говорю", offline: "Нет связи",
};

/** Долгое нажатие на ядро, мс. */
export const LONG_PRESS_MS = 600;

/** Пояснение под статусом: что именно не так со связью. */
function useLinkDetail(): string {
  const link = useApp((s) => s.link);
  const server = useApp((s) => s.server.online);
  const coreReady = useApp((s) => s.settings?.core_ready ?? true);
  if (link !== "open") return "нет связи с ядром — переподключаюсь…";
  if (!coreReady) return "загружаю распознавание речи…";
  if (!server) return "нет связи с сервером";
  return "";
}

function useVisualState(): CoreVisualState {
  const online = useApp((s) => s.link === "open" && s.server.online);
  const state = useApp((s) => s.coreState);
  return online ? state : "offline";
}

export function CoreCard() {
  const visual = useVisualState();
  const getLevel = useApp((s) => s.getLevel);
  const listenNow = useApp((s) => s.listenNow);
  const toggleMic = useApp((s) => s.toggleMic);
  const mic = useApp((s) => s.settings?.mic_enabled ?? true);
  const mobility = usePrefs((s) => s.mobility);
  const preset = usePrefs((s) => s.preset);
  const detail = useLinkDetail();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const longFired = useRef(false);

  // Короткий клик — «говорить сейчас», долгий — заглушить/включить микрофон.
  const down = () => {
    longFired.current = false;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      longFired.current = true;
      void toggleMic();
    }, LONG_PRESS_MS);
  };
  const up = () => {
    clearTimeout(timer.current);
    if (!longFired.current) void listenNow();
    longFired.current = true; // повторный pointerup без pointerdown ничего не делает
  };
  const cancel = () => { clearTimeout(timer.current); longFired.current = true; };
  const key = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); void listenNow(); }
    if (e.key.toLowerCase() === "m") { e.preventDefault(); void toggleMic(); }
  };
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <section className="relative h-[287px] w-[300px] shrink-0 overflow-visible rounded-card bg-panel" aria-label="Ядро Сакуры">
      {/* Центр капли — (150, 98) от угла карточки; viewBox 260 → центр svg (130, 130). */}
      <SakuraCore state={visual} level={getLevel} mobility={mobility} preset={preset} size={260}
                  className="pointer-events-none absolute left-[20px] top-[-32px]" />
      <button type="button"
              aria-label="Говорить сейчас. Долгое нажатие или M — выключить микрофон"
              title="Клик — говорить сейчас, удерживать — микрофон"
              onPointerDown={down} onPointerUp={up} onPointerLeave={cancel} onKeyDown={key}
              className="absolute left-[90px] top-[38px] h-[120px] w-[120px] rounded-full outline-none focus-visible:ring-2 focus-visible:ring-accent" />
      <div className="absolute inset-x-0 top-[196px] text-center">
        <div className="text-lg font-semibold text-ink">Sakura</div>
        <div className="mt-1 flex items-center justify-center gap-2 text-sm text-ink-dim" role="status">
          <span className={"h-2 w-2 rounded-full " + (visual === "offline" ? "bg-ink-dim" : "bg-online")} />
          {STATUS[visual]}
          {!mic && <span className="flex items-center gap-1 text-accent"><MicOff size={14} /> микрофон выкл.</span>}
        </div>
        {detail && <div className="mt-1 px-4 text-xs text-ink-dim">{detail}</div>}
      </div>
    </section>
  );
}

const item = "flex h-[35px] w-[260px] shrink-0 items-center gap-3 rounded-btn px-3 text-sm transition-colors ";
const tool = "flex h-[30px] w-full items-center gap-2 rounded-btn px-3 text-xs text-ink-dim transition-colors hover:bg-panel2 hover:text-ink disabled:opacity-40";

function BoardTools() {
  const editing = usePrefs((s) => s.editing);
  const locked = usePrefs((s) => s.locked);
  const layout = usePrefs((s) => s.layout);
  const p = usePrefs((s) => s);
  const hidden = hiddenWidgets(layout);
  return (
    <div className="mt-[15px] flex min-h-0 flex-col gap-1 overflow-y-auto border-t border-line pt-3 [@media(max-height:860px)]:mt-2 [@media(max-height:860px)]:pt-2" aria-label="Доска">
      <div className="flex gap-1">
        <button type="button" className={tool} aria-pressed={editing} disabled={locked}
                onClick={() => p.setEditing(!editing)}>
          <LayoutGrid size={14} /> {editing ? "Готово" : "Правка доски"}
        </button>
        <button type="button" className={tool + " w-auto"} aria-pressed={locked}
                aria-label={locked ? "Снять замок доски" : "Закрепить доску"} title={locked ? "Снять замок" : "Закрепить доску"}
                onClick={() => { p.set("locked", !locked); p.setEditing(false); }}>
          {locked ? <Lock size={14} /> : <Unlock size={14} />}
        </button>
      </div>
      {editing && (
        <>
          {hidden.map((id) => (
            <button key={id} type="button" className={tool} onClick={() => p.addWidget(id)}>
              <Plus size={14} /> {WIDGETS[id].title}
            </button>
          ))}
          <button type="button" className={tool} onClick={p.resetLayout}><RotateCcw size={14} /> Сбросить раскладку</button>
        </>
      )}
    </div>
  );
}

export function MenuCard({ section, onSection }: { section: Section; onSection(s: Section): void }) {
  const [version, setVersion] = useState(__APP_VERSION__);
  const server = useApp((s) => s.link === "open" && s.server.online);
  useEffect(() => {
    void bridge().version().then((v) => v !== "dev" && setVersion(v));
  }, []);

  return (
    // Низкое окно (до 860 px): поля и шаг меню меньше, чтобы инструменты доски не уходили под прокрутку.
    <nav aria-label="Меню" className="flex min-h-0 w-[300px] flex-1 flex-col rounded-card bg-panel px-gap py-edge [@media(max-height:860px)]:py-gap">
      <div className="flex flex-col gap-[15px] [@media(max-height:860px)]:gap-[6px]">
        {MENU.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" onClick={() => onSection(id)} aria-current={section === id ? "page" : undefined}
                  className={item + (section === id ? "bg-accent-grad text-white shadow-glow" : "text-ink-dim hover:bg-panel2 hover:text-ink")}>
            <Icon size={18} /> {label}
          </button>
        ))}
      </div>
      {section === "home" && <BoardTools />}
      <div className="mt-auto flex h-[20px] w-[260px] shrink-0 items-center gap-2 pt-1 text-xs text-ink-dim">
        Sakura v{version}
        <span className={"ml-auto h-2 w-2 rounded-full " + (server ? "bg-online" : "bg-ink-dim")}
              role="img" aria-label={server ? "Сервер на связи" : "Нет связи с сервером"} title={server ? "Сервер на связи" : "Нет связи с сервером"} />
      </div>
    </nav>
  );
}

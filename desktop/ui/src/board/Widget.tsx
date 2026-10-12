// Рамка виджета: заголовок — ручка перетаскивания; меню «⋮» и правый клик (Настройки, Дублировать,
// Закрепить, Свернуть до заголовка, В отдельное окно, Сбросить виджет, Убрать); в режиме правки — «×»
// и клавиатура: Alt+стрелки — сдвиг, Alt+Shift+стрелки — размер.
import { ChevronDown, ChevronUp, GripVertical, MoreVertical, Pin, X } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useState } from "react";

/** Классы для react-grid-layout: за что тянуть и что не начинает перетаскивание. */
export const DRAG_HANDLE = "widget-handle";
export const NO_DRAG = "widget-nodrag";

export interface WidgetActions {
  remove(): void;
  duplicate?(): void;
  toggleLock(): void;
  toggleCollapse(): void;
  popout?(): void;
  reset(): void;
  settings?(): void;
  nudge(dx: number, dy: number, resize: boolean): void;
}

interface Props {
  title: string;
  icon?: ReactNode;
  editing: boolean;
  /** Замок всей доски или закреплённый виджет — не тянется. */
  fixed: boolean;
  pinned: boolean;
  collapsed: boolean;
  bare?: boolean;
  actions: WidgetActions;
  children: ReactNode;
}

const ARROWS: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

function Menu({ title, pinned, collapsed, actions, onClose }: {
  title: string; pinned: boolean; collapsed: boolean; actions: WidgetActions; onClose(): void;
}) {
  const item = "w-full rounded-btn px-3 py-1.5 text-left text-xs text-ink hover:bg-panel disabled:opacity-40";
  const run = (fn?: () => void) => () => { fn?.(); onClose(); };
  return (
    <div role="menu" aria-label={`Меню виджета «${title}»`} onMouseLeave={onClose}
         className={NO_DRAG + " absolute right-2 top-10 z-30 w-52 rounded-btn border border-line bg-panel2 p-1 shadow-soft"}>
      <button type="button" role="menuitem" className={item} disabled={!actions.settings} onClick={run(actions.settings)}>Настройки</button>
      <button type="button" role="menuitem" className={item} disabled={!actions.duplicate} onClick={run(actions.duplicate)}>Дублировать</button>
      <button type="button" role="menuitem" className={item} onClick={run(actions.toggleLock)}>{pinned ? "Открепить" : "Закрепить"}</button>
      <button type="button" role="menuitem" className={item} onClick={run(actions.toggleCollapse)}>
        {collapsed ? "Развернуть" : "Свернуть до заголовка"}</button>
      <button type="button" role="menuitem" className={item} disabled={!actions.popout} onClick={run(actions.popout)}>В отдельное окно</button>
      <button type="button" role="menuitem" className={item} onClick={run(actions.reset)}>Сбросить виджет</button>
      <button type="button" role="menuitem" className={item + " text-accent"} onClick={run(actions.remove)}>Убрать</button>
    </div>
  );
}

export function Widget({ title, icon, editing, fixed, pinned, collapsed, bare, actions, children }: Props) {
  const [menu, setMenu] = useState(false);
  const handle = fixed ? "" : DRAG_HANDLE + " cursor-grab active:cursor-grabbing ";
  const onKey = (e: KeyboardEvent) => {
    const d = ARROWS[e.key];
    if (!editing || !e.altKey || !d) return;
    e.preventDefault();
    actions.nudge(d[0], d[1], e.shiftKey);
  };
  const remove = (
    <button type="button" onClick={actions.remove} aria-label={`Убрать виджет «${title}»`} title="Убрать с доски"
            className={NO_DRAG + " grid h-7 w-7 shrink-0 place-items-center rounded-btn text-ink-dim hover:bg-panel2 hover:text-accent"}>
      <X size={16} />
    </button>
  );
  const menuBtn = (
    <button type="button" onClick={() => setMenu(!menu)} aria-label={`Меню виджета «${title}»`} aria-haspopup="menu"
            className={NO_DRAG + " grid h-7 w-7 shrink-0 place-items-center rounded-btn text-ink-dim hover:bg-panel2 hover:text-ink"}>
      <MoreVertical size={15} />
    </button>
  );
  const ring = editing ? "ring-1 ring-accent/50 " : "";
  const common = {
    "aria-label": title,
    tabIndex: editing ? 0 : -1,
    onKeyDown: onKey,
    onContextMenu: (e: React.MouseEvent) => { e.preventDefault(); setMenu(true); },
  };

  if (bare && !collapsed) {
    return (
      <section {...common} className={"relative flex h-full overflow-hidden rounded-card bg-panel outline-none focus-visible:ring-2 focus-visible:ring-accent " + ring}>
        {!fixed && (
          <div className={handle + "grid w-5 shrink-0 place-items-center text-ink-dim/60 hover:text-ink"} title="Перетащить">
            <GripVertical size={14} />
          </div>
        )}
        <div className="min-w-0 flex-1">{children}</div>
        {editing && <div className="flex flex-col gap-1 p-1">{remove}{menuBtn}</div>}
        {menu && <Menu title={title} pinned={pinned} collapsed={collapsed} actions={actions} onClose={() => setMenu(false)} />}
      </section>
    );
  }
  return (
    <section {...common} className={"relative flex h-full flex-col overflow-hidden rounded-card bg-panel outline-none focus-visible:ring-2 focus-visible:ring-accent " + ring}>
      <header className={handle + "flex h-11 shrink-0 select-none items-center gap-2 px-4"} onDoubleClick={actions.toggleCollapse}>
        {icon && <span className="text-accent">{icon}</span>}
        <h2 className="min-w-0 truncate text-sm font-semibold text-ink">{title}</h2>
        {pinned && <Pin size={12} className="shrink-0 text-ink-dim" aria-label="закреплён" />}
        <div className={NO_DRAG + " ml-auto flex items-center gap-1"}>
          <button type="button" onClick={actions.toggleCollapse} aria-label={collapsed ? "Развернуть" : "Свернуть"}
                  className="grid h-7 w-7 place-items-center rounded-btn text-ink-dim hover:bg-panel2 hover:text-ink">
            {collapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
          </button>
          {menuBtn}
          {editing && remove}
        </div>
      </header>
      {/* Содержимое не обрезается: прокрутка внутри виджета. */}
      {!collapsed && <div className="flex min-h-0 flex-1 flex-col overflow-auto">{children}</div>}
      {menu && <Menu title={title} pinned={pinned} collapsed={collapsed} actions={actions} onClose={() => setMenu(false)} />}
    </section>
  );
}

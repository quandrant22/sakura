// Рамка виджета доски: заголовок — ручка перетаскивания; в режиме правки — кнопка «убрать».
import { GripVertical, X } from "lucide-react";
import type { ReactNode } from "react";

/** Классы для react-grid-layout: за что тянуть и что не начинает перетаскивание. */
export const DRAG_HANDLE = "widget-handle";
export const NO_DRAG = "widget-nodrag";

interface Props {
  title: string;
  icon?: ReactNode;
  action?: ReactNode;
  editing: boolean;
  locked: boolean;
  onRemove(): void;
  /** Без заголовка (музыка 100 px): ручка — узкая полоса слева. */
  bare?: boolean;
  children: ReactNode;
}

function RemoveButton({ title, onRemove }: { title: string; onRemove(): void }) {
  return (
    <button type="button" onClick={onRemove} aria-label={`Убрать виджет «${title}»`} title="Убрать с доски"
            className={NO_DRAG + " grid h-7 w-7 shrink-0 place-items-center rounded-btn text-ink-dim hover:bg-panel2 hover:text-accent"}>
      <X size={16} />
    </button>
  );
}

export function Widget({ title, icon, action, editing, locked, onRemove, bare, children }: Props) {
  const handle = (locked ? "" : DRAG_HANDLE + " cursor-grab active:cursor-grabbing ");
  if (bare) {
    return (
      <section aria-label={title} className={"flex h-full overflow-hidden rounded-card bg-panel " + (editing ? "ring-1 ring-accent/50" : "")}>
        {!locked && (
          <div className={handle + "grid w-5 shrink-0 place-items-center text-ink-dim/60 hover:text-ink"} title="Перетащить">
            <GripVertical size={14} />
          </div>
        )}
        <div className="min-w-0 flex-1">{children}</div>
        {editing && <div className="p-1"><RemoveButton title={title} onRemove={onRemove} /></div>}
      </section>
    );
  }
  return (
    <section aria-label={title} className={"flex h-full flex-col overflow-hidden rounded-card bg-panel " + (editing ? "ring-1 ring-accent/50" : "")}>
      <header className={handle + "flex h-11 shrink-0 select-none items-center gap-2 px-4"}>
        {icon && <span className="text-accent">{icon}</span>}
        <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
        <div className={NO_DRAG + " ml-auto flex items-center gap-1"}>
          {action}
          {editing && <RemoveButton title={title} onRemove={onRemove} />}
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </section>
  );
}

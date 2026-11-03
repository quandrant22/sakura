// Галерея виджетов («+ Виджет»): панель справа — поиск, фильтры, карточки с описанием и предпросмотром
// размера, кнопки S/M/L; клик — добавить в первую свободную позицию, перетаскивание — на нужное место.
import { Search, X } from "lucide-react";
import { useState } from "react";

import { canAdd, CATALOG, type Category, type Size, WIDGET_TYPES, type WidgetType } from "../layout/boardModel";
import { usePrefs } from "../layout/prefs";
import { VIEWS } from "./registry";

export const GALLERY_MIME = "application/x-sakura-widget";
const FILTERS: Record<Category | "all", string> = { all: "Все", media: "Медиа", system: "Система", assistant: "Ассистент" };

/** Схема размера: прямоугольник w×h в масштабе 24 колонок. */
function Preview({ w, h }: { w: number; h: number }) {
  return (
    <div className="flex h-10 w-16 items-end rounded bg-panel p-1" aria-hidden="true">
      <div className="rounded-sm bg-accent-grad opacity-80" style={{ width: `${(w / 24) * 100}%`, height: `${Math.min(100, (h / 31) * 100)}%` }} />
    </div>
  );
}

export function Gallery({ onClose, onAdd, onDragType }: {
  onClose(): void; onAdd(type: WidgetType, size: Size): void; onDragType(v: { type: WidgetType; size: Size } | null): void;
}) {
  const board = usePrefs((s) => s.board);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Category | "all">("all");
  const list = WIDGET_TYPES.filter((t) => {
    const m = CATALOG[t];
    const text = `${m.title} ${m.description}`.toLowerCase();
    return (filter === "all" || m.category === filter) && (!q.trim() || text.includes(q.trim().toLowerCase()));
  });

  return (
    <aside aria-label="Галерея виджетов"
           className="absolute inset-y-0 right-0 z-30 flex w-[300px] flex-col rounded-card border border-line bg-panel2 shadow-soft">
      <header className="flex items-center gap-2 px-4 pb-2 pt-3">
        <h2 className="text-sm font-semibold text-ink">Виджеты</h2>
        <button type="button" onClick={onClose} aria-label="Закрыть галерею" className="ml-auto text-ink-dim hover:text-ink"><X size={16} /></button>
      </header>
      <label className="mx-4 flex items-center gap-2 rounded-btn border border-line bg-panel px-2.5 py-1.5">
        <Search size={14} className="text-ink-dim" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск" aria-label="Поиск виджета"
               className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-dim" />
      </label>
      <div className="flex flex-wrap gap-1 px-4 py-2" role="radiogroup" aria-label="Фильтр">
        {(Object.keys(FILTERS) as (Category | "all")[]).map((f) => (
          <button key={f} type="button" role="radio" aria-checked={filter === f} onClick={() => setFilter(f)}
                  className={"rounded-full px-2.5 py-1 text-xs " + (filter === f ? "bg-accent-grad text-white" : "text-ink-dim hover:text-ink")}>
            {FILTERS[f]}</button>
        ))}
      </div>
      <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-4 pb-4">
        {list.map((t) => {
          const m = CATALOG[t];
          const allowed = canAdd(board, t);
          return (
            <li key={t} draggable={allowed} aria-label={m.title}
                onDragStart={(e) => {
                  e.dataTransfer.setData(GALLERY_MIME, JSON.stringify({ type: t, size: "M" }));
                  e.dataTransfer.setData("text/plain", "");
                  onDragType({ type: t, size: "M" });
                }}
                onDragEnd={() => onDragType(null)}
                className={"rounded-btn border border-line bg-panel p-3 " + (allowed ? "cursor-grab" : "opacity-60")}>
              <div className="flex items-center gap-2">
                <span className="text-accent">{VIEWS[t].icon}</span>
                <span className="text-sm font-medium text-ink">{m.title}</span>
                <Preview {...m.sizes.M} />
              </div>
              <p className="mt-1 text-xs text-ink-dim">{m.description}{m.singleton ? " · один на страницу" : ""}</p>
              <div className="mt-2 flex items-center gap-1">
                {allowed ? (["S", "M", "L"] as Size[]).map((s) => (
                  <button key={s} type="button" onClick={() => onAdd(t, s)} aria-label={`Добавить «${m.title}» ${s}`}
                          className="rounded-btn border border-line px-2 py-0.5 text-xs text-ink-dim hover:border-accent hover:text-ink">{s}</button>
                )) : <span className="text-xs text-ink-dim">уже на странице</span>}
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

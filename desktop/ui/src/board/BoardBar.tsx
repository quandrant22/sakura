// Страницы доски и инструменты — в центре верхней панели (над доской, геометрия наброска не меняется).
// Вкладки: щелчок — открыть, двойной — переименовать, перетаскивание — переставить, «×» — удалить
// (с подтверждением), «+» — новая страница из пресета. Справа: «+ Виджет», «Правка», замок, меню доски.
import { LayoutGrid, Lock, MoreHorizontal, Plus, Unlock, X } from "lucide-react";
import { useState } from "react";

import { bridge } from "../bridge";
import {
  addPage, deletePage, movePage, PRESETS, renamePage, resetPage, setActivePage, validateBoard,
} from "../layout/boardModel";
import { usePrefs } from "../layout/prefs";

const tool = "no-drag flex h-8 items-center gap-1.5 rounded-btn px-2.5 text-xs text-ink-dim transition-colors hover:bg-panel2 hover:text-ink";

function BoardMenu({ onClose }: { onClose(): void }) {
  const mode = usePrefs((s) => s.boardMode);
  const auto = usePrefs((s) => s.autoGamePage);
  const board = usePrefs((s) => s.board);
  const set = usePrefs((s) => s.set);
  const update = usePrefs((s) => s.updateBoard);
  const [msg, setMsg] = useState<string | null>(null);
  const item = "w-full rounded-btn px-3 py-1.5 text-left text-xs text-ink hover:bg-panel";
  const doImport = async () => {
    const text = await bridge().layout.importFile();
    if (!text) return;
    try {
      update(() => validateBoard(JSON.parse(text)));
      setMsg("Раскладка загружена");
    } catch {
      setMsg("Файл не похож на раскладку Сакуры");
    }
  };
  return (
    <div role="menu" aria-label="Меню доски" onMouseLeave={onClose}
         className="no-drag absolute right-0 top-10 z-50 w-64 rounded-btn border border-line bg-panel2 p-1 shadow-soft">
      <button type="button" role="menuitem" className={item} onClick={() => { update((b) => resetPage(b)); onClose(); }}>
        Сбросить раскладку страницы</button>
      <button type="button" role="menuitemcheckbox" aria-checked={mode === "pack"} className={item}
              onClick={() => set("boardMode", mode === "pack" ? "free" : "pack")}>
        Режим: {mode === "pack" ? "авто-упаковка" : "свободно"}</button>
      <button type="button" role="menuitemcheckbox" aria-checked={auto} className={item}
              onClick={() => set("autoGamePage", !auto)}>
        {auto ? "✓ " : ""}Запущена игра → страница «Игры»</button>
      <button type="button" role="menuitem" className={item}
              onClick={() => void bridge().layout.exportFile(JSON.stringify(board, null, 1)).then((ok) => setMsg(ok ? "Сохранено" : null))}>
        Экспорт раскладки…</button>
      <button type="button" role="menuitem" className={item} onClick={() => void doImport()}>Импорт раскладки…</button>
      {msg && <div role="status" className="px-3 py-1 text-[11px] text-ink-dim">{msg}</div>}
    </div>
  );
}

export function BoardBar({ galleryOpen, onGallery }: { galleryOpen: boolean; onGallery(): void }) {
  const board = usePrefs((s) => s.board);
  const editing = usePrefs((s) => s.editing);
  const locked = usePrefs((s) => s.locked);
  const set = usePrefs((s) => s.set);
  const setEditing = usePrefs((s) => s.setEditing);
  const update = usePrefs((s) => s.updateBoard);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [menu, setMenu] = useState(false);
  const [dragFrom, setDragFrom] = useState<number | null>(null);

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2">
      <nav aria-label="Страницы доски" className="no-drag flex min-w-0 items-center gap-1 overflow-x-auto">
        {board.pages.map((p, i) => {
          const active = p.id === board.active_page;
          return (
            <div key={p.id} draggable onDragStart={() => setDragFrom(i)} onDragOver={(e) => e.preventDefault()}
                 onDrop={() => { if (dragFrom != null) update((b) => movePage(b, dragFrom, i)); setDragFrom(null); }}
                 className={"group flex h-8 shrink-0 items-center rounded-btn " + (active ? "bg-panel2" : "hover:bg-panel2/60")}>
              {renaming === p.id ? (
                <input autoFocus defaultValue={p.name} aria-label="Название страницы"
                       onBlur={(e) => { update((b) => renamePage(b, p.id, e.target.value)); setRenaming(null); }}
                       onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setRenaming(null); }}
                       className="h-7 w-28 rounded bg-panel px-2 text-xs text-ink outline-none" />
              ) : (
                <button type="button" aria-current={active ? "page" : undefined} title={`Ctrl+${i + 1}; двойной щелчок — переименовать`}
                        onClick={() => update((b) => setActivePage(b, p.id))} onDoubleClick={() => setRenaming(p.id)}
                        className={"px-3 text-xs " + (active ? "font-semibold text-ink" : "text-ink-dim")}>{p.name}</button>
              )}
              {board.pages.length > 1 && (
                <button type="button" aria-label={`Удалить страницу «${p.name}»`}
                        onClick={() => { if (window.confirm(`Удалить страницу «${p.name}» со всеми виджетами?`)) update((b) => deletePage(b, p.id)); }}
                        className="mr-1 hidden h-5 w-5 place-items-center rounded text-ink-dim hover:text-accent group-hover:grid">
                  <X size={12} /></button>
              )}
            </div>
          );
        })}
        <div className="relative">
          <button type="button" className={tool} aria-label="Новая страница" onClick={() => setAdding(!adding)}><Plus size={14} /></button>
          {adding && (
            <div role="menu" aria-label="Новая страница из пресета" onMouseLeave={() => setAdding(false)}
                 className="absolute left-0 top-9 z-50 w-40 rounded-btn border border-line bg-panel2 p-1 shadow-soft">
              {Object.entries(PRESETS).map(([key, name]) => (
                <button key={key} type="button" role="menuitem"
                        className="w-full rounded-btn px-3 py-1.5 text-left text-xs text-ink hover:bg-panel"
                        onClick={() => { update((b) => addPage(b, name, key)); setAdding(false); }}>{name}</button>
              ))}
            </div>
          )}
        </div>
      </nav>
      <div className="h-full flex-1" />
      <button type="button" className={tool} aria-pressed={galleryOpen} onClick={onGallery}><Plus size={14} /> Виджет</button>
      <button type="button" className={tool} aria-pressed={editing} disabled={locked} onClick={() => setEditing(!editing)}>
        <LayoutGrid size={14} /> {editing ? "Готово" : "Правка"}</button>
      <button type="button" className={tool} aria-pressed={locked} aria-label={locked ? "Снять замок доски" : "Закрепить доску"}
              title={locked ? "Снять замок" : "Закрепить доску"} onClick={() => { set("locked", !locked); setEditing(false); }}>
        {locked ? <Lock size={14} /> : <Unlock size={14} />}</button>
      <div className="relative">
        <button type="button" className={tool} aria-label="Меню доски" onClick={() => setMenu(!menu)}><MoreHorizontal size={15} /></button>
        {menu && <BoardMenu onClose={() => setMenu(false)} />}
      </div>
    </div>
  );
}

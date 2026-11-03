// Доска виджетов (экран «Главная»): страница из layout.json v2, точки адаптивности lg/md/sm
// (24/12/1 колонка) по ширине доски — без CSS-масштабирования. Перетаскивание за заголовок,
// ручки размера по краям и углам, «авто-упаковка» или «свободно», галерея «+ Виджет» (клик или
// перетаскивание на доску), отмена удаления 10 с.
import "react-grid-layout/css/styles.css";

import { useCallback, useEffect, useMemo, useState } from "react";
import GridLayout, { getCompactor, type Layout, type LayoutItem, useContainerWidth } from "react-grid-layout";
import { absoluteStrategy } from "react-grid-layout/core";

import { bridge } from "../bridge";
import {
  addWidgetTo, type Breakpoint, breakpointFor, CATALOG, COLS, duplicateWidget, getPage, MARGIN, minFor,
  nudgeWidget, patchWidget, removeWidgetFrom, type Removed, resetWidget, restoreWidget, ROW_HEIGHT, setLayout,
  type Size, type WidgetItem, type WidgetType,
} from "../layout/boardModel";
import { usePrefs } from "../layout/prefs";
import { Gallery, GALLERY_MIME } from "./Gallery";
import { interactionStore } from "./interaction";
import { VIEWS } from "./registry";
import { DRAG_HANDLE, NO_DRAG, Widget } from "./Widget";

const packCompactor = getCompactor("vertical", false, false);      // без перекрытий, подтягивает вверх
const freeCompactor = getCompactor(null, false, true);             // свободно: в занятое место не встаёт
const HANDLES = ["s", "e", "w", "n", "se", "sw", "ne", "nw"] as const;
const UNDO_MS = 10_000;
const HIGHLIGHT_MS = 1600;

export function WidgetBoard({ galleryOpen, onCloseGallery }: { galleryOpen: boolean; onCloseGallery(): void }) {
  const board = usePrefs((s) => s.board);
  const editing = usePrefs((s) => s.editing);
  const locked = usePrefs((s) => s.locked);
  const mode = usePrefs((s) => s.boardMode);
  const update = usePrefs((s) => s.updateBoard);
  const { width: measured, containerRef, mounted } = useContainerWidth({ initialWidth: 690 });
  const width = measured > 0 ? measured : 690;
  const bp: Breakpoint = breakpointFor(width);
  const page = getPage(board);
  const items = page.breakpoints[bp];
  const [undo, setUndo] = useState<{ removed: Removed; title: string } | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const [drop, setDrop] = useState<{ type: WidgetType; size: Size } | null>(null);

  useEffect(() => {
    if (!undo) return;
    const t = setTimeout(() => setUndo(null), UNDO_MS);
    return () => clearTimeout(t);
  }, [undo]);
  useEffect(() => {
    if (!fresh) return;
    const t = setTimeout(() => setFresh(null), HIGHLIGHT_MS);
    return () => clearTimeout(t);
  }, [fresh]);

  const gridLayout = useMemo<Layout>(() => items.map((it) => {
    const min = minFor(it.type, bp);
    const max = CATALOG[it.type].max;
    return { i: it.id, x: it.x, y: it.y, w: it.w, h: it.h, minW: min.w, minH: it.collapsed ? it.h : min.h,
             maxH: it.collapsed ? it.h : undefined, maxW: bp === "lg" ? max?.w : undefined, static: locked || !!it.locked };
  }), [items, bp, locked]);

  const onLayoutChange = (next: Layout) => {
    const changed = next.some((n) => {
      const it = items.find((x) => x.id === n.i);
      return it && (it.x !== n.x || it.y !== n.y || it.w !== n.w || it.h !== n.h);
    });
    if (changed) update((b) => setLayout(b, bp, next.map((n) => ({ id: n.i, x: n.x, y: n.y, w: n.w, h: n.h }))));
  };

  const add = useCallback((type: WidgetType, size: Size, at?: { x: number; y: number }) => {
    let id: string | null = null;
    update((b) => {
      const r = addWidgetTo(b, type, size, at ? { bp, ...at } : undefined);
      id = r.id;
      return r.board;
    });
    if (id) setFresh(id);
  }, [update, bp]);

  const remove = (it: WidgetItem) => {
    let removed: Removed | null = null;
    update((b) => {
      const r = removeWidgetFrom(b, it.id);
      removed = r.removed;
      return r.board;
    });
    if (removed) setUndo({ removed, title: CATALOG[it.type].title });
  };

  const interacting = (on: boolean) => () => interactionStore.getState().set(on);
  const dropSize = drop ? { w: Math.min(COLS[bp], CATALOG[drop.type].sizes[drop.size].w), h: CATALOG[drop.type].sizes[drop.size].h } : undefined;

  return (
    <div className="relative h-full min-w-0">
      <div ref={containerRef} className="h-full min-w-0 overflow-y-auto overflow-x-hidden" aria-label="Доска виджетов"
           data-breakpoint={bp}
           onDragOver={(e) => { if (e.dataTransfer.types.includes(GALLERY_MIME)) e.preventDefault(); }}>
        {items.length === 0 && (
          <div className="grid h-full place-items-center text-sm text-ink-dim">
            На странице «{page.name}» пока нет виджетов — «+ Виджет» в верхней панели
          </div>
        )}
        {mounted && (
          <GridLayout
            width={width}
            layout={gridLayout}
            gridConfig={{ cols: COLS[bp], rowHeight: ROW_HEIGHT, margin: MARGIN, containerPadding: [0, 0] }}
            dragConfig={{ enabled: !locked, handle: "." + DRAG_HANDLE, cancel: "." + NO_DRAG }}
            resizeConfig={{ enabled: !locked, handles: HANDLES }}
            dropConfig={{ enabled: !!drop, defaultItem: dropSize ?? { w: 6, h: 6 } }}
            compactor={mode === "free" ? freeCompactor : packCompactor}
            positionStrategy={absoluteStrategy}
            // Высота сетки у react-grid-layout включает отступ под последним рядом (+20 px) — без
            // компенсации раскладка наброска (890 px) давала полосу прокрутки и сужала доску.
            style={{ marginBottom: -MARGIN[1] }}
            onLayoutChange={onLayoutChange}
            onDragStart={interacting(true)} onDragStop={interacting(false)}
            onResizeStart={interacting(true)} onResizeStop={interacting(false)}
            onDrop={(_l: Layout, item: LayoutItem | undefined) => {
              if (drop && item) add(drop.type, drop.size, { x: item.x, y: item.y });
              setDrop(null);
            }}
          >
            {items.map((it) => {
              const meta = CATALOG[it.type];
              const view = VIEWS[it.type];
              return (
                <div key={it.id} className={fresh === it.id ? "rounded-card ring-2 ring-accent transition-shadow" : undefined}>
                  <Widget title={meta.title} icon={view.icon} bare={view.bare} editing={editing}
                          fixed={locked || !!it.locked} pinned={!!it.locked} collapsed={!!it.collapsed}
                          actions={{
                            remove: () => remove(it),
                            duplicate: meta.singleton ? undefined : () => {
                              let id: string | null = null;
                              update((b) => { const r = duplicateWidget(b, it.id); id = r.id; return r.board; });
                              if (id) setFresh(id);
                            },
                            toggleLock: () => update((b) => patchWidget(b, it.id, { locked: !it.locked })),
                            toggleCollapse: () => update((b) => patchWidget(b, it.id, { collapsed: !it.collapsed })),
                            popout: () => void bridge().widgets.popout(it.type, it.id),
                            reset: () => update((b) => resetWidget(b, it.id)),
                            nudge: (dx, dy, resize) => update((b) => nudgeWidget(b, it.id, bp, dx, dy, resize)),
                          }}>
                    <view.Component item={it}
                                    setSettings={(patch) => update((b) => patchWidget(b, it.id, { settings: { ...it.settings, ...patch } }))} />
                  </Widget>
                </div>
              );
            })}
          </GridLayout>
        )}
      </div>

      {galleryOpen && (
        <Gallery onClose={onCloseGallery} onAdd={(t, s) => add(t, s)} onDragType={setDrop} />
      )}

      {undo && (
        <div role="status" className="absolute bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-card border border-line bg-panel2 px-4 py-2 text-sm text-ink shadow-soft">
          Виджет «{undo.title}» убран
          <button type="button" className="font-medium text-accent hover:underline"
                  onClick={() => { update((b) => restoreWidget(b, undo.removed)); setUndo(null); }}>Отменить</button>
        </div>
      )}
    </div>
  );
}

// Доска виджетов (экран «Главная»): react-grid-layout, 24 колонки, отступ 20, без схлопывания.
import "react-grid-layout/css/styles.css";

import { AppWindow, Cpu, Film } from "lucide-react";
import { type ReactNode, useMemo } from "react";
import GridLayout, { getCompactor, type Layout, useContainerWidth } from "react-grid-layout";
import { createScaledStrategy } from "react-grid-layout/core";

import { boardScale, GRID, type LayoutItem, layoutHeight, sanitizeLayout, type WidgetId, WIDGETS } from "../layout/board";
import { usePrefs } from "../layout/prefs";
import { DRAG_HANDLE, NO_DRAG, Widget } from "./Widget";
import { AppWindowWidget } from "./widgets/AppWindowWidget";
import { MusicWidget } from "./widgets/MusicWidget";
import { SystemWidget } from "./widgets/SystemWidget";
import { VideoWidget } from "./widgets/VideoWidget";

// Без схлопывания вверх и без наложения: мешающий виджет сдвигается.
const compactor = getCompactor(null, false, false);

const CONTENT: Record<WidgetId, { icon?: ReactNode; bare?: boolean; render(): ReactNode }> = {
  system: { icon: <Cpu size={16} />, render: () => <SystemWidget /> },
  video: { icon: <Film size={16} />, render: () => <VideoWidget /> },
  app: { icon: <AppWindow size={16} />, render: () => <AppWindowWidget /> },
  music: { bare: true, render: () => <MusicWidget /> },
};

const same = (a: LayoutItem[], b: LayoutItem[]) =>
  a.length === b.length && a.every((x, i) => {
    const y = b[i];
    return y && x.i === y.i && x.x === y.x && x.y === y.y && x.w === y.w && x.h === y.h;
  });

export function WidgetBoard() {
  const layout = usePrefs((s) => s.layout);
  const editing = usePrefs((s) => s.editing);
  const locked = usePrefs((s) => s.locked);
  const setPref = usePrefs((s) => s.set);
  const remove = usePrefs((s) => s.removeWidget);
  const { width: measured, containerRef, mounted } = useContainerWidth({ initialWidth: GRID.designWidth });
  // До первого замера (и в jsdom, где ширина 0) — ширина кадра наброска.
  const width = measured > 0 ? measured : GRID.designWidth;

  // Уже кадра наброска доска рисуется в 690 px и уменьшается целиком (см. DECISIONS.md).
  const scale = boardScale(width);
  const gridWidth = scale < 1 ? GRID.designWidth : width;
  const strategy = useMemo(() => (scale < 1 ? createScaledStrategy(scale) : undefined), [scale]);
  const gridLayout = useMemo<Layout>(
    () => layout.map((it) => ({ ...it, minW: WIDGETS[it.i].minW, minH: WIDGETS[it.i].minH })),
    [layout],
  );

  const onLayoutChange = (next: Layout) => {
    const clean = sanitizeLayout(next.map(({ i, x, y, w, h }) => ({ i, x, y, w, h })));
    if (clean && !same(clean, layout)) setPref("layout", clean);
  };

  return (
    <div ref={containerRef} className="h-full min-w-0 overflow-y-auto overflow-x-hidden" aria-label="Доска виджетов">
      {layout.length === 0 && (
        <div className="grid h-full place-items-center text-sm text-ink-dim">
          Доска пуста — «Правка доски» в меню, чтобы добавить виджеты
        </div>
      )}
      {mounted && (
        // transform не уменьшает место в потоке — внешний блок задаёт уменьшенную высоту, чтобы не было лишней прокрутки.
        <div style={scale < 1 ? { height: layoutHeight(layout) * scale, overflow: "hidden" } : undefined}>
        <div style={scale < 1 ? { width: gridWidth, transform: `scale(${scale})`, transformOrigin: "0 0" } : undefined}>
          <GridLayout
            width={gridWidth}
            layout={gridLayout}
            gridConfig={{ cols: GRID.cols, rowHeight: GRID.rowHeight, margin: GRID.margin, containerPadding: [0, 0] }}
            dragConfig={{ enabled: !locked, handle: "." + DRAG_HANDLE, cancel: "." + NO_DRAG }}
            resizeConfig={{ enabled: !locked }}
            compactor={compactor}
            positionStrategy={strategy}
            onLayoutChange={onLayoutChange}
          >
            {layout.map((it) => {
              const c = CONTENT[it.i];
              return (
                <div key={it.i}>
                  <Widget title={WIDGETS[it.i].title} icon={c.icon} bare={c.bare} editing={editing} locked={locked}
                          onRemove={() => remove(it.i)}>
                    {c.render()}
                  </Widget>
                </div>
              );
            })}
          </GridLayout>
        </div>
        </div>
      )}
    </div>
  );
}

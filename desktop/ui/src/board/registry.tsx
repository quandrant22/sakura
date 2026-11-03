// Тип виджета → иконка и отрисовка. Метаданные (название, размеры, singleton) — boardModel.CATALOG.
import {
  AppWindow, Bell, CalendarDays, Cpu, Film, Music2, NotebookPen, Server, Timer, Workflow, Zap,
} from "lucide-react";
import type { ComponentType, ReactNode } from "react";

import type { WidgetType } from "../layout/boardModel";
import { AppWindowWidget } from "./widgets/AppWindowWidget";
import { MusicWidget } from "./widgets/MusicWidget";
import {
  FocusTimerWidget, NotesWidget, NotificationsWidget, QuickActionsWidget, ScenariosWidget, ServerWidget, TodayWidget,
  type WidgetProps,
} from "./widgets/SmallWidgets";
import { SystemWidget } from "./widgets/SystemWidget";
import { VideoWidget } from "./widgets/VideoWidget";

export interface WidgetView {
  icon: ReactNode;
  /** Без заголовка: музыка — панель 100 px, ручка — полоса слева. */
  bare?: boolean;
  Component: ComponentType<WidgetProps>;
}

export const VIEWS: Record<WidgetType, WidgetView> = {
  music: { icon: <Music2 size={16} />, bare: true, Component: MusicWidget },
  video: { icon: <Film size={16} />, Component: VideoWidget },
  window: { icon: <AppWindow size={16} />, Component: AppWindowWidget },
  system: { icon: <Cpu size={16} />, Component: SystemWidget },
  scenarios: { icon: <Workflow size={16} />, Component: ScenariosWidget },
  today: { icon: <CalendarDays size={16} />, Component: TodayWidget },
  server: { icon: <Server size={16} />, Component: ServerWidget },
  notes: { icon: <NotebookPen size={16} />, Component: NotesWidget },
  notifications: { icon: <Bell size={16} />, Component: NotificationsWidget },
  "focus-timer": { icon: <Timer size={16} />, Component: FocusTimerWidget },
  "quick-actions": { icon: <Zap size={16} />, Component: QuickActionsWidget },
};

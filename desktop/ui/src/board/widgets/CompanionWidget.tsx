import { Bot, Eraser, Eye, Film, Gamepad2, HeartPulse, PhoneCall, Sparkles } from "lucide-react";
import { useState } from "react";

import type { WidgetProps } from "./SmallWidgets";
import { useApp } from "../../store";

const body = "flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 pb-4 text-xs";
const card = "flex flex-col gap-2 rounded-btn bg-panel2 p-3 border border-line";
const chip = "flex items-center gap-1.5 rounded-btn border border-line px-2 py-1 text-xs text-ink-dim hover:border-accent hover:text-ink";
const activeChip = "flex items-center gap-1.5 rounded-btn border border-accent bg-accent/10 px-2 py-1 text-xs text-accent";

export function CompanionWidget({}: WidgetProps) {
  const quick = useApp((s) => s.quickAction);
  const [callActive, setCallActive] = useState(false);
  const [watchActive, setWatchActive] = useState(false);

  const handleToggleCall = async () => {
    await quick("toggle_call_mode");
    setCallActive((prev) => !prev);
  };

  const handleToggleWatch = async () => {
    await quick("toggle_watch_along");
    setWatchActive((prev) => !prev);
  };

  return (
    <div className={body}>
      {/* Husk Mode & Coding Bridge */}
      <div className={card}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 font-semibold text-ink">
            <Bot size={14} className="text-accent" />
            <span>Husk Mode (AI Агент)</span>
          </div>
          <span className="inline-flex items-center gap-1 rounded-full bg-online/10 px-2 py-0.5 text-[10px] text-online">
            <span className="h-1.5 w-1.5 rounded-full bg-online animate-pulse" />
            127.0.0.1:19482
          </span>
        </div>
        <p className="text-[11px] text-ink-dim">
          Сакура озвучивает шаги Claude Code / Codex и зовёт на подтверждения.
        </p>
      </div>

      {/* Gaming & Media Actions */}
      <div className={card}>
        <div className="flex items-center gap-1.5 font-semibold text-ink">
          <Gamepad2 size={14} className="text-accent" />
          <span>GameSense & Откат</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={chip} onClick={() => void quick("clip_that")}>
            <Film size={12} className="text-accent" />
            <span>Заклипать 30с</span>
          </button>
          <button type="button" className={chip} onClick={() => void quick("clear_ink")}>
            <Eraser size={12} />
            <span>Стереть чернила</span>
          </button>
          <button
            type="button"
            className={callActive ? activeChip : chip}
            onClick={() => void handleToggleCall()}
          >
            <PhoneCall size={12} />
            <span>{callActive ? "В звонке (Discord)" : "Режим звонка"}</span>
          </button>
          <button
            type="button"
            className={watchActive ? activeChip : chip}
            onClick={() => void handleToggleWatch()}
          >
            <Eye size={12} />
            <span>{watchActive ? "Смотрим вместе" : "Посмотри со мной"}</span>
          </button>
        </div>
      </div>

      {/* Care & Health Monitor */}
      <div className={card}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 font-semibold text-ink">
            <HeartPulse size={14} className="text-accent" />
            <span>Забота о здоровье (Care)</span>
          </div>
          <Sparkles size={13} className="text-accent" />
        </div>
        <div className="grid grid-cols-2 gap-2 text-[11px] text-ink-dim">
          <div className="flex items-center gap-1.5 rounded bg-panel px-2 py-1">
            <span>💧 Вода:</span>
            <span className="font-medium text-ink">В норме</span>
          </div>
          <div className="flex items-center gap-1.5 rounded bg-panel px-2 py-1">
            <span>🧘 Разминка:</span>
            <span className="font-medium text-ink">~45 мин</span>
          </div>
          <div className="flex items-center gap-1.5 rounded bg-panel px-2 py-1">
            <span>👀 Глаза (20/20):</span>
            <span className="font-medium text-ink">Активно</span>
          </div>
          <div className="flex items-center gap-1.5 rounded bg-panel px-2 py-1">
            <span>🌙 Режим сна:</span>
            <span className="font-medium text-ink">до 01:00</span>
          </div>
        </div>
      </div>
    </div>
  );
}

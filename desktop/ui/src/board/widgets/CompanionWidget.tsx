import {
  Activity,
  Bot,
  Eraser,
  Eye,
  Film,
  Headphones,
  HeartPulse,
  PhoneCall,
  Sliders,
  Sparkles,
  Volume2,
} from "lucide-react";
import { useEffect, useState } from "react";

import type { WidgetProps } from "./SmallWidgets";
import { useMediaClient } from "../../media/MediaContext";
import { useApp } from "../../store";

export function CompanionWidget({}: WidgetProps) {
  const client = useMediaClient();
  const quick = useApp((s) => s.quickAction);
  const s = useApp((s) => s.settings);

  const [callActive, setCallActive] = useState(false);
  const [watchActive, setWatchActive] = useState(false);
  const [callerName, setCallerName] = useState("");
  const [loading, setLoading] = useState(false);

  // Initial fetch of companion status
  useEffect(() => {
    let alive = true;
    client
      .call<{ call_mode: boolean; watch_along: boolean; caller_name: string }>("companion_status")
      .then((res) => {
        if (alive && res) {
          setCallActive(res.call_mode);
          setWatchActive(res.watch_along);
          setCallerName(res.caller_name || "");
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [client]);

  const handleToggleCall = async () => {
    if (loading) return;
    setLoading(true);
    try {
      const res = await client.call<{ active: boolean }>("quick_action", { id: "toggle_call_mode" });
      if (res && typeof res.active === "boolean") {
        setCallActive(res.active);
      } else {
        setCallActive((prev) => !prev);
      }
    } catch {
      await quick("toggle_call_mode");
      setCallActive((prev) => !prev);
    } finally {
      setLoading(false);
    }
  };

  const handleToggleWatch = async () => {
    try {
      const res = await client.call<{ active: boolean }>("quick_action", { id: "toggle_watch_along" });
      if (res && typeof res.active === "boolean") {
        setWatchActive(res.active);
      } else {
        setWatchActive((prev) => !prev);
      }
    } catch {
      await quick("toggle_watch_along");
      setWatchActive((prev) => !prev);
    }
  };

  const voiceVol = typeof s?.voice_volume === "number" ? s.voice_volume : 50;
  const cableVol = typeof s?.cable_volume === "number" ? s.cable_volume : 85;

  const updateVol = (key: "voice_volume" | "cable_volume", val: number) => {
    void client.call("settings_set", { key, value: val });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 pb-4 text-xs select-none">
      {/* 1. Header / AI Companion & Husk Bridge */}
      <div className="relative overflow-hidden rounded-2xl border border-white/[0.06] bg-gradient-to-br from-panel2/90 via-panel2/60 to-panel/80 p-3 shadow-soft backdrop-blur-md transition-all duration-300 hover:border-accent/40">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="grid h-7 w-7 place-items-center rounded-xl bg-accent/15 text-accent shadow-[0_0_12px_rgba(255,42,133,0.3)]">
              <Bot size={15} />
            </div>
            <div>
              <div className="text-xs font-semibold text-ink flex items-center gap-1.5">
                <span>Companion Suite</span>
                <span className="text-[10px] text-ink-dim font-normal">(Husk AI)</span>
              </div>
              <p className="text-[10px] text-ink-dim">Озвучка действий Claude Code, Codex и подтверждений</p>
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-online/20 bg-online/10 px-2 py-0.5 text-[10px] font-medium text-online shadow-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-online animate-pulse" />
            127.0.0.1:19482
          </span>
        </div>
      </div>

      {/* 2. Discord Call Mode Hero Card */}
      <div
        className={`relative overflow-hidden rounded-2xl border transition-all duration-300 p-3.5 shadow-soft backdrop-blur-md ${
          callActive
            ? "border-accent/80 bg-accent/10 shadow-[0_0_20px_rgba(255,42,133,0.2)]"
            : "border-white/[0.06] bg-panel2/60 hover:border-line"
        }`}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div
              className={`grid h-8 w-8 shrink-0 place-items-center rounded-xl transition-all ${
                callActive
                  ? "bg-accent text-white shadow-[0_0_14px_rgba(255,42,133,0.6)]"
                  : "bg-panel text-ink-dim"
              }`}
            >
              <PhoneCall size={16} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-ink">
                  {callActive ? "В звонке Discord" : "Режим звонка"}
                </span>
                {callActive && (
                  <span className="rounded-full bg-accent/20 px-1.5 py-0.2 text-[9px] font-bold text-accent uppercase tracking-wider animate-pulse">
                    LIVE
                  </span>
                )}
              </div>
              <p className="text-[10px] text-ink-dim truncate">
                {callActive
                  ? callerName
                    ? `Слушает: ${callerName} · говорит в кабель`
                    : "Слушает друзей через наушники и отвечает в кабель"
                  : "Перенаправляет речь Сакуры в виртуальный кабель Discord"}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => void handleToggleCall()}
            className={`shrink-0 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all duration-200 cursor-pointer ${
              callActive
                ? "bg-accent text-white shadow-[0_0_15px_rgba(255,42,133,0.5)] hover:brightness-110 active:scale-95"
                : "border border-white/[0.06] bg-panel text-ink hover:border-accent hover:text-accent active:scale-95"
            }`}
          >
            {callActive ? "Завершить звонок" : "Войти в звонок"}
          </button>
        </div>
      </div>

      {/* 3. Audio Routing & Volume Mixer */}
      <div className="rounded-2xl border border-white/[0.06] bg-panel2/50 p-3 shadow-soft backdrop-blur-md">
        <div className="mb-2.5 flex items-center justify-between text-xs font-semibold text-ink">
          <div className="flex items-center gap-1.5">
            <Sliders size={13} className="text-accent" />
            <span>Микшер громкости</span>
          </div>
          <span className="text-[10px] font-normal text-ink-dim">
            {callActive ? "Кабель активен" : "Кабель заглушен"}
          </span>
        </div>

        <div className="flex flex-col gap-2.5">
          {/* Headphones Slider */}
          <div className="flex items-center justify-between gap-3 rounded-xl bg-panel/70 px-2.5 py-1.5 border border-white/[0.06]">
            <div className="flex items-center gap-2 min-w-0">
              <Headphones size={13} className="text-accent shrink-0" />
              <span className="text-[11px] text-ink font-medium">Наушники:</span>
            </div>
            <div className="flex items-center gap-2.5">
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                value={voiceVol}
                aria-label="Громкость в наушниках"
                onChange={(e) => updateVol("voice_volume", Number(e.target.value))}
                className="h-1.5 w-24 cursor-pointer accent-accent"
              />
              <span className="w-8 text-right font-mono text-[11px] font-semibold text-accent">
                {voiceVol}%
              </span>
            </div>
          </div>

          {/* Cable Slider */}
          <div
            className={`flex items-center justify-between gap-3 rounded-xl px-2.5 py-1.5 border transition-all ${
              callActive
                ? "bg-accent/10 border-accent/40"
                : "bg-panel/70 border-white/[0.06] opacity-80"
            }`}
          >
            <div className="flex items-center gap-2 min-w-0">
              <Volume2
                size={13}
                className={callActive ? "text-accent shrink-0" : "text-ink-dim shrink-0"}
              />
              <span className="text-[11px] text-ink font-medium">Discord кабель:</span>
            </div>
            <div className="flex items-center gap-2.5">
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                value={cableVol}
                aria-label="Громкость в Discord кабеле"
                onChange={(e) => updateVol("cable_volume", Number(e.target.value))}
                className="h-1.5 w-24 cursor-pointer accent-accent"
              />
              <span
                className={`w-8 text-right font-mono text-[11px] font-semibold ${
                  callActive ? "text-accent" : "text-ink-dim"
                }`}
              >
                {cableVol}%
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 4. Companion Actions (GameSense, Clips, Watch) */}
      <div className="rounded-2xl border border-white/[0.06] bg-panel2/50 p-3 shadow-soft backdrop-blur-md">
        <div className="mb-2 flex items-center justify-between text-xs font-semibold text-ink">
          <div className="flex items-center gap-1.5">
            <Activity size={13} className="text-accent" />
            <span>Интерактивные действия</span>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <button
            type="button"
            onClick={() => void quick("clip_that")}
            className="flex flex-col items-center justify-center gap-1.5 rounded-xl border border-white/[0.06] bg-panel/70 py-2 px-1 text-ink-dim transition-all duration-200 hover:border-accent hover:text-ink hover:shadow-[0_0_12px_rgba(255,42,133,0.2)] active:scale-95"
          >
            <Film size={14} className="text-accent" />
            <span className="text-[10px] font-medium">Откат 30с</span>
          </button>

          <button
            type="button"
            onClick={() => void handleToggleWatch()}
            className={`flex flex-col items-center justify-center gap-1.5 rounded-xl border py-2 px-1 transition-all duration-200 active:scale-95 ${
              watchActive
                ? "border-accent bg-accent/15 text-accent shadow-[0_0_12px_rgba(255,42,133,0.25)]"
                : "border-white/[0.06] bg-panel/70 text-ink-dim hover:border-accent hover:text-ink"
            }`}
          >
            <Eye size={14} className={watchActive ? "text-accent" : "text-ink-dim"} />
            <span className="text-[10px] font-medium">Смотреть</span>
          </button>

          <button
            type="button"
            onClick={() => void quick("clear_ink")}
            className="flex flex-col items-center justify-center gap-1.5 rounded-xl border border-white/[0.06] bg-panel/70 py-2 px-1 text-ink-dim transition-all duration-200 hover:border-accent hover:text-ink hover:shadow-[0_0_12px_rgba(255,42,133,0.2)] active:scale-95"
          >
            <Eraser size={14} className="text-accent" />
            <span className="text-[10px] font-medium">Чернила</span>
          </button>
        </div>
      </div>

      {/* 5. Health & Care Metrics */}
      <div className="rounded-2xl border border-white/[0.06] bg-panel2/50 p-3 shadow-soft backdrop-blur-md">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-1.5 font-semibold text-ink text-xs">
            <HeartPulse size={13} className="text-accent" />
            <span>Забота о здоровье (Care)</span>
          </div>
          <Sparkles size={12} className="text-accent" />
        </div>

        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <div className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-panel/70 px-2.5 py-1.5">
            <span className="text-ink-dim">💧 Вода</span>
            <span className="font-semibold text-online">В норме</span>
          </div>
          <div className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-panel/70 px-2.5 py-1.5">
            <span className="text-ink-dim">🧘 Разминка</span>
            <span className="font-semibold text-ink">~45 мин</span>
          </div>
          <div className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-panel/70 px-2.5 py-1.5">
            <span className="text-ink-dim">👀 Глаза 20/20</span>
            <span className="font-semibold text-accent">Активно</span>
          </div>
          <div className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-panel/70 px-2.5 py-1.5">
            <span className="text-ink-dim">🌙 Сон</span>
            <span className="font-semibold text-ink">до 01:00</span>
          </div>
        </div>
      </div>
    </div>
  );
}

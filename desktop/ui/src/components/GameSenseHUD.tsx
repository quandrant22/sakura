import { useEffect, useState } from "react";
import { AlertCircle, Film, Flame, Skull, Zap } from "lucide-react";
import { useMediaClient } from "../media/MediaContext";

export interface GameSenseAlert {
  kind: "hurt" | "flash" | "dark" | "bar_drop" | "cut";
  message: string;
  strength?: number;
}

export function GameSenseHUD() {
  const client = useMediaClient();
  const [alert, setAlert] = useState<GameSenseAlert | null>(null);
  const [clipPath, setClipPath] = useState<string | null>(null);
  const [effectClass, setEffectClass] = useState<string>("");

  useEffect(() => {
    let alertTimer: ReturnType<typeof setTimeout> | null = null;
    let clipTimer: ReturnType<typeof setTimeout> | null = null;

    const unreg = client.onEvent((ev: any) => {
      if (ev.type === "gamesense_event") {
        const kind = ev.kind as GameSenseAlert["kind"];
        const msg = ev.message || "Игровое событие";
        setAlert({ kind, message: msg, strength: ev.strength });

        if (kind === "hurt") {
          setEffectClass("shadow-[inset_0_0_100px_rgba(255,0,50,0.6)] border-red-500/50");
        } else if (kind === "flash") {
          setEffectClass("bg-white/30 backdrop-blur-sm");
        } else if (kind === "dark") {
          setEffectClass("shadow-[inset_0_0_120px_rgba(40,0,10,0.85)] border-purple-900/60");
        }

        if (alertTimer) clearTimeout(alertTimer);
        alertTimer = setTimeout(() => {
          setAlert(null);
          setEffectClass("");
        }, 3200);
      } else if (ev.type === "clip_saved") {
        setClipPath(ev.path || "Видео сохранено");
        if (clipTimer) clearTimeout(clipTimer);
        clipTimer = setTimeout(() => {
          setClipPath(null);
        }, 5000);
      }
    });

    return () => {
      unreg();
      if (alertTimer) clearTimeout(alertTimer);
      if (clipTimer) clearTimeout(clipTimer);
    };
  }, [client]);

  return (
    <>
      {/* 1. Fullscreen Vignette FX */}
      {effectClass && (
        <div
          className={`pointer-events-none fixed inset-0 z-40 transition-all duration-300 border-2 ${effectClass}`}
        />
      )}

      {/* 2. Top GameSense Alert Banner */}
      {alert && (
        <div className="pointer-events-none fixed top-12 left-1/2 z-50 -translate-x-1/2 flex items-center gap-2.5 rounded-full border border-accent/80 bg-panel2/95 px-5 py-2 text-xs font-semibold text-white shadow-[0_0_24px_rgba(255,42,133,0.5)] backdrop-blur-xl animate-bounce">
          {alert.kind === "hurt" && <Flame size={16} className="text-red-500 animate-pulse" />}
          {alert.kind === "flash" && <Zap size={16} className="text-yellow-300 animate-pulse" />}
          {alert.kind === "dark" && <Skull size={16} className="text-purple-400 animate-pulse" />}
          {alert.kind !== "hurt" && alert.kind !== "flash" && alert.kind !== "dark" && (
            <AlertCircle size={16} className="text-accent" />
          )}
          <span>{alert.message}</span>
        </div>
      )}

      {/* 3. Clip Saved Notification Toast */}
      {clipPath && (
        <div className="pointer-events-none fixed top-24 left-1/2 z-50 -translate-x-1/2 flex items-center gap-2.5 rounded-full border border-online/80 bg-panel2/95 px-5 py-2 text-xs font-semibold text-white shadow-[0_0_20px_rgba(0,255,160,0.4)] backdrop-blur-xl">
          <Film size={16} className="text-online" />
          <span>Момент заклипан! {clipPath.split("\\").pop()}</span>
        </div>
      )}
    </>
  );
}

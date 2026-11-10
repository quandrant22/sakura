// Сцена (?view=stage): прозрачное окно поверх «экрана Сакуры». Клики проходят насквозь (main),
// здесь только отрисовка: рисование Сакуры (ink_render), субтитры её реплик, игровые реакции и
// маленькое ядро, пока она слушает или говорит в игре. Пустая сцена просит main спрятать окно.
import { useEffect, useMemo, useRef, useState } from "react";

import { WsCoreClient } from "../api/client";
import type { CoreEvent, Message } from "../api/types";
import { bridge } from "../bridge";
import { SakuraCore } from "../core-gfx/SakuraCore";
import { STATE_STYLE } from "../core-gfx/stateStyle";
import {
  arrowHead, EMPTY_STAGE, GAME_EVENT_TITLES, hasContent, type InkShape, prune, scalePoints, type StageModel,
  withInk, withSubtitle, withToast,
} from "./stageLogic";

const TICK_MS = 250;

function useViewport() {
  const [v, setV] = useState({ w: window.innerWidth, h: window.innerHeight });
  useEffect(() => {
    const on = () => setV({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return v;
}

function Shape({ s, space, view }: { s: InkShape; space: { w: number; h: number }; view: { w: number; h: number } }) {
  const p = scalePoints(s.points, space, view);
  const stroke = s.color || "#FF6AE3";
  const width = Math.max(2, (s.width ?? 3) * 1.4);
  const common = { stroke, strokeWidth: width, fill: "none", strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = p;
  switch (s.kind) {
    case "circle": {
      const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
      return <ellipse cx={cx} cy={cy} rx={Math.abs(x2 - x1) / 2} ry={Math.abs(y2 - y1) / 2} {...common} className="ink-draw" />;
    }
    case "box":
      return <rect x={Math.min(x1, x2)} y={Math.min(y1, y2)} width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)} rx={10}
                   {...common} className="ink-draw" />;
    case "arrow": {
      const [ax, ay, bx, by] = arrowHead(x1, y1, x2, y2, 14 + width * 2);
      return (
        <g className="ink-draw">
          <line x1={x1} y1={y1} x2={x2} y2={y2} {...common} />
          <polyline points={`${ax},${ay} ${x2},${y2} ${bx},${by}`} {...common} />
        </g>
      );
    }
    case "line":
      return <line x1={x1} y1={y1} x2={x2} y2={y2} {...common} className="ink-draw" />;
    case "path": {
      const d = p.reduce((acc, v, i) => acc + (i % 2 === 0 ? `${i === 0 ? "M" : " L"}${v}` : `,${v}`), "");
      return <path d={d} {...common} className="ink-draw" />;
    }
    case "text":
      return (
        <text x={x1} y={y1} fill={stroke} fontSize={22} fontWeight={600} className="ink-text"
              paintOrder="stroke" stroke="rgba(10,6,16,.85)" strokeWidth={5}>{s.text}</text>
      );
    default:
      return null;
  }
}

export function Stage() {
  const view = useViewport();
  const [model, setModel] = useState<StageModel>(EMPTY_STAGE);
  const [now, setNow] = useState(() => Date.now());
  const level = useRef(0);
  const client = useMemo(() => new WsCoreClient(() => bridge().core.connection()), []);

  useEffect(() => {
    document.documentElement.classList.add("stage");
    client.start();
    const off = client.onEvent((ev: CoreEvent) => {
      const t = Date.now();
      const e = ev as Record<string, unknown> & { type: string };
      switch (e.type) {
        case "state":
          setModel((m) => ({ ...m, coreState: (e.value as StageModel["coreState"]) ?? "idle" }));
          if (typeof e.level === "number") level.current = e.level;
          break;
        case "audio_level":
          if (Array.isArray(e.bars) && e.bars.length) {
            level.current = Math.min(1, (e.bars as number[]).reduce((a, b) => a + b, 0) / e.bars.length);
          }
          break;
        case "game_mode":
          setModel((m) => ({ ...m, gameMode: Boolean(e.on) }));
          break;
        case "settings": {
          const s = (e.settings ?? {}) as Record<string, unknown>;
          setModel((m) => ({ ...m, subtitlesAlways: Boolean(s.stage_subtitles_always) }));
          break;
        }
        case "ink_render":
          setModel((m) => withInk(m, (e.shapes as InkShape[]) ?? [], e.space as { w: number; h: number } | undefined,
                                  e.duration as number | undefined, t));
          break;
        case "chat_message": {
          const msg = e.message as Message | undefined;
          if (msg && msg.role === "assistant" && msg.kind !== "command" && msg.kind !== "voice_only") {
            setModel((m) => withSubtitle(m, msg.text, t));
          }
          break;
        }
        case "game_event": {
          const kind = String(e.event ?? "");
          const title = String(e.title ?? GAME_EVENT_TITLES[kind] ?? "Игра");
          setModel((m) => withToast(m, title, String(e.text ?? ""), "game", t));
          break;
        }
        case "notify":
          // Вне игры уведомления показывает главное окно; в игре — сцена (главное окно не видно).
          setModel((m) => (m.gameMode ? withToast(m, "Сакура", String(e.text ?? ""), e.level === "info" ? "info" : "warn", t) : m));
          break;
        default:
          break;
      }
    });
    const tick = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => { off(); clearInterval(tick); client.stop(); };
  }, [client]);

  const shown = prune(model, now);
  const visible = hasContent(model, now);
  const lastWanted = useRef<boolean | null>(null);
  useEffect(() => {
    if (lastWanted.current === visible) return;
    lastWanted.current = visible;
    void bridge().stage.want(visible);
  }, [visible]);

  const style = STATE_STYLE[shown.coreState];
  const coreOn = shown.gameMode && shown.coreState !== "idle";

  return (
    <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden>
      {shown.ink && (
        <svg className="absolute inset-0" width={view.w} height={view.h} viewBox={`0 0 ${view.w} ${view.h}`}>
          <defs>
            <filter id="ink-glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="4" result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          <g filter="url(#ink-glow)">
            {shown.ink.shapes.map((s, i) => <Shape key={i} s={s} space={shown.ink!.space} view={view} />)}
          </g>
        </svg>
      )}

      {shown.toasts.length > 0 && (
        <div className="absolute right-6 top-6 flex w-[320px] flex-col gap-2">
          {shown.toasts.map((t) => (
            <div key={t.id} className="stage-in stage-glass rounded-card px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full" style={{ background: t.tone === "warn" ? "rgb(var(--warn))" : style.color }} />
                <span className="font-display text-[13px] tracking-wider text-ink">{t.title}</span>
              </div>
              {t.text && <div className="mt-1 text-[13px] leading-snug text-ink/90">{t.text}</div>}
            </div>
          ))}
        </div>
      )}

      {(shown.subtitle || coreOn) && (
        <div className="absolute inset-x-0 bottom-[7%] flex items-end justify-center gap-3 px-8">
          {coreOn && (
            <div className="stage-in shrink-0" style={{ filter: `drop-shadow(0 0 14px ${style.glow})` }}>
              <SakuraCore state={shown.coreState} level={() => level.current} size={96} />
            </div>
          )}
          {shown.subtitle && (
            <div className="stage-in stage-glass max-w-[880px] rounded-card px-5 py-3">
              <div className="mb-0.5 flex items-center gap-2 font-display text-[11px] tracking-[0.3em]" style={{ color: style.color }}>
                SAKURA <span className="font-sans tracking-normal opacity-70">{style.kana}</span>
              </div>
              <div className="text-[19px] leading-snug text-ink">{shown.subtitle.text}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

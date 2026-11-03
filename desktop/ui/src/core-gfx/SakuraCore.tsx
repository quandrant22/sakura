import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import {
  coreFrame, MERGE_PRESETS, VIEWBOX,
  type CoreFrame, type CoreVisualState, type MergePreset, type Mobility,
} from "./coreFrame";

interface Props {
  state: CoreVisualState;
  /** Уровень звука 0..1; читается каждый кадр. */
  level: () => number;
  preset?: MergePreset;
  mobility?: Mobility;
  /** Частота кадров; по умолчанию зависит от состояния (DEFAULT_FPS). */
  fps?: number;
  /** Ширина в px; высота по viewBox. */
  size?: number;
  className?: string;
}

export const DEFAULT_FPS: Record<CoreVisualState, number> = {
  idle: 30, offline: 10, listening: 60, thinking: 60, speaking: 60,
};

const REDUCED = "(prefers-reduced-motion: reduce)";
const RINGS = 2;
const SATS = 5;

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia?.(REDUCED).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(REDUCED);
    if (!mq) return;
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

const fmt = (v: number) => v.toFixed(2);

/** Переносит кадр в DOM напрямую, без перерисовки React. */
function apply(f: CoreFrame, group: SVGGElement, sats: SVGCircleElement[], drop: SVGCircleElement, rings: SVGCircleElement[]) {
  group.setAttribute("opacity", String(f.opacity));
  drop.setAttribute("r", fmt(f.drop.r));
  f.satellites.forEach((s, i) => {
    const el = sats[i];
    if (!el) return;
    el.setAttribute("cx", fmt(s.cx));
    el.setAttribute("cy", fmt(s.cy));
    el.setAttribute("r", fmt(s.r));
  });
  rings.forEach((el, i) => {
    const r = f.rings[i];
    el.setAttribute("r", fmt(r?.r ?? 0));
    el.setAttribute("opacity", fmt(r?.opacity ?? 0));
  });
}

export function SakuraCore({
  state, level, preset = "soft", mobility = "normal", fps, size = VIEWBOX.w, className,
}: Props) {
  const id = useId().replace(/:/g, "");
  const reduced = usePrefersReducedMotion();
  const levelRef = useRef(level);
  useLayoutEffect(() => { levelRef.current = level; }, [level]);

  const groupRef = useRef<SVGGElement>(null);
  const dropRef = useRef<SVGCircleElement>(null);
  const satRefs = useRef<SVGCircleElement[]>([]);
  const ringRefs = useRef<SVGCircleElement[]>([]);

  const frameFps = fps ?? DEFAULT_FPS[state];

  useEffect(() => {
    const group = groupRef.current, drop = dropRef.current;
    if (!group || !drop) return;
    const draw = (t: number, lv: number) => apply(coreFrame(t, state, lv, mobility), group, satRefs.current, drop, ringRefs.current);

    // reducedMotion: один статичный кадр, цикла нет.
    if (reduced) { draw(0, 0); return; }

    const interval = 1000 / Math.max(1, frameFps);
    const start = performance.now();
    let raf = 0;
    let last = -Infinity;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      // Допуск 2 мс, чтобы 60 fps не проседали до 30 из-за дрожания rAF.
      if (now - last < interval - 2) return;
      last = now;
      draw((now - start) / 1000, levelRef.current());
    };
    const run = () => { if (!raf && !document.hidden) raf = requestAnimationFrame(tick); };
    const stop = () => { cancelAnimationFrame(raf); raf = 0; };
    // Окно свёрнуто или скрыто — цикл полностью останавливается.
    const onVisibility = () => (document.hidden ? stop() : run());

    draw(0, 0);
    run();
    document.addEventListener("visibilitychange", onVisibility);
    return () => { stop(); document.removeEventListener("visibilitychange", onVisibility); };
  }, [state, mobility, frameFps, reduced]);

  // Начальная разметка — кадр t=0; дальше атрибуты обновляет цикл.
  const f0 = coreFrame(0, state, 0, mobility);
  const m = MERGE_PRESETS[preset];
  const { x, y, w, h } = VIEWBOX;

  return (
    <svg viewBox={`${x} ${y} ${w} ${h}`} width={size} height={(size * h) / w} className={className}
      style={{ overflow: "visible" }} role="img" aria-label={`Ядро: ${state}`}>
      <defs>
        <radialGradient id={`g${id}`} gradientUnits="userSpaceOnUse" cx={-21.5} cy={-17} r={71.4}>
          <stop stopColor="#FF6AE3" />
          <stop offset="1" stopColor="#3E0074" />
        </radialGradient>
        {/* sRGB и atop: форма берётся из «слипшейся» альфы, цвет — из исходного градиента без размытия и каймы. */}
        <filter id={`f${id}`} x="-50%" y="-50%" width="200%" height="200%" colorInterpolationFilters="sRGB">
          <feGaussianBlur in="SourceGraphic" stdDeviation={m.blur} result="b" />
          <feColorMatrix in="b" mode="matrix" values={`1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 ${m.matrix}`} result="goo" />
          <feComposite in="SourceGraphic" in2="goo" operator="atop" />
        </filter>
      </defs>
      {Array.from({ length: RINGS }, (_, i) => (
        <circle key={i} ref={(el) => { if (el) ringRefs.current[i] = el; }}
          cx={0} cy={0} r={f0.rings[i]?.r ?? 0} opacity={f0.rings[i]?.opacity ?? 0}
          fill="none" stroke="#FF6AE3" strokeWidth={2} />
      ))}
      <g ref={groupRef} filter={`url(#f${id})`} fill={`url(#g${id})`} opacity={f0.opacity}>
        <circle ref={dropRef} cx={0} cy={0} r={f0.drop.r} />
        {Array.from({ length: SATS }, (_, i) => {
          const s = f0.satellites[i];
          return <circle key={i} ref={(el) => { if (el) satRefs.current[i] = el; }} cx={s?.cx ?? 0} cy={s?.cy ?? 0} r={s?.r ?? 0} />;
        })}
      </g>
    </svg>
  );
}

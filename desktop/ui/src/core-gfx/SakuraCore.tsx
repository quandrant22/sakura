import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import {
  blendFrames, coreFrame, ease, MERGE_PRESETS, TRANSITION_MS, VIEWBOX,
  type CoreFrame, type CoreVisualState, type MergePreset, type Mobility,
} from "./coreFrame";
import { FrameStats, frameStatsEnabled } from "./frameStats";

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

  // Цикл анимации живёт всё время компонента: состояние, подвижность и частота читаются из ref,
  // время отсчитывается от одного начала (смена состояния его не сбрасывает), а переход —
  // смесь последнего нарисованного кадра с кадром нового состояния за TRANSITION_MS.
  const stateRef = useRef(state);
  const mobilityRef = useRef(mobility);
  const fpsRef = useRef(fps);
  const startRef = useRef<number | null>(null);
  const lastFrameRef = useRef<CoreFrame | null>(null);
  const transRef = useRef<{ from: CoreFrame; at: number } | null>(null);

  useLayoutEffect(() => {
    if ((stateRef.current !== state || mobilityRef.current !== mobility) && lastFrameRef.current) {
      transRef.current = { from: lastFrameRef.current, at: performance.now() };
    }
    stateRef.current = state;
    mobilityRef.current = mobility;
    fpsRef.current = fps;
  }, [state, mobility, fps]);

  // reducedMotion: один статичный кадр на состояние, цикла нет.
  useEffect(() => {
    const group = groupRef.current, drop = dropRef.current;
    if (!reduced || !group || !drop) return;
    const f = coreFrame(0, state, 0, mobility);
    lastFrameRef.current = f;
    apply(f, group, satRefs.current, drop, ringRefs.current);
  }, [reduced, state, mobility]);

  useEffect(() => {
    const group = groupRef.current, drop = dropRef.current;
    if (reduced || !group || !drop) return;
    if (startRef.current === null) startRef.current = performance.now();
    const start = startRef.current;
    const stats = frameStatsEnabled()
      ? new FrameStats((s) => console.debug(`[core] кадры за 10 с: ${s.drawn}, пропущено ${s.missed} (${s.pct}%)`))
      : null;

    const frameAt = (now: number): CoreFrame => {
      const target = coreFrame((now - start) / 1000, stateRef.current, levelRef.current(), mobilityRef.current);
      const tr = transRef.current;
      if (!tr) return target;
      const p = (now - tr.at) / TRANSITION_MS;
      if (p >= 1) { transRef.current = null; return target; }
      return blendFrames(tr.from, target, ease(p));
    };
    const draw = (now: number) => {
      const f = frameAt(now);
      lastFrameRef.current = f;
      apply(f, group, satRefs.current, drop, ringRefs.current);
    };

    let raf = 0;
    let last = -Infinity;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      // Во время перехода — с частотой более быстрого состояния, чтобы смесь не дёргалась.
      const target = fpsRef.current ?? (transRef.current ? 60 : DEFAULT_FPS[stateRef.current]);
      const interval = 1000 / Math.max(1, target);
      // Допуск 2 мс, чтобы 60 fps не проседали до 30 из-за дрожания rAF.
      if (now - last < interval - 2) return;
      last = now;
      draw(now);
      stats?.frame(now, interval);
    };
    const run = () => { if (!raf && !document.hidden) raf = requestAnimationFrame(tick); };
    const stop = () => { cancelAnimationFrame(raf); raf = 0; stats?.pause(); };
    // Окно свёрнуто или скрыто — цикл полностью останавливается.
    const onVisibility = () => (document.hidden ? stop() : run());

    draw(performance.now());
    run();
    document.addEventListener("visibilitychange", onVisibility);
    return () => { stop(); document.removeEventListener("visibilitychange", onVisibility); };
  }, [reduced]);

  // Начальная разметка — кадр t=0 первого состояния, один раз: иначе при смене состояния React
  // вернул бы атрибуты к t=0 нового состояния (скачок до следующего кадра цикла).
  const [f0] = useState(() => coreFrame(0, state, 0, mobility));
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

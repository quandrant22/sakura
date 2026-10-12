import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { coreFrame, MERGE_PRESETS, VIEWBOX, type CoreVisualState, type MergePreset } from "./coreFrame";

interface Props {
  state: CoreVisualState;
  /** Уровень звука 0..1; читается каждый кадр. */
  level: () => number;
  preset?: MergePreset;
  /** Ширина в px; высота по viewBox. */
  size?: number;
  className?: string;
}

const REDUCED = "(prefers-reduced-motion: reduce)";

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

export function SakuraCore({ state, level, preset = "soft", size = VIEWBOX.w, className }: Props) {
  const id = useId().replace(/:/g, "");
  const reduced = usePrefersReducedMotion();
  const levelRef = useRef(level);
  useLayoutEffect(() => { levelRef.current = level; }, [level]);
  const [clock, setClock] = useState({ t: 0, lv: 0 });

  useEffect(() => {
    if (reduced) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      // rAF сам замирает в скрытом окне; hidden — страховка для Electron с backgroundThrottling: false.
      if (!document.hidden) setClock({ t: (now - start) / 1000, lv: levelRef.current() });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [reduced]);

  // reducedMotion: статичный кадр t=0 без реакции на звук.
  const f = reduced ? coreFrame(0, state, 0) : coreFrame(clock.t, state, clock.lv);
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
      {f.rings.map((r, i) => (
        <circle key={i} cx={0} cy={0} r={r.r} fill="none" stroke="#FF6AE3" strokeWidth={2} opacity={r.opacity} />
      ))}
      <g filter={`url(#f${id})`} fill={`url(#g${id})`} opacity={f.opacity}>
        <circle cx={0} cy={0} r={f.drop.r} />
        {f.satellites.map((s, i) => <circle key={i} cx={s.cx} cy={s.cy} r={s.r} />)}
      </g>
    </svg>
  );
}

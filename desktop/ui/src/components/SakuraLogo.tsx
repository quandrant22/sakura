// Цветок сакуры: пять лепестков с вырезом на кончике, градиент акцента темы.
import { useId } from "react";

// Лепесток «вверх» от центра; остальные — поворот на 72°.
const PETAL = "M0 -2.2C-3.6 -4.6 -5.6 -9.2 -3.9 -12.6C-2.9 -14.5 -1.2 -14.9 0 -13.4C1.2 -14.9 2.9 -14.5 3.9 -12.6C5.6 -9.2 3.6 -4.6 0 -2.2Z";

export function SakuraLogo({ size = 28, className }: { size?: number; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg width={size} height={size} viewBox="-15 -15 30 30" className={className} aria-hidden="true">
      <defs>
        <radialGradient id={`p${id}`} gradientUnits="userSpaceOnUse" cx="0" cy="0" r="15">
          <stop offset="0.15" style={{ stopColor: "rgb(var(--accent))" }} />
          <stop offset="1" style={{ stopColor: "rgb(var(--accent-deep))" }} />
        </radialGradient>
      </defs>
      <g fill={`url(#p${id})`}>
        {[0, 72, 144, 216, 288].map((a) => <path key={a} d={PETAL} transform={`rotate(${a})`} />)}
      </g>
      <circle r="2.4" style={{ fill: "rgb(var(--accent))" }} />
      {[0, 72, 144, 216, 288].map((a) => (
        <circle key={a} r="0.7" cy="-4" transform={`rotate(${a + 36})`} style={{ fill: "rgb(var(--ink))" }} opacity="0.8" />
      ))}
    </svg>
  );
}

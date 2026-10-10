// Цветок сакуры из 5 лепестков с выемкой на кончике.
const PETAL = "M0 -2 C -7 -9 -8 -20 -3 -27 L 0 -23 L 3 -27 C 8 -20 7 -9 0 -2 Z";

export function SakuraLogo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="-30 -30 60 60" aria-hidden="true">
      <defs>
        <radialGradient id="sakura-petal" cx="0" cy="-12" r="18" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#ffd1e4" />
          <stop offset="1" stopColor="#ff4d94" />
        </radialGradient>
      </defs>
      {[0, 72, 144, 216, 288].map((a) => (
        <path key={a} d={PETAL} transform={`rotate(${a})`} fill="url(#sakura-petal)" />
      ))}
      <circle r="3.2" fill="#fff3a6" />
    </svg>
  );
}

import { useEffect, useState } from "react";
import { useMediaClient } from "../media/MediaContext";

export interface InkShape {
  kind: "circle" | "box" | "arrow" | "line" | "text" | "path" | "heart" | "star" | "smile" | "cat";
  points: number[];
  text?: string;
  color?: string;
  width?: number;
}

export function ScreenInkOverlay() {
  const client = useMediaClient();
  const [shapes, setShapes] = useState<InkShape[]>([]);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;

    const unreg = client.onEvent((ev: any) => {
      if (ev.type === "ink_render") {
        setShapes(ev.shapes || []);
        setVisible(true);

        if (timer) clearTimeout(timer);
        const duration = (typeof ev.duration === "number" ? ev.duration : 10) * 1000;
        if (duration > 0) {
          timer = setTimeout(() => {
            setVisible(false);
          }, duration);
        }
      } else if (ev.type === "ink_clear") {
        setVisible(false);
        setShapes([]);
        if (timer) clearTimeout(timer);
      }
    });

    return () => {
      unreg();
      if (timer) clearTimeout(timer);
    };
  }, [client]);

  if (!visible || shapes.length === 0) return null;

  return (
    <div className="pointer-events-none fixed inset-0 z-50 overflow-hidden transition-opacity duration-500 ease-out">
      <svg
        className="h-full w-full"
        viewBox="0 0 1920 1080"
        preserveAspectRatio="xMidYMid meet"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <filter id="neon-glow-pink" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="neon-glow-cyan" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <marker
            id="arrowhead-pink"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#FF2A85" />
          </marker>
        </defs>

        {shapes.map((s, idx) => {
          const color = s.color || "#FF2A85";
          const strokeWidth = s.width || 3;

          if (s.kind === "circle" && s.points.length >= 4) {
            const [x = 0, y = 0, w = 0, h = 0] = s.points;
            const rx = Math.abs(w) / 2;
            const ry = Math.abs(h) / 2;
            const cx = x > rx ? x : x + rx;
            const cy = y > ry ? y : y + ry;
            return (
              <ellipse
                key={idx}
                cx={cx}
                cy={cy}
                rx={rx}
                ry={ry}
                fill="none"
                stroke={color}
                strokeWidth={strokeWidth}
                filter="url(#neon-glow-pink)"
                className="animate-pulse"
              />
            );
          }

          if (s.kind === "box" && s.points.length >= 4) {
            const [x = 0, y = 0, w = 0, h = 0] = s.points;
            return (
              <rect
                key={idx}
                x={x}
                y={y}
                width={w}
                height={h}
                fill="none"
                stroke={color}
                strokeWidth={strokeWidth}
                filter="url(#neon-glow-pink)"
                rx={8}
                className="animate-pulse"
              />
            );
          }

          if (s.kind === "arrow" && s.points.length >= 4) {
            const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = s.points;
            return (
              <line
                key={idx}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={color}
                strokeWidth={strokeWidth}
                markerEnd="url(#arrowhead-pink)"
                filter="url(#neon-glow-pink)"
              />
            );
          }

          if (s.kind === "line" && s.points.length >= 4) {
            const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = s.points;
            return (
              <line
                key={idx}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={color}
                strokeWidth={strokeWidth}
                filter="url(#neon-glow-pink)"
              />
            );
          }

          if (s.kind === "text" && s.points.length >= 2) {
            const [x = 0, y = 0] = s.points;
            const textWidth = ((s.text?.length || 5) * 9) + 24;
            return (
              <g key={idx} transform={`translate(${x}, ${y})`}>
                <rect
                  x={-textWidth / 2}
                  y="-22"
                  width={textWidth}
                  height="30"
                  rx="8"
                  fill="#120c18"
                  stroke={color}
                  strokeWidth="1.5"
                  filter="url(#neon-glow-pink)"
                  opacity="0.95"
                />
                <text
                  x="0"
                  y="-2"
                  textAnchor="middle"
                  fill="#ffffff"
                  fontSize="14"
                  fontWeight="bold"
                  fontFamily="system-ui, sans-serif"
                  letterSpacing="0.05em"
                >
                  {s.text}
                </text>
              </g>
            );
          }

          if (s.kind === "heart" && s.points.length >= 2) {
            const [x = 0, y = 0, size = 120] = s.points;
            const scale = size / 24;
            return (
              <g
                key={idx}
                transform={`translate(${x - 12 * scale}, ${y - 12 * scale}) scale(${scale})`}
                className="animate-pulse"
              >
                <path
                  d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
                  fill="rgba(255, 42, 133, 0.45)"
                  stroke={color}
                  strokeWidth={Math.max(1, strokeWidth / scale)}
                  filter="url(#neon-glow-pink)"
                />
              </g>
            );
          }

          if (s.kind === "star" && s.points.length >= 2) {
            const [x = 0, y = 0, size = 120] = s.points;
            const scale = size / 24;
            return (
              <g
                key={idx}
                transform={`translate(${x - 12 * scale}, ${y - 12 * scale}) scale(${scale})`}
                className="animate-pulse"
              >
                <path
                  d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"
                  fill="rgba(255, 215, 0, 0.45)"
                  stroke={color || "#FFD700"}
                  strokeWidth={Math.max(1, strokeWidth / scale)}
                  filter="url(#neon-glow-pink)"
                />
              </g>
            );
          }

          if (s.kind === "smile" && s.points.length >= 2) {
            const [x = 0, y = 0, size = 120] = s.points;
            const scale = size / 24;
            return (
              <g
                key={idx}
                transform={`translate(${x - 12 * scale}, ${y - 12 * scale}) scale(${scale})`}
                className="animate-pulse"
              >
                <circle cx="12" cy="12" r="10" fill="rgba(255, 215, 0, 0.25)" stroke={color || "#FFD700"} strokeWidth={strokeWidth / scale} filter="url(#neon-glow-pink)" />
                <circle cx="8.5" cy="9.5" r="1.5" fill={color || "#FFD700"} />
                <circle cx="15.5" cy="9.5" r="1.5" fill={color || "#FFD700"} />
                <path d="M8 14s1.5 2.5 4 2.5 4-2.5 4-2.5" fill="none" stroke={color || "#FFD700"} strokeWidth={strokeWidth / scale} strokeLinecap="round" />
              </g>
            );
          }

          if (s.kind === "cat" && s.points.length >= 2) {
            const [x = 0, y = 0, size = 130] = s.points;
            const scale = size / 24;
            return (
              <g
                key={idx}
                transform={`translate(${x - 12 * scale}, ${y - 12 * scale}) scale(${scale})`}
                className="animate-pulse"
              >
                <path
                  d="M4 11 L4 4 L9 8 C11 7 13 7 15 8 L20 4 L20 11 C21.5 13.5 21.5 17 19 19.5 C16.5 22 7.5 22 5 19.5 C2.5 17 2.5 13.5 4 11 Z"
                  fill="rgba(255, 42, 133, 0.35)"
                  stroke={color}
                  strokeWidth={strokeWidth / scale}
                  filter="url(#neon-glow-pink)"
                />
                <ellipse cx="8.5" cy="13.5" rx="1.2" ry="2" fill={color} />
                <ellipse cx="15.5" cy="13.5" rx="1.2" ry="2" fill={color} />
                <polygon points="12 16, 11 15, 13 15" fill={color} />
                <path d="M12 16 C11 17.5 9.5 17.5 9 17 M12 16 C13 17.5 14.5 17.5 15 17" fill="none" stroke={color} strokeWidth="1" strokeLinecap="round" />
                <line x1="2" y1="13" x2="6" y2="14" stroke={color} strokeWidth="0.8" />
                <line x1="2" y1="16" x2="6" y2="16" stroke={color} strokeWidth="0.8" />
                <line x1="22" y1="13" x2="18" y2="14" stroke={color} strokeWidth="0.8" />
                <line x1="22" y1="16" x2="18" y2="16" stroke={color} strokeWidth="0.8" />
              </g>
            );
          }

          if (s.kind === "path" && s.text) {
            const [cx = 960, cy = 460, size = 220] = s.points.length >= 2 ? s.points : [960, 460, 220];
            const scale = size / 100;
            return (
              <g
                key={idx}
                transform={`translate(${cx - 50 * scale}, ${cy - 50 * scale}) scale(${scale})`}
                className="animate-pulse"
              >
                <path
                  d={s.text}
                  fill="rgba(255, 42, 133, 0.25)"
                  stroke={color}
                  strokeWidth={Math.max(2.5, (strokeWidth || 3) / scale)}
                  filter="url(#neon-glow-pink)"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </g>
            );
          }

          return null;
        })}
      </svg>
    </div>
  );
}

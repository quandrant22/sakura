import { useEffect, useState } from "react";
import { useMediaClient } from "../media/MediaContext";

export interface InkShape {
  kind: "circle" | "box" | "arrow" | "line" | "text" | "path";
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
      <svg className="h-full w-full" xmlns="http://www.w3.org/2000/svg">
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
            const cx = x + rx;
            const cy = y + ry;
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
            return (
              <g key={idx} transform={`translate(${x}, ${y})`}>
                <rect
                  x="-8"
                  y="-22"
                  width={((s.text?.length || 5) * 8) + 16}
                  height="28"
                  rx="6"
                  fill="#120c18"
                  stroke={color}
                  strokeWidth="1.5"
                  filter="url(#neon-glow-pink)"
                  opacity="0.9"
                />
                <text
                  x="0"
                  y="-3"
                  fill="#ffffff"
                  fontSize="13"
                  fontWeight="bold"
                  fontFamily="system-ui, sans-serif"
                  letterSpacing="0.05em"
                >
                  {s.text}
                </text>
              </g>
            );
          }

          return null;
        })}
      </svg>
    </div>
  );
}

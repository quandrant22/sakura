/**
 * SakuraCore — живое жидкое ядро со спутниками и кольцами состояния.
 * Порт desktop/ui/src/core-gfx/SakuraCore.tsx и coreFrame.ts.
 */

import React, { useEffect, useId, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Circle, Defs, G, RadialGradient, Stop } from 'react-native-svg';
import { SakuraState } from '../../api/types';
import { CORE_STATE_STYLE } from '../../constants/colors';

export type CoreVisualState = SakuraState | 'offline';

const DROP_R = 44;
const SATELLITES: readonly (readonly [number, number, number])[] = [
  [33.7, -61.1, 31.0],
  [-61.1, -37.6, 24.5],
  [-28.2, -84.0, 14.5],
  [53, 24, 11.5],
  [-46, 28, 8.5],
];
const WOBBLE: readonly (readonly [number, number, number])[] = [
  [0, 1, 1],
  [1.9, 1.27, -1],
  [3.7, 0.83, 1],
  [5.1, 1.51, -1],
  [2.6, 1.13, 1],
];
const VIEWBOX = { x: -125, y: -125, w: 250, h: 250 };
const MAX_RING_R = 84;
const ORBIT_SPEED = 0.6;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function motionParams(state: CoreVisualState) {
  switch (state) {
    case 'listening':
      return { base: 0.52, amp: 0.3, omega: 1.8 };
    case 'thinking':
      return { base: 0.7, amp: 0.25, omega: 1.5 };
    case 'speaking':
      return { base: 0.65, amp: 0.25, omega: 4.2 };
    case 'offline':
      return { base: 0.3, amp: 0.03, omega: 0.35 };
    default:
      return { base: 0.55, amp: 0.32, omega: 1.1 };
  }
}

function computeFrame(t: number, state: CoreVisualState) {
  const m = motionParams(state);
  const orbit = state === 'thinking' ? ORBIT_SPEED * t : 0;
  const breathe =
    state === 'offline'
      ? 1
      : state === 'speaking'
      ? 1 + 0.06 * Math.sin(t * 7.5)
      : 1 + 0.03 * Math.sin(t * 0.9);
  const dropR = DROP_R * breathe;

  const satellites = SATELLITES.map(([dx, dy, r], i) => {
    const [phase, speed, dir] = WOBBLE[i] ?? [0, 1, 1];
    const e = clamp(m.base + m.amp * Math.sin(t * m.omega * speed + phase), 0, 1);
    const a = orbit * dir;
    const cos = Math.cos(a);
    const sin = Math.sin(a);
    return {
      cx: (dx * cos - dy * sin) * e,
      cy: (dx * sin + dy * cos) * e,
      r: r * (0.6 + 0.4 * e),
    };
  });

  const rings: { r: number; opacity: number }[] = [];
  if (state === 'listening' || state === 'speaking') {
    const reach = state === 'listening' ? 32 : 26;
    for (let k = 0; k < 2; k++) {
      const p = (((t * 0.75 + k / 2) % 1) + 1) % 1;
      rings.push({
        r: Math.min(MAX_RING_R, DROP_R + reach * p),
        opacity: (1 - p) * 0.5,
      });
    }
  } else if (state === 'idle') {
    const p = ((t * 0.25) % 1 + 1) % 1;
    rings.push({
      r: DROP_R + 18 * p,
      opacity: (1 - p) * 0.18,
    });
  }

  return {
    dropR,
    satellites,
    rings,
    opacity: state === 'offline' ? 0.5 : 1,
  };
}

interface SakuraCoreProps {
  state: CoreVisualState;
  size?: number;
}

export const SakuraCore: React.FC<SakuraCoreProps> = ({ state, size = 128 }) => {
  const uid = useId().replace(/:/g, '');
  const gradId = `coreGrad_${uid}`;
  const glowId = `coreGlow_${uid}`;
  const [t, setT] = useState(0);

  useEffect(() => {
    let raf = 0;
    const start = Date.now();
    const fps = state === 'offline' ? 12 : state === 'idle' ? 24 : 40;
    const interval = 1000 / fps;
    let last = 0;

    const tick = () => {
      raf = requestAnimationFrame(tick);
      const now = Date.now();
      if (now - last < interval) return;
      last = now;
      setT((now - start) / 1000);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [state]);

  const frame = computeFrame(t, state);
  const style = CORE_STATE_STYLE[state] || CORE_STATE_STYLE.idle;

  return (
    <View style={[styles.wrap, { width: size, height: size }]}>
      <Svg
        width={size}
        height={size}
        viewBox={`${VIEWBOX.x} ${VIEWBOX.y} ${VIEWBOX.w} ${VIEWBOX.h}`}>
        <Defs>
          <RadialGradient id={glowId} cx="0" cy="0" r="105" gradientUnits="userSpaceOnUse">
            <Stop offset="0" stopColor={style.color} stopOpacity="0.28" />
            <Stop offset="0.6" stopColor={style.deep} stopOpacity="0.10" />
            <Stop offset="1" stopColor={style.deep} stopOpacity="0" />
          </RadialGradient>
          <RadialGradient
            id={gradId}
            gradientUnits="userSpaceOnUse"
            cx={-20}
            cy={-16}
            r={76}>
            <Stop offset="0" stopColor={style.color} />
            <Stop offset="1" stopColor={style.deep} />
          </RadialGradient>
        </Defs>

        {/* Мягкая внешняя аура */}
        <Circle cx={0} cy={0} r={105} fill={`url(#${glowId})`} />

        {/* Волны */}
        {frame.rings.map((ring, i) => (
          <Circle
            key={i}
            cx={0}
            cy={0}
            r={ring.r}
            opacity={ring.opacity}
            fill="none"
            stroke={style.color}
            strokeWidth={2}
          />
        ))}

        {/* Основная капля и спутники */}
        <G fill={`url(#${gradId})`} opacity={frame.opacity}>
          <Circle cx={0} cy={0} r={frame.dropR} />
          {frame.satellites.map((s, i) => (
            <Circle key={i} cx={s.cx} cy={s.cy} r={s.r} />
          ))}
        </G>
      </Svg>
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});

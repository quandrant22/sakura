/**
 * SakuraCore — многослойное живое квантовое ядро с орбитальными кольцами,
 * спекулярным бликом и плавной жидкой динамикой состояний.
 */

import React, { useEffect, useId, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Circle, Defs, G, RadialGradient, Stop } from 'react-native-svg';
import { SakuraState } from '../../api/types';
import { CORE_STATE_STYLE } from '../../constants/colors';

export type CoreVisualState = SakuraState | 'offline';

const DROP_R = 42;
const SATELLITES: readonly (readonly [number, number, number])[] = [
  [33.7, -60.0, 29.5],
  [-60.0, -37.0, 23.5],
  [-28.0, -82.0, 14.0],
  [52.0, 25.0, 11.5],
  [-46.0, 28.0, 8.5],
];
const WOBBLE: readonly (readonly [number, number, number])[] = [
  [0, 1, 1],
  [1.9, 1.27, -1],
  [3.7, 0.83, 1],
  [5.1, 1.51, -1],
  [2.6, 1.13, 1],
];
const VIEWBOX = { x: -130, y: -130, w: 260, h: 260 };
const MAX_RING_R = 92;
const ORBIT_SPEED = 0.6;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function motionParams(state: CoreVisualState) {
  switch (state) {
    case 'listening':
      return { base: 0.54, amp: 0.3, omega: 1.9 };
    case 'thinking':
      return { base: 0.72, amp: 0.25, omega: 1.6 };
    case 'speaking':
      return { base: 0.66, amp: 0.26, omega: 4.3 };
    case 'offline':
      return { base: 0.3, amp: 0.03, omega: 0.35 };
    default:
      return { base: 0.56, amp: 0.3, omega: 1.05 };
  }
}

function computeFrame(t: number, state: CoreVisualState) {
  const m = motionParams(state);
  const orbit = state === 'thinking' ? ORBIT_SPEED * t : state === 'offline' ? 0 : 0.14 * t;
  const breathe =
    state === 'offline'
      ? 1
      : state === 'speaking'
      ? 1 + 0.065 * Math.sin(t * 7.8)
      : state === 'listening'
      ? 1 + 0.045 * Math.sin(t * 3.2)
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
      r: r * (0.58 + 0.42 * e),
    };
  });

  const rings: { r: number; opacity: number }[] = [];
  if (state === 'listening' || state === 'speaking') {
    const reach = state === 'listening' ? 38 : 32;
    for (let k = 0; k < 2; k++) {
      const p = (((t * 0.8 + k / 2) % 1) + 1) % 1;
      rings.push({
        r: Math.min(MAX_RING_R, DROP_R + reach * p),
        opacity: (1 - p) * 0.55,
      });
    }
  } else if (state === 'idle') {
    const p = ((t * 0.24) % 1 + 1) % 1;
    rings.push({
      r: DROP_R + 24 * p,
      opacity: (1 - p) * 0.22,
    });
  }

  return {
    dropR,
    satellites,
    rings,
    ringAngle: (t * 14) % 360,
    innerAngle: (-t * 22) % 360,
    opacity: state === 'offline' ? 0.52 : 1,
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
  const specId = `coreSpec_${uid}`;
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
          <RadialGradient id={glowId} cx="0" cy="0" r="118" gradientUnits="userSpaceOnUse">
            <Stop offset="0" stopColor={style.color} stopOpacity="0.34" />
            <Stop offset="0.52" stopColor={style.deep} stopOpacity="0.16" />
            <Stop offset="1" stopColor={style.deep} stopOpacity="0" />
          </RadialGradient>
          <RadialGradient
            id={gradId}
            gradientUnits="userSpaceOnUse"
            cx={-18}
            cy={-16}
            r={78}>
            <Stop offset="0" stopColor="#FFFFFF" stopOpacity="0.95" />
            <Stop offset="0.22" stopColor={style.color} />
            <Stop offset="1" stopColor={style.deep} />
          </RadialGradient>
          <RadialGradient id={specId} cx={-14} cy={-16} r={22} gradientUnits="userSpaceOnUse">
            <Stop offset="0" stopColor="#FFFFFF" stopOpacity="0.52" />
            <Stop offset="1" stopColor="#FFFFFF" stopOpacity="0" />
          </RadialGradient>
        </Defs>

        {/* Многослойная аура */}
        <Circle cx={0} cy={0} r={118} fill={`url(#${glowId})`} />

        {/* Внешнее прецизионное орбитальное кольцо */}
        <G rotation={frame.ringAngle}>
          <Circle
            cx={0}
            cy={0}
            r={98}
            fill="none"
            stroke={style.color}
            strokeOpacity={state === 'offline' ? 0.14 : 0.26}
            strokeWidth={1}
            strokeDasharray="2 7"
          />
        </G>

        {/* Внутренняя орбита с дугой */}
        <G rotation={frame.innerAngle}>
          <Circle
            cx={0}
            cy={0}
            r={76}
            fill="none"
            stroke={style.color}
            strokeOpacity={state === 'offline' ? 0.08 : 0.2}
            strokeWidth={1.2}
            strokeDasharray="34 44"
          />
        </G>

        {/* Импульсные волны активности */}
        {frame.rings.map((ring, i) => (
          <Circle
            key={i}
            cx={0}
            cy={0}
            r={ring.r}
            opacity={ring.opacity}
            fill="none"
            stroke={style.color}
            strokeWidth={1.8}
          />
        ))}

        {/* Основная капля и спутники */}
        <G fill={`url(#${gradId})`} opacity={frame.opacity}>
          <Circle cx={0} cy={0} r={frame.dropR} />
          {frame.satellites.map((s, i) => (
            <Circle key={i} cx={s.cx} cy={s.cy} r={s.r} />
          ))}
        </G>

        {/* Глянцевый спекулярный блик поверх ядра */}
        <Circle cx={-12} cy={-14} r={20} fill={`url(#${specId})`} opacity={frame.opacity} />
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

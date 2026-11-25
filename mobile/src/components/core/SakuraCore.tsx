/**
 * SakuraCore — многослойное живое квантовое ядро на native UI-thread Reanimated 4
 * (0 JS-рендеров в секунду в простое и под нагрузкой, автопауза вне фокуса экрана).
 */

import { useFocusEffect } from 'expo-router';
import React, { memo, useCallback, useEffect, useId, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, Defs, G, RadialGradient, Stop } from 'react-native-svg';
import { SakuraState } from '../../api/types';
import { CORE_STATE_STYLE } from '../../constants/colors';

export type CoreVisualState = SakuraState | 'offline';

const SATELLITES: readonly (readonly [number, number, number])[] = [
  [21, -37, 17],
  [-36, -22, 13.5],
  [-17, -49, 8.5],
  [31, 15, 7],
  [-28, 17, 5.2],
];

interface StaticSvgProps {
  size: number;
  color: string;
  deep: string;
  offline: boolean;
}

function CoreGlowAndBodyBase({ size, color, deep, offline }: StaticSvgProps) {
  const uid = useId().replace(/:/g, '');
  const gradId = `cg_${uid}`;
  const glowId = `cl_${uid}`;
  const specId = `cs_${uid}`;

  return (
    <Svg width={size} height={size} viewBox="-130 -130 260 260">
      <Defs>
        <RadialGradient id={glowId} cx="0" cy="0" r="118" gradientUnits="userSpaceOnUse">
          <Stop offset="0" stopColor={color} stopOpacity="0.34" />
          <Stop offset="0.52" stopColor={deep} stopOpacity="0.16" />
          <Stop offset="1" stopColor={deep} stopOpacity="0" />
        </RadialGradient>
        <RadialGradient id={gradId} gradientUnits="userSpaceOnUse" cx={-18} cy={-16} r={78}>
          <Stop offset="0" stopColor="#FFFFFF" stopOpacity="0.95" />
          <Stop offset="0.22" stopColor={color} />
          <Stop offset="1" stopColor={deep} />
        </RadialGradient>
        <RadialGradient id={specId} cx={-14} cy={-16} r={22} gradientUnits="userSpaceOnUse">
          <Stop offset="0" stopColor="#FFFFFF" stopOpacity="0.52" />
          <Stop offset="1" stopColor="#FFFFFF" stopOpacity="0" />
        </RadialGradient>
      </Defs>
      <Circle cx={0} cy={0} r={118} fill={`url(#${glowId})`} />
      <G fill={`url(#${gradId})`} opacity={offline ? 0.52 : 1}>
        <Circle cx={0} cy={0} r={42} />
        {SATELLITES.map(([cx, cy, r], i) => (
          <Circle key={i} cx={cx} cy={cy} r={r} />
        ))}
      </G>
      <Circle cx={-12} cy={-14} r={20} fill={`url(#${specId})`} opacity={offline ? 0.52 : 1} />
    </Svg>
  );
}
const CoreGlowAndBody = memo(CoreGlowAndBodyBase);

function OuterOrbitRingBase({ size, color, offline }: { size: number; color: string; offline: boolean }) {
  return (
    <Svg width={size} height={size} viewBox="-130 -130 260 260">
      <Circle
        cx={0}
        cy={0}
        r={98}
        fill="none"
        stroke={color}
        strokeOpacity={offline ? 0.14 : 0.28}
        strokeWidth={1}
        strokeDasharray="2 7"
      />
    </Svg>
  );
}
const OuterOrbitRing = memo(OuterOrbitRingBase);

function InnerOrbitRingBase({ size, color, offline }: { size: number; color: string; offline: boolean }) {
  return (
    <Svg width={size} height={size} viewBox="-130 -130 260 260">
      <Circle
        cx={0}
        cy={0}
        r={76}
        fill="none"
        stroke={color}
        strokeOpacity={offline ? 0.08 : 0.22}
        strokeWidth={1.2}
        strokeDasharray="34 44"
      />
    </Svg>
  );
}
const InnerOrbitRing = memo(InnerOrbitRingBase);

function PulseRingSvgBase({ size, color }: { size: number; color: string }) {
  return (
    <Svg width={size} height={size} viewBox="-130 -130 260 260">
      <Circle cx={0} cy={0} r={48} fill="none" stroke={color} strokeWidth={1.8} />
    </Svg>
  );
}
const PulseRingSvg = memo(PulseRingSvgBase);

interface SakuraCoreProps {
  state: CoreVisualState;
  size?: number;
}

const SakuraCoreBase: React.FC<SakuraCoreProps> = ({ state, size = 128 }) => {
  const [isFocused, setIsFocused] = useState(true);
  const [appActive, setAppActive] = useState(AppState.currentState === 'active');

  useFocusEffect(
    useCallback(() => {
      setIsFocused(true);
      return () => setIsFocused(false);
    }, [])
  );

  useEffect(() => {
    const sub = AppState.addEventListener('change', (s) => {
      setAppActive(s === 'active');
    });
    return () => sub.remove();
  }, []);

  const active = isFocused && appActive;
  const offline = state === 'offline';
  const style = CORE_STATE_STYLE[state] || CORE_STATE_STYLE.idle;

  const outerDeg = useSharedValue(0);
  const innerDeg = useSharedValue(0);
  const breathe = useSharedValue(1);
  const pulse = useSharedValue(0);

  useEffect(() => {
    if (!active) {
      cancelAnimation(outerDeg);
      cancelAnimation(innerDeg);
      cancelAnimation(breathe);
      cancelAnimation(pulse);
      return;
    }

    const outerMs = state === 'thinking' ? 7500 : offline ? 42000 : 22000;
    const innerMs = state === 'thinking' ? 5200 : offline ? 34000 : 15000;
    const breatheMs = state === 'speaking' ? 420 : state === 'listening' ? 850 : 2200;
    const breatheAmp = state === 'speaking' ? 1.07 : state === 'listening' ? 1.05 : offline ? 1.01 : 1.03;

    outerDeg.value = 0;
    outerDeg.value = withRepeat(
      withTiming(360, { duration: outerMs, easing: Easing.linear }),
      -1,
      false
    );

    innerDeg.value = 360;
    innerDeg.value = withRepeat(
      withTiming(0, { duration: innerMs, easing: Easing.linear }),
      -1,
      false
    );

    breathe.value = withRepeat(
      withSequence(
        withTiming(breatheAmp, { duration: breatheMs, easing: Easing.inOut(Easing.sin) }),
        withTiming(1, { duration: breatheMs, easing: Easing.inOut(Easing.sin) })
      ),
      -1,
      false
    );

    if (!offline) {
      const pulseMs = state === 'listening' || state === 'speaking' ? 1300 : 3400;
      pulse.value = 0;
      pulse.value = withRepeat(
        withTiming(1, { duration: pulseMs, easing: Easing.out(Easing.quad) }),
        -1,
        false
      );
    } else {
      cancelAnimation(pulse);
      pulse.value = 0;
    }
  }, [active, state, offline, outerDeg, innerDeg, breathe, pulse]);

  const outerStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${outerDeg.value}deg` }],
  }));

  const innerStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${innerDeg.value}deg` }],
  }));

  const bodyStyle = useAnimatedStyle(() => ({
    transform: [{ scale: breathe.value }],
  }));

  const pulseStyle = useAnimatedStyle(() => {
    const sc = 1 + pulse.value * (state === 'listening' || state === 'speaking' ? 0.72 : 0.45);
    const op = offline ? 0 : (1 - pulse.value) * (state === 'listening' || state === 'speaking' ? 0.55 : 0.24);
    return {
      opacity: op,
      transform: [{ scale: sc }],
    };
  });

  return (
    <View style={[styles.wrap, { width: size, height: size }]}>
      <Animated.View style={[StyleSheet.absoluteFill, pulseStyle]} pointerEvents="none">
        <PulseRingSvg size={size} color={style.color} />
      </Animated.View>
      <Animated.View style={[StyleSheet.absoluteFill, outerStyle]} pointerEvents="none">
        <OuterOrbitRing size={size} color={style.color} offline={offline} />
      </Animated.View>
      <Animated.View style={[StyleSheet.absoluteFill, innerStyle]} pointerEvents="none">
        <InnerOrbitRing size={size} color={style.color} offline={offline} />
      </Animated.View>
      <Animated.View style={[StyleSheet.absoluteFill, bodyStyle]} pointerEvents="none">
        <CoreGlowAndBody size={size} color={style.color} deep={style.deep} offline={offline} />
      </Animated.View>
    </View>
  );
};

export const SakuraCore = memo(SakuraCoreBase);

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});

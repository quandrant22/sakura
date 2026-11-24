/**
 * AppShell — премиальный живой фон «Sakura Noir Luxe» на всех экранах
 * с динамической авророй под выбранный цветовой акцент темы.
 */

import React, { useSyncExternalStore } from 'react';
import { Platform, StyleSheet, useWindowDimensions, View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, RadialGradient, Rect, Stop } from 'react-native-svg';
import { SakuraColors } from '../../constants/colors';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

const emptySubscribe = () => () => {};

function useIsHydrated() {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );
}

const AmbientBackdrop: React.FC<{ accent: string }> = ({ accent }) => (
  <View pointerEvents="none" style={StyleSheet.absoluteFill}>
    <Svg width="100%" height="100%" preserveAspectRatio="none" viewBox="0 0 400 800">
      <Defs>
        <LinearGradient id="bgBase" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor="#090512" />
          <Stop offset="0.55" stopColor="#06040B" />
          <Stop offset="1" stopColor="#040207" />
        </LinearGradient>
        <RadialGradient id="glowTop" cx="200" cy="70" r="260" gradientUnits="userSpaceOnUse">
          <Stop offset="0" stopColor={accent} stopOpacity="0.16" />
          <Stop offset="0.55" stopColor="#3E0074" stopOpacity="0.10" />
          <Stop offset="1" stopColor="#06040B" stopOpacity="0" />
        </RadialGradient>
        <RadialGradient id="glowBottom" cx="340" cy="720" r="240" gradientUnits="userSpaceOnUse">
          <Stop offset="0" stopColor="#5CE1FF" stopOpacity="0.09" />
          <Stop offset="0.6" stopColor="#260A4A" stopOpacity="0.08" />
          <Stop offset="1" stopColor="#06040B" stopOpacity="0" />
        </RadialGradient>
      </Defs>
      <Rect x="0" y="0" width="400" height="800" fill="url(#bgBase)" />
      <Circle cx="200" cy="70" r="260" fill="url(#glowTop)" />
      <Circle cx="340" cy="720" r="240" fill="url(#glowBottom)" />
    </Svg>
  </View>
);

export const AppShell: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { width } = useWindowDimensions();
  const hydrated = useIsHydrated();
  const accentId = usePhoneSettingsStore((s) => s.accentTheme);
  const accent = ACCENT_THEMES[accentId].accent;
  const isWide = (Platform.OS !== 'web' || hydrated) && width > 540;

  if (!isWide) {
    return (
      <View style={styles.mobileFull}>
        <AmbientBackdrop accent={accent} />
        {children}
      </View>
    );
  }

  return (
    <View style={styles.desktopBackdrop}>
      <View style={styles.ambientGlowTop} />
      <View style={styles.ambientGlowBottom} />
      <View style={styles.phoneFrame}>
        <AmbientBackdrop accent={accent} />
        {children}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  mobileFull: {
    flex: 1,
    backgroundColor: SakuraColors.bg,
  },
  desktopBackdrop: {
    flex: 1,
    backgroundColor: '#040207',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  ambientGlowTop: {
    position: 'absolute',
    top: -140,
    width: 520,
    height: 360,
    borderRadius: 260,
    backgroundColor: 'rgba(255, 106, 227, 0.08)',
  },
  ambientGlowBottom: {
    position: 'absolute',
    bottom: -160,
    width: 480,
    height: 340,
    borderRadius: 240,
    backgroundColor: 'rgba(62, 0, 116, 0.16)',
  },
  phoneFrame: {
    flex: 1,
    width: '100%',
    maxWidth: 450,
    maxHeight: 920,
    backgroundColor: SakuraColors.bg,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: SakuraColors.lineStrong,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 18 },
    shadowOpacity: 0.65,
    shadowRadius: 36,
    overflow: 'hidden',
  },
});

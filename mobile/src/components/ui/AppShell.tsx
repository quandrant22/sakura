/**
 * AppShell — адаптивная оболочка: на телефоне во весь экран,
 * на широком экране/браузере — аккуратный центрированный мобильный терминал.
 */

import React, { useSyncExternalStore } from 'react';
import { Platform, StyleSheet, useWindowDimensions, View } from 'react-native';
import { SakuraColors } from '../../constants/colors';

const emptySubscribe = () => () => {};

function useIsHydrated() {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );
}

export const AppShell: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { width } = useWindowDimensions();
  const hydrated = useIsHydrated();
  const isWide = (Platform.OS !== 'web' || hydrated) && width > 540;

  if (!isWide) {
    return <View style={styles.mobileFull}>{children}</View>;
  }

  return (
    <View style={styles.desktopBackdrop}>
      <View style={styles.ambientGlowTop} />
      <View style={styles.ambientGlowBottom} />
      <View style={styles.phoneFrame}>{children}</View>
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
    backgroundColor: '#050308',
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

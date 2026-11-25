/**
 * GlassCard — матовая стеклянная карточка с верхним спекулярным бликом и мягкой глубиной.
 */

import React, { memo } from 'react';
import { Platform, StyleProp, StyleSheet, View, ViewStyle } from 'react-native';
import { SakuraColors } from '../../constants/colors';

interface GlassCardProps {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  accent?: 'pink' | 'cyan' | 'warn' | 'none';
}

const ACCENT_STYLES: Record<NonNullable<GlassCardProps['accent']>, ViewStyle | null> = {
  pink: {
    borderColor: SakuraColors.borderAccent,
    borderTopColor: 'rgba(255, 160, 240, 0.32)',
    shadowColor: SakuraColors.pink,
    shadowOpacity: Platform.OS === 'android' ? 0 : 0.18,
  },
  cyan: {
    borderColor: SakuraColors.borderFocus,
    borderTopColor: 'rgba(130, 235, 255, 0.3)',
    shadowColor: SakuraColors.cyan,
    shadowOpacity: Platform.OS === 'android' ? 0 : 0.16,
  },
  warn: {
    borderColor: 'rgba(255, 189, 89, 0.42)',
  },
  none: null,
};

const GlassCardBase: React.FC<GlassCardProps> = ({ children, style, accent = 'none' }) => (
  <View style={[styles.card, ACCENT_STYLES[accent], style]}>{children}</View>
);

export const GlassCard = memo(GlassCardBase);

const styles = StyleSheet.create({
  card: {
    backgroundColor: SakuraColors.panel,
    borderRadius: 22,
    padding: 16,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    borderTopColor: SakuraColors.glassHighlight,
    ...(Platform.OS === 'android'
      ? { elevation: 2 }
      : {
          shadowColor: '#000',
          shadowOffset: { width: 0, height: 10 },
          shadowOpacity: 0.5,
          shadowRadius: 20,
        }),
  },
});

/**
 * GlassCard — матовая стеклянная карточка с верхним спекулярным бликом и мягкой глубиной.
 */

import React from 'react';
import { StyleProp, StyleSheet, View, ViewStyle } from 'react-native';
import { SakuraColors } from '../../constants/colors';

interface GlassCardProps {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  accent?: 'pink' | 'cyan' | 'warn' | 'none';
}

export const GlassCard: React.FC<GlassCardProps> = ({ children, style, accent = 'none' }) => {
  const accentStyle =
    accent === 'pink'
      ? {
          borderColor: SakuraColors.borderAccent,
          borderTopColor: 'rgba(255, 160, 240, 0.32)',
          shadowColor: SakuraColors.pink,
          shadowOpacity: 0.18,
        }
      : accent === 'cyan'
      ? {
          borderColor: SakuraColors.borderFocus,
          borderTopColor: 'rgba(130, 235, 255, 0.3)',
          shadowColor: SakuraColors.cyan,
          shadowOpacity: 0.16,
        }
      : accent === 'warn'
      ? { borderColor: 'rgba(255, 189, 89, 0.42)' }
      : null;

  return <View style={[styles.card, accentStyle, style]}>{children}</View>;
};

const styles = StyleSheet.create({
  card: {
    backgroundColor: SakuraColors.panel,
    borderRadius: 22,
    padding: 16,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    borderTopColor: SakuraColors.glassHighlight,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.5,
    shadowRadius: 20,
    elevation: 8,
  },
});

/**
 * GlassCard — карточка в стиле «Сакура-ночь» (card-depth: мягкая глубина и верхний блик).
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
      ? { borderColor: SakuraColors.borderAccent }
      : accent === 'cyan'
      ? { borderColor: SakuraColors.borderFocus }
      : accent === 'warn'
      ? { borderColor: 'rgba(255, 184, 77, 0.4)' }
      : null;

  return <View style={[styles.card, accentStyle, style]}>{children}</View>;
};

const styles = StyleSheet.create({
  card: {
    backgroundColor: SakuraColors.panel,
    borderRadius: 20,
    padding: 16,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    borderTopColor: 'rgba(255, 255, 255, 0.12)',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.45,
    shadowRadius: 16,
    elevation: 6,
  },
});

/**
 * Палитра «Сакура-ночь» (синхронизирована с desktop/docs/UI.md и desktop/ui/src/index.css).
 */

import { SakuraState } from '../api/types';

export const SakuraColors = {
  // Основные фоны («Сакура-ночь»)
  bg: '#0a0610',
  bgDeep: '#0a0610',
  bar: '#0a0610',
  panel: '#14101c',
  panel2: '#1d1628',
  bgCard: '#14101c',
  bgCardHover: '#1d1628',
  bgInput: '#1d1628',

  // Границы и разделители
  line: 'rgba(255, 255, 255, 0.07)',
  lineStrong: 'rgba(255, 255, 255, 0.12)',
  borderSubtle: 'rgba(255, 255, 255, 0.07)',
  borderAccent: 'rgba(255, 106, 227, 0.35)',
  borderFocus: 'rgba(79, 216, 255, 0.45)',

  // Акценты бренда
  accent: '#FF6AE3',
  accentDeep: '#3E0074',
  accentSoft: 'rgba(255, 106, 227, 0.16)',
  accentBubble: 'rgba(255, 106, 227, 0.08)',
  pink: '#FF6AE3',
  pinkLight: '#FF7EB9',
  pinkMuted: 'rgba(255, 106, 227, 0.16)',
  pinkGlow: 'rgba(255, 106, 227, 0.35)',

  // Состояния и вспомогательные цвета
  cyan: '#4FD8FF',
  cyanMuted: 'rgba(79, 216, 255, 0.14)',
  purple: '#3E0074',
  purpleMuted: 'rgba(62, 0, 116, 0.35)',
  gold: '#FFCF6B',

  // Статусы
  online: '#3ddc97',
  onlineSoft: 'rgba(61, 220, 151, 0.14)',
  warn: '#ffb84d',
  warnSoft: 'rgba(255, 184, 77, 0.14)',
  connecting: '#FFCF6B',
  error: '#ff5c7c',
  errorSoft: 'rgba(255, 92, 124, 0.14)',
  offline: '#6B6475',

  // Типографика
  ink: '#f1e9f5',
  inkDim: '#9b8fa8',
  textPrimary: '#f1e9f5',
  textSecondary: '#9b8fa8',
  textMuted: '#6B6475',
  textAccent: '#FF6AE3',
} as const;

export interface CoreStateTheme {
  color: string;
  deep: string;
  glow: string;
  kana: string;
  label: string;
}

export const CORE_STATE_STYLE: Record<SakuraState | 'offline', CoreStateTheme> = {
  idle: { color: '#FF6AE3', deep: '#3E0074', glow: 'rgba(255,106,227,0.35)', kana: '待機中', label: 'Онлайн' },
  listening: { color: '#4FD8FF', deep: '#1B2A8F', glow: 'rgba(79,216,255,0.45)', kana: '聴取中', label: 'Слушаю' },
  thinking: { color: '#FFCF6B', deep: '#6B1F7A', glow: 'rgba(255,207,107,0.40)', kana: '思考中', label: 'Думаю' },
  speaking: { color: '#FF7EB9', deep: '#5A0F8C', glow: 'rgba(255,126,185,0.50)', kana: '発話中', label: 'Говорю' },
  offline: { color: '#6B6475', deep: '#1D1628', glow: 'rgba(107,100,117,0.20)', kana: '切断', label: 'Нет связи' },
};

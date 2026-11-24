/**
 * Палитра «Sakura Noir Luxe» (глубокий ночной обсидиан, стеклянные поверхности и неоновый шелк).
 */

import { SakuraState } from '../api/types';

export const SakuraColors = {
  // Основные фоны
  bg: '#06040B',
  bgDeep: '#040208',
  bar: '#0B0814',
  panel: 'rgba(20, 15, 32, 0.78)',
  panelSolid: '#140F20',
  panel2: 'rgba(30, 23, 46, 0.88)',
  panel2Solid: '#1E172E',
  bgCard: 'rgba(20, 15, 32, 0.78)',
  bgCardHover: 'rgba(32, 24, 50, 0.9)',
  bgInput: '#161124',

  // Границы и блики стекла
  line: 'rgba(255, 255, 255, 0.08)',
  lineStrong: 'rgba(255, 255, 255, 0.14)',
  glassHighlight: 'rgba(255, 255, 255, 0.17)',
  borderSubtle: 'rgba(255, 255, 255, 0.08)',
  borderAccent: 'rgba(255, 106, 227, 0.42)',
  borderFocus: 'rgba(79, 216, 255, 0.55)',

  // Акценты бренда
  accent: '#FF6AE3',
  accentDeep: '#3E0074',
  accentSoft: 'rgba(255, 106, 227, 0.16)',
  accentBubble: 'rgba(255, 106, 227, 0.09)',
  pink: '#FF6AE3',
  pinkLight: '#FF8AC8',
  pinkMuted: 'rgba(255, 106, 227, 0.16)',
  pinkGlow: 'rgba(255, 106, 227, 0.35)',

  // Состояния и дополнительные цвета
  cyan: '#5CE1FF',
  cyanMuted: 'rgba(92, 225, 255, 0.14)',
  purple: '#4B1696',
  purpleMuted: 'rgba(75, 22, 150, 0.38)',
  gold: '#FFD373',

  // Статусы
  online: '#3EE5A2',
  onlineSoft: 'rgba(62, 229, 162, 0.14)',
  warn: '#FFBD59',
  warnSoft: 'rgba(255, 189, 89, 0.14)',
  connecting: '#FFD373',
  error: '#FF5C82',
  errorSoft: 'rgba(255, 92, 130, 0.15)',
  offline: '#706782',

  // Типографика
  ink: '#F8F4FF',
  inkDim: '#A69BB8',
  textPrimary: '#F8F4FF',
  textSecondary: '#A69BB8',
  textMuted: '#6D6380',
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
  idle: { color: '#FF6AE3', deep: '#3E0074', glow: 'rgba(255,106,227,0.38)', kana: '待機中', label: 'Онлайн' },
  listening: { color: '#5CE1FF', deep: '#1A2D9C', glow: 'rgba(92,225,255,0.48)', kana: '聴取中', label: 'Слушаю' },
  thinking: { color: '#FFD373', deep: '#742282', glow: 'rgba(255,211,115,0.42)', kana: '思考中', label: 'Думаю' },
  speaking: { color: '#FF8AC8', deep: '#621299', glow: 'rgba(255,138,200,0.52)', kana: '発話中', label: 'Говорю' },
  offline: { color: '#706782', deep: '#1D1628', glow: 'rgba(112,103,130,0.22)', kana: '切断', label: 'Нет связи' },
};

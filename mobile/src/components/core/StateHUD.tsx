/**
 * StateHUD — верхняя панель бренда SAKURA, ядро состояния и статус защищённого канала.
 */

import { Lock, LockOpen, ShieldAlert } from 'lucide-react-native';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { LinkInfo, SakuraState, SakuraStatus } from '../../api/types';
import { CORE_STATE_STYLE, SakuraColors } from '../../constants/colors';
import { CoreVisualState, SakuraCore } from './SakuraCore';
import { SakuraLogo } from './SakuraLogo';

interface StateHUDProps {
  sakuraState: SakuraState;
  status: SakuraStatus;
  linkInfo: LinkInfo;
  onPressStatus?: () => void;
}

export const StateHUD: React.FC<StateHUDProps> = ({
  sakuraState,
  status,
  linkInfo,
  onPressStatus,
}) => {
  const isConnected = linkInfo.state === 'connected';
  const visualState: CoreVisualState = isConnected ? sakuraState : 'offline';
  const theme = CORE_STATE_STYLE[visualState];

  const badgeColor =
    linkInfo.state === 'connected'
      ? linkInfo.secure
        ? SakuraColors.online
        : SakuraColors.cyan
      : linkInfo.state === 'connecting'
      ? SakuraColors.gold
      : SakuraColors.warn;

  const badgeLabel =
    linkInfo.state === 'connected'
      ? linkInfo.secure
        ? 'Noise IK'
        : 'WSS'
      : linkInfo.state === 'connecting'
      ? 'Связь…'
      : linkInfo.state === 'pairing_required'
      ? 'Нужен /pair'
      : 'Нет связи';

  return (
    <View style={styles.wrapper}>
      {/* Верхняя полоса: логотип и статус */}
      <View style={styles.topBar}>
        <View style={styles.brandRow}>
          <SakuraLogo size={24} />
          <Text style={styles.brandTitle}>SAKURA</Text>
          {status?.tone ? (
            <View style={styles.toneChip}>
              <Text style={styles.toneText}>{status.tone}</Text>
            </View>
          ) : null}
        </View>

        <Pressable
          style={({ pressed }) => [
            styles.linkPill,
            { borderColor: badgeColor + '55', backgroundColor: badgeColor + '16' },
            pressed && { opacity: 0.75 },
          ]}
          onPress={onPressStatus}>
          {linkInfo.state === 'connected' ? (
            linkInfo.secure ? (
              <Lock size={12} color={badgeColor} />
            ) : (
              <LockOpen size={12} color={badgeColor} />
            )
          ) : (
            <ShieldAlert size={12} color={badgeColor} />
          )}
          <Text style={[styles.linkPillText, { color: badgeColor }]}>{badgeLabel}</Text>
        </Pressable>
      </View>

      {/* Компактная карточка живого ядра */}
      <View style={styles.coreCard}>
        <SakuraCore state={visualState} size={96} />
        <View style={styles.coreMeta}>
          <View style={styles.stateHeader}>
            <View style={[styles.stateDot, { backgroundColor: theme.color }]} />
            <Text style={styles.stateLabel}>{theme.label}</Text>
            <Text style={[styles.kanaBadge, { color: theme.color }]}>{theme.kana}</Text>
          </View>
          <Text style={styles.subText} numberOfLines={2}>
            {isConnected
              ? status?.quote || status?.context || 'Готова к диалогу и командам'
              : linkInfo.reason || 'Настройте защищённое соединение во вкладке Связь'}
          </Text>
        </View>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  wrapper: {
    paddingHorizontal: 14,
    paddingTop: 6,
    paddingBottom: 10,
    backgroundColor: SakuraColors.bg,
    borderBottomWidth: 1,
    borderBottomColor: SakuraColors.line,
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  brandRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  brandTitle: {
    color: SakuraColors.ink,
    fontSize: 15,
    fontWeight: '800',
    letterSpacing: 2.2,
  },
  toneChip: {
    backgroundColor: SakuraColors.accentSoft,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
  },
  toneText: {
    color: SakuraColors.accent,
    fontSize: 11,
    fontWeight: '600',
  },
  linkPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    borderWidth: 1,
  },
  linkPillText: {
    fontSize: 11,
    fontWeight: '700',
  },
  coreCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: SakuraColors.panel,
    borderRadius: 20,
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    borderTopColor: 'rgba(255, 255, 255, 0.12)',
    gap: 10,
  },
  coreMeta: {
    flex: 1,
    gap: 4,
  },
  stateHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
  },
  stateDot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
  },
  stateLabel: {
    color: SakuraColors.ink,
    fontSize: 15,
    fontWeight: '700',
  },
  kanaBadge: {
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1,
    opacity: 0.9,
  },
  subText: {
    color: SakuraColors.inkDim,
    fontSize: 12,
    lineHeight: 16,
  },
});

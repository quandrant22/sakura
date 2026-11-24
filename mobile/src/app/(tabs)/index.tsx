/**
 * Главный экран «Ядро Сакуры» — чистая сфера присутствия, последний ответ
 * и голосовой ввод без дублирования кнопок нижней панели.
 */

import * as Haptics from 'expo-haptics';
import { useRouter } from 'expo-router';
import {
  KeyRound,
  Mic,
  Volume2,
  VolumeX,
  WifiOff,
} from 'lucide-react-native';
import React, { useEffect } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CoreVisualState, SakuraCore } from '../../components/core/SakuraCore';
import { SakuraLogo } from '../../components/core/SakuraLogo';
import { GlassCard } from '../../components/ui/GlassCard';
import { CORE_STATE_STYLE, SakuraColors } from '../../constants/colors';
import { SakuraFonts } from '../../constants/fonts';
import { useVoiceRecorder } from '../../hooks/useVoiceRecorder';
import { useChatStore } from '../../stores/useChatStore';
import { useConnectionStore } from '../../stores/useConnectionStore';
import { useMusicStore } from '../../stores/useMusicStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

export default function CoreHubScreen() {
  const router = useRouter();
  const { linkState, linkInfo, init: initConnection, connect, serverUrl, token } =
    useConnectionStore();
  const {
    lastReply,
    sakuraState,
    status,
    isSending,
    bindEvents,
  } = useChatStore();
  const settings = usePhoneSettingsStore();
  const { loadCache } = useMusicStore();
  const { isRecording, micError, startRecording, stopAndSend } = useVoiceRecorder();

  const accent = ACCENT_THEMES[settings.accentTheme].accent;
  const isConnected = linkState === 'connected';
  const needsPairing = linkState === 'pairing_required';
  const visualState: CoreVisualState = isConnected
    ? isRecording
      ? 'listening'
      : sakuraState
    : 'offline';
  const stateTheme = CORE_STATE_STYLE[visualState];

  useEffect(() => {
    void initConnection();
    bindEvents();
    void loadCache();
  }, [initConnection, bindEvents, loadCache]);

  const haptic = (medium = false) => {
    if (!settings.hapticsEnabled) return;
    try {
      void Haptics.impactAsync(
        medium ? Haptics.ImpactFeedbackStyle.Medium : Haptics.ImpactFeedbackStyle.Light
      );
    } catch {}
  };

  const toggleVoiceMode = () => {
    haptic();
    void settings.update({ voiceRepliesEnabled: !settings.voiceRepliesEnabled });
  };

  const dotColor = isConnected
    ? linkInfo.secure
      ? SakuraColors.online
      : SakuraColors.cyan
    : linkState === 'connecting'
    ? SakuraColors.gold
    : SakuraColors.warn;

  const isReplaced = linkInfo.reason?.includes('заменено') || linkInfo.reason?.includes('сессия');

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      {/* Компактная шапка Ядра */}
      <View style={styles.topBar}>
        <View style={styles.brandGroup}>
          <SakuraLogo size={22} />
          <Text style={styles.brandText}>SAKURA</Text>
          <View style={[styles.statusDot, { backgroundColor: dotColor }]} />
          <Text style={styles.stateMicro}>
            {isConnected ? stateTheme.label : linkState === 'connecting' ? 'Связь…' : 'Оффлайн'}
          </Text>
        </View>

        <Pressable
          style={({ pressed }) => [
            styles.pillBtn,
            !settings.voiceRepliesEnabled && {
              borderColor: SakuraColors.lineStrong,
              backgroundColor: SakuraColors.panel2,
            },
            settings.voiceRepliesEnabled && {
              borderColor: accent + '55',
              backgroundColor: accent + '18',
            },
            pressed && { opacity: 0.75 },
          ]}
          onPress={toggleVoiceMode}>
          {settings.voiceRepliesEnabled ? (
            <Volume2 size={14} color={accent} />
          ) : (
            <VolumeX size={14} color={SakuraColors.inkDim} />
          )}
          <Text
            style={[
              styles.pillBtnText,
              { color: settings.voiceRepliesEnabled ? accent : SakuraColors.inkDim },
            ]}>
            {settings.voiceRepliesEnabled ? 'Голос' : 'Текст'}
          </Text>
        </Pressable>
      </View>

      {/* Баннер статуса связи */}
      {!isConnected && (
        <Pressable
          style={({ pressed }) => [
            styles.banner,
            needsPairing ? styles.bannerPairing : styles.bannerWarn,
            pressed && { opacity: 0.85 },
          ]}
          onPress={() => {
            if (isReplaced) {
              void connect(serverUrl, token);
            } else {
              router.push('/(tabs)/settings' as any);
            }
          }}>
          {needsPairing ? (
            <KeyRound size={14} color={accent} />
          ) : (
            <WifiOff size={14} color={SakuraColors.warn} />
          )}
          <Text
            style={[
              styles.bannerText,
              { color: needsPairing ? SakuraColors.ink : SakuraColors.warn },
            ]}
            numberOfLines={1}>
            {needsPairing
              ? 'Нужно спаривание (/pair в Telegram) →'
              : isReplaced
              ? 'Сессия заменена · Нажми чтобы вернуть связь'
              : linkInfo.reason || 'Нет связи · Настройки →'}
          </Text>
        </Pressable>
      )}

      {/* Чистая сцена Ядра: сфера + последний ответ + одна кнопка голоса */}
      <View style={styles.coreStage}>
        <View style={styles.orbCenter}>
          <SakuraCore state={visualState} size={224} />
          <Text style={[styles.orbKana, { color: stateTheme.color }]}>{stateTheme.kana}</Text>
          <Text style={styles.orbTitle}>{isRecording ? 'Слушаю тебя…' : stateTheme.label}</Text>
          <Text style={styles.orbQuote} numberOfLines={2}>
            {micError
              ? micError
              : isConnected
              ? status?.quote || status?.context || 'Удерживай микрофон для голосовой команды'
              : needsPairing
              ? 'Спарь телефон во вкладке Настройки'
              : 'Подключаюсь к серверу Сакуры…'}
          </Text>
        </View>

        <View style={styles.bottomZone}>
          {lastReply ? (
            <Pressable onPress={() => router.push('/(tabs)/chat' as any)}>
              <GlassCard style={styles.replyPreviewCard}>
                <View style={styles.replyHeader}>
                  <Text style={[styles.replyBadge, { color: accent }]}>Последний ответ</Text>
                  <Text style={styles.replyLink}>Открыть чат →</Text>
                </View>
                <Text style={styles.replyPreviewText} numberOfLines={3}>
                  {lastReply}
                </Text>
              </GlassCard>
            </Pressable>
          ) : null}

          <Pressable
            onPressIn={() => {
              haptic(true);
              void startRecording();
            }}
            onPressOut={() => {
              void stopAndSend();
            }}
            disabled={!isConnected || isSending}
            style={({ pressed }) => [
              styles.pttBtn,
              {
                borderColor: isRecording ? accent : accent + '55',
                backgroundColor: isRecording ? accent : accent + '1C',
                opacity: !isConnected ? 0.45 : pressed ? 0.9 : 1,
              },
            ]}>
            <Mic size={22} color={isRecording ? '#fff' : accent} />
            <Text style={[styles.pttText, isRecording && { color: '#fff' }]}>
              {isRecording
                ? 'Говори… отпусти чтобы отправить'
                : isSending
                ? 'Думаю…'
                : 'Удерживай, чтобы сказать'}
            </Text>
          </Pressable>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: SakuraColors.bg,
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: SakuraColors.line,
  },
  brandGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  brandText: {
    fontFamily: SakuraFonts.displayExtra,
    fontSize: 15,
    color: SakuraColors.ink,
    letterSpacing: 2.2,
  },
  statusDot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
  },
  stateMicro: {
    fontSize: 12,
    color: SakuraColors.inkDim,
    fontWeight: '500',
  },
  pillBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
  },
  pillBtnText: {
    fontSize: 11.5,
    fontWeight: '700',
  },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 14,
    marginTop: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 12,
    borderWidth: 1,
  },
  bannerPairing: {
    backgroundColor: SakuraColors.accentSoft,
    borderColor: SakuraColors.borderAccent,
  },
  bannerWarn: {
    backgroundColor: SakuraColors.warnSoft,
    borderColor: 'rgba(255, 184, 77, 0.35)',
  },
  bannerText: {
    flex: 1,
    fontSize: 12,
    fontWeight: '600',
  },
  coreStage: {
    flex: 1,
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 18,
  },
  orbCenter: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  orbKana: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 3,
    marginTop: 4,
  },
  orbTitle: {
    fontSize: 22,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  orbQuote: {
    fontSize: 13,
    color: SakuraColors.inkDim,
    textAlign: 'center',
    maxWidth: '88%',
    lineHeight: 18,
  },
  bottomZone: {
    gap: 12,
  },
  replyPreviewCard: {
    gap: 6,
    paddingVertical: 12,
  },
  replyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  replyBadge: {
    fontSize: 11.5,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  replyLink: {
    fontSize: 11.5,
    color: SakuraColors.inkDim,
    fontWeight: '600',
  },
  replyPreviewText: {
    fontSize: 13.5,
    lineHeight: 19,
    color: SakuraColors.ink,
  },
  pttBtn: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    paddingVertical: 15,
    paddingHorizontal: 18,
    borderRadius: 20,
    borderWidth: 1.5,
  },
  pttText: {
    fontSize: 14,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
});

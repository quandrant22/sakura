/**
 * Главный экран «Ядро Сакуры» — живое присутствие класса флагмана:
 * стеклянная верхняя консоль, квантовое Ядро, превью последнего ответа и тактильный Voice Dock.
 */

import * as Haptics from 'expo-haptics';
import { useRouter } from 'expo-router';
import {
  Ear,
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
import { useWakeControlStore } from '../../hooks/useWakeControlStore';
import { useChatStore } from '../../stores/useChatStore';
import { useConnectionStore } from '../../stores/useConnectionStore';
import { useMusicStore } from '../../stores/useMusicStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

export default function CoreHubScreen() {
  const router = useRouter();
  const linkState = useConnectionStore((s) => s.linkState);
  const linkInfo = useConnectionStore((s) => s.linkInfo);
  const initConnection = useConnectionStore((s) => s.init);
  const connect = useConnectionStore((s) => s.connect);
  const serverUrl = useConnectionStore((s) => s.serverUrl);
  const token = useConnectionStore((s) => s.token);

  const lastReply = useChatStore((s) => s.lastReply);
  const sakuraState = useChatStore((s) => s.sakuraState);
  const status = useChatStore((s) => s.status);
  const isSending = useChatStore((s) => s.isSending);
  const bindEvents = useChatStore((s) => s.bindEvents);

  const settings = usePhoneSettingsStore();
  const loadCache = useMusicStore((s) => s.loadCache);
  const { isRecording, micError, startRecording, stopAndSend } = useVoiceRecorder();
  const wakeStatus = useWakeControlStore((s) => s.wakeStatus);

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

  const toggleWakeWord = () => {
    haptic();
    void settings.update({ handsFreeMode: !settings.handsFreeMode });
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
      {/* Парящая стеклянная шапка */}
      <View style={styles.topBar}>
        <View style={styles.brandChip}>
          <SakuraLogo size={20} />
          <Text style={styles.brandText}>SAKURA</Text>
          <View style={styles.dividerV} />
          <View style={[styles.statusDot, { backgroundColor: dotColor }]} />
          <Text style={styles.stateMicro}>
            {isConnected ? stateTheme.label : linkState === 'connecting' ? 'Связь…' : 'Оффлайн'}
          </Text>
        </View>

        <View style={{ flexDirection: 'row', gap: 6 }}>
          <Pressable
            style={({ pressed }) => [
              styles.pillBtn,
              !settings.handsFreeMode
                ? { borderColor: SakuraColors.lineStrong, backgroundColor: SakuraColors.panel }
                : { borderColor: SakuraColors.cyan + '66', backgroundColor: 'rgba(92,225,255,0.16)' },
              pressed && { opacity: 0.78 },
            ]}
            onPress={toggleWakeWord}>
            <Ear
              size={14}
              color={
                wakeStatus === 'listening'
                  ? SakuraColors.online
                  : settings.handsFreeMode
                  ? SakuraColors.cyan
                  : SakuraColors.inkDim
              }
            />
            <Text
              style={[
                styles.pillBtnText,
                {
                  color: settings.handsFreeMode ? SakuraColors.cyan : SakuraColors.inkDim,
                },
              ]}>
              {wakeStatus === 'listening'
                ? 'Сакура'
                : wakeStatus === 'unsupported'
                ? 'Вейк APK'
                : 'Вейк'}
            </Text>
          </Pressable>

          <Pressable
            style={({ pressed }) => [
              styles.pillBtn,
              !settings.voiceRepliesEnabled && {
                borderColor: SakuraColors.lineStrong,
                backgroundColor: SakuraColors.panel,
              },
              settings.voiceRepliesEnabled && {
                borderColor: accent + '66',
                backgroundColor: accent + '1C',
              },
              pressed && { opacity: 0.78 },
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

      {/* Сцена Ядра */}
      <View style={styles.coreStage}>
        <View style={styles.orbCenter}>
          <SakuraCore state={visualState} size={244} />
          <View style={styles.coreMeta}>
            <Text style={[styles.orbKana, { color: stateTheme.color }]}>{stateTheme.kana}</Text>
            <Text style={styles.orbTitle}>
              {isRecording ? 'Слушаю тебя…' : stateTheme.label}
            </Text>
            <Text style={styles.orbQuote} numberOfLines={2}>
              {micError
                ? micError
                : isConnected
                ? wakeStatus === 'listening'
                  ? 'Скажи «Сакура», чтобы задать вопрос…'
                  : status?.quote || status?.context || 'Готова к диалогу и командам'
                : needsPairing
                ? 'Спарь телефон во вкладке Настройки'
                : 'Подключаюсь к серверу Сакуры…'}
            </Text>
          </View>
        </View>

        <View style={styles.bottomZone}>
          {lastReply ? (
            <Pressable onPress={() => router.push('/(tabs)/chat' as any)}>
              <GlassCard style={[styles.replyPreviewCard, { borderLeftColor: accent }]} accent="pink">
                <View style={styles.replyHeader}>
                  <Text style={[styles.replyBadge, { color: accent }]}>Последний ответ</Text>
                  <Text style={styles.replyLink}>В чат →</Text>
                </View>
                <Text style={styles.replyPreviewText} numberOfLines={5}>
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
              styles.pttOuter,
              {
                borderColor: isRecording ? SakuraColors.cyan : accent + '66',
                backgroundColor: isRecording ? 'rgba(92, 225, 255, 0.2)' : 'rgba(20, 14, 34, 0.88)',
                shadowColor: isRecording ? SakuraColors.cyan : accent,
                opacity: !isConnected ? 0.45 : pressed ? 0.92 : 1,
                transform: [{ scale: pressed || isRecording ? 0.985 : 1 }],
              },
            ]}>
            <View
              style={[
                styles.pttIconWrap,
                {
                  backgroundColor: isRecording ? SakuraColors.cyan : accent + '26',
                  borderColor: isRecording ? SakuraColors.cyan : accent + '55',
                },
              ]}>
              <Mic size={20} color={isRecording ? '#06040B' : accent} />
            </View>
            <Text style={styles.pttText}>
              {isRecording
                ? 'Говори… отпусти чтобы отправить'
                : isSending
                ? 'Сакура думает…'
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
    backgroundColor: 'transparent',
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 14,
    paddingTop: 10,
    paddingBottom: 6,
  },
  brandChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 999,
    backgroundColor: 'rgba(20, 15, 32, 0.78)',
    borderWidth: 1,
    borderColor: SakuraColors.lineStrong,
    borderTopColor: SakuraColors.glassHighlight,
  },
  brandText: {
    fontFamily: SakuraFonts.displayExtra,
    fontSize: 13.5,
    color: SakuraColors.ink,
    letterSpacing: 2.2,
  },
  dividerV: {
    width: 1,
    height: 12,
    backgroundColor: SakuraColors.lineStrong,
  },
  statusDot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
  },
  stateMicro: {
    fontSize: 11.5,
    color: SakuraColors.inkDim,
    fontWeight: '600',
  },
  pillBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderTopColor: SakuraColors.glassHighlight,
  },
  pillBtnText: {
    fontSize: 12,
    fontWeight: '700',
  },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 14,
    marginTop: 6,
    paddingHorizontal: 13,
    paddingVertical: 9,
    borderRadius: 14,
    borderWidth: 1,
  },
  bannerPairing: {
    backgroundColor: SakuraColors.accentSoft,
    borderColor: SakuraColors.borderAccent,
  },
  bannerWarn: {
    backgroundColor: SakuraColors.warnSoft,
    borderColor: 'rgba(255, 189, 89, 0.38)',
  },
  bannerText: {
    flex: 1,
    fontSize: 12,
    fontWeight: '600',
  },
  coreStage: {
    flex: 1,
    justifyContent: 'space-between',
    paddingHorizontal: 14,
    paddingTop: 6,
    paddingBottom: 14,
  },
  orbCenter: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  coreMeta: {
    alignItems: 'center',
    gap: 5,
    marginTop: -6,
  },
  orbKana: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 4,
  },
  orbTitle: {
    fontSize: 24,
    fontWeight: '800',
    color: SakuraColors.ink,
    letterSpacing: -0.3,
  },
  orbQuote: {
    fontSize: 13,
    color: SakuraColors.inkDim,
    textAlign: 'center',
    maxWidth: '86%',
    lineHeight: 19,
  },
  bottomZone: {
    gap: 12,
  },
  replyPreviewCard: {
    gap: 6,
    paddingVertical: 13,
    borderLeftWidth: 2.5,
  },
  replyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  replyBadge: {
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 1.1,
  },
  replyLink: {
    fontSize: 11.5,
    color: SakuraColors.inkDim,
    fontWeight: '600',
  },
  replyPreviewText: {
    fontSize: 14,
    lineHeight: 20,
    color: SakuraColors.ink,
  },
  pttOuter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 18,
    borderRadius: 24,
    borderWidth: 1.2,
    borderTopColor: SakuraColors.glassHighlight,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.32,
    shadowRadius: 16,
    elevation: 8,
  },
  pttIconWrap: {
    width: 38,
    height: 38,
    borderRadius: 19,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pttText: {
    fontSize: 14.5,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
});

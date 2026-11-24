/**
 * Dedicated Chat Screen — полная история диалога с Сакурой, быстрые подсказки
 * и Hold-to-Talk голосовой ввод отдельно от экрана Ядра.
 */

import * as Haptics from 'expo-haptics';
import { useRouter } from 'expo-router';
import {
  KeyRound,
  MessageCircleHeart,
  RefreshCw,
  Volume2,
  VolumeX,
  WifiOff,
} from 'lucide-react-native';
import React, { useEffect, useRef } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { InputToolbar } from '../../components/chat/InputToolbar';
import { MessageBubble } from '../../components/chat/MessageBubble';
import { CORE_STATE_STYLE, SakuraColors } from '../../constants/colors';
import { useVoiceRecorder } from '../../hooks/useVoiceRecorder';
import { useChatStore } from '../../stores/useChatStore';
import { useConnectionStore } from '../../stores/useConnectionStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

export default function ChatScreen() {
  const router = useRouter();
  const { linkState, linkInfo } = useConnectionStore();
  const {
    messages,
    sakuraState,
    isSending,
    isLoadingHistory,
    bindEvents,
    loadHistory,
    sendMessage,
  } = useChatStore();
  const settings = usePhoneSettingsStore();
  const { isRecording, micError, startRecording, stopAndSend } = useVoiceRecorder();

  const flatListRef = useRef<FlatList>(null);
  const accent = ACCENT_THEMES[settings.accentTheme].accent;
  const isConnected = linkState === 'connected';
  const needsPairing = linkState === 'pairing_required';
  const visualState = isConnected ? (isRecording ? 'listening' : sakuraState) : 'offline';
  const stateTheme = CORE_STATE_STYLE[visualState];

  useEffect(() => {
    bindEvents();
  }, [bindEvents]);

  useEffect(() => {
    if (messages.length > 0) {
      setTimeout(() => {
        flatListRef.current?.scrollToEnd({ animated: true });
      }, 90);
    }
  }, [messages.length]);

  const haptic = () => {
    if (!settings.hapticsEnabled) return;
    try {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch {}
  };

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      {/* Шапка чата */}
      <View style={styles.topBar}>
        <View style={styles.titleRow}>
          <MessageCircleHeart size={18} color={accent} />
          <Text style={styles.titleText}>Диалог</Text>
          <View style={[styles.dot, { backgroundColor: isConnected ? stateTheme.color : SakuraColors.warn }]} />
          <Text style={styles.stateLabel}>
            {isRecording ? 'Слушаю…' : isConnected ? stateTheme.label : 'Оффлайн'}
          </Text>
        </View>

        <View style={styles.actions}>
          <Pressable
            style={({ pressed }) => [
              styles.pillBtn,
              settings.voiceRepliesEnabled
                ? { borderColor: accent + '55', backgroundColor: accent + '18' }
                : { borderColor: SakuraColors.lineStrong, backgroundColor: SakuraColors.panel2 },
              pressed && { opacity: 0.75 },
            ]}
            onPress={() => {
              haptic();
              void settings.update({ voiceRepliesEnabled: !settings.voiceRepliesEnabled });
            }}>
            {settings.voiceRepliesEnabled ? (
              <Volume2 size={14} color={accent} />
            ) : (
              <VolumeX size={14} color={SakuraColors.inkDim} />
            )}
            <Text
              style={[
                styles.pillText,
                { color: settings.voiceRepliesEnabled ? accent : SakuraColors.inkDim },
              ]}>
              {settings.voiceRepliesEnabled ? 'Голос' : 'Текст'}
            </Text>
          </Pressable>

          <Pressable
            style={({ pressed }) => [styles.iconBtn, pressed && { opacity: 0.7 }]}
            onPress={() => {
              haptic();
              void loadHistory();
            }}>
            <RefreshCw size={15} color={isLoadingHistory ? accent : SakuraColors.inkDim} />
          </Pressable>
        </View>
      </View>

      {!isConnected && (
        <Pressable
          style={[styles.banner, needsPairing ? styles.bannerPairing : styles.bannerWarn]}
          onPress={() => router.push('/(tabs)/settings' as any)}>
          {needsPairing ? (
            <KeyRound size={14} color={accent} />
          ) : (
            <WifiOff size={14} color={SakuraColors.warn} />
          )}
          <Text style={styles.bannerText} numberOfLines={1}>
            {needsPairing
              ? 'Нужно спаривание (/pair в Telegram) →'
              : linkInfo.reason || 'Нет связи · Настройки →'}
          </Text>
        </Pressable>
      )}

      {micError ? <Text style={styles.micError}>{micError}</Text> : null}

      <FlatList
        ref={flatListRef}
        data={messages}
        keyExtractor={(item) => item.id || String(item.ts)}
        renderItem={({ item }) => <MessageBubble message={item} />}
        contentContainerStyle={messages.length === 0 ? styles.emptyContainer : styles.listContent}
        style={styles.list}
        ListEmptyComponent={
          <View style={styles.emptyBox}>
            <MessageCircleHeart size={32} color={SakuraColors.textMuted} />
            <Text style={styles.emptyTitle}>Чат пока пуст</Text>
            <Text style={styles.emptySub}>
              Напиши Сакуре сообщение снизу или удерживай микрофон
            </Text>
          </View>
        }
      />

      <InputToolbar
        onSendText={(t) => {
          void sendMessage(t, 'text');
        }}
        onVoiceStart={() => {
          void startRecording();
        }}
        onVoiceEnd={() => {
          void stopAndSend();
        }}
        isSending={isSending}
        showPrompts={isConnected && settings.showQuickPrompts}
      />
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
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  titleText: {
    fontSize: 16,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
  },
  stateLabel: {
    fontSize: 12,
    color: SakuraColors.inkDim,
  },
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
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
  pillText: {
    fontSize: 11.5,
    fontWeight: '700',
  },
  iconBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    alignItems: 'center',
    justifyContent: 'center',
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
    color: SakuraColors.ink,
  },
  micError: {
    color: SakuraColors.warn,
    fontSize: 12,
    textAlign: 'center',
    paddingTop: 6,
  },
  list: {
    flex: 1,
  },
  listContent: {
    paddingVertical: 12,
    paddingBottom: 18,
  },
  emptyContainer: {
    flexGrow: 1,
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  emptyBox: {
    alignItems: 'center',
    gap: 8,
  },
  emptyTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  emptySub: {
    fontSize: 13,
    color: SakuraColors.inkDim,
    textAlign: 'center',
    lineHeight: 18,
  },
});

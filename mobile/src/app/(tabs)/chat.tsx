/**
 * Dedicated Chat Screen — кристально видимая строка ввода над клавиатурой (Android/iOS/Expo Go),
 * живой стриминг текста и единая лента сообщений.
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
import React, { useEffect, useRef, useState } from 'react';
import {
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  LayoutChangeEvent,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
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
  const baseHeightRef = useRef(0);
  const currentHeightRef = useRef(0);
  const kbVisibleRef = useRef(false);
  const [androidKbPad, setAndroidKbPad] = useState(0);

  const accent = ACCENT_THEMES[settings.accentTheme].accent;
  const isConnected = linkState === 'connected';
  const needsPairing = linkState === 'pairing_required';
  const visualState = isConnected ? (isRecording ? 'listening' : sakuraState) : 'offline';
  const stateTheme = CORE_STATE_STYLE[visualState];

  useEffect(() => {
    bindEvents();
  }, [bindEvents]);

  const lastMsgText = messages[messages.length - 1]?.text;

  useEffect(() => {
    if (messages.length > 0) {
      setTimeout(() => {
        flatListRef.current?.scrollToEnd({ animated: true });
      }, 60);
    }
  }, [messages.length, lastMsgText]);

  useEffect(() => {
    if (Platform.OS !== 'android') return;
    const onShow = Keyboard.addListener('keyboardDidShow', (e) => {
      kbVisibleRef.current = true;
      const kbHeight = e?.endCoordinates?.height || 0;
      setTimeout(() => {
        const base = baseHeightRef.current;
        const cur = currentHeightRef.current;
        const resizedByOs = base > 0 && cur > 0 && base - cur > kbHeight * 0.4;
        setAndroidKbPad(resizedByOs ? 0 : kbHeight);
        flatListRef.current?.scrollToEnd({ animated: true });
      }, 45);
    });
    const onHide = Keyboard.addListener('keyboardDidHide', () => {
      kbVisibleRef.current = false;
      setAndroidKbPad(0);
    });
    return () => {
      onShow.remove();
      onHide.remove();
    };
  }, []);

  const handleLayout = (ev: LayoutChangeEvent) => {
    const h = ev.nativeEvent.layout.height;
    currentHeightRef.current = h;
    if (!kbVisibleRef.current && h > baseHeightRef.current) {
      baseHeightRef.current = h;
    }
  };

  const haptic = () => {
    if (!settings.hapticsEnabled) return;
    try {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch {}
  };

  const chatBody = (
    <>
      {/* Шапка чата */}
      <View style={styles.topBar}>
        <View style={styles.titleChip}>
          <MessageCircleHeart size={16} color={accent} />
          <Text style={styles.titleText}>Диалог</Text>
          <View style={styles.dividerV} />
          <View
            style={[
              styles.dot,
              { backgroundColor: isConnected ? stateTheme.color : SakuraColors.warn },
            ]}
          />
          <Text style={styles.stateLabel}>
            {isRecording ? 'Слушаю…' : isConnected ? stateTheme.label : 'Оффлайн'}
          </Text>
        </View>

        <View style={styles.actions}>
          <Pressable
            style={({ pressed }) => [
              styles.pillBtn,
              settings.voiceRepliesEnabled
                ? { borderColor: accent + '66', backgroundColor: accent + '1C' }
                : { borderColor: SakuraColors.lineStrong, backgroundColor: SakuraColors.panel },
              pressed && { opacity: 0.78 },
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
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="interactive"
        contentContainerStyle={messages.length === 0 ? styles.emptyContainer : styles.listContent}
        style={styles.list}
        ListEmptyComponent={
          <View style={styles.emptyBox}>
            <View style={[styles.emptyIcon, { borderColor: accent + '44' }]}>
              <MessageCircleHeart size={28} color={accent} />
            </View>
            <Text style={styles.emptyTitle}>Начни диалог с Сакурой</Text>
            <Text style={styles.emptySub}>
              Напиши сообщение снизу или удерживай микрофон слева от поля
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
    </>
  );

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']} onLayout={handleLayout}>
      {Platform.OS === 'ios' ? (
        <KeyboardAvoidingView style={styles.flex1} behavior="padding" keyboardVerticalOffset={10}>
          {chatBody}
        </KeyboardAvoidingView>
      ) : (
        <View style={[styles.flex1, androidKbPad > 0 && { paddingBottom: androidKbPad }]}>
          {chatBody}
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  flex1: {
    flex: 1,
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 14,
    paddingTop: 10,
    paddingBottom: 8,
  },
  titleChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 999,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.lineStrong,
    borderTopColor: SakuraColors.glassHighlight,
  },
  titleText: {
    fontSize: 14,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  dividerV: {
    width: 1,
    height: 12,
    backgroundColor: SakuraColors.lineStrong,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
  },
  stateLabel: {
    fontSize: 11.5,
    color: SakuraColors.inkDim,
    fontWeight: '600',
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
    paddingHorizontal: 11,
    paddingVertical: 7,
    borderRadius: 999,
    borderWidth: 1,
    borderTopColor: SakuraColors.glassHighlight,
  },
  pillText: {
    fontSize: 12,
    fontWeight: '700',
  },
  iconBtn: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.lineStrong,
    alignItems: 'center',
    justifyContent: 'center',
  },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 14,
    marginBottom: 4,
    paddingHorizontal: 12,
    paddingVertical: 8,
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
    color: SakuraColors.ink,
  },
  micError: {
    color: SakuraColors.warn,
    fontSize: 12,
    textAlign: 'center',
    paddingTop: 4,
  },
  list: {
    flex: 1,
  },
  listContent: {
    paddingVertical: 10,
    paddingBottom: 14,
  },
  emptyContainer: {
    flexGrow: 1,
    justifyContent: 'center',
    paddingHorizontal: 28,
  },
  emptyBox: {
    alignItems: 'center',
    gap: 10,
  },
  emptyIcon: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
  },
  emptyTitle: {
    fontSize: 17,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  emptySub: {
    fontSize: 13,
    color: SakuraColors.inkDim,
    textAlign: 'center',
    lineHeight: 19,
  },
});

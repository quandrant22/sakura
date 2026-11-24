/**
 * InputToolbar — премиальная строка ввода сообщений с фокусом, быстрыми подсказками и PTT.
 * Намеренно не содержит внутреннего KeyboardAvoidingView: обёртка клавиатуры живёт на уровне ChatScreen.
 */

import * as Haptics from 'expo-haptics';
import { Mic, Send } from 'lucide-react-native';
import React, { useState } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SakuraColors } from '../../constants/colors';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

const QUICK_PROMPTS = ['Что у меня сегодня?', 'Погода', 'Включи музыку', 'Статус ПК'];

interface InputToolbarProps {
  onSendText: (text: string) => void;
  onVoiceStart: () => void;
  onVoiceEnd: () => void;
  isSending?: boolean;
  showPrompts?: boolean;
}

export const InputToolbar: React.FC<InputToolbarProps> = ({
  onSendText,
  onVoiceStart,
  onVoiceEnd,
  isSending = false,
  showPrompts = true,
}) => {
  const [text, setText] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [isFocused, setIsFocused] = useState(false);

  const accentId = usePhoneSettingsStore((s) => s.accentTheme);
  const hapticsEnabled = usePhoneSettingsStore((s) => s.hapticsEnabled);
  const accent = ACCENT_THEMES[accentId].accent;

  const haptic = (style = Haptics.ImpactFeedbackStyle.Light) => {
    if (!hapticsEnabled) return;
    try {
      void Haptics.impactAsync(style);
    } catch {}
  };

  const handleSend = (overrideText?: string) => {
    const val = (overrideText ?? text).trim();
    if (!val || isSending) return;
    haptic(Haptics.ImpactFeedbackStyle.Light);
    onSendText(val);
    if (!overrideText) setText('');
  };

  const handlePressIn = () => {
    haptic(Haptics.ImpactFeedbackStyle.Medium);
    setIsRecording(true);
    onVoiceStart();
  };

  const handlePressOut = () => {
    if (isRecording) {
      if (hapticsEnabled) {
        try {
          void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        } catch {}
      }
      setIsRecording(false);
      onVoiceEnd();
    }
  };

  const hasText = text.trim().length > 0;

  return (
    <View style={styles.wrapper}>
      {showPrompts && !isFocused && (
        <ScrollView
          horizontal
          keyboardShouldPersistTaps="handled"
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.promptsRow}>
          {QUICK_PROMPTS.map((prompt) => (
            <Pressable
              key={prompt}
              style={({ pressed }) => [styles.promptChip, pressed && { opacity: 0.72 }]}
              onPress={() => handleSend(prompt)}>
              <Text style={styles.promptText}>{prompt}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}

      <View
        style={[
          styles.bar,
          isFocused && { borderColor: accent + '88', backgroundColor: '#1B152A' },
          isRecording && { borderColor: SakuraColors.cyan, backgroundColor: '#141B2D' },
        ]}>
        <Pressable
          style={({ pressed }) => [
            styles.micButton,
            isRecording && styles.micRecording,
            pressed && styles.pressed,
          ]}
          onPressIn={handlePressIn}
          onPressOut={handlePressOut}>
          <Mic size={18} color={isRecording ? '#fff' : SakuraColors.cyan} />
        </Pressable>

        <TextInput
          style={styles.input}
          placeholder={isRecording ? 'Говорите…' : 'Написать Сакуре…'}
          placeholderTextColor={isRecording ? SakuraColors.cyan : 'rgba(248, 244, 255, 0.42)'}
          selectionColor={accent}
          cursorColor={accent}
          value={text}
          onChangeText={setText}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          multiline
          maxLength={4000}
          textAlignVertical="center"
          blurOnSubmit={false}
          editable={!isRecording}
          underlineColorAndroid="transparent"
        />

        <Pressable
          style={({ pressed }) => [
            styles.sendButton,
            hasText ? { backgroundColor: accent, shadowColor: accent } : styles.sendButtonDisabled,
            pressed && hasText ? styles.pressed : null,
          ]}
          onPress={() => handleSend()}
          disabled={!hasText || isSending}>
          <Send size={16} color={hasText ? '#fff' : SakuraColors.textMuted} />
        </Pressable>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  wrapper: {
    backgroundColor: 'rgba(10, 7, 18, 0.94)',
    borderTopWidth: 1,
    borderTopColor: SakuraColors.lineStrong,
    paddingTop: 8,
    paddingBottom: 10,
  },
  promptsRow: {
    paddingHorizontal: 14,
    paddingBottom: 8,
    gap: 8,
  },
  promptChip: {
    backgroundColor: 'rgba(28, 21, 44, 0.85)',
    borderWidth: 1,
    borderColor: SakuraColors.lineStrong,
    borderRadius: 999,
    paddingHorizontal: 13,
    paddingVertical: 6,
  },
  promptText: {
    color: SakuraColors.ink,
    fontSize: 12,
    fontWeight: '600',
  },
  bar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    marginHorizontal: 12,
    paddingHorizontal: 6,
    paddingVertical: 6,
    borderRadius: 26,
    backgroundColor: SakuraColors.bgInput,
    borderWidth: 1.5,
    borderColor: SakuraColors.lineStrong,
    gap: 8,
  },
  micButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: SakuraColors.cyanMuted,
    justifyContent: 'center',
    alignItems: 'center',
  },
  micRecording: {
    backgroundColor: SakuraColors.error,
    transform: [{ scale: 1.06 }],
  },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 116,
    color: '#FFFFFF',
    fontSize: 15,
    lineHeight: 20,
    paddingHorizontal: 6,
    paddingTop: 9,
    paddingBottom: 9,
  },
  sendButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.5,
    shadowRadius: 10,
    elevation: 5,
  },
  sendButtonDisabled: {
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    shadowOpacity: 0,
    elevation: 0,
  },
  pressed: {
    opacity: 0.82,
  },
});

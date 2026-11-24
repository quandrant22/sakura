/**
 * InputToolbar — панель ввода с быстрыми подсказками, кнопкой отправки и микрофоном PTT.
 */

import * as Haptics from 'expo-haptics';
import { Mic, Send } from 'lucide-react-native';
import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SakuraColors } from '../../constants/colors';

const QUICK_PROMPTS = ['Что у меня сегодня?', 'Погода', 'Включи музыку'];

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

  const handleSend = (overrideText?: string) => {
    const val = (overrideText ?? text).trim();
    if (!val || isSending) return;
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch {}
    onSendText(val);
    if (!overrideText) setText('');
  };

  const handlePressIn = () => {
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    } catch {}
    setIsRecording(true);
    onVoiceStart();
  };

  const handlePressOut = () => {
    if (isRecording) {
      try {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      } catch {}
      setIsRecording(false);
      onVoiceEnd();
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}>
      <View style={styles.wrapper}>
        {showPrompts && (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.promptsRow}>
            {QUICK_PROMPTS.map((prompt) => (
              <Pressable
                key={prompt}
                style={({ pressed }) => [styles.promptChip, pressed && { opacity: 0.7 }]}
                onPress={() => handleSend(prompt)}>
                <Text style={styles.promptText}>{prompt}</Text>
              </Pressable>
            ))}
          </ScrollView>
        )}

        <View style={styles.bar}>
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
            placeholder={isRecording ? 'Говорите…' : 'Спроси Сакуру…'}
            placeholderTextColor={isRecording ? SakuraColors.cyan : SakuraColors.textMuted}
            value={text}
            onChangeText={setText}
            onSubmitEditing={() => handleSend()}
            returnKeyType="send"
            editable={!isRecording}
          />

          <Pressable
            style={({ pressed }) => [
              styles.sendButton,
              !text.trim() && styles.sendButtonDisabled,
              pressed && text.trim() ? styles.pressed : null,
            ]}
            onPress={() => handleSend()}
            disabled={!text.trim() || isSending}>
            <Send size={16} color={text.trim() ? '#fff' : SakuraColors.textMuted} />
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  wrapper: {
    backgroundColor: SakuraColors.bg,
    borderTopWidth: 1,
    borderTopColor: SakuraColors.line,
    paddingTop: 6,
    paddingBottom: 8,
  },
  promptsRow: {
    paddingHorizontal: 14,
    paddingBottom: 6,
    gap: 8,
  },
  promptChip: {
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 5,
  },
  promptText: {
    color: SakuraColors.inkDim,
    fontSize: 12,
    fontWeight: '500',
  },
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: 12,
    paddingHorizontal: 6,
    paddingVertical: 5,
    borderRadius: 26,
    backgroundColor: SakuraColors.panel2,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    gap: 6,
  },
  micButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: SakuraColors.cyanMuted,
    justifyContent: 'center',
    alignItems: 'center',
  },
  micRecording: {
    backgroundColor: SakuraColors.error,
    transform: [{ scale: 1.08 }],
  },
  input: {
    flex: 1,
    color: SakuraColors.ink,
    fontSize: 14.5,
    paddingHorizontal: 8,
    paddingVertical: 6,
  },
  sendButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: SakuraColors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: SakuraColors.accent,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.45,
    shadowRadius: 8,
    elevation: 4,
  },
  sendButtonDisabled: {
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    shadowOpacity: 0,
    elevation: 0,
  },
  pressed: {
    opacity: 0.8,
  },
});

/**
 * MessageBubble — пузырь сообщения в стиле desktop/ui/src/components/Chat.tsx.
 */

import { CheckCheck, Clock3, Mic, Volume2, Zap } from 'lucide-react-native';
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Message } from '../../api/types';
import { SakuraColors } from '../../constants/colors';
import { SakuraLogo } from '../core/SakuraLogo';

interface MessageBubbleProps {
  message: Message;
}

function sourceLabel(m: Message): string {
  if (m.role === 'system') return 'система';
  if (m.channel === 'telegram') return 'Telegram';
  if (m.channel === 'voice' || m.source === 'mic') return 'микрофон';
  return '';
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message }) => {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';
  const label = sourceLabel(message);

  const timeString = message.ts
    ? new Date(message.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  if (isSystem && (message.kind === 'command' || message.kind === 'error')) {
    return (
      <View style={styles.actionLine}>
        <Zap
          size={12}
          color={message.kind === 'error' ? SakuraColors.accent : SakuraColors.inkDim}
        />
        <Text
          style={[
            styles.actionText,
            message.kind === 'error' && { color: SakuraColors.accent },
          ]}
          numberOfLines={2}>
          {message.text}
        </Text>
        <Text style={styles.metaText}>{timeString}</Text>
      </View>
    );
  }

  if (isSystem) {
    return (
      <View style={styles.systemContainer}>
        <View style={styles.systemPill}>
          <Text style={styles.systemText}>
            {message.text} · {timeString}
          </Text>
        </View>
      </View>
    );
  }

  if (isUser) {
    return (
      <View style={styles.userRow}>
        <View style={styles.userBubble}>
          <Text style={styles.messageText}>{message.text}</Text>
          <View style={styles.metaRow}>
            {label ? (
              <View style={styles.sourceInline}>
                <Mic size={10} color={SakuraColors.cyan} />
                <Text style={[styles.metaText, { color: SakuraColors.cyan }]}>{label} ·</Text>
              </View>
            ) : null}
            <Text style={styles.metaText}>{timeString}</Text>
            {message.pending ? (
              <Clock3 size={12} color={SakuraColors.inkDim} />
            ) : (
              <CheckCheck size={13} color={SakuraColors.accent} />
            )}
          </View>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.assistantRow}>
      <View style={styles.avatarWrap}>
        <SakuraLogo size={24} />
      </View>
      <View style={styles.assistantBubble}>
        <View style={styles.assistantHeader}>
          <Text style={styles.authorTitle}>Sakura</Text>
          {message.streaming && (
            <View style={styles.chipAccent}>
              <Text style={styles.chipAccentText}>печатает…</Text>
            </View>
          )}
          {message.kind === 'proactive' && (
            <View style={styles.chipAccent}>
              <Text style={styles.chipAccentText}>проактивно</Text>
            </View>
          )}
        </View>
        {message.kind === 'voice_only' ? (
          <View style={styles.voiceOnlyRow}>
            <Volume2 size={14} color={SakuraColors.inkDim} />
            <Text style={styles.voiceOnlyText}>{message.text}</Text>
          </View>
        ) : (
          <Text style={styles.messageText}>
            {message.text}
            {message.streaming ? ' ▍' : ''}
          </Text>
        )}
        <View style={styles.metaRow}>
          {label ? <Text style={styles.metaText}>{label} ·</Text> : null}
          <Text style={styles.metaText}>{timeString}</Text>
        </View>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  userRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    paddingHorizontal: 14,
    marginVertical: 4,
  },
  userBubble: {
    maxWidth: '84%',
    backgroundColor: SakuraColors.panel2,
    borderRadius: 20,
    borderBottomRightRadius: 6,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.05)',
  },
  assistantRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
    paddingHorizontal: 14,
    marginVertical: 4,
  },
  avatarWrap: {
    marginBottom: 4,
  },
  assistantBubble: {
    maxWidth: '82%',
    backgroundColor: SakuraColors.panel,
    borderRadius: 20,
    borderBottomLeftRadius: 6,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: 'rgba(255, 106, 227, 0.22)',
  },
  assistantHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 3,
  },
  authorTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: SakuraColors.accent,
  },
  chipAccent: {
    backgroundColor: SakuraColors.accentSoft,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 999,
  },
  chipAccentText: {
    fontSize: 10,
    fontWeight: '600',
    color: SakuraColors.accent,
  },
  messageText: {
    fontSize: 14.5,
    lineHeight: 20,
    color: SakuraColors.ink,
  },
  voiceOnlyRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  voiceOnlyText: {
    fontSize: 14,
    fontStyle: 'italic',
    color: SakuraColors.inkDim,
  },
  metaRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    alignItems: 'center',
    gap: 5,
    marginTop: 5,
  },
  sourceInline: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
  },
  metaText: {
    fontSize: 10.5,
    color: SakuraColors.inkDim,
  },
  systemContainer: {
    alignItems: 'center',
    marginVertical: 6,
    paddingHorizontal: 20,
  },
  systemPill: {
    backgroundColor: 'rgba(255, 255, 255, 0.04)',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 999,
  },
  systemText: {
    fontSize: 11,
    color: SakuraColors.inkDim,
    textAlign: 'center',
  },
  actionLine: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingLeft: 44,
    paddingRight: 16,
    marginVertical: 3,
  },
  actionText: {
    flex: 1,
    fontSize: 12,
    color: SakuraColors.inkDim,
  },
});

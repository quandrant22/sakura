/**
 * Chat Store — real-time messages, dialogue history, Sakura's affective state,
 * and TTS audio chunk playback.
 */

import { AppState, Platform } from 'react-native';
import { create } from 'zustand';
import { showPopupNotification } from '../../modules/sakura-wake';
import { sakuraClient } from '../api/client';
import { Message, SakuraState, SakuraStatus } from '../api/types';
import { ttsPlayer } from '../services/ttsPlayer';
import { getActiveTabRoute } from '../utils/activeRoute';
import { useMusicStore } from './useMusicStore';
import { usePhoneSettingsStore } from './usePhoneSettingsStore';

let lastPopupKey = '';
let lastPopupAt = 0;

function maybeNotifyPopup(title: string, body: string, tag?: string, forceWhenNotChat = false) {
  if (Platform.OS !== 'android') return;
  if (!usePhoneSettingsStore.getState().notificationsEnabled) return;
  const clean = (body || '').trim();
  if (!clean) return;
  const isBg = AppState.currentState !== 'active';
  const awayFromChat = getActiveTabRoute() !== 'chat';
  if (!isBg && !(forceWhenNotChat && awayFromChat)) return;

  const key = tag || clean.slice(0, 64);
  const now = Date.now();
  if (key === lastPopupKey && now - lastPopupAt < 10000) return;
  lastPopupKey = key;
  lastPopupAt = now;
  showPopupNotification(title, clean, '(tabs)/chat', tag || 'sakura_msg');
}

function mergeHistoryWithLocal(serverHistory: Message[], current: Message[]): Message[] {
  const serverIds = new Set(serverHistory.map((m) => m.id));
  const serverCmids = new Set(serverHistory.map((m) => m.client_msg_id).filter(Boolean));
  const serverTurnIds = new Set(
    serverHistory.filter((m) => m.role === 'assistant' && m.turn_id).map((m) => m.turn_id)
  );
  const nowSec = Date.now() / 1000;

  const trailingLocal = current.filter((m) => {
    if (serverIds.has(m.id)) return false;
    if (m.client_msg_id && serverCmids.has(m.client_msg_id)) return false;
    if (m.role === 'assistant' && m.turn_id && serverTurnIds.has(m.turn_id)) return false;
    if (m.streaming) return true;
    if (m.pending) {
      const matched = serverHistory.some(
        (s) => s.role === 'user' && s.text === m.text && Math.abs((s.ts || nowSec) - m.ts) < 90
      );
      return !matched;
    }
    return false;
  });

  return [...serverHistory, ...trailingLocal];
}

interface ChatState {
  messages: Message[];
  lastReply: string | null;
  sakuraState: SakuraState;
  status: SakuraStatus;
  isLoadingHistory: boolean;
  historyLoaded: boolean;
  isSending: boolean;
  bound: boolean;

  bindEvents: () => void;
  loadHistory: () => Promise<void>;
  sendMessage: (text: string, channel?: 'text' | 'voice') => Promise<void>;
  sendVoiceAudioBase64: (
    base64: string,
    mimeType?: string
  ) => Promise<{ transcript: string }>;
  setSakuraState: (state: SakuraState) => void;
  addMessage: (message: Message) => void;
  clearChat: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  lastReply: null,
  sakuraState: 'idle',
  status: { tone: 'calm', mode: 'normal' },
  isLoadingHistory: false,
  historyLoaded: false,
  isSending: false,
  bound: false,

  bindEvents: () => {
    if (get().bound) return;

    ttsPlayer.setCallbacks({
      onSpeakingChange: (speaking) => {
        set({ sakuraState: speaking ? 'speaking' : 'idle' });
      },
      onDuckMusic: (duck) => {
        void useMusicStore.getState().duckVolume(duck);
      },
    });

    sakuraClient.on<any>('chat_message', (payload) => {
      if (payload?.message) {
        get().addMessage(payload.message);
        if (payload.message.role === 'assistant' && payload.message.text) {
          const tId = payload.message.turn_id ? `turn_${payload.message.turn_id}` : undefined;
          maybeNotifyPopup('Сакура', String(payload.message.text), tId, payload.message.kind === 'proactive');
        }
      }
    });

    sakuraClient.on<any>('notification', (payload) => {
      const body = String(payload?.body || payload?.text || payload?.message || '').trim();
      const title = String(payload?.title || 'Сакура').trim();
      if (body) {
        maybeNotifyPopup(title, body, undefined, true);
      }
    });

    sakuraClient.on<any>('reply_chunk', (payload) => {
      const delta = typeof payload?.text === 'string' ? payload.text : '';
      if (!delta) return;
      const turnId: string | null = payload?.turn_id ?? null;
      const streamId = turnId ? `stream_${turnId}` : 'stream_live';

      set((state) => {
        const idx = state.messages.findIndex(
          (m) =>
            m.id === streamId ||
            (m.role === 'assistant' && m.streaming && (!turnId || m.turn_id === turnId))
        );
        const speakEnabled = usePhoneSettingsStore.getState().voiceRepliesEnabled;
        if (idx >= 0) {
          const prev = state.messages[idx];
          const updatedText = prev.text + delta;
          const next = state.messages.map((m, i) =>
            i === idx ? { ...m, text: updatedText, turn_id: turnId ?? m.turn_id, streaming: true } : m
          );
          return {
            messages: next,
            lastReply: updatedText,
            sakuraState: speakEnabled ? state.sakuraState : 'thinking',
          };
        }
        const msg: Message = {
          id: streamId,
          ts: Date.now() / 1000,
          role: 'assistant',
          text: delta,
          kind: 'ack',
          turn_id: turnId,
          streaming: true,
        };
        // Используем llm kind
        msg.kind = undefined;
        return {
          messages: [...state.messages, msg],
          lastReply: delta,
          sakuraState: speakEnabled ? state.sakuraState : 'thinking',
        };
      });
    });

    sakuraClient.on<any>('reply', (payload) => {
      if (!payload?.text) return;
      const text = String(payload.text);
      const turnId: string | null = payload.turn_id ?? null;
      const kind = payload.kind;
      const speakEnabled = usePhoneSettingsStore.getState().voiceRepliesEnabled;
      maybeNotifyPopup(
        kind === 'proactive' ? 'Сакура · напоминание' : 'Сакура',
        text,
        turnId ? `turn_${turnId}` : undefined,
        kind === 'proactive'
      );

      set((state) => {
        const streamIdx = state.messages.findIndex(
          (m) =>
            m.role === 'assistant' &&
            ((turnId && (m.id === `stream_${turnId}` || m.id === `reply_${turnId}` || m.turn_id === turnId)) ||
              m.streaming)
        );

        if (streamIdx >= 0) {
          const updated = state.messages.map((m, i) =>
            i === streamIdx
              ? {
                  ...m,
                  id: turnId ? `reply_${turnId}` : m.id,
                  text,
                  kind: kind ?? m.kind,
                  turn_id: turnId ?? m.turn_id,
                  streaming: false,
                }
              : m
          );
          return {
            messages: updated,
            lastReply: text,
            sakuraState: speakEnabled ? state.sakuraState : 'idle',
          };
        }

        const now = Date.now() / 1000;
        const already = state.messages.some(
          (m) =>
            m.role === 'assistant' &&
            ((turnId && m.turn_id === turnId && m.text === text) ||
              (m.text === text && Math.abs(now - m.ts) < 15))
        );
        if (already) {
          return {
            lastReply: text,
            sakuraState: speakEnabled ? state.sakuraState : 'idle',
          };
        }

        const msg: Message = {
          id: turnId ? `reply_${turnId}` : `reply_${Date.now()}`,
          ts: payload.ts || now,
          role: 'assistant',
          text,
          kind,
          turn_id: turnId,
          streaming: false,
        };
        return {
          messages: [...state.messages, msg],
          lastReply: text,
          sakuraState: speakEnabled ? 'speaking' : 'idle',
        };
      });
    });

    sakuraClient.on<any>('tts_chunk', (payload) => {
      if (!usePhoneSettingsStore.getState().voiceRepliesEnabled) return;
      if (payload?.audio) {
        ttsPlayer.feedChunk(payload.audio, payload.sample_rate || 24000, payload.turn_id);
      }
    });

    sakuraClient.on<any>('tts_end', () => {
      const s = usePhoneSettingsStore.getState();
      set((state) =>
        state.messages.some((m) => m.streaming)
          ? { messages: state.messages.map((m) => (m.streaming ? { ...m, streaming: false } : m)) }
          : state
      );
      void ttsPlayer.finishTurn({
        enabled: s.voiceRepliesEnabled,
        speed: s.ttsSpeed,
        duckMusic: s.duckMusicOnVoice,
      });
      if (!s.voiceRepliesEnabled) {
        set({ sakuraState: 'idle' });
      }
    });

    sakuraClient.on<any>('status', (payload) => {
      set({
        status: {
          tone: payload.tone || get().status.tone,
          mode: payload.mode || get().status.mode,
          context: payload.context,
          quote: payload.quote,
        },
      });
    });

    sakuraClient.on<any>('state', (payload) => {
      if (payload?.value) {
        set({ sakuraState: payload.value });
      }
    });

    sakuraClient.onLinkState((state) => {
      if (state === 'connected') {
        void get().loadHistory();
      }
    });

    AppState.addEventListener('change', (nextState) => {
      if (nextState === 'active' && sakuraClient.getStatus() === 'connected') {
        void get().loadHistory();
      }
    });

    set({ bound: true });
  },

  loadHistory: async () => {
    if (sakuraClient.getStatus() !== 'connected') return;
    if (get().isLoadingHistory) return;
    set({ isLoadingHistory: true });
    try {
      const history = await sakuraClient.getHistory(50);
      const lastAssist = [...history].reverse().find((m) => m.role === 'assistant');
      set((state) => ({
        messages: mergeHistoryWithLocal(history, state.messages),
        lastReply: lastAssist?.text || state.lastReply,
        historyLoaded: true,
        isLoadingHistory: false,
      }));
    } catch {
      set({ isLoadingHistory: false });
    }
  },

  sendMessage: async (text: string, channel: 'text' | 'voice' = 'text') => {
    const trimmed = text.trim();
    if (!trimmed) return;

    const speak = usePhoneSettingsStore.getState().voiceRepliesEnabled;
    const effectiveChannel = speak ? channel : 'text';
    const clientMsgId = `mob_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

    const tempUserMsg: Message = {
      id: `local_${clientMsgId}`,
      ts: Date.now() / 1000,
      role: 'user',
      text: trimmed,
      channel: effectiveChannel,
      device: 'phone',
      client_msg_id: clientMsgId,
      pending: true,
    };

    set((state) => ({
      messages: [...state.messages, tempUserMsg],
      isSending: true,
      sakuraState: 'thinking',
    }));

    try {
      if (effectiveChannel === 'text') {
        try {
          const ack = await sakuraClient.sendChatMessage(trimmed, clientMsgId, speak);
          if (ack?.id) {
            set((state) => ({
              messages: state.messages.map((m) =>
                m.client_msg_id === clientMsgId ? { ...m, id: String(ack.id), pending: false } : m
              ),
            }));
          }
          return;
        } catch (err: any) {
          if (err?.code && err.code !== 'unsupported' && err.code !== 'timeout') {
            throw err;
          }
        }
      }
      await sakuraClient.sendVoiceCommand(trimmed, effectiveChannel, speak);
    } catch (e) {
      console.warn('[useChatStore] Failed to send message:', e);
    } finally {
      set({ isSending: false });
    }
  },

  sendVoiceAudioBase64: async (base64: string, mimeType = 'audio/mp4') => {
    const speak = usePhoneSettingsStore.getState().voiceRepliesEnabled;
    set({ isSending: true, sakuraState: 'thinking' });
    try {
      const res = await sakuraClient.sendVoiceAudio(base64, mimeType, speak);
      if (!res?.transcript) {
        set({ sakuraState: 'idle', isSending: false });
        return { transcript: '' };
      }
      set({ isSending: false });
      return { transcript: res.transcript };
    } catch (e) {
      console.warn('[useChatStore] Voice audio failed:', e);
      set({ sakuraState: 'idle', isSending: false });
      throw e;
    }
  },

  setSakuraState: (state: SakuraState) => {
    set({ sakuraState: state });
  },

  addMessage: (message: Message) => {
    set((state) => {
      const exists = state.messages.some((m) => m.id === message.id);
      if (exists) return state;

      // Replace optimistic pending user message
      if (message.role === 'user') {
        const pendingIdx = state.messages.findIndex(
          (m) =>
            (message.client_msg_id && m.client_msg_id === message.client_msg_id) ||
            (m.pending && m.role === 'user' && m.text === message.text)
        );
        const nextMsgs =
          pendingIdx >= 0
            ? state.messages.map((m, i) => (i === pendingIdx ? { ...message, pending: false } : m))
            : [...state.messages, message];
        return { messages: nextMsgs };
      }

      // Replace temporary stream_*/reply_* assistant bubble instead of duplicating it!
      if (message.role === 'assistant') {
        const msgTurnId = message.turn_id;
        const msgTs = message.ts || Date.now() / 1000;
        const dupIdx = state.messages.findIndex((m) => {
          if (m.role !== 'assistant') return false;
          const isLocalTemp = m.id.startsWith('stream_') || m.id.startsWith('reply_') || Boolean(m.streaming);
          if (msgTurnId && m.turn_id && m.turn_id === msgTurnId && isLocalTemp) {
            return true;
          }
          if (isLocalTemp && (m.text === message.text || message.text.startsWith(m.text.slice(0, 24)))) {
            return Math.abs(msgTs - m.ts) < 30;
          }
          return m.text === message.text && Math.abs(msgTs - m.ts) < 15;
        });

        const nextMsgs =
          dupIdx >= 0
            ? state.messages.map((m, i) =>
                i === dupIdx ? { ...message, streaming: false } : m
              )
            : [...state.messages, { ...message, streaming: false }];

        return {
          messages: nextMsgs,
          lastReply: message.text,
          sakuraState: usePhoneSettingsStore.getState().voiceRepliesEnabled
            ? state.sakuraState
            : 'idle',
        };
      }

      return { messages: [...state.messages, message] };
    });
  },

  clearChat: () => {
    set({ messages: [], lastReply: null });
  },
}));

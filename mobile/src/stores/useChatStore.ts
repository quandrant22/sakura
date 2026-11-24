/**
 * Chat Store — real-time messages, dialogue history, Sakura's affective state,
 * and TTS audio chunk playback.
 */

import { create } from 'zustand';
import { sakuraClient } from '../api/client';
import { Message, SakuraState, SakuraStatus } from '../api/types';
import { ttsPlayer } from '../services/ttsPlayer';
import { useMusicStore } from './useMusicStore';
import { usePhoneSettingsStore } from './usePhoneSettingsStore';

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
      }
    });

    sakuraClient.on<any>('reply', (payload) => {
      if (payload?.text) {
        set({ lastReply: String(payload.text) });
        const hasHistoryMsg = get().messages.some(
          (m) => m.role === 'assistant' && m.text === payload.text && Date.now() / 1000 - m.ts < 5
        );
        if (!hasHistoryMsg) {
          get().addMessage({
            id: `reply_${Date.now()}`,
            ts: Date.now() / 1000,
            role: 'assistant',
            text: String(payload.text),
            kind: payload.kind,
          });
        }
        if (!usePhoneSettingsStore.getState().voiceRepliesEnabled) {
          set({ sakuraState: 'idle' });
        }
      }
    });

    sakuraClient.on<any>('tts_chunk', (payload) => {
      if (!usePhoneSettingsStore.getState().voiceRepliesEnabled) return;
      if (payload?.audio) {
        ttsPlayer.feedChunk(payload.audio, payload.sample_rate || 24000, payload.turn_id);
      }
    });

    sakuraClient.on<any>('tts_end', () => {
      const s = usePhoneSettingsStore.getState();
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

    set({ bound: true });
  },

  loadHistory: async () => {
    if (get().isLoadingHistory) return;
    set({ isLoadingHistory: true });
    try {
      const history = await sakuraClient.getHistory(50);
      const lastAssist = [...history].reverse().find((m) => m.role === 'assistant');
      set({
        messages: history,
        lastReply: lastAssist?.text || get().lastReply,
        historyLoaded: true,
        isLoadingHistory: false,
      });
    } catch {
      set({ isLoadingHistory: false });
    }
  },

  sendMessage: async (text: string, channel: 'text' | 'voice' = 'text') => {
    const trimmed = text.trim();
    if (!trimmed) return;

    const speak = usePhoneSettingsStore.getState().voiceRepliesEnabled;
    const effectiveChannel = speak ? channel : 'text';

    const tempUserMsg: Message = {
      id: `local_${Date.now()}`,
      ts: Date.now() / 1000,
      role: 'user',
      text: trimmed,
      channel: effectiveChannel,
      device: 'phone',
      pending: true,
    };

    set((state) => ({
      messages: [...state.messages, tempUserMsg],
      isSending: true,
      sakuraState: 'thinking',
    }));

    try {
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

      // Replace optimistic pending message if same user text just arrived from server
      const filtered =
        message.role === 'user'
          ? state.messages.filter(
              (m) => !(m.pending && m.role === 'user' && m.text === message.text)
            )
          : state.messages;

      const isAssist = message.role === 'assistant';
      const speakEnabled = usePhoneSettingsStore.getState().voiceRepliesEnabled;
      const nextState: SakuraState = isAssist
        ? speakEnabled
          ? 'speaking'
          : 'idle'
        : state.sakuraState;

      return {
        messages: [...filtered, message],
        lastReply: isAssist ? message.text : state.lastReply,
        sakuraState: nextState,
      };
    });
  },

  clearChat: () => {
    set({ messages: [], lastReply: null });
  },
}));

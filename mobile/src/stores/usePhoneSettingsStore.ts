/**
 * Phone Settings Store — все локальные настройки телефона, режима ответа (Голос/Текст),
 * Яндекс.Музыки, тактильности, пульта и оформления.
 */

import { create } from 'zustand';
import { safeStorage } from '../services/storage';

const SETTINGS_STORAGE_KEY = 'sakura_phone_settings_v1';

// Токен из .env проекта (можно заменить прямо в настройках телефона)
export const DEFAULT_YANDEX_TOKEN =
  'y0__wgBEP68lP0DGN74BiDextSQGTmTybEEdcXmE4ywib4auQ5Gono-';

export type AccentThemeId = 'sakura' | 'cyan' | 'violet' | 'crimson';

export const ACCENT_THEMES: Record<
  AccentThemeId,
  { name: string; accent: string; deep: string; soft: string }
> = {
  sakura: { name: 'Сакура', accent: '#FF6AE3', deep: '#3E0074', soft: 'rgba(255,106,227,0.16)' },
  cyan: { name: 'Неон', accent: '#4FD8FF', deep: '#0E2E5C', soft: 'rgba(79,216,255,0.16)' },
  violet: { name: 'Ночь', accent: '#A855F7', deep: '#2E1065', soft: 'rgba(168,85,247,0.16)' },
  crimson: { name: 'Алый', accent: '#FF4D6D', deep: '#590D22', soft: 'rgba(255,77,109,0.16)' },
};

export interface PhoneSettings {
  // Голос и ответы
  voiceRepliesEnabled: boolean; // false = только текстовые ответы (speak: false)
  ttsSpeed: number;
  duckMusicOnVoice: boolean;
  autoResumeMusic: boolean;
  handsFreeMode: boolean;

  // Телефон и система
  hapticsEnabled: boolean;
  telemetryEnabled: boolean;
  notificationsEnabled: boolean;
  keepScreenAwake: boolean;

  // Пульт ПК
  confirmPowerActions: boolean; // false = выключать/перезагружать ПК сразу в 1 тап

  // Яндекс.Музыка
  yandexToken: string;
  yandexHighQuality: boolean;
  autoCacheMusic: boolean;

  // Внешний вид
  accentTheme: AccentThemeId;
  showQuickPrompts: boolean;
}

export const DEFAULT_PHONE_SETTINGS: PhoneSettings = {
  voiceRepliesEnabled: true,
  ttsSpeed: 1.0,
  duckMusicOnVoice: true,
  autoResumeMusic: true,
  handsFreeMode: false,

  hapticsEnabled: true,
  telemetryEnabled: true,
  notificationsEnabled: true,
  keepScreenAwake: false,

  confirmPowerActions: false,

  yandexToken: DEFAULT_YANDEX_TOKEN,
  yandexHighQuality: true,
  autoCacheMusic: true,

  accentTheme: 'sakura',
  showQuickPrompts: true,
};

interface PhoneSettingsState extends PhoneSettings {
  loaded: boolean;
  load: () => Promise<void>;
  update: (patch: Partial<PhoneSettings>) => Promise<void>;
  resetDefaults: () => Promise<void>;
}

export const usePhoneSettingsStore = create<PhoneSettingsState>((set, get) => ({
  ...DEFAULT_PHONE_SETTINGS,
  loaded: false,

  load: async () => {
    if (get().loaded) return;
    try {
      const raw = await safeStorage.getItem(SETTINGS_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        set({
          ...DEFAULT_PHONE_SETTINGS,
          ...parsed,
          yandexToken: parsed.yandexToken || DEFAULT_YANDEX_TOKEN,
          loaded: true,
        });
        return;
      }
    } catch {}
    set({ loaded: true });
  },

  update: async (patch: Partial<PhoneSettings>) => {
    set(patch);
    const cur = get();
    const toSave: PhoneSettings = {
      voiceRepliesEnabled: cur.voiceRepliesEnabled,
      ttsSpeed: cur.ttsSpeed,
      duckMusicOnVoice: cur.duckMusicOnVoice,
      autoResumeMusic: cur.autoResumeMusic,
      handsFreeMode: cur.handsFreeMode,
      hapticsEnabled: cur.hapticsEnabled,
      telemetryEnabled: cur.telemetryEnabled,
      notificationsEnabled: cur.notificationsEnabled,
      keepScreenAwake: cur.keepScreenAwake,
      confirmPowerActions: cur.confirmPowerActions,
      yandexToken: cur.yandexToken,
      yandexHighQuality: cur.yandexHighQuality,
      autoCacheMusic: cur.autoCacheMusic,
      accentTheme: cur.accentTheme,
      showQuickPrompts: cur.showQuickPrompts,
    };
    await safeStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(toSave));
  },

  resetDefaults: async () => {
    set({ ...DEFAULT_PHONE_SETTINGS });
    await safeStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(DEFAULT_PHONE_SETTINGS));
  },
}));

/**
 * useVoiceRecorder — Hold-to-Talk и Hands-Free запись речи через expo-audio (SDK 58)
 * с остановкой локального wake-word перед захватом микрофона и авто-стопом по тишине (VAD).
 */

import {
  getRecordingPermissionsAsync,
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
} from 'expo-audio';
import { File } from 'expo-file-system';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Platform } from 'react-native';
import { stopWakeWord } from '../../modules/sakura-wake';
import { useChatStore } from '../stores/useChatStore';
import { useMusicStore } from '../stores/useMusicStore';
import { useWakeControlStore } from './useWakeControlStore';

function uint8ToBase64(bytes: Uint8Array): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const has1 = i + 1 < bytes.length;
    const has2 = i + 2 < bytes.length;
    const b1 = has1 ? bytes[i + 1] : 0;
    const b2 = has2 ? bytes[i + 2] : 0;
    out += chars[b0 >> 2];
    out += chars[((b0 & 3) << 4) | (b1 >> 4)];
    out += has1 ? chars[((b1 & 15) << 2) | (b2 >> 6)] : '=';
    out += has2 ? chars[b2 & 63] : '=';
  }
  return out;
}

export function useVoiceRecorder() {
  const recorder = useAudioRecorder({
    ...RecordingPresets.HIGH_QUALITY,
    isMeteringEnabled: true,
  });
  const { setSakuraState, sendVoiceAudioBase64 } = useChatStore();
  const [isRecording, setIsRecording] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const activeRef = useRef(false);
  const vadTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearVadTimer = useCallback(() => {
    if (vadTimerRef.current) {
      clearInterval(vadTimerRef.current);
      vadTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      clearVadTimer();
    };
  }, [clearVadTimer]);

  const startRecording = useCallback(async (): Promise<boolean> => {
    setMicError(null);
    if (Platform.OS === 'web') {
      setMicError('Голосовой ввод доступен в приложении на телефоне');
      return false;
    }
    if (activeRef.current) return true;

    try {
      const perm = await getRecordingPermissionsAsync();
      let granted = perm.granted;
      if (!granted) {
        const req = await requestRecordingPermissionsAsync();
        granted = req.granted;
      }
      if (!granted) {
        setMicError('Нет доступа к микрофону');
        return false;
      }

      useWakeControlStore.getState().setMicBusy(true);
      await stopWakeWord();
      await useMusicStore.getState().duckVolume(true);

      await setAudioModeAsync({
        allowsRecording: true,
        playsInSilentMode: true,
        shouldPlayInBackground: true,
        interruptionMode: 'duckOthers',
      });
      await recorder.prepareToRecordAsync();
      recorder.record();
      activeRef.current = true;
      setIsRecording(true);
      setSakuraState('listening');
      return true;
    } catch (e: any) {
      activeRef.current = false;
      setIsRecording(false);
      setSakuraState('idle');
      useWakeControlStore.getState().setMicBusy(false);
      await useMusicStore.getState().duckVolume(false);
      setMicError(e?.message || 'Ошибка запуска микрофона');
      return false;
    }
  }, [recorder, setSakuraState]);

  const stopAndSend = useCallback(async () => {
    clearVadTimer();
    if (!activeRef.current) return;
    activeRef.current = false;
    setIsRecording(false);
    setSakuraState('thinking');

    try {
      await recorder.stop();
    } catch {}

    try {
      await setAudioModeAsync({
        allowsRecording: false,
        playsInSilentMode: true,
        shouldPlayInBackground: true,
        interruptionMode: 'doNotMixPersistent',
      });
    } catch {}

    await useMusicStore.getState().duckVolume(false);
    const uri = recorder.uri;
    if (!uri) {
      setSakuraState('idle');
      useWakeControlStore.getState().setMicBusy(false);
      return;
    }

    try {
      const file = new File(uri);
      const buf = await file.arrayBuffer();
      if (buf.byteLength < 800) {
        setSakuraState('idle');
        useWakeControlStore.getState().setMicBusy(false);
        return;
      }
      const b64 = uint8ToBase64(new Uint8Array(buf));
      const res = await sendVoiceAudioBase64(b64, 'audio/mp4');
      if (!res.transcript) {
        setMicError('Речь не распознана');
      }
      try {
        file.delete();
      } catch {}
    } catch (e: any) {
      setSakuraState('idle');
      setMicError(e?.message || 'Не удалось отправить голос');
    } finally {
      useWakeControlStore.getState().setMicBusy(false);
    }
  }, [clearVadTimer, recorder, setSakuraState, sendVoiceAudioBase64]);

  /**
   * Запускает запись после активации по wake-word и автоматически завершает по тишине.
   */
  const recordWithAutoSilence = useCallback(
    async (maxMs = 8500, silenceMs = 1250) => {
      const startedOk = await startRecording();
      if (!startedOk) return;

      clearVadTimer();
      const startedAt = Date.now();
      let lastSpeechAt = Date.now();
      let heardSpeech = false;

      vadTimerRef.current = setInterval(() => {
        if (!activeRef.current) {
          clearVadTimer();
          return;
        }
        const now = Date.now();
        const elapsed = now - startedAt;

        let level = -160;
        try {
          const st = recorder.getStatus();
          if (typeof st.metering === 'number') {
            level = st.metering;
          }
        } catch {}

        if (level > -38) {
          heardSpeech = true;
          lastSpeechAt = now;
        }

        const quietFor = now - lastSpeechAt;
        const shouldStop =
          elapsed >= maxMs ||
          (heardSpeech && quietFor >= silenceMs && elapsed >= 900) ||
          (!heardSpeech && elapsed >= 4200);

        if (shouldStop) {
          clearVadTimer();
          void stopAndSend();
        }
      }, 160);
    },
    [clearVadTimer, recorder, startRecording, stopAndSend]
  );

  return {
    isRecording,
    micError,
    startRecording,
    stopAndSend,
    recordWithAutoSilence,
  };
}

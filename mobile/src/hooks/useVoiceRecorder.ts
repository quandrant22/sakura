/**
 * useVoiceRecorder — Hold-to-Talk запись речи через expo-audio (SDK 58)
 * с безопасным переключением audio mode, чтением файла в base64 и отправкой в Sakura STT.
 */

import {
  getRecordingPermissionsAsync,
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
} from 'expo-audio';
import { File } from 'expo-file-system';
import { useCallback, useRef, useState } from 'react';
import { Platform } from 'react-native';
import { useChatStore } from '../stores/useChatStore';

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
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const { setSakuraState, sendVoiceAudioBase64 } = useChatStore();
  const [isRecording, setIsRecording] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const activeRef = useRef(false);

  const startRecording = useCallback(async () => {
    setMicError(null);
    if (Platform.OS === 'web') {
      setMicError('Голосовой ввод доступен в приложении на телефоне');
      return;
    }
    try {
      const perm = await getRecordingPermissionsAsync();
      let granted = perm.granted;
      if (!granted) {
        const req = await requestRecordingPermissionsAsync();
        granted = req.granted;
      }
      if (!granted) {
        setMicError('Нет доступа к микрофону');
        return;
      }

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
    } catch (e: any) {
      activeRef.current = false;
      setIsRecording(false);
      setSakuraState('idle');
      setMicError(e?.message || 'Ошибка запуска микрофона');
    }
  }, [recorder, setSakuraState]);

  const stopAndSend = useCallback(async () => {
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
        interruptionMode: 'duckOthers',
      });
    } catch {}

    const uri = recorder.uri;
    if (!uri) {
      setSakuraState('idle');
      return;
    }

    try {
      const file = new File(uri);
      const buf = await file.arrayBuffer();
      if (buf.byteLength < 800) {
        setSakuraState('idle');
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
    }
  }, [recorder, setSakuraState, sendVoiceAudioBase64]);

  return {
    isRecording,
    micError,
    startRecording,
    stopAndSend,
  };
}

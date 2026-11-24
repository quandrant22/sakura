/**
 * useWakeWordRunner — глобальный обработчик голосового wake-word «Сакура» (Vosk offline на Android).
 */

import { getRecordingPermissionsAsync, requestRecordingPermissionsAsync } from 'expo-audio';
import * as Haptics from 'expo-haptics';
import { useEffect, useRef } from 'react';
import { AppState, Platform } from 'react-native';
import {
  addWakeStateListener,
  addWakeWordListener,
  isWakeWordSupported,
  startWakeWord,
  stopWakeWord,
} from '../../modules/sakura-wake';
import { useChatStore } from '../stores/useChatStore';
import { useConnectionStore } from '../stores/useConnectionStore';
import { usePhoneSettingsStore } from '../stores/usePhoneSettingsStore';
import { useVoiceRecorder } from './useVoiceRecorder';
import { useWakeControlStore } from './useWakeControlStore';

const WAKE_PHRASES = ['сакура', 'привет сакура', 'слушай сакура', 'эй сакура'];

export function useWakeWordRunner() {
  const handsFreeMode = usePhoneSettingsStore((s) => s.handsFreeMode);
  const hapticsEnabled = usePhoneSettingsStore((s) => s.hapticsEnabled);
  const linkState = useConnectionStore((s) => s.linkState);
  const sakuraState = useChatStore((s) => s.sakuraState);
  const { micBusy, setWakeStatus } = useWakeControlStore();
  const { recordWithAutoSilence } = useVoiceRecorder();

  const recordFnRef = useRef(recordWithAutoSilence);
  useEffect(() => {
    recordFnRef.current = recordWithAutoSilence;
  }, [recordWithAutoSilence]);

  useEffect(() => {
    const stateSub = addWakeStateListener((ev) => {
      if (ev.state === 'listening') setWakeStatus('listening');
      else if (ev.state === 'triggered') setWakeStatus('triggered');
      else if (ev.state === 'permission_denied') setWakeStatus('denied');
      else if (ev.state === 'error' || ev.state === 'mic_error' || ev.state === 'model_missing') {
        setWakeStatus('error');
      } else {
        setWakeStatus('off');
      }
    });

    const wordSub = addWakeWordListener(() => {
      if (hapticsEnabled) {
        try {
          void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        } catch {}
      }
      setWakeStatus('triggered');
      void recordFnRef.current();
    });

    return () => {
      stateSub.remove();
      wordSub.remove();
    };
  }, [hapticsEnabled, setWakeStatus]);

  useEffect(() => {
    let cancelled = false;

    const syncEngine = async () => {
      const shouldListen =
        Platform.OS === 'android' &&
        handsFreeMode &&
        linkState === 'connected' &&
        sakuraState === 'idle' &&
        !micBusy &&
        AppState.currentState === 'active';

      if (!shouldListen) {
        await stopWakeWord();
        if (!handsFreeMode) setWakeStatus('off');
        return;
      }

      if (!isWakeWordSupported()) {
        setWakeStatus('unsupported');
        return;
      }

      try {
        const perm = await getRecordingPermissionsAsync();
        if (!perm.granted) {
          const req = await requestRecordingPermissionsAsync();
          if (!req.granted) {
            if (!cancelled) setWakeStatus('denied');
            return;
          }
        }
      } catch {}

      if (cancelled) return;
      const ok = await startWakeWord(WAKE_PHRASES);
      if (!cancelled && !ok) {
        setWakeStatus('error');
      }
    };

    void syncEngine();

    const appSub = AppState.addEventListener('change', (nextState) => {
      if (nextState === 'active') {
        void syncEngine();
      } else {
        void stopWakeWord();
      }
    });

    return () => {
      cancelled = true;
      appSub.remove();
      void stopWakeWord();
    };
  }, [handsFreeMode, linkState, sakuraState, micBusy, setWakeStatus]);
}

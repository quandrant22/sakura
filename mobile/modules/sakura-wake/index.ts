import { requireOptionalNativeModule } from 'expo-modules-core';
import { Platform } from 'react-native';

export interface WakeWordEvent {
  phrase: string;
  text: string;
}

export interface WakeStateEvent {
  state: 'idle' | 'listening' | 'triggered' | 'permission_denied' | 'model_missing' | 'mic_error' | 'error';
}

interface SakuraWakeNative {
  isSupported(): boolean;
  start(phrases?: string[]): Promise<boolean>;
  stop(): Promise<boolean>;
  addListener(eventName: 'onWakeWord', listener: (ev: WakeWordEvent) => void): { remove: () => void };
  addListener(eventName: 'onWakeState', listener: (ev: WakeStateEvent) => void): { remove: () => void };
}

const nativeWake =
  Platform.OS === 'android' ? requireOptionalNativeModule<SakuraWakeNative>('SakuraWake') : null;

export function isWakeWordSupported(): boolean {
  if (!nativeWake) return false;
  try {
    return Boolean(nativeWake.isSupported());
  } catch {
    return false;
  }
}

export async function startWakeWord(phrases?: string[]): Promise<boolean> {
  if (!nativeWake) return false;
  try {
    return await nativeWake.start(phrases);
  } catch {
    return false;
  }
}

export async function stopWakeWord(): Promise<void> {
  if (!nativeWake) return;
  try {
    await nativeWake.stop();
  } catch {}
}

export function addWakeWordListener(listener: (ev: WakeWordEvent) => void): { remove: () => void } {
  if (!nativeWake) return { remove: () => {} };
  return nativeWake.addListener('onWakeWord', listener);
}

export function addWakeStateListener(listener: (ev: WakeStateEvent) => void): { remove: () => void } {
  if (!nativeWake) return { remove: () => {} };
  return nativeWake.addListener('onWakeState', listener);
}

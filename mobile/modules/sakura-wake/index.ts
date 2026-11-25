import { requireOptionalNativeModule } from 'expo-modules-core';
import { Platform } from 'react-native';

export interface WakeWordEvent {
  phrase: string;
  text: string;
}

export interface WakeStateEvent {
  state: 'idle' | 'listening' | 'triggered' | 'permission_denied' | 'model_missing' | 'mic_error' | 'error';
}

export type MediaActionType = 'play' | 'pause' | 'next' | 'previous' | 'toggle_like' | 'seek';

export interface MediaActionEvent {
  action: MediaActionType;
  positionMs?: number;
}

export interface NativeMediaStatePayload {
  trackId: string;
  title: string;
  artist: string;
  album: string;
  artworkUrl: string | null;
  durationMs: number;
  positionMs: number;
  isPlaying: boolean;
  isLiked: boolean;
  hasPrev: boolean;
  hasNext: boolean;
}

interface SakuraWakeNative {
  isSupported(): boolean;
  start(phrases?: string[]): Promise<boolean>;
  stop(): Promise<boolean>;
  showNotification(title: string, body: string, route?: string | null, tag?: string | null): boolean;
  updateMediaState(
    trackId: string,
    title: string,
    artist: string,
    album: string,
    artworkUrl: string | null,
    durationMs: number,
    positionMs: number,
    isPlaying: boolean,
    isLiked: boolean,
    hasPrev: boolean,
    hasNext: boolean
  ): boolean;
  clearMediaState(): boolean;
  addListener(eventName: 'onWakeWord', listener: (ev: WakeWordEvent) => void): { remove: () => void };
  addListener(eventName: 'onWakeState', listener: (ev: WakeStateEvent) => void): { remove: () => void };
  addListener(eventName: 'onMediaAction', listener: (ev: MediaActionEvent) => void): { remove: () => void };
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

export function showPopupNotification(
  title: string,
  body: string,
  route?: string | null,
  tag?: string | null
): boolean {
  if (!nativeWake || typeof nativeWake.showNotification !== 'function') return false;
  try {
    return Boolean(nativeWake.showNotification(title, body, route ?? null, tag ?? null));
  } catch {
    return false;
  }
}

export function updateNativeMediaState(payload: NativeMediaStatePayload): boolean {
  if (!nativeWake || typeof nativeWake.updateMediaState !== 'function') return false;
  try {
    return Boolean(
      nativeWake.updateMediaState(
        payload.trackId,
        payload.title,
        payload.artist,
        payload.album,
        payload.artworkUrl,
        payload.durationMs,
        payload.positionMs,
        payload.isPlaying,
        payload.isLiked,
        payload.hasPrev,
        payload.hasNext
      )
    );
  } catch {
    return false;
  }
}

export function clearNativeMediaState(): void {
  if (!nativeWake || typeof nativeWake.clearMediaState !== 'function') return;
  try {
    nativeWake.clearMediaState();
  } catch {}
}

export function addMediaActionListener(listener: (ev: MediaActionEvent) => void): { remove: () => void } {
  if (!nativeWake) return { remove: () => {} };
  return nativeWake.addListener('onMediaAction', listener);
}

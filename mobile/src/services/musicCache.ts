/**
 * Offline Music Cache — постоянный локальный кэш треков Яндекс.Музыки на базе expo-file-system (SDK 58).
 * Хранится в Paths.document/sakura_music_cache, не очищается ОС автоматически.
 */

import { Directory, File, Paths } from 'expo-file-system';
import { Platform } from 'react-native';
import { safeStorage } from './storage';
import { YandexTrack } from './yandexMusic';

const CACHE_INDEX_KEY = 'sakura_music_cache_index_v1';
const CACHE_DIR_NAME = 'sakura_music_cache';

export interface CachedTrackEntry {
  track: YandexTrack;
  localUri: string;
  sizeBytes: number;
  cachedAt: number;
}

function getCacheDir(): Directory | null {
  if (Platform.OS === 'web') return null;
  const dir = new Directory(Paths.document, CACHE_DIR_NAME);
  if (!dir.exists) {
    dir.create({ intermediates: true, idempotent: true });
  }
  return dir;
}

function safeFileName(trackId: string): string {
  return `${trackId.replace(/[^a-zA-Z0-9_-]/g, '_')}.mp3`;
}

export async function loadMusicCacheIndex(): Promise<Record<string, CachedTrackEntry>> {
  try {
    const raw = await safeStorage.getItem(CACHE_INDEX_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, CachedTrackEntry>;
    if (Platform.OS === 'web') return {};

    const clean: Record<string, CachedTrackEntry> = {};
    let changed = false;
    for (const [id, entry] of Object.entries(parsed)) {
      try {
        const f = new File(entry.localUri);
        if (f.exists) {
          clean[id] = entry;
        } else {
          changed = true;
        }
      } catch {
        changed = true;
      }
    }
    if (changed) {
      await safeStorage.setItem(CACHE_INDEX_KEY, JSON.stringify(clean));
    }
    return clean;
  } catch {
    return {};
  }
}

export async function getCachedTrackUri(trackId: string): Promise<string | null> {
  if (Platform.OS === 'web') return null;
  const index = await loadMusicCacheIndex();
  const entry = index[trackId];
  if (!entry) return null;
  try {
    const f = new File(entry.localUri);
    return f.exists ? f.uri : null;
  } catch {
    return null;
  }
}

export async function cacheTrackToDisk(
  track: YandexTrack,
  streamUrl: string
): Promise<CachedTrackEntry | null> {
  const dir = getCacheDir();
  if (!dir) return null;

  const dest = new File(dir, safeFileName(track.id));
  if (dest.exists && dest.size > 1024) {
    const entry: CachedTrackEntry = {
      track,
      localUri: dest.uri,
      sizeBytes: dest.size,
      cachedAt: Date.now(),
    };
    const index = await loadMusicCacheIndex();
    index[track.id] = entry;
    await safeStorage.setItem(CACHE_INDEX_KEY, JSON.stringify(index));
    return entry;
  }

  const downloaded = await File.downloadFileAsync(streamUrl, dest, { idempotent: true });
  const entry: CachedTrackEntry = {
    track,
    localUri: downloaded.uri,
    sizeBytes: downloaded.size || 0,
    cachedAt: Date.now(),
  };

  const index = await loadMusicCacheIndex();
  index[track.id] = entry;
  await safeStorage.setItem(CACHE_INDEX_KEY, JSON.stringify(index));
  return entry;
}

export async function removeCachedTrack(trackId: string): Promise<Record<string, CachedTrackEntry>> {
  const index = await loadMusicCacheIndex();
  const entry = index[trackId];
  if (entry && Platform.OS !== 'web') {
    try {
      const f = new File(entry.localUri);
      if (f.exists) f.delete();
    } catch {}
  }
  delete index[trackId];
  await safeStorage.setItem(CACHE_INDEX_KEY, JSON.stringify(index));
  return index;
}

export async function clearAllMusicCache(): Promise<void> {
  if (Platform.OS !== 'web') {
    try {
      const dir = new Directory(Paths.document, CACHE_DIR_NAME);
      if (dir.exists) {
        dir.delete();
      }
    } catch {}
  }
  await safeStorage.removeItem(CACHE_INDEX_KEY);
}

/**
 * Offline Music Cache — постоянный локальный кэш треков Яндекс.Музыки на базе expo-file-system (SDK 58)
 * с O(1) индекс-кэшем в памяти и быстрым дисковым снапшотом медиатеки (2000+ лайков и плейлисты).
 */

import { Directory, File, Paths } from 'expo-file-system';
import { Platform } from 'react-native';
import { safeStorage } from './storage';
import { YandexPlaylist, YandexTrack } from './yandexMusic';

const CACHE_INDEX_KEY = 'sakura_music_cache_index_v1';
const CACHE_DIR_NAME = 'sakura_music_cache';
const LIBRARY_SNAPSHOT_FILE = 'sakura_music_library_snapshot_v1.json';

export interface CachedTrackEntry {
  track: YandexTrack;
  localUri: string;
  sizeBytes: number;
  cachedAt: number;
}

export interface LibrarySnapshot {
  likedTracks: YandexTrack[];
  likedTotal: number;
  playlists: YandexPlaylist[];
  savedAt: number;
}

let memoryIndex: Record<string, CachedTrackEntry> | null = null;
let loadPromise: Promise<Record<string, CachedTrackEntry>> | null = null;

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

export async function loadMusicCacheIndex(
  forceReload = false
): Promise<Record<string, CachedTrackEntry>> {
  if (!forceReload && memoryIndex) {
    return memoryIndex;
  }
  if (!forceReload && loadPromise) {
    return loadPromise;
  }

  loadPromise = (async () => {
    try {
      const raw = await safeStorage.getItem(CACHE_INDEX_KEY);
      if (!raw) {
        memoryIndex = {};
        return memoryIndex;
      }
      const parsed = JSON.parse(raw) as Record<string, CachedTrackEntry>;
      if (Platform.OS === 'web') {
        memoryIndex = {};
        return memoryIndex;
      }

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
      memoryIndex = clean;
      if (changed) {
        await safeStorage.setItem(CACHE_INDEX_KEY, JSON.stringify(clean));
      }
      return memoryIndex;
    } catch {
      memoryIndex = {};
      return memoryIndex;
    } finally {
      loadPromise = null;
    }
  })();

  return loadPromise;
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
    const index = { ...(await loadMusicCacheIndex()), [track.id]: entry };
    memoryIndex = index;
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

  const index = { ...(await loadMusicCacheIndex()), [track.id]: entry };
  memoryIndex = index;
  await safeStorage.setItem(CACHE_INDEX_KEY, JSON.stringify(index));
  return entry;
}

export async function removeCachedTrack(trackId: string): Promise<Record<string, CachedTrackEntry>> {
  const current = await loadMusicCacheIndex();
  const entry = current[trackId];
  if (entry && Platform.OS !== 'web') {
    try {
      const f = new File(entry.localUri);
      if (f.exists) f.delete();
    } catch {}
  }
  const next = { ...current };
  delete next[trackId];
  memoryIndex = next;
  await safeStorage.setItem(CACHE_INDEX_KEY, JSON.stringify(next));
  return next;
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
  memoryIndex = {};
  await safeStorage.removeItem(CACHE_INDEX_KEY);
}

export async function loadLibrarySnapshot(): Promise<LibrarySnapshot | null> {
  if (Platform.OS === 'web') return null;
  try {
    const f = new File(Paths.document, LIBRARY_SNAPSHOT_FILE);
    if (!f.exists) return null;
    const text = await f.text();
    const parsed = JSON.parse(text) as LibrarySnapshot;
    if (!parsed || !Array.isArray(parsed.likedTracks)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export async function saveLibrarySnapshot(snapshot: Partial<LibrarySnapshot>): Promise<void> {
  if (Platform.OS === 'web') return;
  try {
    const prev = (await loadLibrarySnapshot()) || {
      likedTracks: [],
      likedTotal: 0,
      playlists: [],
      savedAt: 0,
    };
    const next: LibrarySnapshot = {
      likedTracks: snapshot.likedTracks ?? prev.likedTracks,
      likedTotal: snapshot.likedTotal ?? prev.likedTotal,
      playlists: snapshot.playlists ?? prev.playlists,
      savedAt: Date.now(),
    };
    const f = new File(Paths.document, LIBRARY_SNAPSHOT_FILE);
    f.write(JSON.stringify(next));
  } catch {}
}

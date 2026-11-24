/**
 * Music Store — встроенный плеер Яндекс.Музыки на базе expo-audio + постоянный дисковый кэш треков.
 */

import { AudioPlayer, createAudioPlayer, setAudioModeAsync } from 'expo-audio';
import { Platform } from 'react-native';
import { create } from 'zustand';
import {
  CachedTrackEntry,
  cacheTrackToDisk,
  clearAllMusicCache,
  getCachedTrackUri,
  loadMusicCacheIndex,
  removeCachedTrack,
} from '../services/musicCache';
import {
  checkYandexAccount,
  getLikedTracks,
  getMyWaveTracks,
  getPlaylistTracks,
  getTrackStreamUrl,
  getUserPlaylists,
  searchYandexTracks,
  sendWaveFeedback,
  setTrackLike,
  YandexAccountInfo,
  YandexPlaylist,
  YandexTrack,
} from '../services/yandexMusic';
import { usePhoneSettingsStore } from './usePhoneSettingsStore';

interface MusicState {
  account: YandexAccountInfo | null;
  queue: YandexTrack[];
  currentIndex: number;
  currentTrack: YandexTrack | null;
  likedTracks: YandexTrack[];
  likedTotal: number;
  playlists: YandexPlaylist[];
  selectedPlaylist: YandexPlaylist | null;
  playlistTracks: YandexTrack[];
  loadingPlaylists: boolean;
  loadingPlaylistTracks: boolean;
  searchResults: YandexTrack[];
  cachedMap: Record<string, CachedTrackEntry>;
  cachingIds: Record<string, boolean>;
  batchProgress: { done: number; total: number } | null;
  isPlaying: boolean;
  isLoading: boolean;
  isWaveMode: boolean;
  positionMs: number;
  durationMs: number;
  error: string | null;

  loadCache: () => Promise<void>;
  cacheTrack: (track: YandexTrack) => Promise<void>;
  cacheTrackList: (tracks: YandexTrack[]) => Promise<void>;
  cacheAllLiked: () => Promise<void>;
  removeCached: (trackId: string) => Promise<void>;
  clearCache: () => Promise<void>;
  verifyAccount: (tokenOverride?: string) => Promise<YandexAccountInfo>;
  startMyWave: () => Promise<void>;
  loadLiked: (force?: boolean) => Promise<void>;
  loadPlaylists: (force?: boolean) => Promise<void>;
  openPlaylist: (playlist: YandexPlaylist) => Promise<void>;
  closePlaylist: () => void;
  search: (query: string) => Promise<void>;
  playFromList: (tracks: YandexTrack[], index: number, waveMode?: boolean) => Promise<void>;
  togglePlayPause: () => Promise<void>;
  nextTrack: () => Promise<void>;
  prevTrack: () => Promise<void>;
  toggleCurrentLike: () => Promise<void>;
  duckVolume: (ducked: boolean) => Promise<void>;
}

let activePlayer: AudioPlayer | null = null;
let statusSub: { remove: () => void } | null = null;
let audioConfigured = false;
let finishedTrackKey: string | null = null;

async function ensureAudioMode() {
  if (audioConfigured) return;
  try {
    await setAudioModeAsync({
      playsInSilentMode: true,
      shouldPlayInBackground: true,
      interruptionMode: 'doNotMix',
    });
    audioConfigured = true;
  } catch {}
}

export const useMusicStore = create<MusicState>((set, get) => {
  async function downloadInBackground(track: YandexTrack, streamUrl: string) {
    if (Platform.OS === 'web') return;
    if (get().cachedMap[track.id] || get().cachingIds[track.id]) return;

    set((s) => ({ cachingIds: { ...s.cachingIds, [track.id]: true } }));
    try {
      const entry = await cacheTrackToDisk(track, streamUrl);
      if (entry) {
        set((s) => {
          const nextCaching = { ...s.cachingIds };
          delete nextCaching[track.id];
          return {
            cachedMap: { ...s.cachedMap, [track.id]: entry },
            cachingIds: nextCaching,
          };
        });
        return;
      }
    } catch {}
    set((s) => {
      const nextCaching = { ...s.cachingIds };
      delete nextCaching[track.id];
      return { cachingIds: nextCaching };
    });
  }

  async function playAt(index: number) {
    const { queue, isWaveMode } = get();
    if (index < 0 || index >= queue.length) return;
    const track = queue[index];
    const settings = usePhoneSettingsStore.getState();
    const token = settings.yandexToken.trim();

    finishedTrackKey = null;
    set({
      currentIndex: index,
      currentTrack: track,
      isLoading: true,
      positionMs: 0,
      durationMs: track.durationMs || 0,
      error: null,
    });

    try {
      await ensureAudioMode();

      // 1. Сначала проверяем постоянный дисковый кэш (играет даже оффлайн!)
      let playUri = await getCachedTrackUri(track.id);
      if (!playUri) {
        if (!token) {
          throw new Error('Трек не в кэше, а токен Яндекс.Музыки не задан');
        }
        const streamUrl = await getTrackStreamUrl(token, track.id, settings.yandexHighQuality);
        playUri = streamUrl;
        if (settings.autoCacheMusic) {
          void downloadInBackground(track, streamUrl);
        }
      }

      if (!activePlayer) {
        activePlayer = createAudioPlayer({ uri: playUri }, { updateInterval: 500 });
        statusSub = activePlayer.addListener('playbackStatusUpdate', (status) => {
          const cur = get().currentTrack;
          set({
            isPlaying: status.playing,
            isLoading: status.isBuffering && !status.playing,
            positionMs: Math.round((status.currentTime || 0) * 1000),
            durationMs: Math.round((status.duration || 0) * 1000) || cur?.durationMs || 0,
          });
          if (status.didJustFinish && cur) {
            const key = `${cur.id}_${get().currentIndex}`;
            if (finishedTrackKey !== key) {
              finishedTrackKey = key;
              const tk = usePhoneSettingsStore.getState().yandexToken.trim();
              if (get().isWaveMode && tk) {
                void sendWaveFeedback(
                  tk,
                  'trackFinished',
                  cur.id,
                  cur.batchId,
                  Math.round((cur.durationMs || 0) / 1000)
                );
              }
              void get().nextTrack();
            }
          }
        });
      } else {
        activePlayer.replace({ uri: playUri });
      }

      try {
        activePlayer.setActiveForLockScreen(true, {
          title: track.title,
          artist: track.artist,
          albumTitle: track.album,
          artworkUrl: track.coverUrl || undefined,
        });
      } catch {}

      activePlayer.play();
      set({ isPlaying: true, isLoading: false });

      if (isWaveMode && token) {
        void sendWaveFeedback(token, 'trackStarted', track.id, track.batchId);
      }

      if (isWaveMode && token && index >= queue.length - 2) {
        getMyWaveTracks(token, track.id)
          .then((more) => {
            if (more.length > 0) {
              set((s) => {
                const seen = new Set(s.queue.map((t) => t.id));
                const fresh = more.filter((t) => !seen.has(t.id));
                return fresh.length > 0 ? { queue: [...s.queue, ...fresh] } : s;
              });
            }
          })
          .catch(() => {});
      }
    } catch (e: any) {
      set({
        isLoading: false,
        isPlaying: false,
        error: e?.message || 'Не удалось воспроизвести трек',
      });
    }
  }

  async function ensureAccount(): Promise<{ token: string; acc: YandexAccountInfo }> {
    const token = usePhoneSettingsStore.getState().yandexToken.trim();
    if (!token) throw new Error('Добавь YANDEX_MUSIC_TOKEN в Настройках');
    let acc = get().account;
    if (!acc) {
      acc = await checkYandexAccount(token);
      set({ account: acc });
    }
    return { token, acc };
  }

  return {
    account: null,
    queue: [],
    currentIndex: -1,
    currentTrack: null,
    likedTracks: [],
    likedTotal: 0,
    playlists: [],
    selectedPlaylist: null,
    playlistTracks: [],
    loadingPlaylists: false,
    loadingPlaylistTracks: false,
    searchResults: [],
    cachedMap: {},
    cachingIds: {},
    batchProgress: null,
    isPlaying: false,
    isLoading: false,
    isWaveMode: false,
    positionMs: 0,
    durationMs: 0,
    error: null,

    loadCache: async () => {
      const map = await loadMusicCacheIndex();
      set({ cachedMap: map });
    },

    cacheTrack: async (track: YandexTrack) => {
      if (Platform.OS === 'web') {
        set({ error: 'Файловый кэш доступен на Android/iOS' });
        return;
      }
      const settings = usePhoneSettingsStore.getState();
      const token = settings.yandexToken.trim();
      if (!token) return;
      set((s) => ({ cachingIds: { ...s.cachingIds, [track.id]: true } }));
      try {
        const streamUrl = await getTrackStreamUrl(token, track.id, settings.yandexHighQuality);
        const entry = await cacheTrackToDisk(track, streamUrl);
        if (entry) {
          set((s) => ({ cachedMap: { ...s.cachedMap, [track.id]: entry } }));
        }
      } catch (e: any) {
        set({ error: e?.message || 'Ошибка загрузки трека в кэш' });
      } finally {
        set((s) => {
          const next = { ...s.cachingIds };
          delete next[track.id];
          return { cachingIds: next };
        });
      }
    },

    cacheTrackList: async (list: YandexTrack[]) => {
      if (Platform.OS === 'web') return;
      const missing = list.filter((t) => !get().cachedMap[t.id]);
      if (missing.length === 0) return;

      set({ batchProgress: { done: 0, total: missing.length } });
      for (let i = 0; i < missing.length; i++) {
        await get().cacheTrack(missing[i]);
        set({ batchProgress: { done: i + 1, total: missing.length } });
      }
      set({ batchProgress: null });
    },

    cacheAllLiked: async () => {
      if (Platform.OS === 'web') return;
      if (get().likedTracks.length === 0) {
        await get().loadLiked();
      }
      await get().cacheTrackList(get().likedTracks);
    },

    removeCached: async (trackId: string) => {
      const next = await removeCachedTrack(trackId);
      set({ cachedMap: next });
    },

    clearCache: async () => {
      await clearAllMusicCache();
      set({ cachedMap: {} });
    },

    verifyAccount: async (tokenOverride?: string) => {
      const token = (tokenOverride ?? usePhoneSettingsStore.getState().yandexToken).trim();
      set({ isLoading: true, error: null });
      try {
        const account = await checkYandexAccount(token);
        set({ account, isLoading: false });
        return account;
      } catch (e: any) {
        set({ isLoading: false, error: e?.message || 'Ошибка проверки токена' });
        throw e;
      }
    },

    startMyWave: async () => {
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      set({ isLoading: true, error: null });
      try {
        const tracks = await getMyWaveTracks(token);
        if (tracks.length === 0) throw new Error('Волна не вернула треков');
        set({ queue: tracks, isWaveMode: true });
        await playAt(0);
      } catch (e: any) {
        set({ isLoading: false, error: e?.message || 'Ошибка Моей волны' });
      }
    },

    loadLiked: async (force = false) => {
      if (!force && get().likedTracks.length > 0) return;
      set({ isLoading: true, error: null });
      try {
        const { token, acc } = await ensureAccount();
        const liked = await getLikedTracks(token, acc.uid, (partial, totalCount) => {
          set({ likedTracks: partial, likedTotal: totalCount, isLoading: false });
        });
        set({ likedTracks: liked, likedTotal: liked.length, isLoading: false });
      } catch (e: any) {
        set({ isLoading: false, error: e?.message || 'Ошибка загрузки медиатеки' });
      }
    },

    loadPlaylists: async (force = false) => {
      if (!force && get().playlists.length > 0) return;
      set({ loadingPlaylists: true, error: null });
      try {
        const { token, acc } = await ensureAccount();
        const playlists = await getUserPlaylists(token, acc.uid);
        set({ playlists, loadingPlaylists: false });
      } catch (e: any) {
        set({ loadingPlaylists: false, error: e?.message || 'Ошибка загрузки плейлистов' });
      }
    },

    openPlaylist: async (playlist: YandexPlaylist) => {
      set({ selectedPlaylist: playlist, playlistTracks: [], loadingPlaylistTracks: true, error: null });
      try {
        const { token, acc } = await ensureAccount();
        const owner = playlist.ownerUid || acc.uid;
        const tracks = await getPlaylistTracks(token, owner, playlist.kind, (partial) => {
          if (get().selectedPlaylist?.kind === playlist.kind) {
            set({ playlistTracks: partial });
          }
        });
        if (get().selectedPlaylist?.kind === playlist.kind) {
          set({ playlistTracks: tracks, loadingPlaylistTracks: false });
        }
      } catch (e: any) {
        set({ loadingPlaylistTracks: false, error: e?.message || 'Ошибка открытия плейлиста' });
      }
    },

    closePlaylist: () => {
      set({ selectedPlaylist: null, playlistTracks: [], loadingPlaylistTracks: false });
    },

    search: async (query: string) => {
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      if (!query.trim()) {
        set({ searchResults: [] });
        return;
      }
      set({ isLoading: true, error: null });
      try {
        const res = await searchYandexTracks(token, query);
        set({ searchResults: res, isLoading: false });
      } catch (e: any) {
        set({ isLoading: false, error: e?.message || 'Ошибка поиска' });
      }
    },

    playFromList: async (tracks: YandexTrack[], index: number, waveMode = false) => {
      set({ queue: tracks, isWaveMode: waveMode });
      await playAt(index);
    },

    togglePlayPause: async () => {
      if (!activePlayer) {
        if (get().queue.length > 0 && get().currentIndex >= 0) {
          await playAt(get().currentIndex);
        } else {
          await get().startMyWave();
        }
        return;
      }
      if (activePlayer.playing) {
        activePlayer.pause();
        set({ isPlaying: false });
      } else {
        activePlayer.play();
        set({ isPlaying: true });
      }
    },

    nextTrack: async () => {
      const { currentIndex, queue, currentTrack, isWaveMode, positionMs } = get();
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      if (isWaveMode && currentTrack && token) {
        void sendWaveFeedback(
          token,
          'skip',
          currentTrack.id,
          currentTrack.batchId,
          Math.round(positionMs / 1000)
        );
      }
      if (currentIndex + 1 < queue.length) {
        await playAt(currentIndex + 1);
      } else if (isWaveMode) {
        if (token && currentTrack) {
          try {
            const more = await getMyWaveTracks(token, currentTrack.id);
            const seen = new Set(queue.map((t) => t.id));
            const fresh = more.filter((t) => !seen.has(t.id));
            if (fresh.length > 0) {
              const startAt = queue.length;
              set({ queue: [...queue, ...fresh] });
              await playAt(startAt);
              return;
            }
          } catch {}
        }
        await get().startMyWave();
      }
    },

    prevTrack: async () => {
      const { currentIndex } = get();
      if (currentIndex > 0) {
        await playAt(currentIndex - 1);
      }
    },

    toggleCurrentLike: async () => {
      const { currentTrack, account } = get();
      if (!currentTrack) return;
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      let acc = account;
      if (!acc) {
        acc = await checkYandexAccount(token);
        set({ account: acc });
      }
      const nextLiked = !currentTrack.liked;
      await setTrackLike(token, acc.uid, currentTrack.id, nextLiked);
      set((s) => ({
        currentTrack: s.currentTrack ? { ...s.currentTrack, liked: nextLiked } : null,
        queue: s.queue.map((t) => (t.id === currentTrack.id ? { ...t, liked: nextLiked } : t)),
      }));
    },

    duckVolume: async (ducked: boolean) => {
      if (!activePlayer) return;
      try {
        activePlayer.volume = ducked ? 0.22 : 1.0;
      } catch {}
    },
  };
});

export function disposeMusicPlayer() {
  try {
    statusSub?.remove();
    statusSub = null;
    activePlayer?.remove();
    activePlayer = null;
  } catch {}
}

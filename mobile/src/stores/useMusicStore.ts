/**
 * Music Store — встроенный плеер Яндекс.Музыки на базе expo-audio + постоянный дисковый кэш треков.
 */

import {
  AudioPlayer,
  createAudioPlayer,
  requestNotificationPermissionsAsync,
  setAudioModeAsync,
} from 'expo-audio';
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
  getAlbumTracks,
  getArtistTracks,
  getChartTracks,
  getLikedTrackIds,
  getLikedTracks,
  getPlaylistTracks,
  getRotorStations,
  getStationTracks,
  getTrackLyrics,
  getTrackStreamUrl,
  getUserPlaylists,
  searchYandexAll,
  sendWaveFeedback,
  setTrackLike,
  setWaveSettings,
  WaveDiversity,
  WaveMood,
  YandexAccountInfo,
  YandexAlbum,
  YandexArtist,
  YandexPlaylist,
  YandexStation,
  YandexTrack,
} from '../services/yandexMusic';
import { usePhoneSettingsStore } from './usePhoneSettingsStore';

export type RepeatMode = 'off' | 'all' | 'one';

export interface MusicCollectionView {
  kind: 'album' | 'artist';
  id: string;
  title: string;
  subtitle?: string;
  coverUrl: string | null;
  tracks: YandexTrack[];
  loading: boolean;
}

interface MusicState {
  account: YandexAccountInfo | null;
  queue: YandexTrack[];
  currentIndex: number;
  currentTrack: YandexTrack | null;
  likedIds: Record<string, true>;
  likedIdsLoaded: boolean;
  likedTracks: YandexTrack[];
  likedTotal: number;
  loadingLiked: boolean;
  playlists: YandexPlaylist[];
  selectedPlaylist: YandexPlaylist | null;
  playlistTracks: YandexTrack[];
  loadingPlaylists: boolean;
  loadingPlaylistTracks: boolean;
  chartTracks: YandexTrack[];
  loadingChart: boolean;
  stations: YandexStation[];
  activeStationId: string;
  activeStationName: string;
  waveMood: WaveMood;
  waveDiversity: WaveDiversity;
  searchResults: YandexTrack[];
  searchAlbums: YandexAlbum[];
  searchArtists: YandexArtist[];
  selectedCollection: MusicCollectionView | null;
  cachedMap: Record<string, CachedTrackEntry>;
  cachingIds: Record<string, boolean>;
  batchProgress: { done: number; total: number } | null;
  isPlaying: boolean;
  isLoading: boolean;
  isWaveMode: boolean;
  shuffleEnabled: boolean;
  repeatMode: RepeatMode;
  positionMs: number;
  durationMs: number;
  lyricsText: string | null;
  lyricsLoading: boolean;
  lyricsOpen: boolean;
  fullPlayerOpen: boolean;
  error: string | null;

  loadCache: () => Promise<void>;
  cacheTrack: (track: YandexTrack) => Promise<void>;
  cacheTrackList: (tracks: YandexTrack[]) => Promise<void>;
  cacheAllLiked: () => Promise<void>;
  purgeUnlikedCache: () => Promise<number>;
  removeCached: (trackId: string) => Promise<void>;
  clearCache: () => Promise<void>;
  verifyAccount: (tokenOverride?: string) => Promise<YandexAccountInfo>;
  ensureLikedIds: (force?: boolean) => Promise<void>;
  startMyWave: (stationId?: string, stationName?: string) => Promise<void>;
  setWaveMix: (mood: WaveMood, diversity: WaveDiversity) => Promise<void>;
  loadStations: () => Promise<void>;
  loadChart: () => Promise<void>;
  loadLiked: (force?: boolean) => Promise<void>;
  loadPlaylists: (force?: boolean) => Promise<void>;
  openPlaylist: (playlist: YandexPlaylist) => Promise<void>;
  closePlaylist: () => void;
  search: (query: string) => Promise<void>;
  openAlbum: (album: YandexAlbum) => Promise<void>;
  openArtist: (artist: YandexArtist) => Promise<void>;
  closeCollection: () => void;
  playFromList: (tracks: YandexTrack[], index: number, waveMode?: boolean) => Promise<void>;
  playShuffled: (tracks: YandexTrack[]) => Promise<void>;
  togglePlayPause: () => Promise<void>;
  seekTo: (ms: number) => Promise<void>;
  nextTrack: () => Promise<void>;
  prevTrack: () => Promise<void>;
  toggleShuffle: () => void;
  cycleRepeat: () => void;
  toggleTrackLike: (track: YandexTrack) => Promise<void>;
  toggleCurrentLike: () => Promise<void>;
  dislikeCurrentTrack: () => Promise<void>;
  openLyrics: (track?: YandexTrack) => Promise<void>;
  closeLyrics: () => void;
  setFullPlayerOpen: (open: boolean) => void;
  duckVolume: (ducked: boolean) => Promise<void>;
}

let activePlayer: AudioPlayer | null = null;
let statusSub: { remove: () => void } | null = null;
let lockScreenAttached = false;
let notifPermAsked = false;
let finishedTrackKey: string | null = null;

function withLikedFlag(list: YandexTrack[], likedIds: Record<string, true>): YandexTrack[] {
  if (list.length === 0) return list;
  return list.map((t) => ({ ...t, liked: Boolean(likedIds[t.id] ?? t.liked) }));
}

function patchTrackLiked(list: YandexTrack[], trackId: string, liked: boolean): YandexTrack[] {
  return list.map((t) => (t.id === trackId ? { ...t, liked } : t));
}

async function ensureAudioSetup() {
  if (Platform.OS === 'android' && !notifPermAsked) {
    notifPermAsked = true;
    try {
      await requestNotificationPermissionsAsync();
    } catch {}
  }
  try {
    await setAudioModeAsync({
      playsInSilentMode: true,
      shouldPlayInBackground: true,
      interruptionMode: 'doNotMixPersistent',
    });
  } catch {}
}

export const useMusicStore = create<MusicState>((set, get) => {
  async function playAt(index: number) {
    const { queue, isWaveMode, activeStationId, likedIds, repeatMode } = get();
    if (index < 0 || index >= queue.length) return;
    const rawTrack = queue[index];
    const track: YandexTrack = {
      ...rawTrack,
      liked: Boolean(likedIds[rawTrack.id] ?? rawTrack.liked),
    };
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
      await ensureAudioSetup();

      // 1. Сначала проверяем постоянный дисковый кэш (без автозагрузки обычных треков!)
      let playUri = await getCachedTrackUri(track.id);
      if (!playUri) {
        if (!token) {
          throw new Error('Трек не в кэше, а токен Яндекс.Музыки не задан');
        }
        playUri = await getTrackStreamUrl(token, track.id, settings.yandexHighQuality);
      }

      const lockMeta = {
        title: track.title,
        artist: track.artist,
        albumTitle: track.album || 'Яндекс.Музыка',
        artworkUrl: track.coverUrl || undefined,
      };

      if (!activePlayer) {
        activePlayer = createAudioPlayer(
          { uri: playUri },
          { updateInterval: 400, keepAudioSessionActive: true }
        );
        lockScreenAttached = false;
        statusSub = activePlayer.addListener('playbackStatusUpdate', (status) => {
          const cur = get().currentTrack;
          set({
            isPlaying: status.playing,
            isLoading: status.isBuffering && !status.playing,
            positionMs: Math.round((status.currentTime || 0) * 1000),
            durationMs: Math.round((status.duration || 0) * 1000) || cur?.durationMs || 0,
          });
          if (status.didJustFinish && cur && get().repeatMode !== 'one') {
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
                  Math.round((cur.durationMs || 0) / 1000),
                  get().activeStationId
                );
              }
              void get().nextTrack();
            }
          }
        });
      } else {
        activePlayer.replace({ uri: playUri });
      }

      activePlayer.loop = repeatMode === 'one';

      try {
        if (!lockScreenAttached) {
          activePlayer.setActiveForLockScreen(true, lockMeta, {
            showSeekForward: true,
            showSeekBackward: true,
            seekForwardIntervalSeconds: 15,
            seekBackwardIntervalSeconds: 15,
          });
          lockScreenAttached = true;
        } else {
          activePlayer.updateLockScreenMetadata(lockMeta);
        }
      } catch {}

      activePlayer.play();
      set({ isPlaying: true, isLoading: false });

      if (isWaveMode && token) {
        void sendWaveFeedback(token, 'trackStarted', track.id, track.batchId, 0, activeStationId);
      }

      if (isWaveMode && token && index >= queue.length - 2) {
        getStationTracks(token, activeStationId, track.id)
          .then((more) => {
            if (more.length > 0) {
              set((s) => {
                const hydrated = withLikedFlag(more, s.likedIds);
                const seen = new Set(s.queue.map((t) => t.id));
                const fresh = hydrated.filter((t) => !seen.has(t.id));
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
    likedIds: {},
    likedIdsLoaded: false,
    likedTracks: [],
    likedTotal: 0,
    loadingLiked: false,
    playlists: [],
    selectedPlaylist: null,
    playlistTracks: [],
    loadingPlaylists: false,
    loadingPlaylistTracks: false,
    chartTracks: [],
    loadingChart: false,
    stations: [],
    activeStationId: 'user:onyourwave',
    activeStationName: 'Моя волна',
    waveMood: 'all',
    waveDiversity: 'default',
    searchResults: [],
    searchAlbums: [],
    searchArtists: [],
    selectedCollection: null,
    cachedMap: {},
    cachingIds: {},
    batchProgress: null,
    isPlaying: false,
    isLoading: false,
    isWaveMode: false,
    shuffleEnabled: false,
    repeatMode: 'off',
    positionMs: 0,
    durationMs: 0,
    lyricsText: null,
    lyricsLoading: false,
    lyricsOpen: false,
    fullPlayerOpen: false,
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

    purgeUnlikedCache: async () => {
      await get().ensureLikedIds();
      const { cachedMap, likedIds } = get();
      const toDelete = Object.keys(cachedMap).filter((id) => !likedIds[id]);
      for (const id of toDelete) {
        await removeCachedTrack(id);
      }
      const next = await loadMusicCacheIndex();
      set({ cachedMap: next });
      return toDelete.length;
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

    ensureLikedIds: async (force = false) => {
      if (!force && get().likedIdsLoaded) return;
      try {
        const { token, acc } = await ensureAccount();
        const ids = await getLikedTrackIds(token, acc.uid);
        const map: Record<string, true> = {};
        for (const id of ids) map[id] = true;
        set((s) => ({
          likedIds: map,
          likedIdsLoaded: true,
          likedTotal: s.likedTotal || ids.length,
          currentTrack: s.currentTrack
            ? { ...s.currentTrack, liked: Boolean(map[s.currentTrack.id]) }
            : null,
          queue: withLikedFlag(s.queue, map),
          playlistTracks: withLikedFlag(s.playlistTracks, map),
          searchResults: withLikedFlag(s.searchResults, map),
          chartTracks: withLikedFlag(s.chartTracks, map),
        }));
      } catch {}
    },

    startMyWave: async (stationId?: string, stationName?: string) => {
      const sid = stationId || get().activeStationId || 'user:onyourwave';
      const sname = stationName || (sid === 'user:onyourwave' ? 'Моя волна' : get().activeStationName);
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      set({ isLoading: true, error: null, activeStationId: sid, activeStationName: sname });
      try {
        void get().ensureLikedIds();
        const raw = await getStationTracks(token, sid);
        if (raw.length === 0) throw new Error('Волна не вернула треков');
        const tracks = withLikedFlag(raw, get().likedIds);
        set({ queue: tracks, isWaveMode: true });
        await playAt(0);
      } catch (e: any) {
        set({ isLoading: false, error: e?.message || 'Ошибка Моей волны' });
      }
    },

    setWaveMix: async (mood: WaveMood, diversity: WaveDiversity) => {
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      set({ waveMood: mood, waveDiversity: diversity, isLoading: true, error: null });
      try {
        await setWaveSettings(token, mood, diversity);
        await get().startMyWave('user:onyourwave', 'Моя волна');
      } catch (e: any) {
        set({ isLoading: false, error: e?.message || 'Ошибка настройки волны' });
      }
    },

    loadStations: async () => {
      if (get().stations.length > 0) return;
      try {
        const token = usePhoneSettingsStore.getState().yandexToken.trim();
        if (!token) return;
        const stations = await getRotorStations(token);
        set({ stations });
      } catch {}
    },

    loadChart: async () => {
      if (get().chartTracks.length > 0 || get().loadingChart) return;
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      if (!token) return;
      set({ loadingChart: true });
      try {
        void get().ensureLikedIds();
        const chart = await getChartTracks(token);
        set({ chartTracks: withLikedFlag(chart, get().likedIds), loadingChart: false });
      } catch {
        set({ loadingChart: false });
      }
    },

    loadLiked: async (force = false) => {
      if (!force && (get().likedTracks.length > 0 || get().loadingLiked)) return;
      set({ loadingLiked: true, error: null });
      try {
        const { token, acc } = await ensureAccount();
        const liked = await getLikedTracks(token, acc.uid, (partial, totalCount) => {
          const idMap: Record<string, true> = { ...get().likedIds };
          for (const t of partial) idMap[t.id] = true;
          set({
            likedTracks: partial,
            likedTotal: totalCount,
            likedIds: idMap,
            likedIdsLoaded: true,
            loadingLiked: partial.length < totalCount,
          });
        });
        const finalMap: Record<string, true> = {};
        for (const t of liked) finalMap[t.id] = true;
        set({
          likedTracks: liked,
          likedTotal: liked.length,
          likedIds: finalMap,
          likedIdsLoaded: true,
          loadingLiked: false,
        });
      } catch (e: any) {
        set({ loadingLiked: false, error: e?.message || 'Ошибка загрузки медиатеки' });
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
        void get().ensureLikedIds();
        const { token, acc } = await ensureAccount();
        const owner = playlist.ownerUid || acc.uid;
        const tracks = await getPlaylistTracks(token, owner, playlist.kind, (partial) => {
          if (get().selectedPlaylist?.kind === playlist.kind) {
            set({ playlistTracks: withLikedFlag(partial, get().likedIds) });
          }
        });
        if (get().selectedPlaylist?.kind === playlist.kind) {
          set({ playlistTracks: withLikedFlag(tracks, get().likedIds), loadingPlaylistTracks: false });
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
        set({ searchResults: [], searchAlbums: [], searchArtists: [], selectedCollection: null });
        return;
      }
      set({ isLoading: true, error: null, selectedCollection: null });
      try {
        void get().ensureLikedIds();
        const res = await searchYandexAll(token, query);
        set({
          searchResults: withLikedFlag(res.tracks, get().likedIds),
          searchAlbums: res.albums,
          searchArtists: res.artists,
          isLoading: false,
        });
      } catch (e: any) {
        set({ isLoading: false, error: e?.message || 'Ошибка поиска' });
      }
    },

    openAlbum: async (album: YandexAlbum) => {
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      set({
        selectedCollection: {
          kind: 'album',
          id: album.id,
          title: album.title,
          subtitle: album.artist + (album.year ? ` · ${album.year}` : ''),
          coverUrl: album.coverUrl,
          tracks: [],
          loading: true,
        },
      });
      try {
        const res = await getAlbumTracks(token, album.id);
        set({
          selectedCollection: {
            kind: 'album',
            id: album.id,
            title: res.album?.title || album.title,
            subtitle: album.artist + (album.year ? ` · ${album.year}` : ''),
            coverUrl: res.album?.coverUrl || album.coverUrl,
            tracks: withLikedFlag(res.tracks, get().likedIds),
            loading: false,
          },
        });
      } catch (e: any) {
        set((s) => ({
          selectedCollection: s.selectedCollection ? { ...s.selectedCollection, loading: false } : null,
          error: e?.message || 'Ошибка открытия альбома',
        }));
      }
    },

    openArtist: async (artist: YandexArtist) => {
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      set({
        selectedCollection: {
          kind: 'artist',
          id: artist.id,
          title: artist.name,
          subtitle: 'Популярные треки',
          coverUrl: artist.coverUrl,
          tracks: [],
          loading: true,
        },
      });
      try {
        const tracks = await getArtistTracks(token, artist.id);
        set({
          selectedCollection: {
            kind: 'artist',
            id: artist.id,
            title: artist.name,
            subtitle: `${tracks.length} треков`,
            coverUrl: artist.coverUrl,
            tracks: withLikedFlag(tracks, get().likedIds),
            loading: false,
          },
        });
      } catch (e: any) {
        set((s) => ({
          selectedCollection: s.selectedCollection ? { ...s.selectedCollection, loading: false } : null,
          error: e?.message || 'Ошибка загрузки треков исполнителя',
        }));
      }
    },

    closeCollection: () => {
      set({ selectedCollection: null });
    },

    playFromList: async (tracks: YandexTrack[], index: number, waveMode = false) => {
      set({ queue: withLikedFlag(tracks, get().likedIds), isWaveMode: waveMode });
      await playAt(index);
    },

    playShuffled: async (tracks: YandexTrack[]) => {
      if (tracks.length === 0) return;
      const hydrated = withLikedFlag(tracks, get().likedIds);
      const shuffled = [...hydrated];
      for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
      }
      set({ queue: shuffled, isWaveMode: false, shuffleEnabled: true });
      await playAt(0);
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

    seekTo: async (ms: number) => {
      const clamped = Math.max(0, ms);
      set({ positionMs: clamped });
      if (activePlayer) {
        try {
          await activePlayer.seekTo(clamped / 1000);
        } catch {}
      }
    },

    nextTrack: async () => {
      const { currentIndex, queue, currentTrack, isWaveMode, positionMs, shuffleEnabled, repeatMode, activeStationId } =
        get();
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      if (isWaveMode && currentTrack && token) {
        void sendWaveFeedback(
          token,
          'skip',
          currentTrack.id,
          currentTrack.batchId,
          Math.round(positionMs / 1000),
          activeStationId
        );
      }
      if (shuffleEnabled && !isWaveMode && queue.length > 1) {
        let nextIdx = Math.floor(Math.random() * queue.length);
        if (nextIdx === currentIndex) nextIdx = (nextIdx + 1) % queue.length;
        await playAt(nextIdx);
        return;
      }
      if (currentIndex + 1 < queue.length) {
        await playAt(currentIndex + 1);
      } else if (isWaveMode) {
        if (token && currentTrack) {
          try {
            const more = await getStationTracks(token, activeStationId, currentTrack.id);
            const seen = new Set(queue.map((t) => t.id));
            const fresh = withLikedFlag(more, get().likedIds).filter((t) => !seen.has(t.id));
            if (fresh.length > 0) {
              const startAt = queue.length;
              set({ queue: [...queue, ...fresh] });
              await playAt(startAt);
              return;
            }
          } catch {}
        }
        await get().startMyWave(activeStationId);
      } else if (repeatMode === 'all' && queue.length > 0) {
        await playAt(0);
      }
    },

    prevTrack: async () => {
      const { currentIndex, positionMs, queue, repeatMode } = get();
      if (positionMs > 3500 && activePlayer) {
        await get().seekTo(0);
        return;
      }
      if (currentIndex > 0) {
        await playAt(currentIndex - 1);
      } else if (repeatMode === 'all' && queue.length > 0) {
        await playAt(queue.length - 1);
      }
    },

    toggleShuffle: () => {
      set((s) => ({ shuffleEnabled: !s.shuffleEnabled }));
    },

    cycleRepeat: () => {
      set((s) => {
        const next: RepeatMode = s.repeatMode === 'off' ? 'all' : s.repeatMode === 'all' ? 'one' : 'off';
        if (activePlayer) {
          activePlayer.loop = next === 'one';
        }
        return { repeatMode: next };
      });
    },

    toggleTrackLike: async (track: YandexTrack) => {
      try {
        const { token, acc } = await ensureAccount();
        const prevLiked = Boolean(get().likedIds[track.id] ?? track.liked);
        const nextLiked = !prevLiked;

        set((s) => {
          const nextMap = { ...s.likedIds };
          if (nextLiked) nextMap[track.id] = true;
          else delete nextMap[track.id];

          let nextLikedList = s.likedTracks;
          if (nextLiked) {
            if (!nextLikedList.some((x) => x.id === track.id)) {
              nextLikedList = [{ ...track, liked: true }, ...nextLikedList];
            } else {
              nextLikedList = patchTrackLiked(nextLikedList, track.id, true);
            }
          } else {
            nextLikedList = nextLikedList.filter((x) => x.id !== track.id);
          }

          return {
            likedIds: nextMap,
            likedTotal: Math.max(0, s.likedTotal + (nextLiked ? 1 : -1)),
            likedTracks: nextLikedList,
            currentTrack:
              s.currentTrack?.id === track.id ? { ...s.currentTrack, liked: nextLiked } : s.currentTrack,
            queue: patchTrackLiked(s.queue, track.id, nextLiked),
            playlistTracks: patchTrackLiked(s.playlistTracks, track.id, nextLiked),
            searchResults: patchTrackLiked(s.searchResults, track.id, nextLiked),
            chartTracks: patchTrackLiked(s.chartTracks, track.id, nextLiked),
            selectedCollection: s.selectedCollection
              ? {
                  ...s.selectedCollection,
                  tracks: patchTrackLiked(s.selectedCollection.tracks, track.id, nextLiked),
                }
              : null,
          };
        });

        await setTrackLike(token, acc.uid, track.id, nextLiked);

        if (nextLiked && usePhoneSettingsStore.getState().autoCacheLikedOnly) {
          void get().cacheTrack({ ...track, liked: true });
        }
      } catch (e: any) {
        set({ error: e?.message || 'Не удалось обновить лайк' });
      }
    },

    toggleCurrentLike: async () => {
      const cur = get().currentTrack;
      if (cur) await get().toggleTrackLike(cur);
    },

    dislikeCurrentTrack: async () => {
      const { currentTrack, isWaveMode, activeStationId, positionMs } = get();
      if (!currentTrack) return;
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      if (isWaveMode && token) {
        void sendWaveFeedback(
          token,
          'dislike',
          currentTrack.id,
          currentTrack.batchId,
          Math.round(positionMs / 1000),
          activeStationId
        );
      }
      await get().nextTrack();
    },

    openLyrics: async (track?: YandexTrack) => {
      const target = track || get().currentTrack;
      if (!target) return;
      const token = usePhoneSettingsStore.getState().yandexToken.trim();
      set({ lyricsOpen: true, lyricsLoading: true, lyricsText: null });
      const text = token ? await getTrackLyrics(token, target.id) : null;
      set({
        lyricsLoading: false,
        lyricsText: text || 'Текст для этого трека отсутствует на Яндексе',
      });
    },

    closeLyrics: () => {
      set({ lyricsOpen: false });
    },

    setFullPlayerOpen: (open: boolean) => {
      set({ fullPlayerOpen: open });
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
    lockScreenAttached = false;
    activePlayer?.remove();
    activePlayer = null;
  } catch {}
}

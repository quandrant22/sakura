/**
 * Music Screen — высокопроизводительная Яндекс.Музыка в стиле Noir Luxe:
 * getItemLayout + React.memo строки + expo-image кэш + изоляция прогресс-бара,
 * все 2000+ лайков с оффлайн-снапшотом, Моя волна, плейлисты, чарт, поиск и кэш.
 */

import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
import {
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Disc3,
  Download,
  HardDrive,
  Heart,
  ListMusic,
  Pause,
  Play,
  Radio,
  Search,
  Shuffle,
  SkipBack,
  SkipForward,
  Sparkles,
  Trash2,
  User,
} from 'lucide-react-native';
import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { FullPlayerModal } from '../../components/music/FullPlayerModal';
import { SakuraColors } from '../../constants/colors';
import { SakuraFonts } from '../../constants/fonts';
import {
  WaveDiversity,
  WaveMood,
  YandexPlaylist,
  YandexTrack,
} from '../../services/yandexMusic';
import { useMusicProgressStore } from '../../stores/useMusicProgressStore';
import { useMusicStore } from '../../stores/useMusicStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

type MusicTab = 'wave' | 'liked' | 'playlists' | 'search' | 'cache';

const TRACK_ROW_HEIGHT = 64;
const TRACK_ROW_GAP = 7;
const TRACK_ROW_STRIDE = TRACK_ROW_HEIGHT + TRACK_ROW_GAP;

const MOOD_OPTIONS: { id: WaveMood; label: string }[] = [
  { id: 'all', label: 'Любое' },
  { id: 'active', label: 'Бодрое' },
  { id: 'fun', label: 'Весёлое' },
  { id: 'calm', label: 'Спокойное' },
  { id: 'sad', label: 'Грустное' },
];

const DIVERSITY_OPTIONS: { id: WaveDiversity; label: string }[] = [
  { id: 'default', label: 'Микс' },
  { id: 'favorite', label: 'Любимое' },
  { id: 'popular', label: 'Популярное' },
  { id: 'discover', label: 'Новое' },
];

function fmtTime(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const rem = (s % 60).toString().padStart(2, '0');
  return `${m}:${rem}`;
}

function BottomProgressLineBase({
  accent,
  fallbackDurationMs,
}: {
  accent: string;
  fallbackDurationMs: number;
}) {
  const positionMs = useMusicProgressStore((s) => s.positionMs);
  const durationMs = useMusicProgressStore((s) => s.durationMs) || fallbackDurationMs;
  const progressPct =
    durationMs > 0 ? Math.min(100, Math.max(0, (positionMs / durationMs) * 100)) : 0;

  return (
    <View style={styles.progressBg}>
      <View
        style={[styles.progressFill, { width: `${progressPct}%`, backgroundColor: accent }]}
      />
    </View>
  );
}
const BottomProgressLine = memo(BottomProgressLineBase);

function BottomTimeLabelBase({
  artist,
  fallbackDurationMs,
}: {
  artist: string;
  fallbackDurationMs: number;
}) {
  const positionMs = useMusicProgressStore((s) => s.positionMs);
  const durationMs = useMusicProgressStore((s) => s.durationMs) || fallbackDurationMs;
  return (
    <Text style={styles.playerArtist} numberOfLines={1}>
      {artist} · {fmtTime(positionMs)} / {fmtTime(durationMs)}
    </Text>
  );
}
const BottomTimeLabel = memo(BottomTimeLabelBase);

interface TrackRowProps {
  item: YandexTrack;
  index: number;
  isCurrent: boolean;
  isCached: boolean;
  isCaching: boolean;
  isLiked: boolean;
  accent: string;
  onPress: (index: number) => void;
  onToggleLike: (track: YandexTrack) => void;
  onToggleCache: (track: YandexTrack, isCached: boolean, isCaching: boolean) => void;
}

function TrackRowBase({
  item,
  index,
  isCurrent,
  isCached,
  isCaching,
  isLiked,
  accent,
  onPress,
  onToggleLike,
  onToggleCache,
}: TrackRowProps) {
  return (
    <Pressable
      style={({ pressed }) => [
        styles.trackRow,
        isCurrent && { backgroundColor: accent + '1A', borderColor: accent + '60' },
        pressed && { opacity: 0.8 },
      ]}
      onPress={() => onPress(index)}>
      {item.coverUrl ? (
        <Image
          source={{ uri: item.coverUrl }}
          style={styles.trackCover}
          contentFit="cover"
          cachePolicy="memory-disk"
          recyclingKey={item.id}
        />
      ) : (
        <View style={[styles.trackCover, styles.coverStub]}>
          <Disc3 size={18} color={SakuraColors.inkDim} />
        </View>
      )}

      <View style={styles.trackMeta}>
        <Text style={[styles.trackTitle, isCurrent && { color: accent }]} numberOfLines={1}>
          {item.title}
        </Text>
        <Text style={styles.trackArtist} numberOfLines={1}>
          {item.artist}
          {isCached ? ' · оффлайн' : ''}
        </Text>
      </View>

      <Text style={styles.trackDur}>{fmtTime(item.durationMs)}</Text>

      <Pressable
        hitSlop={8}
        style={styles.rowActionBtn}
        onPress={(e) => {
          e.stopPropagation();
          onToggleLike(item);
        }}>
        <Heart
          size={17}
          color={isLiked ? accent : SakuraColors.inkDim}
          fill={isLiked ? accent : 'transparent'}
        />
      </Pressable>

      {Platform.OS !== 'web' && (
        <Pressable
          hitSlop={8}
          style={styles.rowActionBtn}
          onPress={(e) => {
            e.stopPropagation();
            onToggleCache(item, isCached, isCaching);
          }}>
          {isCaching ? (
            <ActivityIndicator size="small" color={accent} />
          ) : isCached ? (
            <CheckCircle2 size={17} color={SakuraColors.online} />
          ) : (
            <Download size={17} color={SakuraColors.inkDim} />
          )}
        </Pressable>
      )}
    </Pressable>
  );
}
const TrackRow = memo(TrackRowBase);

const TRACK_KEY_EXTRACTOR = (item: YandexTrack, idx: number) => `${item.id}_${idx}`;
const PLAYLIST_KEY_EXTRACTOR = (pl: YandexPlaylist) => `${pl.ownerUid}_${pl.kind}`;
const GET_TRACK_LAYOUT = (_: ArrayLike<YandexTrack> | null | undefined, index: number) => ({
  length: TRACK_ROW_HEIGHT,
  offset: TRACK_ROW_STRIDE * index,
  index,
});

export default function MusicScreen() {
  const queue = useMusicStore((s) => s.queue);
  const currentTrack = useMusicStore((s) => s.currentTrack);
  const likedIds = useMusicStore((s) => s.likedIds);
  const likedTracks = useMusicStore((s) => s.likedTracks);
  const likedTotal = useMusicStore((s) => s.likedTotal);
  const loadingLiked = useMusicStore((s) => s.loadingLiked);
  const playlists = useMusicStore((s) => s.playlists);
  const selectedPlaylist = useMusicStore((s) => s.selectedPlaylist);
  const playlistTracks = useMusicStore((s) => s.playlistTracks);
  const loadingPlaylists = useMusicStore((s) => s.loadingPlaylists);
  const loadingPlaylistTracks = useMusicStore((s) => s.loadingPlaylistTracks);
  const chartTracks = useMusicStore((s) => s.chartTracks);
  const loadingChart = useMusicStore((s) => s.loadingChart);
  const stations = useMusicStore((s) => s.stations);
  const activeStationId = useMusicStore((s) => s.activeStationId);
  const activeStationName = useMusicStore((s) => s.activeStationName);
  const waveMood = useMusicStore((s) => s.waveMood);
  const waveDiversity = useMusicStore((s) => s.waveDiversity);
  const searchResults = useMusicStore((s) => s.searchResults);
  const searchAlbums = useMusicStore((s) => s.searchAlbums);
  const searchArtists = useMusicStore((s) => s.searchArtists);
  const selectedCollection = useMusicStore((s) => s.selectedCollection);
  const cachedMap = useMusicStore((s) => s.cachedMap);
  const cachingIds = useMusicStore((s) => s.cachingIds);
  const batchProgress = useMusicStore((s) => s.batchProgress);
  const isPlaying = useMusicStore((s) => s.isPlaying);
  const isLoading = useMusicStore((s) => s.isLoading);
  const error = useMusicStore((s) => s.error);

  const loadCache = useMusicStore((s) => s.loadCache);
  const ensureLikedIds = useMusicStore((s) => s.ensureLikedIds);
  const startMyWave = useMusicStore((s) => s.startMyWave);
  const setWaveMix = useMusicStore((s) => s.setWaveMix);
  const loadStations = useMusicStore((s) => s.loadStations);
  const loadChart = useMusicStore((s) => s.loadChart);
  const loadLiked = useMusicStore((s) => s.loadLiked);
  const loadPlaylists = useMusicStore((s) => s.loadPlaylists);
  const openPlaylist = useMusicStore((s) => s.openPlaylist);
  const closePlaylist = useMusicStore((s) => s.closePlaylist);
  const search = useMusicStore((s) => s.search);
  const openAlbum = useMusicStore((s) => s.openAlbum);
  const openArtist = useMusicStore((s) => s.openArtist);
  const closeCollection = useMusicStore((s) => s.closeCollection);
  const playFromList = useMusicStore((s) => s.playFromList);
  const playShuffled = useMusicStore((s) => s.playShuffled);
  const togglePlayPause = useMusicStore((s) => s.togglePlayPause);
  const nextTrack = useMusicStore((s) => s.nextTrack);
  const prevTrack = useMusicStore((s) => s.prevTrack);
  const toggleTrackLike = useMusicStore((s) => s.toggleTrackLike);
  const toggleCurrentLike = useMusicStore((s) => s.toggleCurrentLike);
  const cacheTrack = useMusicStore((s) => s.cacheTrack);
  const cacheTrackList = useMusicStore((s) => s.cacheTrackList);
  const cacheAllLiked = useMusicStore((s) => s.cacheAllLiked);
  const cancelBatchCache = useMusicStore((s) => s.cancelBatchCache);
  const purgeUnlikedCache = useMusicStore((s) => s.purgeUnlikedCache);
  const removeCached = useMusicStore((s) => s.removeCached);
  const clearCache = useMusicStore((s) => s.clearCache);
  const setFullPlayerOpen = useMusicStore((s) => s.setFullPlayerOpen);

  const accentTheme = usePhoneSettingsStore((s) => s.accentTheme);
  const hapticsEnabled = usePhoneSettingsStore((s) => s.hapticsEnabled);
  const accent = ACCENT_THEMES[accentTheme].accent;

  const [tab, setTab] = useState<MusicTab>('liked');
  const [query, setQuery] = useState('');
  const [likesFilter, setLikesFilter] = useState('');

  useEffect(() => {
    void loadCache();
    void ensureLikedIds();
  }, [loadCache, ensureLikedIds]);

  useEffect(() => {
    if (tab === 'liked' && likedTracks.length === 0) {
      void loadLiked();
    } else if (tab === 'playlists' && playlists.length === 0) {
      void loadPlaylists();
    } else if (tab === 'wave' && stations.length === 0) {
      void loadStations();
    } else if (tab === 'search' && !query.trim() && chartTracks.length === 0) {
      void loadChart();
    }
  }, [
    tab,
    likedTracks.length,
    playlists.length,
    stations.length,
    chartTracks.length,
    query,
    loadLiked,
    loadPlaylists,
    loadStations,
    loadChart,
  ]);

  const haptic = useCallback(() => {
    if (!hapticsEnabled) return;
    try {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch {}
  }, [hapticsEnabled]);

  const { cachedTracks, unlikedCachedCount, totalMb } = useMemo(() => {
    const entries = Object.values(cachedMap).sort((a, b) => b.cachedAt - a.cachedAt);
    const tracks: YandexTrack[] = entries.map((e) => ({
      ...e.track,
      liked: Boolean(likedIds[e.track.id] ?? e.track.liked),
    }));
    const unliked = entries.filter((e) => !likedIds[e.track.id]).length;
    const bytes = entries.reduce((acc, e) => acc + (e.sizeBytes || 0), 0);
    return {
      cachedTracks: tracks,
      unlikedCachedCount: unliked,
      totalMb: (bytes / (1024 * 1024)).toFixed(1),
    };
  }, [cachedMap, likedIds]);

  const filteredLiked = useMemo(() => {
    const q = likesFilter.trim().toLowerCase();
    if (!q) return likedTracks;
    return likedTracks.filter(
      (t) =>
        t.title.toLowerCase().includes(q) ||
        t.artist.toLowerCase().includes(q) ||
        (t.album || '').toLowerCase().includes(q)
    );
  }, [likedTracks, likesFilter]);

  const listData = useMemo(() => {
    if (tab === 'wave') return queue;
    if (tab === 'liked') return filteredLiked;
    if (tab === 'playlists') return selectedPlaylist ? playlistTracks : [];
    if (tab === 'cache') return cachedTracks;
    if (selectedCollection) return selectedCollection.tracks;
    return query.trim() ? searchResults : chartTracks;
  }, [
    tab,
    queue,
    filteredLiked,
    selectedPlaylist,
    playlistTracks,
    cachedTracks,
    selectedCollection,
    query,
    searchResults,
    chartTracks,
  ]);

  const listDataRef = useRef(listData);
  const tabRef = useRef(tab);
  useEffect(() => {
    listDataRef.current = listData;
    tabRef.current = tab;
  }, [listData, tab]);

  const handlePressTrack = useCallback(
    (index: number) => {
      haptic();
      void playFromList(listDataRef.current, index, tabRef.current === 'wave');
    },
    [haptic, playFromList]
  );

  const handleToggleLike = useCallback(
    (track: YandexTrack) => {
      haptic();
      void toggleTrackLike(track);
    },
    [haptic, toggleTrackLike]
  );

  const handleToggleCache = useCallback(
    (track: YandexTrack, isCached: boolean, isCaching: boolean) => {
      haptic();
      if (isCached) void removeCached(track.id);
      else if (!isCaching) void cacheTrack(track);
    },
    [haptic, removeCached, cacheTrack]
  );

  const confirmClearCache = useCallback(() => {
    if (Platform.OS === 'web') {
      void clearCache();
      return;
    }
    Alert.alert('Очистить весь кэш?', `Удалить ${cachedTracks.length} треков (${totalMb} МБ)?`, [
      { text: 'Отмена', style: 'cancel' },
      { text: 'Очистить', style: 'destructive', onPress: () => void clearCache() },
    ]);
  }, [cachedTracks.length, totalMb, clearCache]);

  const currentTrackId = currentTrack?.id;

  const renderTrack = useCallback(
    ({ item, index }: { item: YandexTrack; index: number }) => (
      <TrackRow
        item={item}
        index={index}
        isCurrent={currentTrackId === item.id}
        isCached={Boolean(cachedMap[item.id])}
        isCaching={Boolean(cachingIds[item.id])}
        isLiked={Boolean(likedIds[item.id] ?? item.liked)}
        accent={accent}
        onPress={handlePressTrack}
        onToggleLike={handleToggleLike}
        onToggleCache={handleToggleCache}
      />
    ),
    [
      currentTrackId,
      cachedMap,
      cachingIds,
      likedIds,
      accent,
      handlePressTrack,
      handleToggleLike,
      handleToggleCache,
    ]
  );

  const renderPlaylist = useCallback(
    ({ item: pl }: { item: YandexPlaylist }) => (
      <Pressable
        style={({ pressed }) => [styles.trackRow, pressed && { opacity: 0.82 }]}
        onPress={() => {
          haptic();
          void openPlaylist(pl);
        }}>
        {pl.coverUrl ? (
          <Image
            source={{ uri: pl.coverUrl }}
            style={styles.trackCover}
            contentFit="cover"
            cachePolicy="memory-disk"
            recyclingKey={`pl_${pl.kind}`}
          />
        ) : (
          <View style={[styles.trackCover, styles.coverStub]}>
            <ListMusic size={20} color={accent} />
          </View>
        )}
        <View style={styles.trackMeta}>
          <Text style={styles.trackTitle} numberOfLines={1}>
            {pl.title}
          </Text>
          <Text style={styles.playlistCount}>{pl.trackCount} ТРЕКОВ</Text>
        </View>
        <ChevronRight size={18} color={SakuraColors.inkDim} />
      </Pressable>
    ),
    [accent, haptic, openPlaylist]
  );

  const renderCollectionBar = (
    title: string,
    sub: string,
    tracks: YandexTrack[],
    onBack: () => void
  ) => (
    <View style={styles.collectionBar}>
      <Pressable
        style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.7 }]}
        onPress={() => {
          haptic();
          onBack();
        }}>
        <ArrowLeft size={16} color={SakuraColors.ink} />
      </Pressable>
      <View style={{ flex: 1 }}>
        <Text style={styles.collectionTitle} numberOfLines={1}>
          {title}
        </Text>
        <Text style={styles.collectionSub} numberOfLines={1}>
          {sub}
        </Text>
      </View>
      {tracks.length > 0 && (
        <>
          <Pressable
            style={[styles.miniPillBtn, { borderColor: accent + '55', backgroundColor: accent + '1C' }]}
            onPress={() => {
              haptic();
              void playFromList(tracks, 0, false);
            }}>
            <Play size={13} color={accent} />
            <Text style={[styles.miniPillText, { color: accent }]}>Слушать</Text>
          </Pressable>
          <Pressable
            style={[styles.miniPillBtn, { borderColor: SakuraColors.lineStrong }]}
            onPress={() => {
              haptic();
              void playShuffled(tracks);
            }}>
            <Shuffle size={13} color={SakuraColors.ink} />
          </Pressable>
          {Platform.OS !== 'web' && !batchProgress && (
            <Pressable
              style={[styles.miniPillBtn, { borderColor: SakuraColors.lineStrong }]}
              onPress={() => {
                haptic();
                void cacheTrackList(tracks);
              }}>
              <Download size={13} color={SakuraColors.ink} />
            </Pressable>
          )}
        </>
      )}
    </View>
  );

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.container}>
          <View style={styles.headerRow}>
            <Text style={styles.screenTitle}>Яндекс.Музыка</Text>
            {cachedTracks.length > 0 && (
              <View style={styles.cacheBadge}>
                <HardDrive size={12} color={SakuraColors.online} />
                <Text style={styles.cacheBadgeText}>
                  {cachedTracks.length} · {totalMb} MB
                </Text>
              </View>
            )}
          </View>

          {error ? <Text style={styles.errorText}>{error}</Text> : null}

          <View style={styles.tabsRowWrap}>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.tabsRow}>
              {[
                { id: 'wave' as MusicTab, label: 'Волна' },
                {
                  id: 'liked' as MusicTab,
                  label:
                    likedTotal > 0 || likedTracks.length > 0
                      ? `Лайки (${likedTotal || likedTracks.length})`
                      : 'Лайки',
                },
                {
                  id: 'playlists' as MusicTab,
                  label: playlists.length > 0 ? `Плейлисты (${playlists.length})` : 'Плейлисты',
                },
                { id: 'search' as MusicTab, label: 'Поиск и Чарт' },
                {
                  id: 'cache' as MusicTab,
                  label: cachedTracks.length > 0 ? `Кэш (${cachedTracks.length})` : 'Кэш',
                },
              ].map((item) => {
                const active = tab === item.id;
                return (
                  <Pressable
                    key={item.id}
                    style={[
                      styles.segmentBtn,
                      active && { backgroundColor: accent + '24', borderColor: accent },
                    ]}
                    onPress={() => {
                      haptic();
                      setTab(item.id);
                      if (item.id === 'wave' && queue.length === 0) {
                        void startMyWave();
                      }
                    }}>
                    <Text
                      style={[styles.segmentText, active && { color: accent }]}
                      numberOfLines={1}>
                      {item.label}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>

          {tab === 'wave' && (
            <View style={styles.waveControlsBox}>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.chipStrip}>
                <View
                  style={[styles.chipPill, { borderColor: accent + '66', backgroundColor: accent + '16' }]}>
                  <Sparkles size={12} color={accent} />
                  <Text style={[styles.chipText, { color: accent }]}>{activeStationName}</Text>
                </View>
                {MOOD_OPTIONS.map((m) => {
                  const active = waveMood === m.id && activeStationId === 'user:onyourwave';
                  return (
                    <Pressable
                      key={m.id}
                      style={[
                        styles.chipPill,
                        active && { borderColor: accent, backgroundColor: accent + '24' },
                      ]}
                      onPress={() => {
                        haptic();
                        void setWaveMix(m.id, waveDiversity);
                      }}>
                      <Text style={[styles.chipText, active && { color: accent }]}>{m.label}</Text>
                    </Pressable>
                  );
                })}
                {DIVERSITY_OPTIONS.map((d) => {
                  const active = waveDiversity === d.id && activeStationId === 'user:onyourwave';
                  return (
                    <Pressable
                      key={d.id}
                      style={[
                        styles.chipPill,
                        active && {
                          borderColor: SakuraColors.cyan,
                          backgroundColor: 'rgba(79,216,255,0.16)',
                        },
                      ]}
                      onPress={() => {
                        haptic();
                        void setWaveMix(waveMood, d.id);
                      }}>
                      <Text style={[styles.chipText, active && { color: SakuraColors.cyan }]}>
                        {d.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </ScrollView>

              {stations.length > 0 && (
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  contentContainerStyle={styles.chipStrip}>
                  {stations.slice(0, 14).map((st) => {
                    const active = activeStationId === st.id;
                    return (
                      <Pressable
                        key={st.id}
                        style={[
                          styles.stationPill,
                          active && { borderColor: accent, backgroundColor: accent + '20' },
                        ]}
                        onPress={() => {
                          haptic();
                          void startMyWave(st.id, st.name);
                        }}>
                        <Radio size={11} color={active ? accent : SakuraColors.inkDim} />
                        <Text style={[styles.stationText, active && { color: accent }]}>
                          {st.name}
                        </Text>
                      </Pressable>
                    );
                  })}
                </ScrollView>
              )}
            </View>
          )}

          {tab === 'liked' && (
            <View style={styles.likesToolbar}>
              <View style={styles.searchBox}>
                <Search size={15} color={SakuraColors.inkDim} />
                <TextInput
                  style={styles.searchInput}
                  placeholder={`Фильтр по лайкам (${likedTracks.length}${
                    likedTotal > likedTracks.length ? ` / ${likedTotal}` : ''
                  })…`}
                  placeholderTextColor="rgba(248, 244, 255, 0.42)"
                  selectionColor={accent}
                  cursorColor={accent}
                  value={likesFilter}
                  onChangeText={setLikesFilter}
                  underlineColorAndroid="transparent"
                />
              </View>
              <View style={styles.likesBtnsRow}>
                <Pressable
                  style={[styles.miniPillBtn, { borderColor: accent + '60', backgroundColor: accent + '1C' }]}
                  onPress={() => {
                    haptic();
                    if (filteredLiked.length > 0) void playFromList(filteredLiked, 0, false);
                  }}>
                  <Play size={13} color={accent} />
                  <Text style={[styles.miniPillText, { color: accent }]}>Играть</Text>
                </Pressable>
                <Pressable
                  style={[styles.miniPillBtn, { borderColor: SakuraColors.lineStrong }]}
                  onPress={() => {
                    haptic();
                    if (filteredLiked.length > 0) void playShuffled(filteredLiked);
                  }}>
                  <Shuffle size={13} color={SakuraColors.ink} />
                  <Text style={[styles.miniPillText, { color: SakuraColors.ink }]}>Вперемешку</Text>
                </Pressable>
                {Platform.OS !== 'web' && !batchProgress && (
                  <Pressable
                    style={[styles.miniPillBtn, { borderColor: SakuraColors.lineStrong, marginLeft: 'auto' }]}
                    onPress={() => {
                      haptic();
                      void cacheAllLiked();
                    }}>
                    <Download size={13} color={SakuraColors.ink} />
                    <Text style={[styles.miniPillText, { color: SakuraColors.ink }]}>В кэш</Text>
                  </Pressable>
                )}
              </View>
            </View>
          )}

          {tab === 'search' && !selectedCollection && (
            <View style={styles.searchBox}>
              <Search size={16} color={SakuraColors.inkDim} />
              <TextInput
                style={styles.searchInput}
                placeholder="Трек, альбом или исполнитель…"
                placeholderTextColor="rgba(248, 244, 255, 0.42)"
                selectionColor={accent}
                cursorColor={accent}
                value={query}
                onChangeText={setQuery}
                onSubmitEditing={() => void search(query)}
                returnKeyType="search"
                underlineColorAndroid="transparent"
              />
            </View>
          )}

          {tab === 'search' &&
            !selectedCollection &&
            Boolean(query.trim()) &&
            (searchArtists.length > 0 || searchAlbums.length > 0) && (
              <View style={styles.searchEntitiesWrap}>
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  contentContainerStyle={styles.chipStrip}>
                  {searchArtists.slice(0, 5).map((ar) => (
                    <Pressable
                      key={`ar_${ar.id}`}
                      style={styles.entityChip}
                      onPress={() => {
                        haptic();
                        void openArtist(ar);
                      }}>
                      {ar.coverUrl ? (
                        <Image
                          source={{ uri: ar.coverUrl }}
                          style={styles.entityAvatar}
                          contentFit="cover"
                          cachePolicy="memory-disk"
                        />
                      ) : (
                        <User size={14} color={accent} />
                      )}
                      <Text style={styles.entityTitle} numberOfLines={1}>
                        {ar.name}
                      </Text>
                    </Pressable>
                  ))}
                  {searchAlbums.slice(0, 6).map((al) => (
                    <Pressable
                      key={`al_${al.id}`}
                      style={styles.entityChip}
                      onPress={() => {
                        haptic();
                        void openAlbum(al);
                      }}>
                      {al.coverUrl ? (
                        <Image
                          source={{ uri: al.coverUrl }}
                          style={styles.entityThumb}
                          contentFit="cover"
                          cachePolicy="memory-disk"
                        />
                      ) : (
                        <Disc3 size={14} color={SakuraColors.cyan} />
                      )}
                      <Text style={styles.entityTitle} numberOfLines={1}>
                        {al.title}
                      </Text>
                    </Pressable>
                  ))}
                </ScrollView>
              </View>
            )}

          {tab === 'search' &&
            selectedCollection &&
            renderCollectionBar(
              selectedCollection.title,
              selectedCollection.subtitle || '',
              selectedCollection.tracks,
              closeCollection
            )}

          {tab === 'playlists' &&
            selectedPlaylist &&
            renderCollectionBar(
              selectedPlaylist.title,
              `${playlistTracks.length || selectedPlaylist.trackCount} треков`,
              playlistTracks,
              closePlaylist
            )}

          {(batchProgress || (tab === 'cache' && Platform.OS !== 'web')) && (
            <View style={styles.cacheActionsRow}>
              {batchProgress ? (
                <View style={styles.batchBanner}>
                  <ActivityIndicator size="small" color={accent} />
                  <Text style={styles.batchText}>
                    Кэширую лайки: {batchProgress.done} / {batchProgress.total}…
                  </Text>
                  <Pressable
                    hitSlop={8}
                    onPress={() => {
                      haptic();
                      cancelBatchCache();
                    }}
                    style={styles.stopBatchBtn}>
                    <Text style={styles.stopBatchText}>Стоп</Text>
                  </Pressable>
                </View>
              ) : (
                <>
                  <Pressable
                    style={[
                      styles.cacheActionBtn,
                      { borderColor: accent + '55', backgroundColor: accent + '14' },
                    ]}
                    onPress={() => {
                      haptic();
                      void cacheAllLiked();
                    }}>
                    <Download size={14} color={accent} />
                    <Text style={[styles.cacheActionText, { color: accent }]}>Скачать лайки</Text>
                  </Pressable>
                  {unlikedCachedCount > 0 && (
                    <Pressable
                      style={[
                        styles.clearCacheBtn,
                        {
                          borderColor: SakuraColors.warn + '66',
                          backgroundColor: 'rgba(255,180,60,0.12)',
                        },
                      ]}
                      onPress={() => {
                        haptic();
                        void purgeUnlikedCache();
                      }}>
                      <Text style={[styles.cacheActionText, { color: SakuraColors.warn }]}>
                        Убрать лишние ({unlikedCachedCount})
                      </Text>
                    </Pressable>
                  )}
                  {cachedTracks.length > 0 && (
                    <Pressable style={styles.clearCacheBtn} onPress={confirmClearCache}>
                      <Trash2 size={14} color={SakuraColors.error} />
                    </Pressable>
                  )}
                </>
              )}
            </View>
          )}

          <View style={{ flex: 1 }}>
            {tab === 'playlists' && !selectedPlaylist ? (
              <FlatList<YandexPlaylist>
                data={playlists}
                keyExtractor={PLAYLIST_KEY_EXTRACTOR}
                renderItem={renderPlaylist}
                initialNumToRender={12}
                maxToRenderPerBatch={10}
                windowSize={5}
                removeClippedSubviews={Platform.OS === 'android'}
                contentContainerStyle={styles.listContent}
                ListEmptyComponent={
                  <View style={styles.emptyBox}>
                    <Text style={styles.emptyText}>
                      {loadingPlaylists ? 'Загрузка плейлистов…' : 'Плейлисты не найдены'}
                    </Text>
                  </View>
                }
              />
            ) : (
              <FlatList
                data={listData}
                keyExtractor={TRACK_KEY_EXTRACTOR}
                renderItem={renderTrack}
                getItemLayout={GET_TRACK_LAYOUT}
                initialNumToRender={12}
                maxToRenderPerBatch={10}
                updateCellsBatchingPeriod={24}
                windowSize={5}
                removeClippedSubviews={Platform.OS === 'android'}
                keyboardShouldPersistTaps="handled"
                contentContainerStyle={styles.listContent}
                ListHeaderComponent={
                  tab === 'search' && !query.trim() && !selectedCollection && chartTracks.length > 0 ? (
                    <Text style={styles.sectionSubHeader}>ЧАРТ ЯНДЕКС.МУЗЫКИ · ТОП-100</Text>
                  ) : undefined
                }
                ListEmptyComponent={
                  <View style={styles.emptyBox}>
                    <Text style={styles.emptyText}>
                      {isLoading ||
                      loadingLiked ||
                      loadingPlaylistTracks ||
                      loadingChart ||
                      selectedCollection?.loading
                        ? 'Загрузка треков…'
                        : tab === 'wave'
                        ? 'Нажми «Моя волна» снизу'
                        : tab === 'liked'
                        ? 'Любимые треки появятся здесь'
                        : tab === 'playlists'
                        ? 'В этом плейлисте пока нет треков'
                        : tab === 'cache'
                        ? 'Кэш пуст — нажми «Скачать лайки» или скачай нужные треки ❤'
                        : 'Введи запрос для поиска'}
                    </Text>
                  </View>
                }
              />
            )}
          </View>

          {currentTrack ? (
            <Pressable
              style={[styles.bottomPlayer, { borderColor: accent + '48' }]}
              onPress={() => {
                haptic();
                setFullPlayerOpen(true);
              }}>
              <BottomProgressLine accent={accent} fallbackDurationMs={currentTrack.durationMs} />

              <View style={styles.bottomPlayerRow}>
                {currentTrack.coverUrl ? (
                  <Image
                    source={{ uri: currentTrack.coverUrl }}
                    style={styles.miniCover}
                    contentFit="cover"
                    cachePolicy="memory-disk"
                    transition={120}
                  />
                ) : (
                  <View style={[styles.miniCover, styles.coverStub]}>
                    <Disc3 size={20} color={accent} />
                  </View>
                )}

                <View style={styles.playerMeta}>
                  <Text style={styles.playerTitle} numberOfLines={1}>
                    {currentTrack.title}
                  </Text>
                  <BottomTimeLabel
                    artist={currentTrack.artist}
                    fallbackDurationMs={currentTrack.durationMs}
                  />
                </View>

                <Pressable
                  hitSlop={8}
                  style={styles.bottomIconBtn}
                  onPress={(e) => {
                    e.stopPropagation();
                    haptic();
                    void toggleCurrentLike();
                  }}>
                  <Heart
                    size={18}
                    color={currentTrack.liked ? accent : SakuraColors.inkDim}
                    fill={currentTrack.liked ? accent : 'transparent'}
                  />
                </Pressable>

                <Pressable
                  hitSlop={8}
                  style={styles.bottomIconBtn}
                  onPress={(e) => {
                    e.stopPropagation();
                    haptic();
                    void prevTrack();
                  }}>
                  <SkipBack size={18} color={SakuraColors.ink} />
                </Pressable>

                <Pressable
                  style={[styles.playMiniBtn, { backgroundColor: accent }]}
                  onPress={(e) => {
                    e.stopPropagation();
                    haptic();
                    void togglePlayPause();
                  }}>
                  {isLoading ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : isPlaying ? (
                    <Pause size={17} color="#fff" fill="#fff" />
                  ) : (
                    <Play size={17} color="#fff" fill="#fff" />
                  )}
                </Pressable>

                <Pressable
                  hitSlop={8}
                  style={styles.bottomIconBtn}
                  onPress={(e) => {
                    e.stopPropagation();
                    haptic();
                    void nextTrack();
                  }}>
                  <SkipForward size={18} color={SakuraColors.ink} />
                </Pressable>
              </View>
            </Pressable>
          ) : (
            <Pressable
              style={({ pressed }) => [styles.bottomWavePill, pressed && { opacity: 0.88 }]}
              onPress={() => {
                haptic();
                setTab('wave');
                void startMyWave();
              }}>
              <View style={styles.waveIconCircle}>
                {isLoading ? (
                  <ActivityIndicator size="small" color="#14101c" />
                ) : (
                  <Radio size={20} color="#14101c" />
                )}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.waveTitle}>Включить «Мою волну»</Text>
                <Text style={styles.waveSub}>Бесконечный персональный поток Яндекса</Text>
              </View>
              <Play size={18} color="#14101c" fill="#14101c" />
            </Pressable>
          )}
        </View>
      </KeyboardAvoidingView>

      <FullPlayerModal />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  container: {
    flex: 1,
    paddingHorizontal: 14,
    paddingTop: 8,
    gap: 8,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 4,
  },
  screenTitle: {
    fontSize: 21,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  cacheBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  cacheBadgeText: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10.5,
    color: SakuraColors.inkDim,
  },
  errorText: {
    color: SakuraColors.warn,
    fontSize: 12,
    fontWeight: '600',
    paddingHorizontal: 4,
  },
  tabsRowWrap: {
    borderRadius: 14,
    backgroundColor: 'rgba(18, 14, 28, 0.85)',
    borderWidth: 1,
    borderColor: SakuraColors.lineStrong,
    overflow: 'hidden',
  },
  tabsRow: {
    flexDirection: 'row',
    padding: 4,
    gap: 4,
  },
  segmentBtn: {
    paddingVertical: 7,
    paddingHorizontal: 11,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: 'transparent',
    alignItems: 'center',
  },
  segmentText: {
    fontSize: 12,
    fontWeight: '700',
    color: SakuraColors.inkDim,
  },
  waveControlsBox: {
    gap: 6,
  },
  chipStrip: {
    flexDirection: 'row',
    gap: 6,
    paddingHorizontal: 2,
  },
  chipPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  chipText: {
    fontSize: 11.5,
    fontWeight: '700',
    color: SakuraColors.inkDim,
  },
  stationPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 10,
    backgroundColor: 'rgba(20, 15, 32, 0.72)',
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  stationText: {
    fontSize: 11,
    fontWeight: '600',
    color: SakuraColors.inkDim,
  },
  likesToolbar: {
    gap: 7,
  },
  likesBtnsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    backgroundColor: SakuraColors.bgInput,
    borderRadius: 13,
    paddingHorizontal: 12,
    borderWidth: 1.2,
    borderColor: SakuraColors.lineStrong,
  },
  searchInput: {
    flex: 1,
    color: '#FFFFFF',
    paddingVertical: 8.5,
    fontSize: 14,
  },
  searchEntitiesWrap: {
    marginVertical: 2,
  },
  entityChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 12,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.lineStrong,
    maxWidth: 170,
  },
  entityAvatar: {
    width: 22,
    height: 22,
    borderRadius: 11,
  },
  entityThumb: {
    width: 22,
    height: 22,
    borderRadius: 6,
  },
  entityTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  collectionBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    paddingVertical: 6,
    paddingHorizontal: 8,
    borderRadius: 13,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.lineStrong,
  },
  backBtn: {
    width: 32,
    height: 32,
    borderRadius: 9,
    backgroundColor: SakuraColors.panel2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  collectionTitle: {
    fontSize: 13.5,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  collectionSub: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10,
    color: SakuraColors.textMuted,
  },
  miniPillBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 6.5,
    borderRadius: 10,
    borderWidth: 1,
    backgroundColor: SakuraColors.panel2,
  },
  miniPillText: {
    fontSize: 11.5,
    fontWeight: '700',
  },
  playlistCount: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10,
    color: SakuraColors.textMuted,
    letterSpacing: 0.4,
  },
  cacheActionsRow: {
    flexDirection: 'row',
    gap: 7,
    alignItems: 'center',
  },
  cacheActionBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 8.5,
    paddingHorizontal: 10,
    borderRadius: 11,
    borderWidth: 1,
  },
  clearCacheBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 5,
    paddingVertical: 8.5,
    paddingHorizontal: 11,
    borderRadius: 11,
    backgroundColor: 'rgba(255, 82, 119, 0.12)',
    borderWidth: 1,
    borderColor: 'rgba(255, 82, 119, 0.35)',
  },
  cacheActionText: {
    fontSize: 12,
    fontWeight: '700',
  },
  batchBanner: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 8.5,
    borderRadius: 11,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  batchText: {
    flex: 1,
    fontSize: 12,
    fontWeight: '600',
    color: SakuraColors.ink,
  },
  stopBatchBtn: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
    backgroundColor: 'rgba(255, 82, 119, 0.16)',
    borderWidth: 1,
    borderColor: 'rgba(255, 82, 119, 0.4)',
  },
  stopBatchText: {
    fontSize: 11,
    fontWeight: '700',
    color: SakuraColors.error,
  },
  sectionSubHeader: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10,
    letterSpacing: 1.0,
    color: SakuraColors.textMuted,
    paddingHorizontal: 4,
    paddingVertical: 4,
  },
  listContent: {
    paddingBottom: 10,
  },
  trackRow: {
    height: TRACK_ROW_HEIGHT,
    marginBottom: TRACK_ROW_GAP,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    paddingHorizontal: 9,
    borderRadius: 13,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  trackCover: {
    width: 44,
    height: 44,
    borderRadius: 10,
    backgroundColor: SakuraColors.panel2,
  },
  coverStub: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  trackMeta: {
    flex: 1,
    gap: 2,
  },
  trackTitle: {
    fontSize: 13.5,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  trackArtist: {
    fontSize: 11.5,
    color: SakuraColors.inkDim,
  },
  trackDur: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10,
    color: SakuraColors.textMuted,
  },
  rowActionBtn: {
    padding: 5,
  },
  emptyBox: {
    paddingVertical: 40,
    alignItems: 'center',
  },
  emptyText: {
    color: SakuraColors.inkDim,
    fontSize: 13,
    textAlign: 'center',
  },
  bottomPlayer: {
    marginBottom: 6,
    borderRadius: 18,
    backgroundColor: 'rgba(20, 14, 34, 0.96)',
    borderWidth: 1,
    borderTopColor: SakuraColors.glassHighlight,
    overflow: 'hidden',
    ...(Platform.OS === 'android'
      ? { elevation: 6 }
      : {
          shadowColor: '#000',
          shadowOffset: { width: 0, height: 8 },
          shadowOpacity: 0.45,
          shadowRadius: 16,
        }),
  },
  progressBg: {
    height: 3,
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  progressFill: {
    height: 3,
  },
  bottomPlayerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    paddingHorizontal: 10,
    paddingVertical: 9,
  },
  miniCover: {
    width: 42,
    height: 42,
    borderRadius: 10,
    backgroundColor: SakuraColors.panel2,
  },
  playerMeta: {
    flex: 1,
    gap: 2,
  },
  playerTitle: {
    fontSize: 13.5,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  playerArtist: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10.5,
    color: SakuraColors.inkDim,
  },
  bottomIconBtn: {
    padding: 5,
  },
  playMiniBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bottomWavePill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: '#FFCC00',
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingVertical: 11,
    marginBottom: 6,
  },
  waveIconCircle: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: 'rgba(255,255,255,0.45)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  waveTitle: {
    fontSize: 14.5,
    fontWeight: '800',
    color: '#14101c',
  },
  waveSub: {
    fontSize: 11.5,
    fontWeight: '600',
    color: 'rgba(20,16,28,0.75)',
  },
});

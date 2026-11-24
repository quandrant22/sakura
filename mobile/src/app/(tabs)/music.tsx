/**
 * Music Screen — полноценная Яндекс.Музыка в стиле Noir Luxe с плеером снизу,
 * всеми 2000+ лайками, Моей волной с настройками, плейлистами, чартом, поиском и кэшем.
 */

import { requestNotificationPermissionsAsync } from 'expo-audio';
import * as Haptics from 'expo-haptics';
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
import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
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
import { useMusicStore } from '../../stores/useMusicStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

type MusicTab = 'wave' | 'liked' | 'playlists' | 'search' | 'cache';

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

export default function MusicScreen() {
  const {
    queue,
    currentTrack,
    likedIds,
    likedTracks,
    likedTotal,
    loadingLiked,
    playlists,
    selectedPlaylist,
    playlistTracks,
    loadingPlaylists,
    loadingPlaylistTracks,
    chartTracks,
    loadingChart,
    stations,
    activeStationId,
    activeStationName,
    waveMood,
    waveDiversity,
    searchResults,
    searchAlbums,
    searchArtists,
    selectedCollection,
    cachedMap,
    cachingIds,
    batchProgress,
    isPlaying,
    isLoading,
    positionMs,
    durationMs,
    error,
    loadCache,
    ensureLikedIds,
    startMyWave,
    setWaveMix,
    loadStations,
    loadChart,
    loadLiked,
    loadPlaylists,
    openPlaylist,
    closePlaylist,
    search,
    openAlbum,
    openArtist,
    closeCollection,
    playFromList,
    playShuffled,
    togglePlayPause,
    nextTrack,
    prevTrack,
    toggleTrackLike,
    toggleCurrentLike,
    cacheTrack,
    cacheTrackList,
    cacheAllLiked,
    purgeUnlikedCache,
    removeCached,
    clearCache,
    setFullPlayerOpen,
  } = useMusicStore();

  const settings = usePhoneSettingsStore();
  const accent = ACCENT_THEMES[settings.accentTheme].accent;

  const [tab, setTab] = useState<MusicTab>('liked');
  const [query, setQuery] = useState('');
  const [likesFilter, setLikesFilter] = useState('');

  useEffect(() => {
    void loadCache();
    void ensureLikedIds();
    if (Platform.OS === 'android') {
      void requestNotificationPermissionsAsync().catch(() => {});
    }
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

  const haptic = () => {
    if (!settings.hapticsEnabled) return;
    try {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch {}
  };

  const cachedEntries = Object.values(cachedMap).sort((a, b) => b.cachedAt - a.cachedAt);
  const cachedTracks = cachedEntries.map((e) => ({
    ...e.track,
    liked: Boolean(likedIds[e.track.id] ?? e.track.liked),
  }));
  const unlikedCachedCount = cachedTracks.filter((t) => !likedIds[t.id]).length;
  const totalBytes = cachedEntries.reduce((acc, e) => acc + (e.sizeBytes || 0), 0);
  const totalMb = (totalBytes / (1024 * 1024)).toFixed(1);

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

  const progressPct =
    durationMs > 0 ? Math.min(100, Math.max(0, (positionMs / durationMs) * 100)) : 0;

  const confirmClearCache = () => {
    if (Platform.OS === 'web') {
      void clearCache();
      return;
    }
    Alert.alert('Очистить весь кэш?', `Удалить ${cachedTracks.length} треков (${totalMb} МБ)?`, [
      { text: 'Отмена', style: 'cancel' },
      { text: 'Очистить', style: 'destructive', onPress: () => void clearCache() },
    ]);
  };

  const renderTrack = ({ item, index }: { item: YandexTrack; index: number }) => {
    const isCurrent = currentTrack?.id === item.id;
    const isCached = Boolean(cachedMap[item.id]);
    const isCaching = Boolean(cachingIds[item.id]);
    const isLiked = Boolean(likedIds[item.id] ?? item.liked);

    return (
      <Pressable
        style={({ pressed }) => [
          styles.trackRow,
          isCurrent && { backgroundColor: accent + '1A', borderColor: accent + '60' },
          pressed && { opacity: 0.8 },
        ]}
        onPress={() => {
          haptic();
          void playFromList(listData, index, tab === 'wave');
        }}>
        {item.coverUrl ? (
          <Image source={{ uri: item.coverUrl }} style={styles.trackCover} />
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
            haptic();
            void toggleTrackLike(item);
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
              haptic();
              if (isCached) void removeCached(item.id);
              else if (!isCaching) void cacheTrack(item);
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
  };

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
          {/* Компактная шапка */}
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

          {/* Верхний переключатель разделов */}
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

          {/* Настройки Моей волны и Станций */}
          {tab === 'wave' && (
            <View style={styles.waveControlsBox}>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.chipStrip}>
                <View style={[styles.chipPill, { borderColor: accent + '66', backgroundColor: accent + '16' }]}>
                  <Sparkles size={12} color={accent} />
                  <Text style={[styles.chipText, { color: accent }]}>{activeStationName}</Text>
                </View>
                {MOOD_OPTIONS.map((m) => {
                  const active = waveMood === m.id && activeStationId === 'user:onyourwave';
                  return (
                    <Pressable
                      key={m.id}
                      style={[styles.chipPill, active && { borderColor: accent, backgroundColor: accent + '24' }]}
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
                      style={[styles.chipPill, active && { borderColor: SakuraColors.cyan, backgroundColor: 'rgba(79,216,255,0.16)' }]}
                      onPress={() => {
                        haptic();
                        void setWaveMix(waveMood, d.id);
                      }}>
                      <Text style={[styles.chipText, active && { color: SakuraColors.cyan }]}>{d.label}</Text>
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
                        style={[styles.stationPill, active && { borderColor: accent, backgroundColor: accent + '20' }]}
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

          {/* Панель Лайков: фильтр + Играть / Перемешать / Скачать лайки */}
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

          {/* Поиск / Чарт / Альбомы / Исполнители */}
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
                        <Image source={{ uri: ar.coverUrl }} style={styles.entityAvatar} />
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
                        <Image source={{ uri: al.coverUrl }} style={styles.entityThumb} />
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

          {/* Прогресс кэширования + Управление только лайкнутыми в Кэше */}
          {(batchProgress || (tab === 'cache' && Platform.OS !== 'web')) && (
            <View style={styles.cacheActionsRow}>
              {batchProgress ? (
                <View style={styles.batchBanner}>
                  <ActivityIndicator size="small" color={accent} />
                  <Text style={styles.batchText}>
                    Кэширую лайки: {batchProgress.done} / {batchProgress.total}…
                  </Text>
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
                    <Text style={[styles.cacheActionText, { color: accent }]}>
                      Скачать лайки
                    </Text>
                  </Pressable>
                  {unlikedCachedCount > 0 && (
                    <Pressable
                      style={[styles.clearCacheBtn, { borderColor: SakuraColors.warn + '66', backgroundColor: 'rgba(255,180,60,0.12)' }]}
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

          {/* Основная прокручиваемая область */}
          <View style={{ flex: 1 }}>
            {tab === 'playlists' && !selectedPlaylist ? (
              <FlatList<YandexPlaylist>
                data={playlists}
                keyExtractor={(pl) => `${pl.ownerUid}_${pl.kind}`}
                renderItem={({ item: pl }) => (
                  <Pressable
                    style={({ pressed }) => [styles.trackRow, pressed && { opacity: 0.82 }]}
                    onPress={() => {
                      haptic();
                      void openPlaylist(pl);
                    }}>
                    {pl.coverUrl ? (
                      <Image source={{ uri: pl.coverUrl }} style={styles.trackCover} />
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
                )}
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
                keyExtractor={(item, idx) => `${item.id}_${idx}`}
                renderItem={renderTrack}
                initialNumToRender={18}
                maxToRenderPerBatch={24}
                windowSize={7}
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

          {/* НИЖНИЙ ЗАКРЕПЛЁННЫЙ ПЛЕЕР (как в Яндекс.Музыке / Spotify) */}
          {currentTrack ? (
            <Pressable
              style={[styles.bottomPlayer, { borderColor: accent + '48' }]}
              onPress={() => {
                haptic();
                setFullPlayerOpen(true);
              }}>
              <View style={styles.progressBg}>
                <View
                  style={[styles.progressFill, { width: `${progressPct}%`, backgroundColor: accent }]}
                />
              </View>

              <View style={styles.bottomPlayerRow}>
                {currentTrack.coverUrl ? (
                  <Image source={{ uri: currentTrack.coverUrl }} style={styles.miniCover} />
                ) : (
                  <View style={[styles.miniCover, styles.coverStub]}>
                    <Disc3 size={20} color={accent} />
                  </View>
                )}

                <View style={styles.playerMeta}>
                  <Text style={styles.playerTitle} numberOfLines={1}>
                    {currentTrack.title}
                  </Text>
                  <Text style={styles.playerArtist} numberOfLines={1}>
                    {currentTrack.artist} · {fmtTime(positionMs)} /{' '}
                    {fmtTime(durationMs || currentTrack.durationMs)}
                  </Text>
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
    fontSize: 12,
    fontWeight: '600',
    color: SakuraColors.ink,
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
    gap: 7,
    paddingBottom: 10,
  },
  trackRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    padding: 9,
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
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.45,
    shadowRadius: 16,
    elevation: 12,
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

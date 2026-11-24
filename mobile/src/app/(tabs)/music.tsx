/**
 * Music Screen — встроенный плеер Яндекс.Музыки («Моя волна», Мне нравится, Поиск и Оффлайн-Кэш).
 */

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
  SkipBack,
  SkipForward,
  Trash2,
} from 'lucide-react-native';
import React, { useEffect, useState } from 'react';
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
import { GlassCard } from '../../components/ui/GlassCard';
import { SakuraColors } from '../../constants/colors';
import { SakuraFonts } from '../../constants/fonts';
import { YandexPlaylist, YandexTrack } from '../../services/yandexMusic';
import { useMusicStore } from '../../stores/useMusicStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

type MusicTab = 'wave' | 'liked' | 'playlists' | 'search' | 'cache';

export default function MusicScreen() {
  const {
    queue,
    currentTrack,
    likedTracks,
    likedTotal,
    playlists,
    selectedPlaylist,
    playlistTracks,
    loadingPlaylists,
    loadingPlaylistTracks,
    searchResults,
    cachedMap,
    cachingIds,
    batchProgress,
    isPlaying,
    isLoading,
    positionMs,
    durationMs,
    error,
    loadCache,
    startMyWave,
    loadLiked,
    loadPlaylists,
    openPlaylist,
    closePlaylist,
    search,
    playFromList,
    togglePlayPause,
    nextTrack,
    prevTrack,
    toggleCurrentLike,
    cacheTrack,
    cacheTrackList,
    cacheAllLiked,
    removeCached,
    clearCache,
  } = useMusicStore();

  const settings = usePhoneSettingsStore();
  const accent = ACCENT_THEMES[settings.accentTheme].accent;

  const [tab, setTab] = useState<MusicTab>('wave');
  const [query, setQuery] = useState('');

  useEffect(() => {
    void loadCache();
  }, [loadCache]);

  useEffect(() => {
    if (tab === 'liked' && likedTracks.length === 0) {
      void loadLiked();
    } else if (tab === 'playlists' && playlists.length === 0) {
      void loadPlaylists();
    }
  }, [tab, likedTracks.length, playlists.length, loadLiked, loadPlaylists]);

  const haptic = () => {
    if (!settings.hapticsEnabled) return;
    try {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch {}
  };

  const cachedEntries = Object.values(cachedMap).sort((a, b) => b.cachedAt - a.cachedAt);
  const cachedTracks = cachedEntries.map((e) => e.track);
  const totalBytes = cachedEntries.reduce((acc, e) => acc + (e.sizeBytes || 0), 0);
  const totalMb = (totalBytes / (1024 * 1024)).toFixed(1);

  const listData =
    tab === 'wave'
      ? queue
      : tab === 'liked'
      ? likedTracks
      : tab === 'playlists'
      ? playlistTracks
      : tab === 'cache'
      ? cachedTracks
      : searchResults;

  const progressPct =
    durationMs > 0 ? Math.min(100, Math.max(0, (positionMs / durationMs) * 100)) : 0;

  const fmtTime = (ms: number) => {
    const s = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(s / 60);
    const rem = (s % 60).toString().padStart(2, '0');
    return `${m}:${rem}`;
  };

  const confirmClearCache = () => {
    if (Platform.OS === 'web') {
      void clearCache();
      return;
    }
    Alert.alert('Очистить кэш музыки?', `Удалить ${cachedTracks.length} треков (${totalMb} МБ)?`, [
      { text: 'Отмена', style: 'cancel' },
      { text: 'Очистить', style: 'destructive', onPress: () => void clearCache() },
    ]);
  };

  const renderTrack = ({ item, index }: { item: YandexTrack; index: number }) => {
    const isCurrent = currentTrack?.id === item.id;
    const isCached = Boolean(cachedMap[item.id]);
    const isCaching = Boolean(cachingIds[item.id]);

    return (
      <Pressable
        style={({ pressed }) => [
          styles.trackRow,
          isCurrent && { backgroundColor: accent + '18', borderColor: accent + '55' },
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
          </Text>
        </View>

        <Text style={styles.trackDur}>{fmtTime(item.durationMs)}</Text>

        {Platform.OS !== 'web' && (
          <Pressable
            hitSlop={8}
            style={styles.cacheIconBtn}
            onPress={(e) => {
              e.stopPropagation();
              haptic();
              if (isCached) {
                void removeCached(item.id);
              } else if (!isCaching) {
                void cacheTrack(item);
              }
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

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
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

        {/* Активный плеер ИЛИ кнопка Моя волна */}
        {currentTrack ? (
          <GlassCard style={styles.playerCard} accent="pink">
            <View style={styles.playerTop}>
              {currentTrack.coverUrl ? (
                <Image source={{ uri: currentTrack.coverUrl }} style={styles.bigCover} />
              ) : (
                <View style={[styles.bigCover, styles.coverStub]}>
                  <Disc3 size={30} color={accent} />
                </View>
              )}

              <View style={styles.playerMeta}>
                <Text style={styles.playerTitle} numberOfLines={1}>
                  {currentTrack.title}
                </Text>
                <Text style={styles.playerArtist} numberOfLines={1}>
                  {currentTrack.artist}
                </Text>
                <Text style={styles.playerTime}>
                  {fmtTime(positionMs)} / {fmtTime(durationMs || currentTrack.durationMs)}
                  {cachedMap[currentTrack.id] ? ' · ОФФЛАЙН' : ''}
                </Text>
              </View>

              <Pressable
                onPress={() => {
                  haptic();
                  void toggleCurrentLike();
                }}>
                <Heart
                  size={22}
                  color={currentTrack.liked ? accent : SakuraColors.inkDim}
                  fill={currentTrack.liked ? accent : 'transparent'}
                />
              </Pressable>
            </View>

            <View style={styles.progressBg}>
              <View style={[styles.progressFill, { width: `${progressPct}%`, backgroundColor: accent }]} />
            </View>

            <View style={styles.playerControls}>
              <Pressable onPress={() => void prevTrack()} style={styles.ctrlBtn}>
                <SkipBack size={22} color={SakuraColors.ink} />
              </Pressable>

              <Pressable
                style={[styles.playBigBtn, { backgroundColor: accent }]}
                onPress={() => {
                  haptic();
                  void togglePlayPause();
                }}>
                {isLoading ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : isPlaying ? (
                  <Pause size={22} color="#fff" fill="#fff" />
                ) : (
                  <Play size={22} color="#fff" fill="#fff" />
                )}
              </Pressable>

              <Pressable onPress={() => void nextTrack()} style={styles.ctrlBtn}>
                <SkipForward size={22} color={SakuraColors.ink} />
              </Pressable>
            </View>
          </GlassCard>
        ) : (
          <Pressable
            style={({ pressed }) => [styles.waveHero, pressed && { opacity: 0.85 }]}
            onPress={() => {
              haptic();
              setTab('wave');
              void startMyWave();
            }}>
            <View style={styles.waveIconCircle}>
              {isLoading ? (
                <ActivityIndicator size="small" color="#14101c" />
              ) : (
                <Radio size={24} color="#14101c" />
              )}
            </View>
            <View style={styles.waveMeta}>
              <Text style={styles.waveTitle}>Включить «Мою волну»</Text>
              <Text style={styles.waveSub}>Бесконечный поток + оффлайн-кэш на телефоне</Text>
            </View>
          </Pressable>
        )}

        {error ? <Text style={styles.errorText}>{error}</Text> : null}

        {/* Сегментный переключатель разделов (5 вкладок) */}
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
              { id: 'search' as MusicTab, label: 'Поиск' },
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
                  <Text style={[styles.segmentText, active && { color: accent }]} numberOfLines={1}>
                    {item.label}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>
        </View>

        {tab === 'search' && (
          <View style={styles.searchBox}>
            <Search size={16} color={SakuraColors.inkDim} />
            <TextInput
              style={styles.searchInput}
              placeholder="Трек, исполнитель или альбом…"
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

        {/* Шапка выбранного плейлиста */}
        {tab === 'playlists' && selectedPlaylist && (
          <View style={styles.playlistHeaderBar}>
            <Pressable
              style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.7 }]}
              onPress={() => {
                haptic();
                closePlaylist();
              }}>
              <ArrowLeft size={16} color={SakuraColors.ink} />
            </Pressable>
            <View style={{ flex: 1 }}>
              <Text style={styles.playlistHeaderTitle} numberOfLines={1}>
                {selectedPlaylist.title}
              </Text>
              <Text style={styles.playlistHeaderSub}>
                {playlistTracks.length || selectedPlaylist.trackCount} треков
              </Text>
            </View>
            {playlistTracks.length > 0 && (
              <Pressable
                style={[styles.miniPillBtn, { borderColor: accent + '55', backgroundColor: accent + '1C' }]}
                onPress={() => {
                  haptic();
                  void playFromList(playlistTracks, 0, false);
                }}>
                <Play size={13} color={accent} />
                <Text style={[styles.miniPillText, { color: accent }]}>Играть</Text>
              </Pressable>
            )}
            {Platform.OS !== 'web' && playlistTracks.length > 0 && !batchProgress && (
              <Pressable
                style={[styles.miniPillBtn, { borderColor: SakuraColors.lineStrong }]}
                onPress={() => {
                  haptic();
                  void cacheTrackList(playlistTracks);
                }}>
                <Download size={13} color={SakuraColors.ink} />
                <Text style={[styles.miniPillText, { color: SakuraColors.ink }]}>Кэш</Text>
              </Pressable>
            )}
          </View>
        )}

        {/* Панель управления оффлайн-кэшем на вкладках Лайки / Кэш (и прогресс плейлиста) */}
        {(tab === 'liked' || tab === 'cache' || (tab === 'playlists' && batchProgress)) &&
          Platform.OS !== 'web' && (
            <View style={styles.cacheActionsRow}>
              {batchProgress ? (
                <View style={styles.batchBanner}>
                  <ActivityIndicator size="small" color={accent} />
                  <Text style={styles.batchText}>
                    Кэширую треки: {batchProgress.done} / {batchProgress.total}…
                  </Text>
                </View>
              ) : (
                <Pressable
                  style={({ pressed }) => [
                    styles.cacheActionBtn,
                    { borderColor: accent + '55', backgroundColor: accent + '14' },
                    pressed && { opacity: 0.75 },
                  ]}
                  onPress={() => {
                    haptic();
                    void cacheAllLiked();
                  }}>
                  <Download size={14} color={accent} />
                  <Text style={[styles.cacheActionText, { color: accent }]}>
                    {likedTracks.length > 0
                      ? `Скачать лайки (${likedTracks.length})`
                      : 'Скачать лайки в кэш'}
                  </Text>
                </Pressable>
              )}

              {tab === 'cache' && cachedTracks.length > 0 && !batchProgress && (
                <Pressable
                  style={({ pressed }) => [styles.clearCacheBtn, pressed && { opacity: 0.75 }]}
                  onPress={confirmClearCache}>
                  <Trash2 size={14} color={SakuraColors.error} />
                  <Text style={[styles.cacheActionText, { color: SakuraColors.error }]}>Очистить</Text>
                </Pressable>
              )}
            </View>
          )}

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
            ListEmptyComponent={
              <View style={styles.emptyBox}>
                <Text style={styles.emptyText}>
                  {isLoading || loadingPlaylistTracks
                    ? 'Загрузка треков…'
                    : tab === 'wave'
                    ? 'Нажми «Включить Мою волну» сверху'
                    : tab === 'liked'
                    ? 'Любимые треки появятся здесь'
                    : tab === 'playlists'
                    ? 'В этом плейлисте пока нет треков'
                    : tab === 'cache'
                    ? 'Кэш пуст — слушай треки или нажми «Скачать лайки»'
                    : 'Введи запрос и нажми Поиск'}
                </Text>
              </View>
            }
          />
        )}
      </View>
      </KeyboardAvoidingView>
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
    paddingTop: 10,
    gap: 10,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 4,
  },
  screenTitle: {
    fontSize: 22,
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
  waveHero: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    backgroundColor: '#FFCC00',
    borderRadius: 20,
    padding: 16,
  },
  waveIconCircle: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: 'rgba(255,255,255,0.4)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  waveMeta: {
    flex: 1,
    gap: 2,
  },
  waveTitle: {
    fontSize: 16,
    fontWeight: '800',
    color: '#14101c',
  },
  waveSub: {
    fontSize: 12.5,
    fontWeight: '600',
    color: 'rgba(20,16,28,0.75)',
  },
  playerCard: {
    gap: 12,
  },
  playerTop: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  bigCover: {
    width: 60,
    height: 60,
    borderRadius: 14,
    backgroundColor: SakuraColors.panel2,
  },
  playerMeta: {
    flex: 1,
    gap: 3,
  },
  playerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  playerArtist: {
    fontSize: 13,
    color: SakuraColors.inkDim,
  },
  playerTime: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10.5,
    color: SakuraColors.textMuted,
  },
  progressBg: {
    height: 4,
    borderRadius: 2,
    backgroundColor: 'rgba(255,255,255,0.08)',
    overflow: 'hidden',
  },
  progressFill: {
    height: 4,
  },
  playerControls: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 28,
  },
  ctrlBtn: {
    padding: 8,
  },
  playBigBtn: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  errorText: {
    color: SakuraColors.warn,
    fontSize: 12,
    fontWeight: '600',
    paddingHorizontal: 4,
  },
  tabsRowWrap: {
    borderRadius: 16,
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
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'transparent',
    alignItems: 'center',
  },
  segmentText: {
    fontSize: 12,
    fontWeight: '700',
    color: SakuraColors.inkDim,
  },
  playlistHeaderBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 6,
    paddingHorizontal: 8,
    borderRadius: 14,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.lineStrong,
  },
  backBtn: {
    width: 34,
    height: 34,
    borderRadius: 10,
    backgroundColor: SakuraColors.panel2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  playlistHeaderTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  playlistHeaderSub: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10,
    color: SakuraColors.textMuted,
  },
  miniPillBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 7,
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
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: SakuraColors.bgInput,
    borderRadius: 14,
    paddingHorizontal: 13,
    borderWidth: 1.2,
    borderColor: SakuraColors.lineStrong,
  },
  searchInput: {
    flex: 1,
    color: '#FFFFFF',
    paddingVertical: 10,
    fontSize: 14.5,
  },
  cacheActionsRow: {
    flexDirection: 'row',
    gap: 8,
    alignItems: 'center',
  },
  cacheActionBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 9,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: 1,
  },
  clearCacheBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 5,
    paddingVertical: 9,
    paddingHorizontal: 12,
    borderRadius: 12,
    backgroundColor: 'rgba(255, 82, 119, 0.12)',
    borderWidth: 1,
    borderColor: 'rgba(255, 82, 119, 0.35)',
  },
  cacheActionText: {
    fontSize: 12.5,
    fontWeight: '700',
  },
  batchBanner: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 9,
    borderRadius: 12,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  batchText: {
    fontSize: 12.5,
    fontWeight: '600',
    color: SakuraColors.ink,
  },
  listContent: {
    gap: 8,
    paddingBottom: 24,
  },
  trackRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    padding: 10,
    borderRadius: 14,
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
    fontSize: 14,
    fontWeight: '600',
    color: SakuraColors.ink,
  },
  trackArtist: {
    fontSize: 12,
    color: SakuraColors.inkDim,
  },
  trackDur: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10.5,
    color: SakuraColors.textMuted,
  },
  cacheIconBtn: {
    padding: 6,
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
});

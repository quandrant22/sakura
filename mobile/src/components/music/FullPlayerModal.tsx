/**
 * FullPlayerModal — полноэкранный плеер Яндекс.Музыки (снизу-вверх)
 * с перемоткой (seekbar), текстом песни, лайком, дизлайком волны, shuffle/repeat и кэшем.
 */

import * as Haptics from 'expo-haptics';
import {
  CheckCircle2,
  ChevronDown,
  Disc3,
  Download,
  FileText,
  Heart,
  Pause,
  Play,
  Repeat,
  Repeat1,
  Shuffle,
  SkipBack,
  SkipForward,
  ThumbsDown,
  X,
} from 'lucide-react-native';
import React, { useState } from 'react';
import {
  ActivityIndicator,
  Image,
  LayoutChangeEvent,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { SakuraColors } from '../../constants/colors';
import { SakuraFonts } from '../../constants/fonts';
import { useMusicStore } from '../../stores/useMusicStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

function fmtTime(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const rem = (s % 60).toString().padStart(2, '0');
  return `${m}:${rem}`;
}

export const FullPlayerModal: React.FC = () => {
  const {
    currentTrack,
    currentIndex,
    queue,
    cachedMap,
    cachingIds,
    isPlaying,
    isLoading,
    isWaveMode,
    activeStationName,
    shuffleEnabled,
    repeatMode,
    positionMs,
    durationMs,
    lyricsOpen,
    lyricsLoading,
    lyricsText,
    fullPlayerOpen,
    setFullPlayerOpen,
    togglePlayPause,
    seekTo,
    nextTrack,
    prevTrack,
    toggleShuffle,
    cycleRepeat,
    toggleCurrentLike,
    dislikeCurrentTrack,
    cacheTrack,
    removeCached,
    openLyrics,
    closeLyrics,
    playFromList,
  } = useMusicStore();

  const settings = usePhoneSettingsStore();
  const accent = ACCENT_THEMES[settings.accentTheme].accent;
  const [barWidth, setBarWidth] = useState(1);

  if (!currentTrack) return null;

  const totalMs = durationMs || currentTrack.durationMs || 1;
  const pct = Math.min(100, Math.max(0, (positionMs / totalMs) * 100));
  const isCached = Boolean(cachedMap[currentTrack.id]);
  const isCaching = Boolean(cachingIds[currentTrack.id]);

  const haptic = () => {
    if (!settings.hapticsEnabled) return;
    try {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch {}
  };

  const handleSeekAt = (x: number, commit = true) => {
    if (typeof x !== 'number' || barWidth <= 0) return;
    const ratio = Math.min(1, Math.max(0, x / barWidth));
    if (commit) {
      haptic();
      void seekTo(Math.round(ratio * totalMs));
    }
  };

  return (
    <Modal
      visible={fullPlayerOpen}
      animationType="slide"
      presentationStyle="fullScreen"
      onRequestClose={() => setFullPlayerOpen(false)}>
      <View style={styles.backdrop}>
        <SafeAreaView style={styles.safeArea} edges={['top', 'bottom']}>
          {/* Верхняя шапка */}
          <View style={styles.topRow}>
            <Pressable
              style={styles.closeBtn}
              onPress={() => {
                haptic();
                setFullPlayerOpen(false);
              }}>
              <ChevronDown size={22} color={SakuraColors.ink} />
            </Pressable>
            <View style={styles.sourceCenter}>
              <Text style={styles.sourceKicker}>
                {isWaveMode ? activeStationName.toUpperCase() : 'СЕЙЧАС ИГРАЕТ'}
              </Text>
              {currentTrack.album ? (
                <Text style={styles.albumSub} numberOfLines={1}>
                  {currentTrack.album}
                </Text>
              ) : null}
            </View>
            <Pressable
              style={styles.closeBtn}
              onPress={() => {
                haptic();
                void openLyrics(currentTrack);
              }}>
              <FileText size={18} color={SakuraColors.inkDim} />
            </Pressable>
          </View>

          <ScrollView
            showsVerticalScrollIndicator={false}
            contentContainerStyle={styles.scrollBody}>
            {/* Обложка */}
            <View style={[styles.coverWrap, { shadowColor: accent }]}>
              {currentTrack.coverUrl ? (
                <Image
                  source={{ uri: currentTrack.coverUrl.replace('400x400', '600x600') }}
                  style={styles.cover}
                />
              ) : (
                <View style={[styles.cover, styles.coverStub]}>
                  <Disc3 size={64} color={accent} />
                </View>
              )}
            </View>

            {/* Название + Лайк */}
            <View style={styles.titleRow}>
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={styles.title} numberOfLines={2}>
                  {currentTrack.title}
                </Text>
                <Text style={styles.artist} numberOfLines={1}>
                  {currentTrack.artist}
                </Text>
              </View>
              <Pressable
                hitSlop={10}
                style={styles.heartBtn}
                onPress={() => {
                  haptic();
                  void toggleCurrentLike();
                }}>
                <Heart
                  size={26}
                  color={currentTrack.liked ? accent : SakuraColors.inkDim}
                  fill={currentTrack.liked ? accent : 'transparent'}
                />
              </Pressable>
            </View>

            {/* Интерактивный Seekbar */}
            <View style={styles.seekSection}>
              <View
                onLayout={(e: LayoutChangeEvent) => setBarWidth(e.nativeEvent.layout.width || 1)}
                onStartShouldSetResponder={() => true}
                onMoveShouldSetResponder={() => true}
                onResponderRelease={(e) => handleSeekAt(e.nativeEvent.locationX, true)}
                onResponderGrant={(e) => handleSeekAt(e.nativeEvent.locationX, false)}
                style={styles.seekHitbox}>
                <View style={styles.seekTrack}>
                  <View style={[styles.seekFill, { width: `${pct}%`, backgroundColor: accent }]} />
                  <View
                    style={[
                      styles.seekThumb,
                      { left: `${pct}%`, backgroundColor: '#fff', borderColor: accent },
                    ]}
                  />
                </View>
              </View>
              <View style={styles.timeRow}>
                <Text style={styles.timeText}>{fmtTime(positionMs)}</Text>
                <Text style={styles.timeText}>
                  {isCached ? 'ОФФЛАЙН · ' : ''}
                  {fmtTime(totalMs)}
                </Text>
              </View>
            </View>

            {/* Основные кнопки управления */}
            <View style={styles.transportRow}>
              <Pressable
                style={styles.sideCtrl}
                onPress={() => {
                  haptic();
                  toggleShuffle();
                }}>
                <Shuffle
                  size={20}
                  color={shuffleEnabled ? accent : SakuraColors.inkDim}
                />
              </Pressable>

              <Pressable
                style={styles.mainNavBtn}
                onPress={() => {
                  haptic();
                  void prevTrack();
                }}>
                <SkipBack size={28} color={SakuraColors.ink} fill={SakuraColors.ink} />
              </Pressable>

              <Pressable
                style={[styles.playBig, { backgroundColor: accent, shadowColor: accent }]}
                onPress={() => {
                  haptic();
                  void togglePlayPause();
                }}>
                {isLoading ? (
                  <ActivityIndicator size="large" color="#fff" />
                ) : isPlaying ? (
                  <Pause size={30} color="#fff" fill="#fff" />
                ) : (
                  <Play size={30} color="#fff" fill="#fff" />
                )}
              </Pressable>

              <Pressable
                style={styles.mainNavBtn}
                onPress={() => {
                  haptic();
                  void nextTrack();
                }}>
                <SkipForward size={28} color={SakuraColors.ink} fill={SakuraColors.ink} />
              </Pressable>

              <Pressable
                style={styles.sideCtrl}
                onPress={() => {
                  haptic();
                  cycleRepeat();
                }}>
                {repeatMode === 'one' ? (
                  <Repeat1 size={20} color={accent} />
                ) : (
                  <Repeat
                    size={20}
                    color={repeatMode === 'all' ? accent : SakuraColors.inkDim}
                  />
                )}
              </Pressable>
            </View>

            {/* Нижние действия: Дизлайк волны / Текст / Кэш */}
            <View style={styles.actionsStrip}>
              {isWaveMode && (
                <Pressable
                  style={styles.actionChip}
                  onPress={() => {
                    haptic();
                    void dislikeCurrentTrack();
                  }}>
                  <ThumbsDown size={16} color={SakuraColors.inkDim} />
                  <Text style={styles.actionLabel}>Не моё</Text>
                </Pressable>
              )}

              <Pressable
                style={styles.actionChip}
                onPress={() => {
                  haptic();
                  void openLyrics(currentTrack);
                }}>
                <FileText size={16} color={SakuraColors.inkDim} />
                <Text style={styles.actionLabel}>Текст</Text>
              </Pressable>

              {Platform.OS !== 'web' && (
                <Pressable
                  style={styles.actionChip}
                  onPress={() => {
                    haptic();
                    if (isCached) void removeCached(currentTrack.id);
                    else if (!isCaching) void cacheTrack(currentTrack);
                  }}>
                  {isCaching ? (
                    <ActivityIndicator size="small" color={accent} />
                  ) : isCached ? (
                    <CheckCircle2 size={16} color={SakuraColors.online} />
                  ) : (
                    <Download size={16} color={SakuraColors.inkDim} />
                  )}
                  <Text style={[styles.actionLabel, isCached && { color: SakuraColors.online }]}>
                    {isCached ? 'В кэше' : 'Скачать'}
                  </Text>
                </Pressable>
              )}
            </View>

            {/* Ближайшая очередь */}
            {queue.length > 1 && (
              <View style={styles.queueBox}>
                <Text style={styles.queueHeading}>
                  ДАЛЕЕ В ОЧЕРЕДИ ({Math.max(0, queue.length - currentIndex - 1)})
                </Text>
                {queue.slice(currentIndex + 1, currentIndex + 7).map((tr, offset) => {
                  const idx = currentIndex + 1 + offset;
                  return (
                    <Pressable
                      key={`${tr.id}_${idx}`}
                      style={styles.queueRow}
                      onPress={() => {
                        haptic();
                        void playFromList(queue, idx, isWaveMode);
                      }}>
                      {tr.coverUrl ? (
                        <Image source={{ uri: tr.coverUrl }} style={styles.qCover} />
                      ) : (
                        <View style={[styles.qCover, styles.coverStub]}>
                          <Disc3 size={14} color={SakuraColors.inkDim} />
                        </View>
                      )}
                      <View style={{ flex: 1 }}>
                        <Text style={styles.qTitle} numberOfLines={1}>
                          {tr.title}
                        </Text>
                        <Text style={styles.qArtist} numberOfLines={1}>
                          {tr.artist}
                        </Text>
                      </View>
                    </Pressable>
                  );
                })}
              </View>
            )}
          </ScrollView>

          {/* Модальное окно текста песни */}
          <Modal visible={lyricsOpen} transparent animationType="fade" onRequestClose={closeLyrics}>
            <View style={styles.lyricsOverlay}>
              <View style={styles.lyricsCard}>
                <View style={styles.lyricsHead}>
                  <Text style={styles.lyricsTitle} numberOfLines={1}>
                    Текст · {currentTrack.title}
                  </Text>
                  <Pressable onPress={closeLyrics} style={styles.lyricsClose}>
                    <X size={20} color={SakuraColors.ink} />
                  </Pressable>
                </View>
                <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
                  {lyricsLoading ? (
                    <ActivityIndicator size="small" color={accent} style={{ marginTop: 24 }} />
                  ) : (
                    <Text style={styles.lyricsText}>{lyricsText}</Text>
                  )}
                </ScrollView>
              </View>
            </View>
          </Modal>
        </SafeAreaView>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: '#0c0816',
  },
  safeArea: {
    flex: 1,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  closeBtn: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: SakuraColors.panel,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sourceCenter: {
    flex: 1,
    alignItems: 'center',
    paddingHorizontal: 10,
  },
  sourceKicker: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10,
    letterSpacing: 1.2,
    color: SakuraColors.textMuted,
  },
  albumSub: {
    fontSize: 12,
    fontWeight: '600',
    color: SakuraColors.ink,
    marginTop: 2,
  },
  scrollBody: {
    paddingHorizontal: 24,
    paddingBottom: 30,
    gap: 20,
  },
  coverWrap: {
    alignSelf: 'center',
    marginTop: 8,
    borderRadius: 24,
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.38,
    shadowRadius: 28,
    elevation: 14,
  },
  cover: {
    width: 268,
    height: 268,
    borderRadius: 24,
    backgroundColor: SakuraColors.panel2Solid,
  },
  coverStub: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  title: {
    fontSize: 21,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  artist: {
    fontSize: 14.5,
    fontWeight: '600',
    color: SakuraColors.inkDim,
  },
  heartBtn: {
    padding: 8,
  },
  seekSection: {
    gap: 6,
  },
  seekHitbox: {
    paddingVertical: 12,
  },
  seekTrack: {
    height: 5,
    borderRadius: 3,
    backgroundColor: 'rgba(255,255,255,0.12)',
    justifyContent: 'center',
  },
  seekFill: {
    height: 5,
    borderRadius: 3,
  },
  seekThumb: {
    position: 'absolute',
    width: 14,
    height: 14,
    borderRadius: 7,
    borderWidth: 2,
    marginLeft: -7,
  },
  timeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  timeText: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10.5,
    color: SakuraColors.textMuted,
  },
  transportRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 8,
  },
  sideCtrl: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mainNavBtn: {
    width: 52,
    height: 52,
    alignItems: 'center',
    justifyContent: 'center',
  },
  playBig: {
    width: 68,
    height: 68,
    borderRadius: 34,
    alignItems: 'center',
    justifyContent: 'center',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.45,
    shadowRadius: 16,
    elevation: 10,
  },
  actionsStrip: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 10,
  },
  actionChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: 14,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  actionLabel: {
    fontSize: 12.5,
    fontWeight: '700',
    color: SakuraColors.inkDim,
  },
  queueBox: {
    gap: 8,
    padding: 14,
    borderRadius: 18,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  queueHeading: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10,
    letterSpacing: 0.9,
    color: SakuraColors.textMuted,
    marginBottom: 4,
  },
  queueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 4,
  },
  qCover: {
    width: 36,
    height: 36,
    borderRadius: 8,
  },
  qTitle: {
    fontSize: 13.5,
    fontWeight: '600',
    color: SakuraColors.ink,
  },
  qArtist: {
    fontSize: 11.5,
    color: SakuraColors.inkDim,
  },
  lyricsOverlay: {
    flex: 1,
    backgroundColor: 'rgba(5, 3, 10, 0.85)',
    justifyContent: 'flex-end',
  },
  lyricsCard: {
    height: '78%',
    backgroundColor: '#130e20',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 20,
    borderWidth: 1,
    borderColor: SakuraColors.lineStrong,
  },
  lyricsHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: SakuraColors.line,
    marginBottom: 12,
  },
  lyricsTitle: {
    flex: 1,
    fontSize: 16,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  lyricsClose: {
    padding: 6,
  },
  lyricsText: {
    fontSize: 15.5,
    lineHeight: 24,
    color: SakuraColors.ink,
  },
});

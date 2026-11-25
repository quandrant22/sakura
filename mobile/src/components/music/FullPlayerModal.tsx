/**
 * FullPlayerModal — полноэкранный плеер Яндекс.Музыки (снизу-вверх)
 * с плавным перетягиваемым seekbar, текстом песни, лайком, дизлайком волны, shuffle/repeat и кэшем.
 */

import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
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
import React, { memo, useState } from 'react';
import {
  ActivityIndicator,
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
import { useMusicProgressStore } from '../../stores/useMusicProgressStore';
import { useMusicStore } from '../../stores/useMusicStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

function fmtTime(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const rem = (s % 60).toString().padStart(2, '0');
  return `${m}:${rem}`;
}

interface SeekSectionProps {
  accent: string;
  fallbackDurationMs: number;
  isCached: boolean;
  onSeek: (ms: number) => Promise<void>;
  haptic: () => void;
}

function FullSeekSectionBase({
  accent,
  fallbackDurationMs,
  isCached,
  onSeek,
  haptic,
}: SeekSectionProps) {
  const positionMs = useMusicProgressStore((s) => s.positionMs);
  const storeDurationMs = useMusicProgressStore((s) => s.durationMs);
  const [barWidth, setBarWidth] = useState(1);
  const [dragMs, setDragMs] = useState<number | null>(null);

  const totalMs = storeDurationMs || fallbackDurationMs || 1;
  const shownMs = dragMs !== null ? dragMs : positionMs;
  const pct = Math.min(100, Math.max(0, (shownMs / totalMs) * 100));

  const ratioToMs = (x: number) => {
    if (typeof x !== 'number' || barWidth <= 0) return 0;
    const ratio = Math.min(1, Math.max(0, x / barWidth));
    return Math.round(ratio * totalMs);
  };

  return (
    <View style={styles.seekSection}>
      <View
        onLayout={(e: LayoutChangeEvent) => setBarWidth(e.nativeEvent.layout.width || 1)}
        onStartShouldSetResponder={() => true}
        onMoveShouldSetResponder={() => true}
        onResponderGrant={(e) => setDragMs(ratioToMs(e.nativeEvent.locationX))}
        onResponderMove={(e) => setDragMs(ratioToMs(e.nativeEvent.locationX))}
        onResponderRelease={(e) => {
          const target = ratioToMs(e.nativeEvent.locationX);
          setDragMs(null);
          haptic();
          void onSeek(target);
        }}
        onResponderTerminate={() => setDragMs(null)}
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
        <Text style={styles.timeText}>{fmtTime(shownMs)}</Text>
        <Text style={styles.timeText}>
          {isCached ? 'ОФФЛАЙН · ' : ''}
          {fmtTime(totalMs)}
        </Text>
      </View>
    </View>
  );
}
const FullSeekSection = memo(FullSeekSectionBase);

function FullPlayerModalBase() {
  const fullPlayerOpen = useMusicStore((s) => s.fullPlayerOpen);
  const currentTrack = useMusicStore((s) => s.currentTrack);
  const currentIndex = useMusicStore((s) => s.currentIndex);
  const queue = useMusicStore((s) => s.queue);
  const isPlaying = useMusicStore((s) => s.isPlaying);
  const isLoading = useMusicStore((s) => s.isLoading);
  const isWaveMode = useMusicStore((s) => s.isWaveMode);
  const activeStationName = useMusicStore((s) => s.activeStationName);
  const shuffleEnabled = useMusicStore((s) => s.shuffleEnabled);
  const repeatMode = useMusicStore((s) => s.repeatMode);
  const lyricsOpen = useMusicStore((s) => s.lyricsOpen);
  const lyricsLoading = useMusicStore((s) => s.lyricsLoading);
  const lyricsText = useMusicStore((s) => s.lyricsText);
  const isCached = useMusicStore((s) =>
    s.currentTrack ? Boolean(s.cachedMap[s.currentTrack.id]) : false
  );
  const isCaching = useMusicStore((s) =>
    s.currentTrack ? Boolean(s.cachingIds[s.currentTrack.id]) : false
  );

  const setFullPlayerOpen = useMusicStore((s) => s.setFullPlayerOpen);
  const togglePlayPause = useMusicStore((s) => s.togglePlayPause);
  const seekTo = useMusicStore((s) => s.seekTo);
  const nextTrack = useMusicStore((s) => s.nextTrack);
  const prevTrack = useMusicStore((s) => s.prevTrack);
  const toggleShuffle = useMusicStore((s) => s.toggleShuffle);
  const cycleRepeat = useMusicStore((s) => s.cycleRepeat);
  const toggleCurrentLike = useMusicStore((s) => s.toggleCurrentLike);
  const dislikeCurrentTrack = useMusicStore((s) => s.dislikeCurrentTrack);
  const cacheTrack = useMusicStore((s) => s.cacheTrack);
  const removeCached = useMusicStore((s) => s.removeCached);
  const openLyrics = useMusicStore((s) => s.openLyrics);
  const closeLyrics = useMusicStore((s) => s.closeLyrics);
  const playFromList = useMusicStore((s) => s.playFromList);

  const accentTheme = usePhoneSettingsStore((s) => s.accentTheme);
  const hapticsEnabled = usePhoneSettingsStore((s) => s.hapticsEnabled);
  const accent = ACCENT_THEMES[accentTheme].accent;

  if (!fullPlayerOpen || !currentTrack) return null;

  const haptic = () => {
    if (!hapticsEnabled) return;
    try {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch {}
  };

  return (
    <Modal
      visible={fullPlayerOpen}
      animationType="slide"
      presentationStyle="fullScreen"
      onRequestClose={() => setFullPlayerOpen(false)}>
      <View style={styles.backdrop}>
        <SafeAreaView style={styles.safeArea} edges={['top', 'bottom']}>
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
            style={{ flex: 1 }}
            showsVerticalScrollIndicator={false}
            contentContainerStyle={styles.scrollBody}>
            <View style={[styles.coverWrap, { shadowColor: accent }]}>
              {currentTrack.coverUrl ? (
                <Image
                  source={{ uri: currentTrack.coverUrl.replace('400x400', '600x600') }}
                  style={styles.cover}
                  contentFit="cover"
                  cachePolicy="memory-disk"
                  transition={160}
                />
              ) : (
                <View style={[styles.cover, styles.coverStub]}>
                  <Disc3 size={64} color={accent} />
                </View>
              )}
            </View>

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

            <FullSeekSection
              accent={accent}
              fallbackDurationMs={currentTrack.durationMs}
              isCached={isCached}
              onSeek={seekTo}
              haptic={haptic}
            />

            <View style={styles.transportRow}>
              <Pressable
                style={styles.sideCtrl}
                onPress={() => {
                  haptic();
                  toggleShuffle();
                }}>
                <Shuffle size={20} color={shuffleEnabled ? accent : SakuraColors.inkDim} />
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
                        <Image
                          source={{ uri: tr.coverUrl }}
                          style={styles.qCover}
                          contentFit="cover"
                          cachePolicy="memory-disk"
                        />
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
}

export const FullPlayerModal = memo(FullPlayerModalBase);

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
    paddingHorizontal: 14,
    paddingTop: 6,
    paddingBottom: 8,
  },
  closeBtn: {
    width: 38,
    height: 38,
    borderRadius: 12,
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
    letterSpacing: 1.1,
    color: SakuraColors.textMuted,
  },
  albumSub: {
    fontSize: 12,
    fontWeight: '600',
    color: SakuraColors.inkDim,
    marginTop: 1,
  },
  scrollBody: {
    paddingHorizontal: 22,
    paddingBottom: 34,
    gap: 18,
  },
  coverWrap: {
    alignItems: 'center',
    marginTop: 8,
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.35,
    shadowRadius: 24,
  },
  cover: {
    width: 280,
    height: 280,
    borderRadius: 24,
    backgroundColor: 'rgba(255,255,255,0.06)',
  },
  coverStub: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginTop: 4,
  },
  title: {
    fontSize: 21,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  artist: {
    fontSize: 14.5,
    color: SakuraColors.inkDim,
    fontWeight: '600',
  },
  heartBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: SakuraColors.panel,
    alignItems: 'center',
    justifyContent: 'center',
  },
  seekSection: {
    gap: 6,
  },
  seekHitbox: {
    paddingVertical: 10,
    justifyContent: 'center',
  },
  seekTrack: {
    height: 4,
    borderRadius: 2,
    backgroundColor: 'rgba(255,255,255,0.14)',
    position: 'relative',
  },
  seekFill: {
    height: 4,
    borderRadius: 2,
  },
  seekThumb: {
    position: 'absolute',
    top: -5,
    marginLeft: -7,
    width: 14,
    height: 14,
    borderRadius: 7,
    borderWidth: 2,
  },
  timeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  timeText: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 11,
    color: SakuraColors.textMuted,
  },
  transportRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 6,
  },
  sideCtrl: {
    width: 42,
    height: 42,
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
    shadowRadius: 14,
    elevation: 8,
  },
  actionsStrip: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 12,
  },
  actionChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: 999,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  actionLabel: {
    fontSize: 12.5,
    fontWeight: '600',
    color: SakuraColors.inkDim,
  },
  queueBox: {
    marginTop: 6,
    gap: 8,
    backgroundColor: SakuraColors.panel,
    borderRadius: 18,
    padding: 12,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  queueHeading: {
    fontFamily: SakuraFonts.displayMedium,
    fontSize: 10,
    letterSpacing: 1,
    color: SakuraColors.textMuted,
    marginBottom: 2,
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
    backgroundColor: 'rgba(255,255,255,0.06)',
  },
  qTitle: {
    fontSize: 13,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  qArtist: {
    fontSize: 11.5,
    color: SakuraColors.inkDim,
  },
  lyricsOverlay: {
    flex: 1,
    backgroundColor: 'rgba(6, 4, 12, 0.86)',
    justifyContent: 'center',
    padding: 18,
  },
  lyricsCard: {
    maxHeight: '82%',
    borderRadius: 22,
    backgroundColor: '#161024',
    borderWidth: 1,
    borderColor: SakuraColors.lineStrong,
    padding: 18,
    gap: 12,
  },
  lyricsHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
  },
  lyricsTitle: {
    flex: 1,
    fontSize: 15,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  lyricsClose: {
    width: 32,
    height: 32,
    borderRadius: 10,
    backgroundColor: SakuraColors.panel,
    alignItems: 'center',
    justifyContent: 'center',
  },
  lyricsText: {
    fontSize: 15,
    lineHeight: 23,
    color: SakuraColors.ink,
  },
});

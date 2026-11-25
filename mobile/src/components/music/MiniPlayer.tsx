/**
 * MiniPlayer — парящий стеклянный мини-плеер Яндекс.Музыки над нижней панелью табов.
 * Прогресс-бар изолирован в отдельном подписчике useMusicProgressStore,
 * чтобы остальной интерфейс не перерисовывался каждые 400 мс.
 */

import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { Disc3, Heart, Pause, Play, SkipForward } from 'lucide-react-native';
import React, { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SakuraColors } from '../../constants/colors';
import { useMusicProgressStore } from '../../stores/useMusicProgressStore';
import { useMusicStore } from '../../stores/useMusicStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

function MiniProgressBarBase({
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
    <View style={styles.progressTrack}>
      <View
        style={[styles.progressFill, { width: `${progressPct}%`, backgroundColor: accent }]}
      />
    </View>
  );
}
const MiniProgressBar = memo(MiniProgressBarBase);

function MiniPlayerBase() {
  const router = useRouter();
  const currentTrack = useMusicStore((s) => s.currentTrack);
  const isPlaying = useMusicStore((s) => s.isPlaying);
  const isOffline = useMusicStore((s) =>
    s.currentTrack ? Boolean(s.cachedMap[s.currentTrack.id]) : false
  );
  const togglePlayPause = useMusicStore((s) => s.togglePlayPause);
  const nextTrack = useMusicStore((s) => s.nextTrack);
  const toggleCurrentLike = useMusicStore((s) => s.toggleCurrentLike);
  const setFullPlayerOpen = useMusicStore((s) => s.setFullPlayerOpen);
  const accentId = usePhoneSettingsStore((s) => s.accentTheme);
  const accent = ACCENT_THEMES[accentId].accent;

  if (!currentTrack) return null;

  return (
    <Pressable
      style={({ pressed }) => [
        styles.wrapper,
        { borderColor: accent + '38' },
        pressed && { opacity: 0.92 },
      ]}
      onPress={() => {
        router.push('/(tabs)/music' as any);
        setFullPlayerOpen(true);
      }}>
      <View style={styles.row}>
        {currentTrack.coverUrl ? (
          <Image
            source={{ uri: currentTrack.coverUrl }}
            style={styles.cover}
            contentFit="cover"
            cachePolicy="memory-disk"
            transition={120}
          />
        ) : (
          <View style={[styles.cover, styles.coverPlaceholder]}>
            <Disc3 size={18} color={accent} />
          </View>
        )}

        <View style={styles.meta}>
          <Text style={styles.title} numberOfLines={1}>
            {currentTrack.title}
          </Text>
          <Text style={styles.artist} numberOfLines={1}>
            {currentTrack.artist}
            {isOffline ? ' · оффлайн' : ''}
          </Text>
        </View>

        <View style={styles.controls}>
          <Pressable
            hitSlop={8}
            style={styles.iconBtn}
            onPress={(e) => {
              e.stopPropagation();
              void toggleCurrentLike();
            }}>
            <Heart
              size={17}
              color={currentTrack.liked ? accent : SakuraColors.inkDim}
              fill={currentTrack.liked ? accent : 'transparent'}
            />
          </Pressable>

          <Pressable
            hitSlop={8}
            style={[styles.playBtn, { backgroundColor: accent }]}
            onPress={(e) => {
              e.stopPropagation();
              void togglePlayPause();
            }}>
            {isPlaying ? (
              <Pause size={15} color="#fff" fill="#fff" />
            ) : (
              <Play size={15} color="#fff" fill="#fff" />
            )}
          </Pressable>

          <Pressable
            hitSlop={8}
            style={styles.iconBtn}
            onPress={(e) => {
              e.stopPropagation();
              void nextTrack();
            }}>
            <SkipForward size={17} color={SakuraColors.ink} />
          </Pressable>
        </View>
      </View>

      <MiniProgressBar accent={accent} fallbackDurationMs={currentTrack.durationMs} />
    </Pressable>
  );
}

export const MiniPlayer = memo(MiniPlayerBase);

const styles = StyleSheet.create({
  wrapper: {
    marginHorizontal: 10,
    marginBottom: 8,
    backgroundColor: 'rgba(22, 16, 36, 0.94)',
    borderRadius: 18,
    borderWidth: 1,
    overflow: 'hidden',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 8,
    gap: 10,
  },
  cover: {
    width: 38,
    height: 38,
    borderRadius: 10,
    backgroundColor: 'rgba(255,255,255,0.06)',
  },
  coverPlaceholder: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  meta: {
    flex: 1,
    gap: 1,
  },
  title: {
    fontSize: 13,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  artist: {
    fontSize: 11,
    color: SakuraColors.inkDim,
  },
  controls: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  iconBtn: {
    width: 32,
    height: 32,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  playBtn: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
  },
  progressTrack: {
    height: 2,
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  progressFill: {
    height: 2,
  },
});

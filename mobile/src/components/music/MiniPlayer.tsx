/**
 * MiniPlayer — компактный плавающий мини-плеер Яндекс.Музыки над нижней панелью табов.
 */

import { useRouter } from 'expo-router';
import { Heart, Pause, Play, SkipForward } from 'lucide-react-native';
import React from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { SakuraColors } from '../../constants/colors';
import { useMusicStore } from '../../stores/useMusicStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

export const MiniPlayer: React.FC = () => {
  const router = useRouter();
  const {
    currentTrack,
    isPlaying,
    positionMs,
    durationMs,
    togglePlayPause,
    nextTrack,
    toggleCurrentLike,
  } = useMusicStore();
  const accentId = usePhoneSettingsStore((s) => s.accentTheme);
  const accent = ACCENT_THEMES[accentId].accent;

  if (!currentTrack) return null;

  const progressPct =
    durationMs > 0 ? Math.min(100, Math.max(0, (positionMs / durationMs) * 100)) : 0;

  return (
    <Pressable
      style={styles.container}
      onPress={() => router.push('/(tabs)/music' as any)}>
      <View style={styles.row}>
        {currentTrack.coverUrl ? (
          <Image source={{ uri: currentTrack.coverUrl }} style={styles.cover} />
        ) : (
          <View style={[styles.cover, styles.coverPlaceholder]} />
        )}

        <View style={styles.meta}>
          <Text style={styles.title} numberOfLines={1}>
            {currentTrack.title}
          </Text>
          <Text style={styles.artist} numberOfLines={1}>
            {currentTrack.artist}
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
              size={18}
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
              <Pause size={16} color="#fff" fill="#fff" />
            ) : (
              <Play size={16} color="#fff" fill="#fff" />
            )}
          </Pressable>

          <Pressable
            hitSlop={8}
            style={styles.iconBtn}
            onPress={(e) => {
              e.stopPropagation();
              void nextTrack();
            }}>
            <SkipForward size={18} color={SakuraColors.ink} />
          </Pressable>
        </View>
      </View>

      {/* Полоска прогресса */}
      <View style={styles.progressTrack}>
        <View
          style={[styles.progressFill, { width: `${progressPct}%`, backgroundColor: accent }]}
        />
      </View>
    </Pressable>
  );
};

const styles = StyleSheet.create({
  container: {
    backgroundColor: SakuraColors.panel,
    borderTopWidth: 1,
    borderTopColor: SakuraColors.lineStrong,
    paddingTop: 8,
    paddingHorizontal: 14,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingBottom: 8,
  },
  cover: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: SakuraColors.panel2,
  },
  coverPlaceholder: {
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  meta: {
    flex: 1,
    gap: 2,
  },
  title: {
    color: SakuraColors.ink,
    fontSize: 13.5,
    fontWeight: '700',
  },
  artist: {
    color: SakuraColors.inkDim,
    fontSize: 11.5,
  },
  controls: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  iconBtn: {
    padding: 4,
  },
  playBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  progressTrack: {
    height: 2,
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderRadius: 1,
    overflow: 'hidden',
  },
  progressFill: {
    height: 2,
  },
});

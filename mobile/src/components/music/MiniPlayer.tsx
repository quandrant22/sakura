/**
 * MiniPlayer — парящий стеклянный мини-плеер Яндекс.Музыки над нижней панелью табов.
 */

import { useRouter } from 'expo-router';
import { Disc3, Heart, Pause, Play, SkipForward } from 'lucide-react-native';
import React from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { SakuraColors } from '../../constants/colors';
import { useMusicStore } from '../../stores/useMusicStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

export const MiniPlayer: React.FC = () => {
  const router = useRouter();
  const {
    currentTrack,
    cachedMap,
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
  const isOffline = Boolean(cachedMap[currentTrack.id]);

  return (
    <Pressable
      style={({ pressed }) => [
        styles.wrapper,
        { borderColor: accent + '38' },
        pressed && { opacity: 0.92 },
      ]}
      onPress={() => router.push('/(tabs)/music' as any)}>
      <View style={styles.row}>
        {currentTrack.coverUrl ? (
          <Image source={{ uri: currentTrack.coverUrl }} style={styles.cover} />
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

      <View style={styles.progressTrack}>
        <View
          style={[styles.progressFill, { width: `${progressPct}%`, backgroundColor: accent }]}
        />
      </View>
    </Pressable>
  );
};

const styles = StyleSheet.create({
  wrapper: {
    marginHorizontal: 10,
    marginBottom: 8,
    backgroundColor: 'rgba(22, 16, 36, 0.94)',
    borderRadius: 18,
    borderWidth: 1,
    borderTopColor: SakuraColors.glassHighlight,
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.45,
    shadowRadius: 16,
    elevation: 10,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  cover: {
    width: 38,
    height: 38,
    borderRadius: 10,
    backgroundColor: SakuraColors.panel2Solid,
  },
  coverPlaceholder: {
    borderWidth: 1,
    borderColor: SakuraColors.line,
    alignItems: 'center',
    justifyContent: 'center',
  },
  meta: {
    flex: 1,
    gap: 1,
  },
  title: {
    color: SakuraColors.ink,
    fontSize: 13,
    fontWeight: '700',
  },
  artist: {
    color: SakuraColors.inkDim,
    fontSize: 11,
  },
  controls: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  iconBtn: {
    padding: 5,
  },
  playBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  progressTrack: {
    height: 2.5,
    backgroundColor: 'rgba(255,255,255,0.06)',
  },
  progressFill: {
    height: 2.5,
  },
});

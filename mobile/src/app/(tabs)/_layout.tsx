/**
 * Mobile-First Tab Layout (4 вкладки + встроенный мини-плеер Яндекс.Музыки).
 */

import { Tabs, useRouter } from 'expo-router';
import {
  Disc3,
  LayoutGrid,
  MessageCircleHeart,
  Radio,
  SlidersHorizontal,
} from 'lucide-react-native';
import React, { useEffect } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { MiniPlayer } from '../../components/music/MiniPlayer';
import { SakuraColors } from '../../constants/colors';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';

const VISIBLE_TABS = new Set(['index', 'chat', 'widgets', 'music', 'settings']);

function CustomTabBar({ state, descriptors, navigation, accent }: any) {
  const insets = useSafeAreaInsets();
  const router = useRouter();

  return (
    <View style={[styles.tabDock, { paddingBottom: Math.max(insets.bottom, 6) }]}>
      <MiniPlayer />
      <View style={styles.tabRow}>
        {state.routes.map((route: any, index: number) => {
          if (!VISIBLE_TABS.has(route.name)) return null;
          const { options } = descriptors[route.key];
          const label = options.title ?? route.name;
          const isFocused = state.index === index;
          const color = isFocused ? accent : SakuraColors.inkDim;

          const onPress = () => {
            if (navigation?.emit && navigation?.navigate) {
              const event = navigation.emit({
                type: 'tabPress',
                target: route.key,
                canPreventDefault: true,
              });
              if (!isFocused && !event?.defaultPrevented) {
                navigation.navigate(route.name, route.params);
              }
              return;
            }
            if (!isFocused) {
              const target = route.name === 'index' ? '/(tabs)' : `/(tabs)/${route.name}`;
              router.navigate(target as any);
            }
          };

          return (
            <Pressable
              key={route.key}
              accessibilityRole="button"
              accessibilityState={isFocused ? { selected: true } : {}}
              onPress={onPress}
              style={styles.tabItem}>
              {options.tabBarIcon ? options.tabBarIcon({ focused: isFocused, color, size: 22 }) : null}
              <Text style={[styles.tabLabel, { color }]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export default function TabLayout() {
  const accentId = usePhoneSettingsStore((s) => s.accentTheme);
  const loadSettings = usePhoneSettingsStore((s) => s.load);
  const accent = ACCENT_THEMES[accentId].accent;

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  return (
    <Tabs
      tabBar={(props) => <CustomTabBar {...props} accent={accent} />}
      screenOptions={{ headerShown: false }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Ядро',
          tabBarIcon: ({ color, size }) => <Radio size={size - 2} color={color} />,
        }}
      />
      <Tabs.Screen
        name="chat"
        options={{
          title: 'Чат',
          tabBarIcon: ({ color, size }) => <MessageCircleHeart size={size - 2} color={color} />,
        }}
      />
      <Tabs.Screen
        name="widgets"
        options={{
          title: 'Пульт',
          tabBarIcon: ({ color, size }) => <LayoutGrid size={size - 2} color={color} />,
        }}
      />
      <Tabs.Screen
        name="music"
        options={{
          title: 'Музыка',
          tabBarIcon: ({ color, size }) => <Disc3 size={size - 2} color={color} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Настройки',
          tabBarIcon: ({ color, size }) => <SlidersHorizontal size={size - 2} color={color} />,
        }}
      />

      {/* Скрытые экраны (доступны по переходу из виджетов) */}
      <Tabs.Screen name="memory" options={{ href: null }} />
      <Tabs.Screen name="devices" options={{ href: null }} />
      <Tabs.Screen name="scenarios" options={{ href: null }} />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  tabDock: {
    backgroundColor: SakuraColors.bg,
    borderTopWidth: 1,
    borderTopColor: SakuraColors.line,
  },
  tabRow: {
    flexDirection: 'row',
    height: 56,
    alignItems: 'center',
    justifyContent: 'space-around',
  },
  tabItem: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
    paddingVertical: 4,
  },
  tabLabel: {
    fontSize: 10.5,
    fontWeight: '600',
  },
});

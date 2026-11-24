/**
 * Root Layout for Sakura Mobile — неблокирующая загрузка Orbitron + Inter и ErrorBoundary.
 */

import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
} from '@expo-google-fonts/inter';
import {
  Orbitron_500Medium,
  Orbitron_600SemiBold,
  Orbitron_700Bold,
  Orbitron_800ExtraBold,
} from '@expo-google-fonts/orbitron';
import { useFonts } from 'expo-font';
import { DarkTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import React, { Component, useEffect } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { AppShell } from '../components/ui/AppShell';
import { SakuraColors } from '../constants/colors';

class AppErrorBoundary extends Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <View style={errStyles.box}>
          <Text style={errStyles.title}>Ошибка интерфейса Сакуры</Text>
          <ScrollView>
            <Text style={errStyles.msg}>{this.state.error.message}</Text>
            <Text style={errStyles.stack}>{this.state.error.stack}</Text>
          </ScrollView>
        </View>
      );
    }
    return this.props.children;
  }
}

export default function RootLayout() {
  useFonts({
    Orbitron_500Medium,
    Orbitron_600SemiBold,
    Orbitron_700Bold,
    Orbitron_800ExtraBold,
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
  });

  useEffect(() => {
    console.log('[SakuraMobile] RootLayout mounted');
    void SplashScreen.hideAsync().catch(() => {});
  }, []);

  return (
    <AppErrorBoundary>
      <ThemeProvider value={DarkTheme}>
        <StatusBar style="light" />
        <AppShell>
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: SakuraColors.bg },
            }}>
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          </Stack>
        </AppShell>
      </ThemeProvider>
    </AppErrorBoundary>
  );
}

const errStyles = StyleSheet.create({
  box: {
    flex: 1,
    backgroundColor: SakuraColors.bg,
    padding: 24,
    paddingTop: 60,
  },
  title: {
    color: SakuraColors.error,
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 12,
  },
  msg: {
    color: SakuraColors.ink,
    fontSize: 14,
    marginBottom: 12,
  },
  stack: {
    color: SakuraColors.inkDim,
    fontSize: 11,
  },
});

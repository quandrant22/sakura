/**
 * Scenarios Screen — сценарии и рутины автоматизации Сакуры.
 */

import * as Haptics from 'expo-haptics';
import { Play, RefreshCw, Zap } from 'lucide-react-native';
import React, { useEffect } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Scenario } from '../../api/types';
import { GlassCard } from '../../components/ui/GlassCard';
import { SakuraColors } from '../../constants/colors';
import { useScenariosStore } from '../../stores/useScenariosStore';

export default function ScenariosScreen() {
  const { scenarios, runningScenarioId, isLoading, bindEvents, fetchScenarios, runScenario } =
    useScenariosStore();

  useEffect(() => {
    bindEvents();
    fetchScenarios();
  }, [bindEvents, fetchScenarios]);

  const handleRun = (id: string) => {
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    } catch {}
    runScenario(id);
  };

  const renderScenario = ({ item }: { item: Scenario }) => {
    const isRunning = runningScenarioId === item.id;

    return (
      <GlassCard style={styles.card} accent={item.enabled ? 'cyan' : 'none'}>
        <View style={styles.headerRow}>
          <Text style={styles.scenarioName}>{item.name}</Text>
          <View style={[styles.statusPill, item.enabled ? styles.activePill : styles.disabledPill]}>
            <Text
              style={[
                styles.statusPillText,
                item.enabled ? styles.activePillText : styles.disabledPillText,
              ]}>
              {item.enabled ? 'Активен' : 'Выкл'}
            </Text>
          </View>
        </View>

        {item.conditions && item.conditions.length > 0 && (
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>Если: </Text>
            <Text style={styles.metaValue}>{item.conditions.map((c) => c.value).join(', ')}</Text>
          </View>
        )}

        {item.actions && item.actions.length > 0 && (
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>То: </Text>
            <Text style={styles.metaValue}>{item.actions.map((a) => a.value).join(' → ')}</Text>
          </View>
        )}

        <Pressable
          style={({ pressed }) => [
            styles.runButton,
            isRunning && styles.runningButton,
            pressed && styles.pressed,
          ]}
          onPress={() => handleRun(item.id)}
          disabled={isRunning}>
          {isRunning ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <>
              <Play size={13} color={SakuraColors.accent} fill={SakuraColors.accent} />
              <Text style={styles.runButtonText}>Выполнить</Text>
            </>
          )}
        </Pressable>
      </GlassCard>
    );
  };

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <View style={styles.container}>
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <Zap size={22} color={SakuraColors.accent} />
            <Text style={styles.title}>Сценарии</Text>
          </View>
          <Pressable
            style={({ pressed }) => [styles.refreshButton, pressed && { opacity: 0.7 }]}
            onPress={fetchScenarios}>
            <RefreshCw size={18} color={SakuraColors.inkDim} />
          </Pressable>
        </View>

        <FlatList
          data={scenarios}
          keyExtractor={(item) => item.id}
          renderItem={renderScenario}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={isLoading}
              onRefresh={fetchScenarios}
              tintColor={SakuraColors.accent}
            />
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyText}>Нет настроенных сценариев</Text>
            </View>
          }
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: SakuraColors.bg,
  },
  container: {
    flex: 1,
    padding: 14,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 14,
    paddingHorizontal: 4,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  refreshButton: {
    width: 36,
    height: 36,
    borderRadius: 12,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    alignItems: 'center',
    justifyContent: 'center',
  },
  list: {
    gap: 12,
    paddingBottom: 24,
  },
  card: {
    gap: 8,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 8,
  },
  scenarioName: {
    fontSize: 15.5,
    fontWeight: '700',
    color: SakuraColors.ink,
    flex: 1,
  },
  statusPill: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
    borderWidth: 1,
  },
  activePill: {
    backgroundColor: SakuraColors.onlineSoft,
    borderColor: 'rgba(61, 220, 151, 0.35)',
  },
  disabledPill: {
    backgroundColor: 'rgba(107, 100, 117, 0.12)',
    borderColor: SakuraColors.line,
  },
  statusPillText: {
    fontSize: 10.5,
    fontWeight: '600',
  },
  activePillText: {
    color: SakuraColors.online,
  },
  disabledPillText: {
    color: SakuraColors.inkDim,
  },
  metaRow: {
    flexDirection: 'row',
  },
  metaLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: SakuraColors.textMuted,
  },
  metaValue: {
    fontSize: 12,
    color: SakuraColors.inkDim,
    flex: 1,
  },
  runButton: {
    marginTop: 6,
    flexDirection: 'row',
    gap: 7,
    backgroundColor: SakuraColors.panel2,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    borderRadius: 12,
    paddingVertical: 9,
    alignItems: 'center',
    justifyContent: 'center',
  },
  runningButton: {
    backgroundColor: SakuraColors.accentSoft,
    borderColor: SakuraColors.accent,
  },
  runButtonText: {
    fontSize: 13,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  pressed: {
    opacity: 0.8,
  },
  empty: {
    paddingVertical: 48,
    alignItems: 'center',
  },
  emptyText: {
    color: SakuraColors.inkDim,
    fontSize: 13.5,
  },
});

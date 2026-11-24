/**
 * Пульт управления ПК и Окно с виджетами (Расписание, Телеметрия, Память, Фокус-таймер, Сценарии).
 */

import * as Haptics from 'expo-haptics';
import { useRouter } from 'expo-router';
import {
  Brain,
  CalendarDays,
  Cpu,
  Laptop,
  Lock,
  Monitor,
  Moon,
  Pause,
  Play,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  SkipForward,
  Timer,
  Volume2,
  VolumeX,
  Zap,
} from 'lucide-react-native';
import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { sakuraClient } from '../../api/client';
import { WidgetsData } from '../../api/types';
import { GlassCard } from '../../components/ui/GlassCard';
import { SakuraColors } from '../../constants/colors';
import { SakuraFonts } from '../../constants/fonts';
import { useChatStore } from '../../stores/useChatStore';
import { useDevicesStore } from '../../stores/useDevicesStore';
import { useMemoryStore } from '../../stores/useMemoryStore';
import { ACCENT_THEMES, usePhoneSettingsStore } from '../../stores/usePhoneSettingsStore';
import { useScenariosStore } from '../../stores/useScenariosStore';

export default function WidgetsAndRemoteScreen() {
  const router = useRouter();
  const { devices, isLoading: devLoading, bindEvents: bindDev, fetchDevices } = useDevicesStore();
  const { scenarios, runningScenarioId, bindEvents: bindScen, fetchScenarios, runScenario } =
    useScenariosStore();
  const { total: memoryTotal, fetchMemories } = useMemoryStore();
  const { status, sendMessage } = useChatStore();
  const settings = usePhoneSettingsStore();

  const accent = ACCENT_THEMES[settings.accentTheme].accent;

  // Целевой ПК для пульта
  const pcs = devices.filter((d) => d.kind === 'pc');
  const [selectedTarget, setSelectedTarget] = useState<string>('pc');
  const [remoteToast, setRemoteToast] = useState<string | null>(null);

  // Быстрая заметка в память
  const [noteText, setNoteText] = useState('');

  // Живые данные виджетов с сервера
  const [widgetsData, setWidgetsData] = useState<WidgetsData | null>(null);

  // Мобильный фокус-таймер (25:00)
  const [timerSec, setTimerSec] = useState(25 * 60);
  const [timerRunning, setTimerRunning] = useState(false);

  const loadWidgets = useCallback(async () => {
    try {
      const data = await sakuraClient.getWidgetsData();
      setWidgetsData(data);
    } catch {}
  }, []);

  useEffect(() => {
    let active = true;
    bindDev();
    bindScen();
    void fetchDevices();
    void fetchScenarios();
    void fetchMemories();
    sakuraClient
      .getWidgetsData()
      .then((data) => {
        if (active) setWidgetsData(data);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [bindDev, bindScen, fetchDevices, fetchScenarios, fetchMemories]);

  useEffect(() => {
    if (!timerRunning) return;
    const id = setInterval(() => {
      setTimerSec((prev) => {
        if (prev <= 1) {
          setTimerRunning(false);
          if (settings.hapticsEnabled) {
            try {
              void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            } catch {}
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [timerRunning, settings.hapticsEnabled]);

  const activePc =
    pcs.find((d) => d.id === selectedTarget) ||
    pcs.find((d) => d.focus) ||
    pcs.find((d) => d.online) ||
    pcs[0];
  const targetId = activePc?.id || selectedTarget || 'pc';

  const haptic = (heavy = false) => {
    if (!settings.hapticsEnabled) return;
    try {
      void Haptics.impactAsync(
        heavy ? Haptics.ImpactFeedbackStyle.Heavy : Haptics.ImpactFeedbackStyle.Light
      );
    } catch {}
  };

  const execRemote = async (action: string, label: string, isPower = false) => {
    const run = async () => {
      haptic(isPower);
      setRemoteToast(`Отправка «${label}» на ${targetId}…`);
      try {
        const res = await sakuraClient.sendRemoteCommand(targetId, action, '', true);
        setRemoteToast(res?.detail || `${label} → отправлено на ${targetId}`);
      } catch (e: any) {
        setRemoteToast(`Ошибка: ${e?.message || 'не удалось выполнить'}`);
      }
      setTimeout(() => setRemoteToast(null), 3500);
    };

    if (isPower && settings.confirmPowerActions && Platform.OS !== 'web') {
      Alert.alert(label, `Выполнить «${label}» на ${activePc?.name || targetId}?`, [
        { text: 'Отмена', style: 'cancel' },
        { text: 'Да', style: 'destructive', onPress: () => void run() },
      ]);
      return;
    }

    await run();
  };

  const handleSaveQuickNote = () => {
    const t = noteText.trim();
    if (!t) return;
    haptic();
    void sendMessage(`Запомни: ${t}`, 'text');
    setNoteText('');
    setRemoteToast('Заметка отправлена в память Сакуры');
    setTimeout(() => setRemoteToast(null), 3000);
  };

  const formatTimer = (sec: number) => {
    const m = Math.floor(sec / 60)
      .toString()
      .padStart(2, '0');
    const s = (sec % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  const onRefreshAll = () => {
    void fetchDevices();
    void fetchScenarios();
    void fetchMemories();
    void loadWidgets();
  };

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={devLoading} onRefresh={onRefreshAll} tintColor={accent} />
        }>
        <View style={styles.pageHeader}>
          <Text style={styles.screenTitle}>Пульт и Виджеты</Text>
          {remoteToast && (
            <View style={[styles.toastChip, { borderColor: accent + '66' }]}>
              <Text style={[styles.toastText, { color: accent }]} numberOfLines={1}>
                {remoteToast}
              </Text>
            </View>
          )}
        </View>

        {/* ── ПУЛЬТ УПРАВЛЕНИЯ ПК ── */}
        <GlassCard style={styles.remoteCard}>
          <View style={styles.remoteTop}>
            <Text style={styles.cardHeading}>Пульт компьютера</Text>
            <Text style={styles.instantBadge}>
              {settings.confirmPowerActions ? 'с подтверждением' : 'мгновенно в 1 тап'}
            </Text>
          </View>

          {/* Выбор ПК */}
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.targetRow}>
            {(pcs.length > 0 ? pcs : [{ id: 'pc', name: 'Игровой ПК', online: false, focus: false } as any]).map(
              (pc) => {
                const selected = targetId === pc.id;
                return (
                  <Pressable
                    key={pc.id}
                    style={[
                      styles.targetChip,
                      selected && { borderColor: accent, backgroundColor: accent + '1E' },
                    ]}
                    onPress={() => {
                      haptic();
                      setSelectedTarget(pc.id);
                    }}>
                    <View
                      style={[
                        styles.onlineDot,
                        { backgroundColor: pc.online ? SakuraColors.online : SakuraColors.offline },
                      ]}
                    />
                    {pc.id === 'laptop' || pc.id === 'mostech' ? (
                      <Laptop size={14} color={selected ? accent : SakuraColors.inkDim} />
                    ) : (
                      <Monitor size={14} color={selected ? accent : SakuraColors.inkDim} />
                    )}
                    <Text style={[styles.targetText, selected && { color: SakuraColors.ink }]}>
                      {pc.name || pc.id}
                    </Text>
                  </Pressable>
                );
              }
            )}
          </ScrollView>

          {/* Кнопки питания (без подтверждения!) */}
          <View style={styles.powerRow}>
            <Pressable
              style={({ pressed }) => [styles.powerBtn, styles.powerShutdown, pressed && styles.pressed]}
              onPress={() => void execRemote('system.shutdown', 'Выключить ПК', true)}>
              <Power size={18} color={SakuraColors.error} />
              <Text style={[styles.powerLabel, { color: SakuraColors.error }]}>Выкл</Text>
            </Pressable>

            <Pressable
              style={({ pressed }) => [styles.powerBtn, styles.powerRestart, pressed && styles.pressed]}
              onPress={() => void execRemote('system.restart', 'Перезагрузить ПК', true)}>
              <RefreshCw size={18} color={SakuraColors.warn} />
              <Text style={[styles.powerLabel, { color: SakuraColors.warn }]}>Ребут</Text>
            </Pressable>

            <Pressable
              style={({ pressed }) => [styles.powerBtn, styles.powerSleep, pressed && styles.pressed]}
              onPress={() => void execRemote('power.sleep', 'Сон', true)}>
              <Moon size={18} color="#C084FC" />
              <Text style={[styles.powerLabel, { color: '#C084FC' }]}>Сон</Text>
            </Pressable>

            <Pressable
              style={({ pressed }) => [styles.powerBtn, styles.powerLock, pressed && styles.pressed]}
              onPress={() => void execRemote('system.lock', 'Блок экрана', false)}>
              <Lock size={18} color={SakuraColors.cyan} />
              <Text style={[styles.powerLabel, { color: SakuraColors.cyan }]}>Блок</Text>
            </Pressable>
          </View>

          {/* Звук и медиа на ПК */}
          <View style={styles.mediaControlsRow}>
            <Pressable
              style={({ pressed }) => [styles.mediaBtn, pressed && styles.pressed]}
              onPress={() => void execRemote('volume:0', 'Выключить звук')}>
              <VolumeX size={16} color={SakuraColors.ink} />
              <Text style={styles.mediaBtnText}>Mute</Text>
            </Pressable>

            <Pressable
              style={({ pressed }) => [styles.mediaBtn, pressed && styles.pressed]}
              onPress={() => void execRemote('volume_down:10', 'Тише')}>
              <Volume2 size={15} color={SakuraColors.inkDim} />
              <Text style={styles.mediaBtnText}>−10%</Text>
            </Pressable>

            <Pressable
              style={({ pressed }) => [styles.mediaBtn, pressed && styles.pressed]}
              onPress={() => void execRemote('volume_up:10', 'Громче')}>
              <Volume2 size={15} color={SakuraColors.ink} />
              <Text style={styles.mediaBtnText}>+10%</Text>
            </Pressable>

            <Pressable
              style={({ pressed }) => [styles.mediaBtn, pressed && styles.pressed]}
              onPress={() => void execRemote('music:play_pause', 'Пауза / Плей')}>
              <Play size={15} color={accent} />
            </Pressable>

            <Pressable
              style={({ pressed }) => [styles.mediaBtn, pressed && styles.pressed]}
              onPress={() => void execRemote('music:next', 'След. трек')}>
              <SkipForward size={15} color={SakuraColors.ink} />
            </Pressable>
          </View>
        </GlassCard>

        {/* ── СЕТКА ВИДЖЕТОВ (2 КОЛОНКИ) ── */}
        <View style={styles.widgetsGrid}>
          {/* Виджет 1: Расписание */}
          <GlassCard style={styles.widgetHalf}>
            <View style={styles.widgetHeader}>
              <CalendarDays size={16} color={accent} />
              <Text style={styles.widgetTitle}>Расписание</Text>
            </View>
            {widgetsData?.schedule?.current ? (
              <Text style={styles.widgetBodyText} numberOfLines={2}>
                Сейчас: {widgetsData.schedule.current.start} {widgetsData.schedule.current.subject}
              </Text>
            ) : widgetsData?.schedule?.today && widgetsData.schedule.today.length > 0 ? (
              <Text style={styles.widgetBodyText} numberOfLines={2}>
                Сегодня: {widgetsData.schedule.today.length} пар · с{' '}
                {widgetsData.schedule.today[0].start}
              </Text>
            ) : widgetsData?.schedule?.has_data ? (
              <Text style={styles.widgetBodyText} numberOfLines={2}>
                Сегодня пар нет
                {widgetsData.schedule.tomorrow.length > 0
                  ? ` · завтра ${widgetsData.schedule.tomorrow.length}`
                  : ''}
              </Text>
            ) : (
              <Text style={styles.widgetBodyText}>
                {new Date().toLocaleDateString('ru-RU', {
                  weekday: 'short',
                  day: 'numeric',
                  month: 'short',
                })}
              </Text>
            )}
            <Pressable
              style={[styles.widgetActionChip, { borderColor: accent + '44' }]}
              onPress={() => {
                haptic();
                void sendMessage('Какие пары или дела у меня сегодня?', 'text');
                router.push('/(tabs)/chat' as any);
              }}>
              <Text style={[styles.widgetActionText, { color: accent }]}>Подробнее в чате →</Text>
            </Pressable>
          </GlassCard>

          {/* Виджет 2: Телеметрия активного ПК */}
          <GlassCard style={styles.widgetHalf}>
            <View style={styles.widgetHeader}>
              <Cpu size={16} color={SakuraColors.cyan} />
              <Text style={styles.widgetTitle}>Система ПК</Text>
            </View>
            {activePc?.online && activePc.stats ? (
              <View style={styles.barsCol}>
                <View style={styles.barRow}>
                  <Text style={styles.barLabel}>CPU</Text>
                  <View style={styles.barBg}>
                    <View
                      style={[
                        styles.barFill,
                        { width: `${Math.min(100, activePc.stats.cpu ?? 0)}%`, backgroundColor: SakuraColors.cyan },
                      ]}
                    />
                  </View>
                  <Text style={styles.barVal}>{activePc.stats.cpu ?? '—'}%</Text>
                </View>
                <View style={styles.barRow}>
                  <Text style={styles.barLabel}>RAM</Text>
                  <View style={styles.barBg}>
                    <View
                      style={[
                        styles.barFill,
                        { width: `${Math.min(100, activePc.stats.ram ?? 0)}%`, backgroundColor: accent },
                      ]}
                    />
                  </View>
                  <Text style={styles.barVal}>{activePc.stats.ram ?? '—'}%</Text>
                </View>
              </View>
            ) : (
              <Text style={styles.widgetMuted}>ПК не в сети или данные не переданы</Text>
            )}
          </GlassCard>

          {/* Виджет 3: Статистика и Память */}
          <GlassCard style={styles.widgetHalf}>
            <Pressable
              style={styles.widgetFill}
              onPress={() => router.push('/(tabs)/memory' as any)}>
              <View style={styles.widgetHeader}>
                <Brain size={16} color="#C084FC" />
                <Text style={styles.widgetTitle}>Память</Text>
              </View>
              <Text style={styles.bigStat}>{widgetsData?.memory?.total ?? memoryTotal}</Text>
              <Text style={styles.widgetMuted}>
                записей · режим {widgetsData?.status?.mode || status?.mode || 'normal'}
              </Text>
            </Pressable>
          </GlassCard>

          {/* Виджет 4: Фокус-таймер */}
          <GlassCard style={styles.widgetHalf}>
            <View style={styles.widgetHeader}>
              <Timer size={16} color={SakuraColors.online} />
              <Text style={styles.widgetTitle}>Фокус</Text>
            </View>
            <Text style={styles.bigStat}>{formatTimer(timerSec)}</Text>
            <View style={styles.timerBtns}>
              <Pressable
                style={[styles.miniCircle, { backgroundColor: accent }]}
                onPress={() => {
                  haptic();
                  setTimerRunning((v) => !v);
                }}>
                {timerRunning ? (
                  <Pause size={12} color="#fff" fill="#fff" />
                ) : (
                  <Play size={12} color="#fff" fill="#fff" />
                )}
              </Pressable>
              <Pressable
                style={styles.miniCircleGhost}
                onPress={() => {
                  haptic();
                  setTimerRunning(false);
                  setTimerSec(25 * 60);
                }}>
                <RotateCcw size={12} color={SakuraColors.inkDim} />
              </Pressable>
            </View>
          </GlassCard>
        </View>

        {/* Виджет 5: Быстрая заметка в память Сакуры */}
        <GlassCard style={styles.noteCard}>
          <Text style={styles.cardHeading}>Быстрая заметка в память</Text>
          <View style={styles.noteRow}>
            <TextInput
              style={styles.noteInput}
              placeholder="Что запомнить Сакуре?…"
              placeholderTextColor={SakuraColors.textMuted}
              value={noteText}
              onChangeText={setNoteText}
              onSubmitEditing={handleSaveQuickNote}
            />
            <Pressable
              style={[styles.noteAddBtn, { backgroundColor: accent }]}
              onPress={handleSaveQuickNote}>
              <Plus size={18} color="#fff" />
            </Pressable>
          </View>
        </GlassCard>

        {/* Виджет 6: Быстрые сценарии */}
        <GlassCard style={styles.noteCard}>
          <View style={styles.remoteTop}>
            <View style={styles.widgetHeader}>
              <Zap size={16} color={accent} />
              <Text style={styles.cardHeading}>Сценарии</Text>
            </View>
            <Text style={styles.widgetMuted}>{scenarios.length} шт.</Text>
          </View>

          {scenarios.length === 0 ? (
            <Text style={styles.widgetMuted}>Сценарии появятся после подключения к серверу</Text>
          ) : (
            <View style={styles.scenariosWrap}>
              {scenarios.map((sc) => {
                const running = runningScenarioId === sc.id;
                return (
                  <Pressable
                    key={sc.id}
                    style={({ pressed }) => [
                      styles.scenarioChip,
                      running && { borderColor: accent, backgroundColor: accent + '22' },
                      pressed && styles.pressed,
                    ]}
                    onPress={() => {
                      haptic();
                      void runScenario(sc.id);
                    }}>
                    <Play size={12} color={accent} fill={accent} />
                    <Text style={styles.scenarioChipText}>{sc.name}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        </GlassCard>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: SakuraColors.bg,
  },
  scrollContent: {
    padding: 14,
    paddingBottom: 36,
    gap: 14,
  },
  pageHeader: {
    gap: 6,
    paddingHorizontal: 4,
  },
  screenTitle: {
    fontSize: 22,
    fontWeight: '800',
    color: SakuraColors.ink,
  },
  toastChip: {
    alignSelf: 'flex-start',
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 4,
  },
  toastText: {
    fontSize: 12,
    fontWeight: '600',
  },
  remoteCard: {
    gap: 12,
  },
  remoteTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  cardHeading: {
    fontSize: 15,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  instantBadge: {
    fontSize: 11,
    fontWeight: '600',
    color: SakuraColors.online,
  },
  targetRow: {
    gap: 8,
  },
  targetChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 12,
    backgroundColor: SakuraColors.panel2,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  onlineDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  targetText: {
    fontSize: 12.5,
    fontWeight: '600',
    color: SakuraColors.inkDim,
  },
  powerRow: {
    flexDirection: 'row',
    gap: 8,
  },
  powerBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 5,
    borderWidth: 1,
  },
  powerShutdown: {
    backgroundColor: 'rgba(255, 92, 124, 0.1)',
    borderColor: 'rgba(255, 92, 124, 0.35)',
  },
  powerRestart: {
    backgroundColor: 'rgba(255, 184, 77, 0.1)',
    borderColor: 'rgba(255, 184, 77, 0.35)',
  },
  powerSleep: {
    backgroundColor: 'rgba(192, 132, 252, 0.1)',
    borderColor: 'rgba(192, 132, 252, 0.35)',
  },
  powerLock: {
    backgroundColor: 'rgba(79, 216, 255, 0.1)',
    borderColor: 'rgba(79, 216, 255, 0.35)',
  },
  powerLabel: {
    fontSize: 11.5,
    fontWeight: '700',
  },
  mediaControlsRow: {
    flexDirection: 'row',
    gap: 8,
  },
  mediaBtn: {
    flex: 1,
    flexDirection: 'row',
    gap: 4,
    paddingVertical: 9,
    borderRadius: 12,
    backgroundColor: SakuraColors.panel2,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mediaBtnText: {
    fontSize: 11.5,
    fontWeight: '600',
    color: SakuraColors.ink,
  },
  widgetsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  widgetHalf: {
    width: '48%',
    flexGrow: 1,
    padding: 14,
    gap: 8,
    minHeight: 122,
    justifyContent: 'space-between',
  },
  widgetFill: {
    flex: 1,
    justifyContent: 'space-between',
    gap: 6,
  },
  widgetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  widgetTitle: {
    fontSize: 13.5,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  widgetBodyText: {
    fontSize: 15,
    fontWeight: '700',
    color: SakuraColors.ink,
    textTransform: 'capitalize',
  },
  widgetMuted: {
    fontSize: 11.5,
    color: SakuraColors.inkDim,
    lineHeight: 15,
  },
  widgetActionChip: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 10,
    borderWidth: 1,
    backgroundColor: SakuraColors.panel2,
    alignItems: 'center',
  },
  widgetActionText: {
    fontSize: 11.5,
    fontWeight: '700',
  },
  barsCol: {
    gap: 6,
  },
  barRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  barLabel: {
    width: 28,
    fontSize: 10.5,
    fontWeight: '600',
    color: SakuraColors.inkDim,
  },
  barBg: {
    flex: 1,
    height: 6,
    borderRadius: 3,
    backgroundColor: 'rgba(255,255,255,0.08)',
    overflow: 'hidden',
  },
  barFill: {
    height: 6,
    borderRadius: 3,
  },
  barVal: {
    width: 30,
    textAlign: 'right',
    fontSize: 10.5,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  bigStat: {
    fontFamily: SakuraFonts.display,
    fontSize: 24,
    color: SakuraColors.ink,
  },
  timerBtns: {
    flexDirection: 'row',
    gap: 8,
  },
  miniCircle: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  miniCircleGhost: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: SakuraColors.panel2,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    alignItems: 'center',
    justifyContent: 'center',
  },
  noteCard: {
    gap: 10,
  },
  noteRow: {
    flexDirection: 'row',
    gap: 8,
  },
  noteInput: {
    flex: 1,
    backgroundColor: SakuraColors.panel2,
    color: SakuraColors.ink,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 9,
    fontSize: 13.5,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  noteAddBtn: {
    width: 42,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  scenariosWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  scenarioChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: SakuraColors.panel2,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 12,
  },
  scenarioChipText: {
    fontSize: 12.5,
    fontWeight: '600',
    color: SakuraColors.ink,
  },
  pressed: {
    opacity: 0.78,
  },
});

/**
 * Settings Screen — все настройки телефона, голос/только текст, Яндекс.Музыка,
 * пульт питания, оформление, профиль Сакуры и защищённый канал Noise.
 */

import * as Haptics from 'expo-haptics';
import {
  CheckCircle2,
  Disc3,
  KeyRound,
  Link2,
  Lock,
  Palette,
  ShieldAlert,
  Smartphone,
  Trash2,
  UserCheck,
  Volume2,
  VolumeX,
} from 'lucide-react-native';
import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { normalizeWords } from '../../api/secure/pairing';
import { GlassCard } from '../../components/ui/GlassCard';
import { SakuraColors } from '../../constants/colors';
import {
  DEFAULT_SERVER_URL,
  DEFAULT_WS_TOKEN,
  useConnectionStore,
} from '../../stores/useConnectionStore';
import { useMusicStore } from '../../stores/useMusicStore';
import {
  ACCENT_THEMES,
  AccentThemeId,
  DEFAULT_YANDEX_TOKEN,
  usePhoneSettingsStore,
} from '../../stores/usePhoneSettingsStore';
import { useProfileStore } from '../../stores/useProfileStore';

const TTS_SPEEDS = [0.9, 1.0, 1.15, 1.3];

export default function SettingsScreen() {
  const {
    linkState,
    linkInfo,
    serverUrl,
    token,
    deviceId,
    deviceFp,
    serverFp,
    isPaired,
    isPairing,
    error: connError,
    connect,
    pairDevice,
    disconnect,
    resetPairing,
    reset,
  } = useConnectionStore();

  const { profile, fetchProfile, updateProfile } = useProfileStore();
  const settings = usePhoneSettingsStore();
  const { account: ymAccount, cachedMap, loadCache, clearCache, verifyAccount } = useMusicStore();

  const cachedEntries = Object.values(cachedMap);
  const cachedTotalMb = (
    cachedEntries.reduce((acc, e) => acc + (e.sizeBytes || 0), 0) /
    (1024 * 1024)
  ).toFixed(1);

  useEffect(() => {
    void loadCache();
  }, [loadCache]);

  const [urlOverride, setUrlOverride] = useState<string | null>(null);
  const [tokenOverride, setTokenOverride] = useState<string | null>(null);
  const [ymTokenOverride, setYmTokenOverride] = useState<string | null>(null);
  const [ymStatus, setYmStatus] = useState<string | null>(null);
  const [ymChecking, setYmChecking] = useState(false);

  const [pairInput, setPairInput] = useState('');
  const [pairSuccess, setPairSuccess] = useState<string | null>(null);
  const [pairError, setPairError] = useState<string | null>(null);

  const inputUrl = urlOverride ?? (serverUrl || DEFAULT_SERVER_URL);
  const inputToken = tokenOverride ?? (token || DEFAULT_WS_TOKEN);
  const inputYmToken = ymTokenOverride ?? (settings.yandexToken || DEFAULT_YANDEX_TOKEN);
  const accent = ACCENT_THEMES[settings.accentTheme].accent;

  useEffect(() => {
    if (linkState === 'connected') {
      void fetchProfile();
    }
  }, [linkState, fetchProfile]);

  const hapticTap = () => {
    if (!settings.hapticsEnabled) return;
    try {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch {}
  };

  const toggleSetting = (key: keyof typeof settings, value: boolean) => {
    hapticTap();
    void settings.update({ [key]: value } as any);
  };

  const handleCheckYandex = async () => {
    hapticTap();
    setYmChecking(true);
    setYmStatus(null);
    await settings.update({ yandexToken: inputYmToken.trim() });
    try {
      const acc = await verifyAccount(inputYmToken.trim());
      setYmStatus(
        `${acc.displayName} (${acc.login}) · ${acc.hasPlus ? 'Плюс активен' : 'без Плюса'}`
      );
    } catch (e: any) {
      setYmStatus(`Ошибка: ${e?.message || 'не удалось проверить'}`);
    } finally {
      setYmChecking(false);
    }
  };

  const wordCount = pairInput.trim().toLowerCase().startsWith('sakura-pair://')
    ? 8
    : normalizeWords(pairInput).split(' ').filter(Boolean).length;

  const handlePair = async () => {
    setPairError(null);
    setPairSuccess(null);
    if (!pairInput.trim()) {
      setPairError('Вставьте 8 слов или QR-ссылку sakura-pair://1 из /pair');
      return;
    }
    hapticTap();
    try {
      await pairDevice(pairInput, inputUrl);
      setPairInput('');
      setPairSuccess('Устройство спарено и подключено по Noise IK');
    } catch (e: any) {
      setPairError(e?.message || 'Ошибка спаривания');
    }
  };

  const handleResetPairing = () => {
    if (Platform.OS === 'web') {
      void resetPairing();
      return;
    }
    Alert.alert('Сбросить ключи Noise?', 'После сброса потребуется новый /pair в Telegram.', [
      { text: 'Отмена', style: 'cancel' },
      { text: 'Сбросить', style: 'destructive', onPress: () => void resetPairing() },
    ]);
  };

  const handleResetAll = () => {
    if (Platform.OS === 'web') {
      void reset();
      void settings.resetDefaults();
      setUrlOverride(null);
      setTokenOverride(null);
      setYmTokenOverride(null);
      return;
    }
    Alert.alert('Сбросить все настройки', 'Удалить ключи спаривания и сбросить параметры телефона?', [
      { text: 'Отмена', style: 'cancel' },
      {
        text: 'Сбросить',
        style: 'destructive',
        onPress: () => {
          void reset();
          void settings.resetDefaults();
          setUrlOverride(null);
          setTokenOverride(null);
          setYmTokenOverride(null);
        },
      },
    ]);
  };

  const statusColor =
    linkState === 'connected'
      ? SakuraColors.online
      : linkState === 'connecting'
      ? SakuraColors.gold
      : linkState === 'pairing_required'
      ? accent
      : SakuraColors.error;

  const statusText =
    linkState === 'connected'
      ? linkInfo.secure
        ? 'Noise IK · Защищено'
        : 'Подключено (WSS)'
      : linkState === 'connecting'
      ? 'Рукопожатие…'
      : linkState === 'pairing_required'
      ? 'Нужен /pair'
      : 'Отключено';

  const renderToggle = (
    label: string,
    sub: string,
    value: boolean,
    onChange: (v: boolean) => void
  ) => (
    <View style={styles.toggleRow}>
      <View style={styles.toggleMeta}>
        <Text style={styles.toggleLabel}>{label}</Text>
        <Text style={styles.toggleSub}>{sub}</Text>
      </View>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ false: '#2a2238', true: accent + '88' }}
        thumbColor={value ? accent : '#9b8fa8'}
      />
    </View>
  );

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.scrollContent}>
          <Text style={styles.screenTitle}>Настройки телефона</Text>

          {/* 1. Голос и режим ответов (Голос / Только текст) */}
          <GlassCard style={styles.card}>
            <View style={styles.titleRow}>
              {settings.voiceRepliesEnabled ? (
                <Volume2 size={17} color={accent} />
              ) : (
                <VolumeX size={17} color={SakuraColors.inkDim} />
              )}
              <Text style={styles.sectionTitle}>Голос и ответы</Text>
            </View>

            {renderToggle(
              'Голосовые ответы (TTS)',
              settings.voiceRepliesEnabled
                ? 'Сакура отвечает текстом и голосом'
                : 'Режим «Только текст» (без звука и синтеза речи)',
              settings.voiceRepliesEnabled,
              (v) => toggleSetting('voiceRepliesEnabled', v)
            )}

            {renderToggle(
              'Голосовой режим (Hands-Free)',
              'Крупная сфера на весь экран при входе в Сакуру',
              settings.handsFreeMode,
              (v) => toggleSetting('handsFreeMode', v)
            )}

            {renderToggle(
              'Приглушать музыку при ответе',
              'Плавно снижать громкость Яндекса, когда Сакура говорит',
              settings.duckMusicOnVoice,
              (v) => toggleSetting('duckMusicOnVoice', v)
            )}

            {renderToggle(
              'Быстрые подсказки в чате',
              'Чипы быстрых фраз над строкой ввода',
              settings.showQuickPrompts,
              (v) => toggleSetting('showQuickPrompts', v)
            )}

            <View style={styles.speedRow}>
              <Text style={styles.toggleLabel}>Скорость речи</Text>
              <View style={styles.chipsRow}>
                {TTS_SPEEDS.map((sp) => {
                  const active = settings.ttsSpeed === sp;
                  return (
                    <Pressable
                      key={sp}
                      style={[
                        styles.chip,
                        active && { backgroundColor: accent + '26', borderColor: accent },
                      ]}
                      onPress={() => {
                        hapticTap();
                        void settings.update({ ttsSpeed: sp });
                      }}>
                      <Text style={[styles.chipText, active && { color: accent }]}>{sp}x</Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>
          </GlassCard>

          {/* 2. Яндекс.Музыка */}
          <GlassCard style={styles.card}>
            <View style={styles.titleRow}>
              <Disc3 size={17} color="#FFCC00" />
              <Text style={styles.sectionTitle}>Яндекс.Музыка</Text>
            </View>

            <Text style={styles.fieldLabel}>OAuth токен (YANDEX_MUSIC_TOKEN)</Text>
            <TextInput
              style={styles.input}
              placeholder="y0__..."
              placeholderTextColor={SakuraColors.textMuted}
              value={inputYmToken}
              onChangeText={(v) => setYmTokenOverride(v)}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
            />

            {ymStatus || ymAccount ? (
              <Text style={styles.ymInfoText}>
                {ymStatus ||
                  `${ymAccount?.displayName} · ${ymAccount?.hasPlus ? 'Плюс активен' : 'без Плюса'}`}
              </Text>
            ) : null}

            <Pressable
              style={({ pressed }) => [
                styles.ymCheckBtn,
                pressed && styles.pressed,
              ]}
              onPress={handleCheckYandex}
              disabled={ymChecking}>
              {ymChecking ? (
                <ActivityIndicator size="small" color="#14101c" />
              ) : (
                <Text style={styles.ymCheckText}>Сохранить и проверить токен</Text>
              )}
            </Pressable>

            {renderToggle(
              'Высокое качество (320 кбит/с)',
              'Для мобильного интернета можно отключить ради экономии трафика',
              settings.yandexHighQuality,
              (v) => toggleSetting('yandexHighQuality', v)
            )}

            {renderToggle(
              'Кэшировать только при лайке',
              'Автозагрузка обычных треков отключена — сохраняются лишь отмеченные ❤',
              settings.autoCacheLikedOnly,
              (v) => toggleSetting('autoCacheLikedOnly', v)
            )}

            <View style={styles.toggleRow}>
              <View style={styles.toggleMeta}>
                <Text style={styles.toggleLabel}>Оффлайн-кэш треков</Text>
                <Text style={styles.toggleSub}>
                  Сохранено: {cachedEntries.length} шт. ({cachedTotalMb} МБ)
                </Text>
              </View>
              <Pressable
                disabled={cachedEntries.length === 0}
                onPress={() => {
                  hapticTap();
                  void clearCache();
                }}
                style={({ pressed }) => [
                  styles.chip,
                  cachedEntries.length === 0 && { opacity: 0.4 },
                  pressed && styles.pressed,
                ]}>
                <Text style={styles.chipText}>Очистить</Text>
              </Pressable>
            </View>
          </GlassCard>

          {/* 3. Телефон, пульт и система */}
          <GlassCard style={styles.card}>
            <View style={styles.titleRow}>
              <Smartphone size={17} color={SakuraColors.cyan} />
              <Text style={styles.sectionTitle}>Фичи телефона и Пульт</Text>
            </View>

            {renderToggle(
              'Спрашивать перед выключением ПК',
              settings.confirmPowerActions
                ? 'Показывать подтверждение при нажатии питания в Пульте'
                : 'Отключено: кнопки Пульта срабатывают мгновенно без вопросов',
              settings.confirmPowerActions,
              (v) => toggleSetting('confirmPowerActions', v)
            )}

            {renderToggle(
              'Передавать заряд и Wi-Fi на ПК',
              'Сакура на компьютере будет видеть батарею телефона',
              settings.telemetryEnabled,
              (v) => toggleSetting('telemetryEnabled', v)
            )}

            {renderToggle(
              'Тактильный отклик (Haptics)',
              'Вибрация при нажатии кнопок Пульта, микрофона и таймера',
              settings.hapticsEnabled,
              (v) => toggleSetting('hapticsEnabled', v)
            )}

            {renderToggle(
              'Не гасить экран в диалоге',
              'Удобно на столе или в держателе машины',
              settings.keepScreenAwake,
              (v) => toggleSetting('keepScreenAwake', v)
            )}

            {renderToggle(
              'Уведомления Сакуры',
              'Проактивные напоминания и статусы',
              settings.notificationsEnabled,
              (v) => toggleSetting('notificationsEnabled', v)
            )}
          </GlassCard>

          {/* 4. Оформление (Акцент) */}
          <GlassCard style={styles.card}>
            <View style={styles.titleRow}>
              <Palette size={17} color={accent} />
              <Text style={styles.sectionTitle}>Акцент темы</Text>
            </View>
            <View style={styles.themeRow}>
              {(Object.keys(ACCENT_THEMES) as AccentThemeId[]).map((id) => {
                const t = ACCENT_THEMES[id];
                const active = settings.accentTheme === id;
                return (
                  <Pressable
                    key={id}
                    style={[
                      styles.themeChip,
                      active && { borderColor: t.accent, backgroundColor: t.soft },
                    ]}
                    onPress={() => {
                      hapticTap();
                      void settings.update({ accentTheme: id });
                    }}>
                    <View style={[styles.themeDot, { backgroundColor: t.accent }]} />
                    <Text style={[styles.themeName, active && { color: SakuraColors.ink }]}>
                      {t.name}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </GlassCard>

          {/* 5. Профиль Сакуры (Сервер) */}
          <GlassCard style={styles.card}>
            <View style={styles.titleRow}>
              <UserCheck size={17} color={SakuraColors.pinkLight} />
              <Text style={styles.sectionTitle}>Характер и обращение (сервер)</Text>
            </View>

            <View style={styles.speedRow}>
              <Text style={styles.toggleLabel}>Обращение</Text>
              <View style={styles.chipsRow}>
                {['ты', 'вы'].map((addr) => {
                  const active = (profile?.address_as || 'ты') === addr;
                  return (
                    <Pressable
                      key={addr}
                      style={[
                        styles.chip,
                        active && { backgroundColor: accent + '26', borderColor: accent },
                      ]}
                      onPress={() => {
                        hapticTap();
                        void updateProfile({ address_as: addr });
                      }}>
                      <Text style={[styles.chipText, active && { color: accent }]}>{addr}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            <View style={styles.fpRow}>
              <Text style={styles.fpLabel}>Голос TTS:</Text>
              <Text style={styles.fpValue}>{profile?.voice || 'Leda'}</Text>
            </View>
            <View style={styles.fpRow}>
              <Text style={styles.fpLabel}>Тон:</Text>
              <Text style={styles.fpValue}>{profile?.tone || 'calm'}</Text>
            </View>
            <View style={styles.fpRow}>
              <Text style={styles.fpLabel}>Тихие часы:</Text>
              <Text style={styles.fpValue}>{profile?.quiet_hours || 'Не заданы'}</Text>
            </View>
          </GlassCard>

          {/* 6. Защищённый канал Noise (securechannel/1) */}
          <GlassCard style={styles.card} accent={isPaired ? 'cyan' : 'pink'}>
            <View style={styles.headerRow}>
              <View style={styles.titleRow}>
                <Lock size={16} color={isPaired ? SakuraColors.online : accent} />
                <Text style={styles.sectionTitle}>Защищённый канал</Text>
              </View>
              <View style={[styles.statusBadge, { borderColor: statusColor + '66' }]}>
                <View style={[styles.statusDot, { backgroundColor: statusColor }]} />
                <Text style={[styles.statusText, { color: statusColor }]}>{statusText}</Text>
              </View>
            </View>

            {isPaired ? (
              <View style={styles.pairedBox}>
                <View style={styles.fpRow}>
                  <Text style={styles.fpLabel}>Устройство:</Text>
                  <Text style={styles.fpValue}>{deviceId}</Text>
                </View>
                {deviceFp ? (
                  <View style={styles.fpRow}>
                    <Text style={styles.fpLabel}>Ключ телефона:</Text>
                    <Text style={styles.fpMono}>{deviceFp}</Text>
                  </View>
                ) : null}
                {serverFp ? (
                  <View style={styles.fpRow}>
                    <Text style={styles.fpLabel}>Ключ сервера:</Text>
                    <Text style={styles.fpMono}>{serverFp}</Text>
                  </View>
                ) : null}
                {linkInfo.master === false && (
                  <View style={styles.warnBox}>
                    <ShieldAlert size={14} color={SakuraColors.warn} />
                    <Text style={styles.warnText}>
                      Устройство «{deviceId}» не в MASTER_DEVICES на сервере.
                    </Text>
                  </View>
                )}
              </View>
            ) : (
              <Text style={styles.hintText}>
                Отправь <Text style={{ color: accent, fontWeight: '700' }}>/pair</Text> Сакуре в
                Telegram и вставь сюда 8 слов или ссылку <Text style={{ color: accent }}>sakura-pair://1…</Text>
              </Text>
            )}

            <View style={styles.pairLabelRow}>
              <Text style={styles.fieldLabel}>
                {isPaired ? 'Переспарить устройство' : '8 слов или QR-ссылка'}
              </Text>
              {!pairInput.trim().toLowerCase().startsWith('sakura-pair://') &&
                pairInput.trim().length > 0 && (
                  <Text
                    style={[
                      styles.wordCounter,
                      wordCount === 8 && { color: SakuraColors.online },
                    ]}>
                    {wordCount}/8 слов
                  </Text>
                )}
            </View>

            <TextInput
              style={styles.inputMultiline}
              placeholder="8 слов из Telegram или sakura-pair://1?..."
              placeholderTextColor={SakuraColors.textMuted}
              value={pairInput}
              onChangeText={setPairInput}
              multiline
              autoCapitalize="none"
              autoCorrect={false}
            />

            {pairError || connError ? (
              <Text style={styles.errorText}>{pairError || connError}</Text>
            ) : null}
            {pairSuccess ? (
              <View style={styles.successRow}>
                <CheckCircle2 size={14} color={SakuraColors.online} />
                <Text style={styles.successText}>{pairSuccess}</Text>
              </View>
            ) : null}

            <View style={styles.buttonRow}>
              <Pressable
                style={({ pressed }) => [
                  styles.primaryButton,
                  { backgroundColor: accent, shadowColor: accent },
                  isPairing && { opacity: 0.7 },
                  pressed && styles.pressed,
                ]}
                onPress={handlePair}
                disabled={isPairing}>
                {isPairing ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <>
                    <KeyRound size={15} color="#fff" />
                    <Text style={styles.primaryButtonText}>
                      {isPaired ? 'Обновить пару' : 'Спарить (Noise)'}
                    </Text>
                  </>
                )}
              </Pressable>

              {isPaired && (
                <Pressable
                  style={({ pressed }) => [styles.iconBtnDanger, pressed && styles.pressed]}
                  onPress={handleResetPairing}>
                  <Trash2 size={16} color={SakuraColors.error} />
                </Pressable>
              )}
            </View>
          </GlassCard>

          {/* 7. Сервер */}
          <GlassCard style={styles.card}>
            <View style={styles.titleRow}>
              <Link2 size={16} color={SakuraColors.cyan} />
              <Text style={styles.sectionTitle}>Адрес сервера (VPS)</Text>
            </View>
            <TextInput
              style={styles.input}
              placeholder="wss://sub.kizune-ryoiki.ru/ws-..."
              placeholderTextColor={SakuraColors.textMuted}
              value={inputUrl}
              onChangeText={setUrlOverride}
              autoCapitalize="none"
              autoCorrect={false}
            />
            <View style={styles.buttonRow}>
              <Pressable
                style={({ pressed }) => [styles.secondaryActionBtn, pressed && styles.pressed]}
                onPress={() => {
                  hapticTap();
                  void connect(inputUrl, inputToken);
                }}>
                <Text style={styles.secondaryActionText}>
                  {linkState === 'connected' ? 'Переподключить' : 'Подключиться'}
                </Text>
              </Pressable>
              {linkState === 'connected' && (
                <Pressable
                  style={({ pressed }) => [styles.secondaryButton, pressed && styles.pressed]}
                  onPress={disconnect}>
                  <Text style={styles.secondaryButtonText}>Отключить</Text>
                </Pressable>
              )}
            </View>

            <Pressable
              style={({ pressed }) => [styles.dangerButton, pressed && styles.pressed]}
              onPress={handleResetAll}>
              <Text style={styles.dangerButtonText}>Сбросить все настройки и ключи</Text>
            </Pressable>
          </GlassCard>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  keyboardView: {
    flex: 1,
  },
  scrollContent: {
    padding: 14,
    paddingBottom: 40,
    gap: 14,
  },
  screenTitle: {
    fontSize: 22,
    fontWeight: '800',
    color: SakuraColors.ink,
    paddingHorizontal: 4,
    marginBottom: 2,
  },
  card: {
    gap: 12,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 8,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  sectionTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    paddingVertical: 4,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.04)',
  },
  toggleMeta: {
    flex: 1,
    gap: 2,
  },
  toggleLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: SakuraColors.ink,
  },
  toggleSub: {
    fontSize: 11.5,
    color: SakuraColors.inkDim,
    lineHeight: 15,
  },
  speedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 6,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.04)',
  },
  chipsRow: {
    flexDirection: 'row',
    gap: 6,
  },
  chip: {
    paddingHorizontal: 11,
    paddingVertical: 5,
    borderRadius: 999,
    backgroundColor: SakuraColors.panel2,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  chipText: {
    fontSize: 12,
    fontWeight: '700',
    color: SakuraColors.inkDim,
  },
  themeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  themeChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 12,
    backgroundColor: SakuraColors.panel2,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  themeDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  themeName: {
    fontSize: 12.5,
    fontWeight: '600',
    color: SakuraColors.inkDim,
  },
  ymInfoText: {
    fontSize: 12,
    color: SakuraColors.online,
    fontWeight: '600',
  },
  ymCheckBtn: {
    backgroundColor: '#FFCC00',
    borderRadius: 12,
    paddingVertical: 10,
    alignItems: 'center',
  },
  ymCheckText: {
    color: '#14101c',
    fontSize: 13.5,
    fontWeight: '800',
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 9,
    paddingVertical: 3,
    borderRadius: 999,
    borderWidth: 1,
    gap: 6,
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '700',
  },
  hintText: {
    fontSize: 12.5,
    color: SakuraColors.inkDim,
    lineHeight: 18,
  },
  pairedBox: {
    backgroundColor: SakuraColors.panel2,
    borderRadius: 14,
    padding: 12,
    gap: 5,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  fpRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 2,
  },
  fpLabel: {
    fontSize: 12.5,
    color: SakuraColors.inkDim,
  },
  fpValue: {
    fontSize: 12.5,
    fontWeight: '600',
    color: SakuraColors.ink,
  },
  fpMono: {
    fontSize: 12,
    fontWeight: '600',
    color: SakuraColors.cyan,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  warnBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 4,
    padding: 8,
    borderRadius: 10,
    backgroundColor: SakuraColors.warnSoft,
  },
  warnText: {
    flex: 1,
    fontSize: 11.5,
    color: SakuraColors.warn,
  },
  pairLabelRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  wordCounter: {
    fontSize: 11.5,
    fontWeight: '600',
    color: SakuraColors.warn,
  },
  fieldLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: SakuraColors.inkDim,
  },
  input: {
    backgroundColor: SakuraColors.panel2,
    color: SakuraColors.ink,
    borderRadius: 12,
    paddingHorizontal: 13,
    paddingVertical: 10,
    fontSize: 13.5,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  inputMultiline: {
    backgroundColor: SakuraColors.bgInput,
    color: '#FFFFFF',
    borderRadius: 14,
    paddingHorizontal: 13,
    paddingVertical: 11,
    fontSize: 13.5,
    minHeight: 58,
    textAlignVertical: 'top',
    borderWidth: 1.2,
    borderColor: SakuraColors.lineStrong,
  },
  errorText: {
    fontSize: 12,
    color: SakuraColors.error,
    fontWeight: '500',
  },
  successRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  successText: {
    fontSize: 12,
    color: SakuraColors.online,
    fontWeight: '600',
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 8,
  },
  primaryButton: {
    flex: 1,
    flexDirection: 'row',
    gap: 8,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: 'center',
    justifyContent: 'center',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.4,
    shadowRadius: 8,
    elevation: 4,
  },
  primaryButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '700',
  },
  iconBtnDanger: {
    width: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: SakuraColors.errorSoft,
    borderWidth: 1,
    borderColor: 'rgba(255, 92, 124, 0.35)',
  },
  secondaryActionBtn: {
    flex: 1,
    backgroundColor: SakuraColors.panel2,
    borderRadius: 12,
    paddingVertical: 11,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: SakuraColors.borderFocus,
  },
  secondaryActionText: {
    color: SakuraColors.cyan,
    fontSize: 13.5,
    fontWeight: '700',
  },
  secondaryButton: {
    backgroundColor: SakuraColors.panel2,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 11,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  secondaryButtonText: {
    color: SakuraColors.inkDim,
    fontSize: 13.5,
    fontWeight: '600',
  },
  dangerButton: {
    marginTop: 4,
    paddingVertical: 10,
    alignItems: 'center',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(255, 92, 124, 0.3)',
    backgroundColor: SakuraColors.errorSoft,
  },
  dangerButtonText: {
    color: SakuraColors.error,
    fontSize: 13,
    fontWeight: '600',
  },
  pressed: {
    opacity: 0.8,
  },
});

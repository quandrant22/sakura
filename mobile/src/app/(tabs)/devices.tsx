/**
 * Devices Screen — мультидевайс-сеть Сакуры и телеметрия устройств.
 */

import {
  Battery,
  BatteryCharging,
  Cpu,
  Headphones,
  Laptop,
  Monitor,
  MonitorSmartphone,
  RefreshCw,
  Smartphone,
  Star,
  Tablet,
  Wifi,
} from 'lucide-react-native';
import React, { useEffect } from 'react';
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Device } from '../../api/types';
import { GlassCard } from '../../components/ui/GlassCard';
import { SakuraColors } from '../../constants/colors';
import { useDevicesStore } from '../../stores/useDevicesStore';

export default function DevicesScreen() {
  const { devices, isLoading, bindEvents, fetchDevices } = useDevicesStore();

  useEffect(() => {
    bindEvents();
    fetchDevices();
  }, [bindEvents, fetchDevices]);

  const renderIcon = (kind: string, id: string, active: boolean) => {
    const color = active ? SakuraColors.accent : SakuraColors.inkDim;
    if (id === 'phone' || kind === 'phone') return <Smartphone size={22} color={color} />;
    if (kind === 'tablet') return <Tablet size={22} color={color} />;
    if (kind === 'headphones') return <Headphones size={22} color={color} />;
    if (id === 'laptop') return <Laptop size={22} color={color} />;
    return <Monitor size={22} color={color} />;
  };

  const renderDeviceCard = ({ item }: { item: Device }) => {
    const isOnline = item.online;
    const hasFocus = item.focus;

    return (
      <GlassCard
        style={styles.card}
        accent={hasFocus ? 'pink' : isOnline ? 'cyan' : 'none'}>
        <View style={styles.cardHeader}>
          <View style={styles.deviceTitleRow}>
            <View style={[styles.iconBox, isOnline && styles.iconBoxOnline]}>
              {renderIcon(item.kind, item.id, hasFocus || isOnline)}
            </View>
            <View>
              <Text style={styles.deviceName}>{item.name || item.id}</Text>
              <Text style={styles.deviceId}>id: {item.id}</Text>
            </View>
          </View>

          <View style={styles.badgesCol}>
            {hasFocus && (
              <View style={styles.focusBadge}>
                <Star size={10} color={SakuraColors.accent} fill={SakuraColors.accent} />
                <Text style={styles.focusBadgeText}>Фокус</Text>
              </View>
            )}
            <View
              style={[
                styles.statusBadge,
                { borderColor: isOnline ? SakuraColors.online + '66' : SakuraColors.line },
              ]}>
              <View
                style={[
                  styles.statusDot,
                  { backgroundColor: isOnline ? SakuraColors.online : SakuraColors.offline },
                ]}
              />
              <Text
                style={[
                  styles.statusText,
                  { color: isOnline ? SakuraColors.online : SakuraColors.inkDim },
                ]}>
                {isOnline ? 'Онлайн' : 'Оффлайн'}
              </Text>
            </View>
          </View>
        </View>

        {item.stats && (
          <View style={styles.statsRow}>
            {item.stats.battery !== null && item.stats.battery !== undefined && (
              <View style={styles.statChip}>
                {item.stats.charging ? (
                  <BatteryCharging size={13} color={SakuraColors.online} />
                ) : (
                  <Battery size={13} color={SakuraColors.inkDim} />
                )}
                <Text style={styles.statItem}>{item.stats.battery}%</Text>
              </View>
            )}
            {item.stats.wifi ? (
              <View style={styles.statChip}>
                <Wifi size={12} color={SakuraColors.cyan} />
                <Text style={styles.statItem}>{item.stats.wifi}</Text>
              </View>
            ) : null}
            {item.stats.cpu !== null && item.stats.cpu !== undefined && (
              <View style={styles.statChip}>
                <Cpu size={12} color={SakuraColors.inkDim} />
                <Text style={styles.statItem}>CPU {item.stats.cpu}%</Text>
              </View>
            )}
            {item.stats.ram !== null && item.stats.ram !== undefined && (
              <Text style={styles.statItem}>RAM {item.stats.ram}%</Text>
            )}
            {item.stats.gpu !== null && item.stats.gpu !== undefined && (
              <Text style={styles.statItem}>
                GPU {item.stats.gpu}%
                {item.stats.gpu_temp != null ? ` · ${Math.round(item.stats.gpu_temp)}°C` : ''}
              </Text>
            )}
          </View>
        )}
      </GlassCard>
    );
  };

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <View style={styles.container}>
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <MonitorSmartphone size={22} color={SakuraColors.accent} />
            <Text style={styles.title}>Устройства</Text>
          </View>
          <Pressable
            style={({ pressed }) => [styles.refreshButton, pressed && { opacity: 0.7 }]}
            onPress={fetchDevices}>
            <RefreshCw size={18} color={SakuraColors.inkDim} />
          </Pressable>
        </View>

        <FlatList
          data={devices}
          keyExtractor={(item) => item.id}
          renderItem={renderDeviceCard}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={isLoading}
              onRefresh={fetchDevices}
              tintColor={SakuraColors.accent}
            />
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyText}>Нет данных об устройствах (подключите связь)</Text>
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
    padding: 14,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  deviceTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  iconBox: {
    width: 42,
    height: 42,
    borderRadius: 14,
    backgroundColor: SakuraColors.panel2,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconBoxOnline: {
    borderColor: SakuraColors.borderAccent,
    backgroundColor: SakuraColors.accentSoft,
  },
  deviceName: {
    fontSize: 15.5,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  deviceId: {
    fontSize: 11.5,
    color: SakuraColors.inkDim,
  },
  badgesCol: {
    alignItems: 'flex-end',
    gap: 5,
  },
  focusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: SakuraColors.accentSoft,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
  },
  focusBadgeText: {
    color: SakuraColors.accent,
    fontSize: 10.5,
    fontWeight: '700',
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
    borderWidth: 1,
    gap: 5,
  },
  statusDot: {
    width: 5,
    height: 5,
    borderRadius: 2.5,
  },
  statusText: {
    fontSize: 10.5,
    fontWeight: '600',
  },
  statsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
    marginTop: 12,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: SakuraColors.line,
  },
  statChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  statItem: {
    color: SakuraColors.inkDim,
    fontSize: 12,
    fontWeight: '500',
  },
  empty: {
    paddingVertical: 48,
    alignItems: 'center',
  },
  emptyText: {
    color: SakuraColors.inkDim,
    fontSize: 13.5,
    textAlign: 'center',
  },
});

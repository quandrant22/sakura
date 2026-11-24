/**
 * Mobile device telemetry collection (Battery, Network, Platform).
 */

import * as Battery from 'expo-battery';
import * as Network from 'expo-network';
import { Platform } from 'react-native';
import { SystemTelemetry } from '../api/types';
import { usePhoneSettingsStore } from '../stores/usePhoneSettingsStore';

export async function getDeviceTelemetry(): Promise<SystemTelemetry> {
  const telemetry: SystemTelemetry = {
    os: `${Platform.OS} ${Platform.Version}`,
  };

  if (!usePhoneSettingsStore.getState().telemetryEnabled) {
    return telemetry;
  }

  try {
    const batteryLevel = await Battery.getBatteryLevelAsync();
    if (batteryLevel >= 0) {
      telemetry.battery = Math.round(batteryLevel * 100);
    }
    const batteryState = await Battery.getBatteryStateAsync();
    telemetry.charging =
      batteryState === Battery.BatteryState.CHARGING || batteryState === Battery.BatteryState.FULL;
  } catch {
    // Battery API might be restricted in web/simulators
  }

  try {
    const networkState = await Network.getNetworkStateAsync();
    if (networkState.type === Network.NetworkStateType.WIFI) {
      telemetry.wifi = 'Wi-Fi';
    } else if (networkState.type === Network.NetworkStateType.CELLULAR) {
      telemetry.wifi = 'Cellular';
    } else {
      telemetry.wifi = networkState.isConnected ? 'Online' : 'Offline';
    }
  } catch {
    // Network API fallback
  }

  return telemetry;
}

/**
 * Devices Store — manages multi-device state and presence in the Sakura mesh.
 */

import { create } from 'zustand';
import { sakuraClient } from '../api/client';
import { Device } from '../api/types';

interface DevicesState {
  devices: Device[];
  isLoading: boolean;
  bound: boolean;

  bindEvents: () => void;
  fetchDevices: () => Promise<void>;
  updateDevice: (device: Device) => void;
}

export const useDevicesStore = create<DevicesState>((set, get) => ({
  devices: [],
  isLoading: false,
  bound: false,

  bindEvents: () => {
    if (get().bound) return;

    sakuraClient.on<any>('device_update', (payload) => {
      if (payload?.device) {
        get().updateDevice(payload.device);
      }
    });

    sakuraClient.on<any>('devices', (payload) => {
      if (Array.isArray(payload?.devices)) {
        set({ devices: payload.devices });
      }
    });

    sakuraClient.onLinkState((state) => {
      if (state === 'connected') {
        get().fetchDevices();
      }
    });

    set({ bound: true });
  },

  fetchDevices: async () => {
    set({ isLoading: true });
    try {
      const list = await sakuraClient.getDevices();
      set({ devices: list, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  updateDevice: (updated: Device) => {
    set((state) => {
      const idx = state.devices.findIndex((d) => d.id === updated.id);
      if (idx >= 0) {
        const next = [...state.devices];
        next[idx] = { ...next[idx], ...updated };
        return { devices: next };
      }
      return { devices: [...state.devices, updated] };
    });
  },
}));

/**
 * Resilient key-value storage wrapper over AsyncStorage with in-memory fallback.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';

const memoryFallback = new Map<string, string>();

export const safeStorage = {
  async getItem(key: string): Promise<string | null> {
    try {
      const val = await AsyncStorage.getItem(key);
      if (val !== null) memoryFallback.set(key, val);
      return val;
    } catch {
      return memoryFallback.get(key) ?? null;
    }
  },

  async setItem(key: string, value: string): Promise<void> {
    memoryFallback.set(key, value);
    try {
      await AsyncStorage.setItem(key, value);
    } catch (e) {
      console.warn('[safeStorage] setItem fallback:', e);
    }
  },

  async removeItem(key: string): Promise<void> {
    memoryFallback.delete(key);
    try {
      await AsyncStorage.removeItem(key);
    } catch (e) {
      console.warn('[safeStorage] removeItem fallback:', e);
    }
  },
};

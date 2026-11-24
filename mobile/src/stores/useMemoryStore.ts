/**
 * Memory Store — long-term memory, knowledge items, category filters and search.
 */

import { create } from 'zustand';
import { sakuraClient } from '../api/client';
import { MemoryItem } from '../api/types';

interface MemoryState {
  items: MemoryItem[];
  total: number;
  category: string;
  searchQuery: string;
  isLoading: boolean;

  fetchMemories: (category?: string) => Promise<void>;
  search: (query: string) => Promise<void>;
  updateItem: (id: string, text: string) => Promise<void>;
  deleteItem: (id: string) => Promise<void>;
  setCategory: (category: string) => void;
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  items: [],
  total: 0,
  category: '',
  searchQuery: '',
  isLoading: false,

  fetchMemories: async (category?: string) => {
    set({ isLoading: true, category: category || '' });
    try {
      const res = await sakuraClient.getMemories(category);
      set({ items: res.items, total: res.total, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  search: async (query: string) => {
    const q = query.trim();
    set({ searchQuery: q, isLoading: true });
    if (!q) {
      await get().fetchMemories(get().category);
      return;
    }

    try {
      const results = await sakuraClient.searchMemories(q);
      set({ items: results, total: results.length, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  updateItem: async (id: string, text: string) => {
    try {
      const updated = await sakuraClient.updateMemory(id, text);
      set((state) => ({
        items: state.items.map((item) => (item.id === id ? { ...item, text: updated.text } : item)),
      }));
    } catch (e) {
      console.warn('[useMemoryStore] Failed to update memory:', e);
    }
  },

  deleteItem: async (id: string) => {
    try {
      await sakuraClient.deleteMemory(id);
      set((state) => ({
        items: state.items.filter((item) => item.id !== id),
        total: Math.max(0, state.total - 1),
      }));
    } catch (e) {
      console.warn('[useMemoryStore] Failed to delete memory:', e);
    }
  },

  setCategory: (category: string) => {
    get().fetchMemories(category);
  },
}));

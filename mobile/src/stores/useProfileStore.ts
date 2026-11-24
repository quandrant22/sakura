/**
 * Profile Store — Sakura personal profile, naming and quiet hours.
 */

import { create } from 'zustand';
import { sakuraClient } from '../api/client';
import { Profile } from '../api/types';

interface ProfileState {
  profile: Profile | null;
  isLoading: boolean;

  fetchProfile: () => Promise<void>;
  updateProfile: (patch: Partial<Profile>) => Promise<void>;
}

export const useProfileStore = create<ProfileState>((set) => ({
  profile: null,
  isLoading: false,

  fetchProfile: async () => {
    set({ isLoading: true });
    try {
      const profile = await sakuraClient.getProfile();
      set({ profile, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  updateProfile: async (patch: Partial<Profile>) => {
    set({ isLoading: true });
    try {
      const updated = await sakuraClient.setProfile(patch);
      set({ profile: updated, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },
}));

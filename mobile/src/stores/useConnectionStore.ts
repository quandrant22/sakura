/**
 * Connection Store — управляет подключением WSS, ключами защищённого канала Noise (securechannel/1)
 * и сохранением состояния в AsyncStorage.
 */

import { create } from 'zustand';
import { sakuraClient } from '../api/client';
import { LinkInfo, LinkState } from '../api/types';
import { safeStorage } from '../services/storage';
import { getDeviceTelemetry } from '../services/telemetry';

const KEY_URL = 'sakura_server_url';
const KEY_TOKEN = 'sakura_ws_token';
const KEY_DEVICE_ID = 'sakura_device_id';
const KEY_DEVICE_PRIV = 'sakura_device_priv_b64';
const KEY_DEVICE_FP = 'sakura_device_fp';
const KEY_SERVER_PUB = 'sakura_server_pub_b64';
const KEY_SERVER_FP = 'sakura_server_fp';

export const DEFAULT_SERVER_URL = 'wss://sub.kizune-ryoiki.ru/ws-f35dd3bb670e9cc3';
export const DEFAULT_WS_TOKEN = 'ae89231d100bd2adf5981a079e2c7de8e5ae7c35dbfc58347ad30c97df69fe20';

async function setMany(entries: [string, string][]): Promise<void> {
  await Promise.all(entries.map(([k, v]) => safeStorage.setItem(k, v)));
}

async function removeMany(keys: string[]): Promise<void> {
  await Promise.all(keys.map((k) => safeStorage.removeItem(k)));
}

interface ConnectionState {
  linkState: LinkState;
  linkInfo: LinkInfo;
  serverUrl: string;
  token: string;
  deviceId: string;
  devicePrivB64: string | null;
  deviceFp: string | null;
  serverPubB64: string | null;
  serverFp: string | null;
  isPaired: boolean;
  isPairing: boolean;
  isInitialized: boolean;
  error: string | null;

  init: () => Promise<void>;
  connect: (url: string, token: string) => Promise<void>;
  pairDevice: (uriOrWords: string, urlOverride?: string, deviceName?: string) => Promise<void>;
  disconnect: () => void;
  resetPairing: () => Promise<void>;
  reset: () => Promise<void>;
}

sakuraClient.setTelemetryProvider(getDeviceTelemetry);

let initInFlight: Promise<void> | null = null;

export const useConnectionStore = create<ConnectionState>((set, get) => {
  sakuraClient.onLinkState((linkState, linkInfo) => {
    set({ linkState, linkInfo });
  });

  sakuraClient.onServerKeyRotated(async (newPubB64, newFp) => {
    set({ serverPubB64: newPubB64, serverFp: newFp });
    await setMany([
      [KEY_SERVER_PUB, newPubB64],
      [KEY_SERVER_FP, newFp],
    ]);
  });

  return {
    linkState: 'disconnected',
    linkInfo: sakuraClient.getLinkInfo(),
    serverUrl: DEFAULT_SERVER_URL,
    token: DEFAULT_WS_TOKEN,
    deviceId: 'phone',
    devicePrivB64: null,
    deviceFp: null,
    serverPubB64: null,
    serverFp: null,
    isPaired: false,
    isPairing: false,
    isInitialized: false,
    error: null,

    init: async () => {
      if (get().isInitialized) return;
      if (initInFlight) return initInFlight;
      initInFlight = (async () => {
        try {
          const [savedUrl, savedToken, savedId, savedPriv, savedDevFp, savedSrvPub, savedSrvFp] =
            await Promise.all([
              safeStorage.getItem(KEY_URL),
              safeStorage.getItem(KEY_TOKEN),
              safeStorage.getItem(KEY_DEVICE_ID),
              safeStorage.getItem(KEY_DEVICE_PRIV),
              safeStorage.getItem(KEY_DEVICE_FP),
              safeStorage.getItem(KEY_SERVER_PUB),
              safeStorage.getItem(KEY_SERVER_FP),
            ]);

          const serverUrl = savedUrl || DEFAULT_SERVER_URL;
          const token = savedToken || DEFAULT_WS_TOKEN;
          const deviceId = savedId || 'phone';
          const devicePrivB64 = savedPriv || null;
          const deviceFp = savedDevFp || null;
          const serverPubB64 = savedSrvPub || null;
          const serverFp = savedSrvFp || null;
          const isPaired = Boolean(devicePrivB64 && serverPubB64);

          set({
            serverUrl,
            token,
            deviceId,
            devicePrivB64,
            deviceFp,
            serverPubB64,
            serverFp,
            isPaired,
            isInitialized: true,
          });

          sakuraClient.connect({
            url: serverUrl,
            token,
            deviceId,
            devicePrivB64,
            serverPubB64,
          });
        } catch (e: any) {
          set({ isInitialized: true, error: e?.message || 'Ошибка чтения хранилища' });
        } finally {
          initInFlight = null;
        }
      })();
      return initInFlight;
    },

    connect: async (url: string, token: string) => {
      const cleanUrl = url.trim();
      const cleanToken = token.trim();
      set({ serverUrl: cleanUrl, token: cleanToken, error: null });

      await setMany([
        [KEY_URL, cleanUrl],
        [KEY_TOKEN, cleanToken],
      ]);

      const { deviceId, devicePrivB64, serverPubB64 } = get();
      sakuraClient.connect({
        url: cleanUrl,
        token: cleanToken,
        deviceId,
        devicePrivB64,
        serverPubB64,
      });
    },

    pairDevice: async (uriOrWords: string, urlOverride?: string, deviceName?: string) => {
      set({ isPairing: true, error: null });
      try {
        const currentUrl = (urlOverride || get().serverUrl || DEFAULT_SERVER_URL).trim();
        const res = await sakuraClient.pair({
          fallbackUrl: currentUrl,
          uriOrWords,
          existingDevicePrivB64: get().devicePrivB64,
          deviceIdHint: 'phone',
          deviceName: deviceName || 'Телефон',
        });

        await setMany([
          [KEY_URL, res.url],
          [KEY_DEVICE_ID, res.deviceId],
          [KEY_DEVICE_PRIV, res.devicePrivB64],
          [KEY_DEVICE_FP, res.deviceFp],
          [KEY_SERVER_PUB, res.serverPubB64],
          [KEY_SERVER_FP, res.serverFp],
        ]);

        set({
          serverUrl: res.url,
          deviceId: res.deviceId,
          devicePrivB64: res.devicePrivB64,
          deviceFp: res.deviceFp,
          serverPubB64: res.serverPubB64,
          serverFp: res.serverFp,
          isPaired: true,
          isPairing: false,
          error: null,
        });

        sakuraClient.connect({
          url: res.url,
          token: get().token,
          deviceId: res.deviceId,
          devicePrivB64: res.devicePrivB64,
          serverPubB64: res.serverPubB64,
        });
      } catch (e: any) {
        set({ isPairing: false, error: e?.message || 'Не удалось выполнить спаривание' });
        throw e;
      }
    },

    disconnect: () => {
      sakuraClient.disconnect();
    },

    resetPairing: async () => {
      sakuraClient.disconnect();
      await removeMany([
        KEY_DEVICE_ID,
        KEY_DEVICE_PRIV,
        KEY_DEVICE_FP,
        KEY_SERVER_PUB,
        KEY_SERVER_FP,
      ]);
      set({
        deviceId: 'phone',
        devicePrivB64: null,
        deviceFp: null,
        serverPubB64: null,
        serverFp: null,
        isPaired: false,
        error: null,
      });
    },

    reset: async () => {
      sakuraClient.disconnect();
      await removeMany([
        KEY_URL,
        KEY_TOKEN,
        KEY_DEVICE_ID,
        KEY_DEVICE_PRIV,
        KEY_DEVICE_FP,
        KEY_SERVER_PUB,
        KEY_SERVER_FP,
      ]);
      set({
        serverUrl: DEFAULT_SERVER_URL,
        token: DEFAULT_WS_TOKEN,
        deviceId: 'phone',
        devicePrivB64: null,
        deviceFp: null,
        serverPubB64: null,
        serverFp: null,
        isPaired: false,
        linkState: 'disconnected',
        error: null,
      });
    },
  };
});

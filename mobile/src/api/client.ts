/**
 * Sakura WebSocket Protocol v2 Client for Mobile.
 * Поддерживает как защищённый канал securechannel/1 (Noise IK + XXpsk3),
 * так и fallback на token WebSocket (если на сервере SECURE_CHANNEL=off).
 */

import { CLOSE_TEXT, connectNoiseIK, NoiseSocket, SecureError, xxPair } from './secure/client';
import { generateKeypair, publicFromPrivate } from './secure/noise';
import { b64u, fingerprint, parseQrUri, unb64u, wordsToPsk } from './secure/pairing';
import {
  Device,
  LinkInfo,
  LinkState,
  MemoryItem,
  Message,
  Profile,
  SakuraApiError,
  SakuraStatus,
  Scenario,
  SystemTelemetry,
  WidgetsData,
} from './types';

export const REQUEST_TIMEOUT_MS = 10_000;
export const HEARTBEAT_INTERVAL_MS = 30_000;
export const INITIAL_RECONNECT_DELAY_MS = 1_500;
export const MAX_RECONNECT_DELAY_MS = 15_000;

interface PendingRequest {
  resolve: (value: any) => void;
  reject: (reason: any) => void;
  timer: ReturnType<typeof setTimeout>;
}

type PushListener = (data: any) => void;
type LinkListener = (state: LinkState, info: LinkInfo) => void;

export interface ConnectConfig {
  url: string;
  token?: string;
  deviceId: string;
  devicePrivB64?: string | null;
  serverPubB64?: string | null;
}

export class SakuraClient {
  private ws: WebSocket | null = null;
  private noiseWs: NoiseSocket | null = null;
  private config: ConnectConfig = { url: '', token: '', deviceId: 'phone' };
  private seq = 0;
  private pendingRequests = new Map<string, PendingRequest>();
  private pushListeners = new Map<string, Set<PushListener>>();
  private linkListeners = new Set<LinkListener>();
  private serverKeyListeners = new Set<(newPubB64: string, newFp: string) => void>();
  private linkInfo: LinkInfo = {
    state: 'disconnected',
    secure: false,
    transport: null,
    reason: null,
    master: null,
  };
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectDelay = INITIAL_RECONNECT_DELAY_MS;
  private intentionalClose = false;
  private telemetryProvider: (() => Promise<SystemTelemetry>) | null = null;
  private connectGen = 0;

  public getStatus(): LinkState {
    return this.linkInfo.state;
  }

  public getLinkInfo(): LinkInfo {
    return this.linkInfo;
  }

  public setTelemetryProvider(provider: () => Promise<SystemTelemetry>): void {
    this.telemetryProvider = provider;
  }

  public onLinkState(listener: LinkListener): () => void {
    this.linkListeners.add(listener);
    listener(this.linkInfo.state, this.linkInfo);
    return () => this.linkListeners.delete(listener);
  }

  public onServerKeyRotated(listener: (newPubB64: string, newFp: string) => void): () => void {
    this.serverKeyListeners.add(listener);
    return () => this.serverKeyListeners.delete(listener);
  }

  public on<T = any>(type: string, listener: (data: T) => void): () => void {
    if (!this.pushListeners.has(type)) {
      this.pushListeners.set(type, new Set());
    }
    const set = this.pushListeners.get(type)!;
    set.add(listener as PushListener);
    return () => set.delete(listener as PushListener);
  }

  private setLinkInfo(patch: Partial<LinkInfo>): void {
    this.linkInfo = { ...this.linkInfo, ...patch };
    for (const listener of this.linkListeners) {
      try {
        listener(this.linkInfo.state, this.linkInfo);
      } catch (e) {
        console.warn('[SakuraClient] Link listener error:', e);
      }
    }
  }

  public connect(cfg: ConnectConfig): void {
    this.disconnectSilent();
    this.config = {
      ...cfg,
      url: cfg.url.trim(),
      token: (cfg.token || '').trim(),
      deviceId: cfg.deviceId.trim() || 'phone',
    };
    this.intentionalClose = false;
    this.reconnectDelay = INITIAL_RECONNECT_DELAY_MS;

    if (!this.config.url) {
      this.setLinkInfo({ state: 'disconnected', transport: null, secure: false, reason: 'Укажите адрес сервера' });
      return;
    }

    const hasKeys = Boolean(this.config.devicePrivB64 && this.config.serverPubB64);
    if (!hasKeys && !this.config.token) {
      this.setLinkInfo({
        state: 'pairing_required',
        transport: null,
        secure: false,
        reason: 'Выполните спаривание (/pair в Telegram)',
      });
      return;
    }

    void this.doConnect();
  }

  private disconnectSilent(): void {
    this.connectGen += 1;
    this.stopTimers();
    this.rejectAllPending('client_closed', 'Соединение закрыто');
    if (this.noiseWs) {
      try {
        this.noiseWs.close(1000, 'reconnect');
      } catch {}
      this.noiseWs = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {}
      this.ws = null;
    }
  }

  public disconnect(): void {
    this.intentionalClose = true;
    this.disconnectSilent();
    this.setLinkInfo({ state: 'disconnected', transport: null, secure: false, reason: null });
  }

  private async doConnect(): Promise<void> {
    const gen = ++this.connectGen;
    this.stopTimers();
    const hasNoiseKeys = Boolean(this.config.devicePrivB64 && this.config.serverPubB64);

    this.setLinkInfo({
      state: 'connecting',
      transport: hasNoiseKeys ? 'noise' : 'ws',
      secure: hasNoiseKeys,
      reason: hasNoiseKeys ? 'Рукопожатие Noise IK…' : 'Подключение к серверу…',
    });

    if (hasNoiseKeys) {
      await this.connectNoise(gen);
    } else {
      this.connectPlainWs(gen);
    }
  }

  private async connectNoise(gen: number): Promise<void> {
    try {
      const devicePriv = unb64u(this.config.devicePrivB64!);
      const serverPub = unb64u(this.config.serverPubB64!);
      const sock = await connectNoiseIK({
        url: this.config.url,
        devicePriv,
        serverPub,
        deviceId: this.config.deviceId,
        handlers: {
          onJson: (msg) => {
            if (gen !== this.connectGen) return;
            this.handleIncomingObj(msg);
          },
          onServerKeyRotated: (newPub) => {
            const newB64 = b64u(newPub);
            const newFp = fingerprint(newPub);
            this.config.serverPubB64 = newB64;
            for (const cb of this.serverKeyListeners) {
              try {
                cb(newB64, newFp);
              } catch {}
            }
          },
          onClose: (code, reason) => {
            if (gen !== this.connectGen) return;
            this.noiseWs = null;
            this.stopHeartbeat();
            this.rejectAllPending('disconnected', reason || 'Соединение разорвано');

            if (code === 4408) {
              this.setLinkInfo({
                state: 'pairing_required',
                transport: null,
                secure: false,
                reason: CLOSE_TEXT[4408],
              });
              return;
            }
            if (code === 4000) {
              this.setLinkInfo({
                state: 'disconnected',
                transport: null,
                secure: false,
                reason: 'Открыта другая сессия (заменено)',
              });
              return;
            }
            if (!this.intentionalClose) {
              this.setLinkInfo({
                state: 'disconnected',
                reason: reason || `Отключено (${code})`,
              });
              this.scheduleReconnect();
            }
          },
        },
      });

      if (gen !== this.connectGen) {
        sock.close();
        return;
      }

      this.noiseWs = sock;
      this.reconnectDelay = INITIAL_RECONNECT_DELAY_MS;
      await this.sendRegister();
    } catch (err: any) {
      if (gen !== this.connectGen) return;
      const code = err instanceof SecureError ? err.code : undefined;
      const reason = err?.message || 'Ошибка защищённого канала';
      if (code === 4408 || code === 4412) {
        this.setLinkInfo({
          state: 'pairing_required',
          transport: null,
          secure: false,
          reason,
        });
        return;
      }
      this.setLinkInfo({ state: 'error', transport: null, secure: false, reason });
      this.scheduleReconnect();
    }
  }

  private connectPlainWs(gen: number): void {
    try {
      this.ws = new WebSocket(this.config.url);
    } catch (err: any) {
      this.setLinkInfo({
        state: 'error',
        transport: null,
        secure: false,
        reason: err?.message || 'Некорректный адрес WebSocket',
      });
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = async () => {
      if (gen !== this.connectGen) return;
      this.reconnectDelay = INITIAL_RECONNECT_DELAY_MS;
      await this.sendRegister();
    };

    this.ws.onmessage = (event: WebSocketMessageEvent) => {
      if (gen !== this.connectGen) return;
      if (typeof event.data !== 'string') return;
      try {
        this.handleIncomingObj(JSON.parse(event.data));
      } catch {}
    };

    this.ws.onerror = () => {
      if (gen !== this.connectGen) return;
      this.setLinkInfo({ state: 'error', reason: 'Ошибка сети при подключении' });
    };

    this.ws.onclose = (event) => {
      if (gen !== this.connectGen) return;
      this.ws = null;
      this.stopHeartbeat();
      this.rejectAllPending('disconnected', 'Соединение разорвано');

      if (event.code === 4412) {
        this.setLinkInfo({
          state: 'pairing_required',
          transport: null,
          secure: false,
          reason: 'Сервер требует защищённый канал — спарьте устройство (/pair)',
        });
        return;
      }

      if (event.code === 4401) {
        this.setLinkInfo({
          state: 'error',
          transport: null,
          secure: false,
          reason: 'Неверный токен доступа (4401)',
        });
        return;
      }

      if (event.code === 4000) {
        this.setLinkInfo({
          state: 'disconnected',
          transport: null,
          secure: false,
          reason: 'Открыта другая сессия (заменено)',
        });
        return;
      }

      if (!this.intentionalClose) {
        this.setLinkInfo({
          state: 'disconnected',
          reason: event.reason || `Соединение закрыто (${event.code})`,
        });
        this.scheduleReconnect();
      } else {
        this.setLinkInfo({ state: 'disconnected', reason: null });
      }
    };
  }

  private async sendRegister(): Promise<void> {
    let telemetry: SystemTelemetry = { os: 'mobile' };
    if (this.telemetryProvider) {
      try {
        telemetry = await this.telemetryProvider();
      } catch {}
    }

    const payload: Record<string, unknown> = {
      type: 'register',
      device_id: this.config.deviceId,
      proto: 2,
      system_info: telemetry,
      features: ['voice.playback', 'notifications'],
    };
    if (!this.noiseWs && this.config.token) {
      payload.token = this.config.token;
    }
    this.sendRaw(payload);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(async () => {
      if (this.linkInfo.state !== 'connected') return;
      let telemetry: SystemTelemetry = {};
      if (this.telemetryProvider) {
        try {
          telemetry = await this.telemetryProvider();
        } catch {}
      }

      const payload: Record<string, unknown> = {
        type: 'ping',
        device_id: this.config.deviceId,
        proto: 2,
        system_info: telemetry,
      };
      if (!this.noiseWs && this.config.token) {
        payload.token = this.config.token;
      }
      this.sendRaw(payload);
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private stopTimers(): void {
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.intentionalClose) return;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.intentionalClose && this.config.url) {
        void this.doConnect();
      }
    }, this.reconnectDelay);

    this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, MAX_RECONNECT_DELAY_MS);
  }

  private handleIncomingObj(msg: any): void {
    if (!msg || typeof msg !== 'object') return;

    if (msg.type === 'registered') {
      if (msg.proto >= 2) {
        const isNoise = Boolean(this.noiseWs);
        this.setLinkInfo({
          state: 'connected',
          transport: isNoise ? 'noise' : 'ws',
          secure: isNoise,
          master: Boolean(msg.master),
          reason: msg.master === false ? 'Нет прав master (проверьте MASTER_DEVICES)' : null,
        });
        this.startHeartbeat();
      } else {
        this.setLinkInfo({
          state: 'error',
          reason: 'Сервер устарел (proto < 2)',
        });
      }
      return;
    }

    if (msg.request_id && this.pendingRequests.has(msg.request_id)) {
      const pending = this.pendingRequests.get(msg.request_id)!;
      this.pendingRequests.delete(msg.request_id);
      clearTimeout(pending.timer);

      if (msg.type === 'error') {
        pending.reject(
          new SakuraApiError(msg.code || 'unknown_error', msg.message || 'Ошибка сервера', msg.request_id)
        );
      } else {
        pending.resolve(msg);
      }
      return;
    }

    const listeners = this.pushListeners.get(msg.type);
    if (listeners) {
      for (const listener of listeners) {
        try {
          listener(msg);
        } catch (e) {
          console.warn(`[SakuraClient] Listener error for ${msg.type}:`, e);
        }
      }
    }
    const allListeners = this.pushListeners.get('*');
    if (allListeners) {
      for (const listener of allListeners) {
        try {
          listener(msg);
        } catch {}
      }
    }
  }

  private sendRaw(obj: any): boolean {
    if (this.noiseWs) {
      return this.noiseWs.sendJson(obj);
    }
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    try {
      this.ws.send(JSON.stringify(obj));
      return true;
    } catch {
      return false;
    }
  }

  public call<T = any>(
    type: string,
    payload: Record<string, unknown> = {},
    timeoutMs = REQUEST_TIMEOUT_MS
  ): Promise<T> {
    if (this.linkInfo.state !== 'connected') {
      return Promise.reject(new SakuraApiError('offline', 'Нет активного подключения к Сакуре'));
    }

    const requestId = `req_${++this.seq}_${Date.now().toString(36)}`;
    const fullPayload: Record<string, unknown> = {
      type,
      request_id: requestId,
      device_id: this.config.deviceId,
      ...payload,
    };
    if (!this.noiseWs && this.config.token) {
      fullPayload.token = this.config.token;
    }

    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingRequests.delete(requestId);
        reject(new SakuraApiError('timeout', `Таймаут запроса ${type}`, requestId));
      }, timeoutMs);

      this.pendingRequests.set(requestId, { resolve, reject, timer });

      const ok = this.sendRaw(fullPayload);
      if (!ok) {
        this.pendingRequests.delete(requestId);
        clearTimeout(timer);
        reject(new SakuraApiError('send_failed', 'Не удалось отправить сообщение'));
      }
    });
  }

  private rejectAllPending(code: string, message: string): void {
    for (const [id, req] of this.pendingRequests.entries()) {
      clearTimeout(req.timer);
      req.reject(new SakuraApiError(code, message, id));
    }
    this.pendingRequests.clear();
  }

  // --- Спаривание XXpsk3 ---

  public async pair(params: {
    fallbackUrl: string;
    uriOrWords: string;
    existingDevicePrivB64?: string | null;
    deviceIdHint?: string;
    deviceName?: string;
  }): Promise<{
    url: string;
    deviceId: string;
    devicePrivB64: string;
    deviceFp: string;
    serverPubB64: string;
    serverFp: string;
  }> {
    const raw = params.uriOrWords.trim();
    let targetUrl = params.fallbackUrl.trim();
    let psk: Uint8Array;
    let expectedServerPub: Uint8Array | null = null;

    if (raw.toLowerCase().startsWith('sakura-pair://')) {
      const parsed = parseQrUri(raw);
      targetUrl = parsed.url || targetUrl;
      psk = wordsToPsk(parsed.words);
      expectedServerPub = parsed.serverPub;
    } else {
      psk = wordsToPsk(raw);
    }

    if (!targetUrl) {
      throw new SecureError('Не указан WebSocket URL сервера');
    }

    let devicePriv: Uint8Array;
    let devicePub: Uint8Array;
    if (params.existingDevicePrivB64) {
      devicePriv = unb64u(params.existingDevicePrivB64);
      devicePub = publicFromPrivate(devicePriv);
    } else {
      const kp = generateKeypair();
      devicePriv = kp.priv;
      devicePub = kp.pub;
    }

    const res = await xxPair({
      url: targetUrl,
      devicePriv,
      psk,
      deviceName: params.deviceName || 'Телефон',
      deviceIdHint: params.deviceIdHint || 'phone',
      expectedServerPub,
    });

    return {
      url: targetUrl,
      deviceId: res.deviceId,
      devicePrivB64: b64u(devicePriv),
      deviceFp: fingerprint(devicePub),
      serverPubB64: b64u(res.serverPub),
      serverFp: res.serverFp,
    };
  }

  // --- Convenience API Methods (Protocol v2) ---

  public async sendChatMessage(
    text: string,
    clientMsgId: string,
    speak = true
  ): Promise<{ id?: string | null; client_msg_id?: string | null }> {
    return this.call<{ id?: string | null; client_msg_id?: string | null }>('chat_send', {
      text,
      client_msg_id: clientMsgId,
      speak,
    });
  }

  public async sendVoiceCommand(
    text: string,
    channel: 'text' | 'voice' = 'text',
    speak = true
  ): Promise<void> {
    const payload: Record<string, unknown> = {
      type: 'voice_command',
      device_id: this.config.deviceId,
      text,
      channel,
      speak,
    };
    if (!this.noiseWs && this.config.token) {
      payload.token = this.config.token;
    }
    this.sendRaw(payload);
  }

  public async sendRemoteCommand(
    target: string,
    action: string,
    arg = '',
    confirmed = true
  ): Promise<{ ok: boolean; detail?: string }> {
    try {
      const res = await this.call<{ ok: boolean; detail?: string }>('remote_command', {
        target,
        action,
        arg,
        confirmed,
      });
      return res;
    } catch (e: any) {
      if (e instanceof SakuraApiError && e.code === 'unsupported') {
        // Fallback через голосовую/текстовую команду, если сервер не обновлён
        const phraseMap: Record<string, string> = {
          'system.shutdown': `выключи ${target === 'pc' ? 'игровой пк' : target}`,
          'system.restart': `перезагрузи ${target === 'pc' ? 'игровой пк' : target}`,
          'power.sleep': `усыпи ${target === 'pc' ? 'игровой пк' : target}`,
          'system.lock': `заблокируй ${target === 'pc' ? 'игровой пк' : target}`,
          'volume_up': 'сделай громче',
          'volume_down': 'сделай тише',
          'volume:0': 'выключи звук',
          'music:play_pause': 'пауза музыка',
          'music:next': 'следующий трек',
        };
        const text = phraseMap[action] || `${action} ${arg}`.trim();
        await this.sendVoiceCommand(text, 'text', false);
        return { ok: true, detail: `Отправлено: ${text}` };
      }
      throw e;
    }
  }

  public async getHistory(limit = 50, beforeTs?: number): Promise<Message[]> {
    const res = await this.call<{ messages: Message[] }>('history_request', {
      limit,
      ...(beforeTs ? { before_ts: beforeTs } : {}),
    });
    return res.messages || [];
  }

  public async deleteMessage(id: string): Promise<void> {
    await this.call('chat_delete', { id });
  }

  public async getDevices(): Promise<Device[]> {
    const res = await this.call<{ devices: Device[] }>('devices_request');
    return res.devices || [];
  }

  public async getStatusData(): Promise<SakuraStatus> {
    return this.call<SakuraStatus>('status_request');
  }

  public async getScenarios(): Promise<Scenario[]> {
    const res = await this.call<{ scenarios: Scenario[] }>('scenarios_list');
    return res.scenarios || [];
  }

  public async runScenario(id: string): Promise<{ run_id: string; id: string }> {
    return this.call<{ run_id: string; id: string }>('scenario_run', { id });
  }

  public async getMemories(
    category?: string,
    offset = 0,
    limit = 50
  ): Promise<{ items: MemoryItem[]; total: number }> {
    const res = await this.call<{ items: MemoryItem[]; total: number }>('memory_list', {
      category,
      offset,
      limit,
    });
    return { items: res.items || [], total: res.total || (res.items || []).length };
  }

  public async searchMemories(q: string, limit = 20): Promise<MemoryItem[]> {
    const res = await this.call<{ items: MemoryItem[] }>('memory_search', { q, limit });
    return res.items || [];
  }

  public async updateMemory(id: string, text: string): Promise<MemoryItem> {
    const res = await this.call<{ items: MemoryItem[] }>('memory_update', { id, text });
    return res.items[0];
  }

  public async deleteMemory(id: string): Promise<void> {
    await this.call('memory_delete', { id });
  }

  public async getProfile(): Promise<Profile> {
    const res = await this.call<{ profile: Profile }>('profile_get');
    return res.profile;
  }

  public async setProfile(patch: Partial<Profile>): Promise<Profile> {
    const res = await this.call<{ profile: Profile }>('profile_set', patch);
    return res.profile;
  }

  public async sendVoiceAudio(
    audioBase64: string,
    mimeType = 'audio/mp4',
    speak = true
  ): Promise<{ transcript: string; turn_id?: string }> {
    return this.call<{ transcript: string; turn_id?: string }>(
      'voice_audio',
      { audio: audioBase64, mime_type: mimeType, speak },
      25_000
    );
  }

  public async getWidgetsData(): Promise<WidgetsData> {
    return this.call<WidgetsData>('widgets_data');
  }
}

const globalObj = globalThis as { __sakuraActiveClient?: SakuraClient };
if (globalObj.__sakuraActiveClient) {
  try {
    globalObj.__sakuraActiveClient.disconnect();
  } catch {}
}
export const sakuraClient = new SakuraClient();
globalObj.__sakuraActiveClient = sakuraClient;

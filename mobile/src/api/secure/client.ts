/**
 * Клиент securechannel/1: сеанс Noise IK и спаривание Noise XXpsk3 поверх WebSocket.
 * Порт desktop/core/securechannel/client.py.
 */

import { Platform } from 'react-native';
import { IntegrityError, SecureChannel } from './channel';
import { decodeFrame, encodeFrame, FrameError, FrameType, InnerType } from './frames';
import { HandshakeState, NoiseError } from './noise';
import { b64u, fingerprint, unb64u } from './pairing';

const utf8Encode = new TextEncoder();
const utf8Decode = new TextDecoder();

export const PROLOGUE_SESSION = utf8Encode.encode('sakura-securechannel/1\x00session');
export const PROLOGUE_PAIR = utf8Encode.encode('sakura-securechannel/1\x00pair');
export const HANDSHAKE_TIMEOUT_MS = 8000;

export const CLOSE_TEXT: Record<number, string> = {
  4400: 'сервер не принял защищённый канал (ошибка формата)',
  4408: 'сервер не узнал устройство — выполните /pair в Telegram',
  4409: 'нарушена целостность канала — соединение разорвано',
  4412: 'сервер требует защищённый канал (/pair в Telegram)',
  4413: 'сообщение слишком большое',
  4429: 'слишком много попыток — подождите минуту',
};

export class SecureError extends Error {
  public code?: number;
  constructor(message: string, code?: number) {
    super(message);
    this.name = 'SecureError';
    this.code = code;
  }
}

function toUint8Array(data: unknown): Uint8Array | null {
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  if (data instanceof Uint8Array) return data;
  if (ArrayBuffer.isView(data)) {
    return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  }
  return null;
}

class WsBinaryReader {
  private queue: { data?: Uint8Array; text?: string; closed?: number; error?: string }[] = [];
  private waiter: ((item: { data?: Uint8Array; text?: string; closed?: number; error?: string }) => void) | null = null;

  constructor(private ws: WebSocket) {
    ws.binaryType = 'arraybuffer';
    ws.onmessage = (ev: WebSocketMessageEvent) => {
      const bin = toUint8Array(ev.data);
      const item = bin
        ? { data: bin }
        : typeof ev.data === 'string'
        ? { text: ev.data }
        : { error: 'неизвестный формат сообщения' };
      this.push(item);
    };
    ws.onerror = () => {
      this.push({ error: 'ошибка WebSocket' });
    };
    ws.onclose = (ev: WebSocketCloseEvent) => {
      this.push({ closed: ev.code });
    };
  }

  private push(item: { data?: Uint8Array; text?: string; closed?: number; error?: string }) {
    if (this.waiter) {
      const w = this.waiter;
      this.waiter = null;
      w(item);
    } else {
      this.queue.push(item);
    }
  }

  async nextFrame(timeoutMs = HANDSHAKE_TIMEOUT_MS): Promise<{ ftype: FrameType; body: Uint8Array }> {
    const item = await new Promise<{ data?: Uint8Array; text?: string; closed?: number; error?: string }>(
      (resolve, reject) => {
        if (this.queue.length > 0) {
          resolve(this.queue.shift()!);
          return;
        }
        const timer = setTimeout(() => {
          if (this.waiter) {
            this.waiter = null;
            reject(new SecureError('сервер не ответил на рукопожатие', 4408));
          }
        }, timeoutMs);
        this.waiter = (val) => {
          clearTimeout(timer);
          resolve(val);
        };
      }
    );

    if (item.closed !== undefined) {
      const code = item.closed;
      throw new SecureError(CLOSE_TEXT[code] || `соединение закрыто (${code})`, code);
    }
    if (item.error) {
      throw new SecureError(item.error);
    }
    if (item.text !== undefined) {
      throw new SecureError('сервер ответил текстом — защищённый канал отключён', 4400);
    }
    try {
      return decodeFrame(item.data!);
    } catch (e) {
      if (e instanceof FrameError) {
        throw new SecureError(`неверный кадр рукопожатия: ${e.message}`, 4400);
      }
      throw e;
    }
  }
}

function openWebSocket(url: string, timeoutMs = HANDSHAKE_TIMEOUT_MS): Promise<WebSocket> {
  return new Promise((resolve, reject) => {
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
    } catch (e: any) {
      reject(new SecureError(e?.message || 'не удалось открыть WebSocket'));
      return;
    }
    const timer = setTimeout(() => {
      try {
        ws.close();
      } catch {}
      reject(new SecureError('таймаут подключения к серверу'));
    }, timeoutMs);

    ws.onopen = () => {
      clearTimeout(timer);
      resolve(ws);
    };
    ws.onerror = () => {
      clearTimeout(timer);
      reject(new SecureError('не удалось подключиться к серверу Сакуры'));
    };
  });
}

export interface PairingResult {
  deviceId: string;
  serverPub: Uint8Array;
  serverFp: string;
}

export async function xxPair(params: {
  url: string;
  devicePriv: Uint8Array;
  psk: Uint8Array;
  deviceName?: string;
  deviceIdHint?: string;
  expectedServerPub?: Uint8Array | null;
}): Promise<PairingResult> {
  const ws = await openWebSocket(params.url);
  const reader = new WsBinaryReader(ws);
  try {
    const hs = new HandshakeState({
      pattern: 'XXpsk3',
      initiator: true,
      prologue: PROLOGUE_PAIR,
      sPriv: params.devicePriv,
      psk: params.psk,
    });

    ws.send(encodeFrame(FrameType.XX_1, hs.write(new Uint8Array(0))));

    const msg2 = await reader.nextFrame();
    if (msg2.ftype !== FrameType.XX_2) {
      throw new SecureError('неожиданный ответ сервера при спаривании', 4400);
    }
    try {
      hs.read(msg2.body);
    } catch (e) {
      if (e instanceof NoiseError) {
        throw new SecureError('ответ сервера при спаривании не прошёл проверку', 4408);
      }
      throw e;
    }

    if (params.expectedServerPub && hs.remoteStatic) {
      const got = b64u(hs.remoteStatic);
      const exp = b64u(params.expectedServerPub);
      if (got !== exp) {
        ws.close(1000, 'server key mismatch');
        throw new SecureError('ключ сервера не совпал с QR — возможна подмена');
      }
    }

    const info = {
      v: 1,
      name: (params.deviceName || (Platform.OS === 'web' ? 'Phone Web' : 'Phone')).slice(0, 40),
      kind: 'phone',
      device_id_hint: params.deviceIdHint || 'phone',
    };
    ws.send(encodeFrame(FrameType.XX_3, hs.write(utf8Encode.encode(JSON.stringify(info)))));

    const [sendCipher, recvCipher] = hs.split();
    const ch = new SecureChannel(sendCipher, recvCipher);

    let msg4: { ftype: FrameType; body: Uint8Array };
    try {
      msg4 = await reader.nextFrame();
    } catch (e: any) {
      throw new SecureError(
        'код спаривания не подошёл или истёк — получите новый в Telegram (/pair)',
        e?.code
      );
    }

    let items: { inner: InnerType; data: Uint8Array }[];
    try {
      items = ch.open(encodeFrame(msg4.ftype, msg4.body));
    } catch (e) {
      if (e instanceof IntegrityError) {
        throw new SecureError('код спаривания не подошёл — ответ сервера не расшифровался');
      }
      throw e;
    }

    for (const { inner, data } of items) {
      if (inner === InnerType.PAIRED) {
        const paired = JSON.parse(utf8Decode.decode(data));
        if (paired.server_pub && hs.remoteStatic && paired.server_pub !== b64u(hs.remoteStatic)) {
          throw new SecureError('сервер сообщил другой ключ — спаривание остановлено');
        }
        try {
          ws.close(1000, 'paired');
        } catch {}
        return {
          deviceId: paired.device_id || params.deviceIdHint || 'phone',
          serverPub: hs.remoteStatic!,
          serverFp: fingerprint(hs.remoteStatic!),
        };
      }
    }
    throw new SecureError('сервер не подтвердил спаривание');
  } finally {
    try {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    } catch {}
  }
}

export interface SecureSessionHandlers {
  onJson: (msg: any) => void;
  onServerKeyRotated: (newPub: Uint8Array) => void;
  onClose: (code: number, reason: string) => void;
}

export class NoiseSocket {
  public readonly channel: SecureChannel;
  public readonly session: string | null;
  private closedNotified = false;

  constructor(
    private ws: WebSocket,
    channel: SecureChannel,
    session: string | null,
    private handlers: SecureSessionHandlers
  ) {
    this.channel = channel;
    this.session = session;
    this.attachTransportHandlers();
  }

  private notifyClose(code: number, reason: string): void {
    if (this.closedNotified) return;
    this.closedNotified = true;
    this.handlers.onClose(code, reason);
  }

  private attachTransportHandlers(): void {
    this.ws.binaryType = 'arraybuffer';
    this.ws.onmessage = (ev: WebSocketMessageEvent) => {
      const bin = toUint8Array(ev.data);
      if (!bin) {
        this.close(4400, 'text inside noise');
        return;
      }
      let items: { inner: InnerType; data: Uint8Array }[];
      try {
        items = this.channel.open(bin);
      } catch {
        this.ws.close(4409, 'integrity');
        return;
      }

      for (const { inner, data } of items) {
        if (inner === InnerType.DATA) {
          const text = utf8Decode.decode(data);
          try {
            const obj = JSON.parse(text);
            if (obj?.type === 'secure_server_key' && obj?.pub) {
              this.handlers.onServerKeyRotated(unb64u(obj.pub));
              continue;
            }
            this.handlers.onJson(obj);
          } catch {}
        } else if (inner === InnerType.PING) {
          try {
            this.ws.send(this.channel.pong(data));
          } catch {}
        } else if (inner === InnerType.CLOSE) {
          const code = data.length >= 2 ? new DataView(data.buffer, data.byteOffset).getUint16(0, false) : 1000;
          const reason = data.length > 2 ? utf8Decode.decode(data.subarray(2)) : '';
          this.notifyClose(code, CLOSE_TEXT[code] || reason);
          try {
            this.ws.close(code, reason);
          } catch {}
        }
      }
    };

    this.ws.onerror = () => {
      // handled by onclose
    };

    this.ws.onclose = (ev: WebSocketCloseEvent) => {
      const code = ev.code ?? 1000;
      this.notifyClose(code, CLOSE_TEXT[code] || ev.reason || '');
    };
  }

  sendJson(obj: unknown): boolean {
    if (this.ws.readyState !== WebSocket.OPEN) return false;
    try {
      const frames = this.channel.seal(JSON.stringify(obj));
      for (const frame of frames) {
        this.ws.send(frame);
      }
      return true;
    } catch {
      return false;
    }
  }

  close(code = 1000, reason = ''): void {
    try {
      if (this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(this.channel.closeFrame(code, reason));
      }
    } catch {}
    try {
      this.ws.close(code, reason);
    } catch {}
  }
}

export async function connectNoiseIK(params: {
  url: string;
  devicePriv: Uint8Array;
  serverPub: Uint8Array;
  deviceId: string;
  handlers: SecureSessionHandlers;
}): Promise<NoiseSocket> {
  const ws = await openWebSocket(params.url);
  const reader = new WsBinaryReader(ws);
  try {
    const hs = new HandshakeState({
      pattern: 'IK',
      initiator: true,
      prologue: PROLOGUE_SESSION,
      sPriv: params.devicePriv,
      rs: params.serverPub,
    });

    const ident = JSON.stringify({
      v: 1,
      device_id: params.deviceId,
      ts: Date.now() / 1000,
    });
    ws.send(encodeFrame(FrameType.IK_INIT, hs.write(utf8Encode.encode(ident))));

    const resp = await reader.nextFrame();
    if (resp.ftype !== FrameType.IK_RESP) {
      throw new SecureError('неожиданный ответ сервера на рукопожатие', 4400);
    }

    let sessParams: any = {};
    try {
      const plain = hs.read(resp.body);
      sessParams = plain.length ? JSON.parse(utf8Decode.decode(plain)) : {};
    } catch {
      throw new SecureError('ответ сервера не прошёл проверку ключа', 4408);
    }

    const [sendCipher, recvCipher] = hs.split();
    const ch = new SecureChannel(
      sendCipher,
      recvCipher,
      Number(sessParams.rekey_messages || 10000),
      Number(sessParams.rekey_seconds || 3600)
    );

    return new NoiseSocket(ws, ch, sessParams.session || null, params.handlers);
  } catch (e) {
    try {
      ws.close();
    } catch {}
    throw e;
  }
}

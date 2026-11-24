/**
 * Зашифрованный канал после рукопожатия (PROTOCOL.md §4): seal/open кадров TRANSPORT,
 * rekey, ping, close. Порт desktop/core/securechannel/channel.py.
 */

import {
  decodeFrame,
  decodeInner,
  encodeFrame,
  encodeInner,
  fragmentMessage,
  FrameType,
  InnerType,
  Reassembler,
} from './frames';
import { CipherState, concatBytes, NoiseError } from './noise';

export class IntegrityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'IntegrityError';
  }
}

const utf8Encode = new TextEncoder();

export class SecureChannel {
  private sendCipher: CipherState;
  private recvCipher: CipherState;
  public rekeyMessages: number;
  public rekeySeconds: number;
  private sentSince = 0;
  private rekeyAt: number;
  private asm = new Reassembler();
  public started: number;
  public rekeysOut = 0;
  public rekeysIn = 0;
  public framesOut = 0;
  public framesIn = 0;

  constructor(
    send: CipherState,
    recv: CipherState,
    rekeyMessages = 10000,
    rekeySeconds = 3600
  ) {
    this.sendCipher = send;
    this.recvCipher = recv;
    this.rekeyMessages = rekeyMessages;
    this.rekeySeconds = rekeySeconds;
    const now = Date.now() / 1000;
    this.rekeyAt = now;
    this.started = now;
  }

  sealInner(innerPlain: Uint8Array): Uint8Array {
    this.framesOut += 1;
    return encodeFrame(
      FrameType.TRANSPORT,
      this.sendCipher.encryptWithAd(new Uint8Array(0), innerPlain)
    );
  }

  private maybeRekey(): Uint8Array[] {
    const now = Date.now() / 1000;
    const due =
      this.sentSince >= this.rekeyMessages || now - this.rekeyAt >= this.rekeySeconds;
    if (!due) return [];
    const frame = this.sealInner(encodeInner(InnerType.REKEY, 0, new Uint8Array(0)));
    this.sendCipher.rekey();
    this.sentSince = 0;
    this.rekeyAt = now;
    this.rekeysOut += 1;
    return [frame];
  }

  seal(message: string | Uint8Array): Uint8Array[] {
    const data = typeof message === 'string' ? utf8Encode.encode(message) : message;
    const out: Uint8Array[] = [];
    for (const chunk of fragmentMessage(data)) {
      out.push(...this.maybeRekey());
      out.push(this.sealInner(chunk));
      this.sentSince += 1;
    }
    return out;
  }

  ping(data: Uint8Array = new Uint8Array(0)): Uint8Array {
    return this.sealInner(encodeInner(InnerType.PING, 0, data.subarray(0, 32)));
  }

  pong(payload: Uint8Array): Uint8Array {
    return this.sealInner(encodeInner(InnerType.PONG, 0, payload));
  }

  closeFrame(code: number, reason = ''): Uint8Array {
    const codeBytes = new Uint8Array(2);
    new DataView(codeBytes.buffer).setUint16(0, code, false);
    const reasonBytes = utf8Encode.encode(reason).subarray(0, 120);
    return this.sealInner(
      encodeInner(InnerType.CLOSE, 0, concatBytes(codeBytes, reasonBytes))
    );
  }

  open(frame: Uint8Array): { inner: InnerType; data: Uint8Array }[] {
    let ftype: FrameType;
    let body: Uint8Array;
    try {
      const decoded = decodeFrame(frame);
      ftype = decoded.ftype;
      body = decoded.body;
    } catch (e: any) {
      throw new IntegrityError(e?.message || 'ошибка формата кадра');
    }
    if (ftype !== FrameType.TRANSPORT) {
      throw new IntegrityError('после рукопожатия допустимы только кадры TRANSPORT');
    }
    let plain: Uint8Array;
    try {
      plain = this.recvCipher.decryptWithAd(new Uint8Array(0), body);
    } catch (e) {
      if (e instanceof NoiseError) {
        throw new IntegrityError('кадр не расшифровался (подмена, повтор или перестановка)');
      }
      throw e;
    }
    this.framesIn += 1;
    const { inner, flags, data } = decodeInner(plain);
    if (inner === InnerType.REKEY) {
      this.recvCipher.rekey();
      this.rekeysIn += 1;
      return [];
    }
    if (
      this.asm.inProgress &&
      inner !== InnerType.DATA &&
      inner !== InnerType.PING &&
      inner !== InnerType.PONG
    ) {
      throw new IntegrityError('посторонний кадр посреди сообщения');
    }
    if (inner === InnerType.DATA) {
      const msg = this.asm.feed(flags, data);
      return msg === null ? [] : [{ inner: InnerType.DATA, data: msg }];
    }
    return [{ inner, data }];
  }
}

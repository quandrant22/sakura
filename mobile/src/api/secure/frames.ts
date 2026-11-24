/**
 * Кадры securechannel/1 (PROTOCOL.md §2, §4.1–4.2): внешний кадр «SK»,
 * внутренний заголовок, фрагментация. Порт desktop/core/securechannel/frames.py.
 */

export const MAGIC = new Uint8Array([0x53, 0x4b]); // "SK"
export const VERSION = 0x01;
export const HEADER_SIZE = 8;
export const MAX_BODY = 65535;
export const MAX_CHUNK = 65535 - 16 - 2; // AEAD tag 16 + inner header 2
export const MAX_MESSAGE = 2 * 1024 * 1024;
export const MAX_FRAGMENTS = 64;
export const FLAG_MORE = 0x01;

export enum FrameType {
  IK_INIT = 0x01,
  IK_RESP = 0x02,
  XX_1 = 0x11,
  XX_2 = 0x12,
  XX_3 = 0x13,
  TRANSPORT = 0x20,
}

export enum InnerType {
  DATA = 0x01,
  REKEY = 0x02,
  CLOSE = 0x03,
  PING = 0x04,
  PONG = 0x05,
  PAIRED = 0x06,
}

export class FrameError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FrameError';
  }
}

export class TooLargeError extends FrameError {
  constructor(message: string) {
    super(message);
    this.name = 'TooLargeError';
  }
}

const VALID_FRAME_TYPES = new Set<number>([
  FrameType.IK_INIT,
  FrameType.IK_RESP,
  FrameType.XX_1,
  FrameType.XX_2,
  FrameType.XX_3,
  FrameType.TRANSPORT,
]);

const VALID_INNER_TYPES = new Set<number>([
  InnerType.DATA,
  InnerType.REKEY,
  InnerType.CLOSE,
  InnerType.PING,
  InnerType.PONG,
  InnerType.PAIRED,
]);

export function encodeFrame(ftype: FrameType, body: Uint8Array): Uint8Array {
  if (body.length > MAX_BODY) {
    throw new FrameError('тело кадра больше 65535 байт');
  }
  const out = new Uint8Array(HEADER_SIZE + body.length);
  out[0] = MAGIC[0];
  out[1] = MAGIC[1];
  out[2] = VERSION;
  out[3] = ftype;
  const view = new DataView(out.buffer, out.byteOffset, out.byteLength);
  view.setUint32(4, body.length, false); // big-endian
  out.set(body, HEADER_SIZE);
  return out;
}

export function decodeFrame(data: Uint8Array): { ftype: FrameType; body: Uint8Array } {
  if (data.length < HEADER_SIZE) {
    throw new FrameError('короткий кадр');
  }
  if (data[0] !== MAGIC[0] || data[1] !== MAGIC[1] || data[2] !== VERSION) {
    throw new FrameError('не кадр securechannel/1');
  }
  const ftype = data[3];
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const length = view.getUint32(4, false);
  const body = data.subarray(HEADER_SIZE);
  if (length !== body.length || length > MAX_BODY) {
    throw new FrameError('длина кадра не совпадает');
  }
  if (!VALID_FRAME_TYPES.has(ftype)) {
    throw new FrameError('неизвестный тип кадра');
  }
  return { ftype: ftype as FrameType, body };
}

export function encodeInner(inner: InnerType, flags: number, data: Uint8Array): Uint8Array {
  const out = new Uint8Array(2 + data.length);
  out[0] = inner;
  out[1] = flags & 0xff;
  out.set(data, 2);
  return out;
}

export function decodeInner(plain: Uint8Array): { inner: InnerType; flags: number; data: Uint8Array } {
  if (plain.length < 2) {
    throw new FrameError('короткий внутренний заголовок');
  }
  const inner = plain[0];
  if (!VALID_INNER_TYPES.has(inner)) {
    throw new FrameError('неизвестный внутренний тип');
  }
  const flags = plain[1];
  if ((flags & ~FLAG_MORE) !== 0) {
    throw new FrameError('неизвестные флаги');
  }
  return { inner: inner as InnerType, flags, data: plain.subarray(2) };
}

export function fragmentMessage(message: Uint8Array): Uint8Array[] {
  if (message.length > MAX_MESSAGE) {
    throw new TooLargeError('сообщение больше 2 МиБ');
  }
  if (message.length === 0) {
    return [encodeInner(InnerType.DATA, 0, new Uint8Array(0))];
  }
  const chunks: Uint8Array[] = [];
  for (let i = 0; i < message.length; i += MAX_CHUNK) {
    chunks.push(message.subarray(i, Math.min(i + MAX_CHUNK, message.length)));
  }
  if (chunks.length > MAX_FRAGMENTS) {
    throw new TooLargeError('больше 64 кусков');
  }
  return chunks.map((chunk, i) =>
    encodeInner(InnerType.DATA, i < chunks.length - 1 ? FLAG_MORE : 0, chunk)
  );
}

export class Reassembler {
  private parts: Uint8Array[] = [];
  private size = 0;

  get inProgress(): boolean {
    return this.parts.length > 0;
  }

  feed(flags: number, data: Uint8Array): Uint8Array | null {
    this.parts.push(data);
    this.size += data.length;
    if (this.size > MAX_MESSAGE || this.parts.length > MAX_FRAGMENTS) {
      this.parts = [];
      this.size = 0;
      throw new TooLargeError('сообщение больше лимита');
    }
    if ((flags & FLAG_MORE) !== 0) {
      return null;
    }
    const out = new Uint8Array(this.size);
    let offset = 0;
    for (const part of this.parts) {
      out.set(part, offset);
      offset += part.length;
    }
    this.parts = [];
    this.size = 0;
    return out;
  }
}

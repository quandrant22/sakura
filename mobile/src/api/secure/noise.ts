/**
 * Noise Protocol Framework (rev 34): Noise_IK и Noise_XXpsk3 на X25519, ChaCha20-Poly1305, BLAKE2s.
 * Точный порт desktop/core/securechannel/noise.py на @noble/* (pure JS, работает в Expo Go и Web).
 */

import { chacha20poly1305 } from '@noble/ciphers/chacha.js';
import { x25519 } from '@noble/curves/ed25519.js';
import { blake2s } from '@noble/hashes/blake2.js';
import { hmac } from '@noble/hashes/hmac.js';
import * as Crypto from 'expo-crypto';

export const DHLEN = 32;
export const HASHLEN = 32;
export const MAX_NONCE = (1n << 64n) - 1n;
export const MAX_MESSAGE = 65535;

export class NoiseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NoiseError';
  }
}

export function concatBytes(...parts: Uint8Array[]): Uint8Array {
  let len = 0;
  for (const p of parts) len += p.length;
  const out = new Uint8Array(len);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

export function generateKeypair(): { priv: Uint8Array; pub: Uint8Array } {
  const seed = Crypto.getRandomBytes(32);
  const { secretKey, publicKey } = x25519.keygen(seed);
  return { priv: secretKey, pub: publicKey };
}

export function publicFromPrivate(priv: Uint8Array): Uint8Array {
  return x25519.getPublicKey(priv);
}

export function dh(priv: Uint8Array, pub: Uint8Array): Uint8Array {
  try {
    const shared = x25519.getSharedSecret(priv, pub);
    let zero = true;
    for (let i = 0; i < shared.length; i++) {
      if (shared[i] !== 0) {
        zero = false;
        break;
      }
    }
    if (zero) throw new NoiseError('недопустимый открытый ключ');
    return shared;
  } catch (e) {
    if (e instanceof NoiseError) throw e;
    throw new NoiseError('недопустимый открытый ключ');
  }
}

function encodeNonce(n: bigint): Uint8Array {
  const out = new Uint8Array(12); // первые 4 байта — нули
  const view = new DataView(out.buffer);
  view.setBigUint64(4, n, true); // 64-bit little-endian
  return out;
}

function hashBlake2s(data: Uint8Array): Uint8Array {
  return blake2s(data, { dkLen: 32 });
}

function hmacBlake2s(key: Uint8Array, data: Uint8Array): Uint8Array {
  return hmac(blake2s, key, data);
}

export function hkdf(ck: Uint8Array, ikm: Uint8Array, n: number): Uint8Array[] {
  const temp = hmacBlake2s(ck, ikm);
  const out: Uint8Array[] = [];
  let prev: Uint8Array = new Uint8Array(0);
  for (let i = 1; i <= n; i++) {
    prev = hmacBlake2s(temp, concatBytes(prev, new Uint8Array([i])));
    out.push(prev);
  }
  return out;
}

export class CipherState {
  public n: bigint = 0n;
  private _k: Uint8Array | null = null;

  constructor(key: Uint8Array | null = null) {
    this.k = key;
  }

  get k(): Uint8Array | null {
    return this._k;
  }

  set k(key: Uint8Array | null) {
    this._k = key ? new Uint8Array(key) : null;
  }

  hasKey(): boolean {
    return this._k !== null;
  }

  encryptWithAd(ad: Uint8Array, plaintext: Uint8Array): Uint8Array {
    if (!this._k) return plaintext;
    if (this.n >= MAX_NONCE) throw new NoiseError('исчерпан счётчик nonce');
    const aead = chacha20poly1305(this._k, encodeNonce(this.n), ad);
    const out = aead.encrypt(plaintext);
    this.n += 1n;
    return out;
  }

  decryptWithAd(ad: Uint8Array, ciphertext: Uint8Array): Uint8Array {
    if (!this._k) return ciphertext;
    if (this.n >= MAX_NONCE) throw new NoiseError('исчерпан счётчик nonce');
    try {
      const aead = chacha20poly1305(this._k, encodeNonce(this.n), ad);
      const out = aead.decrypt(ciphertext);
      this.n += 1n;
      return out;
    } catch {
      throw new NoiseError('ошибка целостности');
    }
  }

  rekey(): void {
    if (!this._k) throw new NoiseError('нет ключа для rekey');
    const aead = chacha20poly1305(this._k, encodeNonce(MAX_NONCE), new Uint8Array(0));
    this._k = aead.encrypt(new Uint8Array(32)).subarray(0, 32);
  }
}

export class SymmetricState {
  public h: Uint8Array;
  public ck: Uint8Array;
  public cipher: CipherState;

  constructor(protocolName: Uint8Array) {
    if (protocolName.length <= HASHLEN) {
      this.h = new Uint8Array(HASHLEN);
      this.h.set(protocolName, 0);
    } else {
      this.h = hashBlake2s(protocolName);
    }
    this.ck = new Uint8Array(this.h);
    this.cipher = new CipherState(null);
  }

  mixKey(ikm: Uint8Array): void {
    const [ck, tempK] = hkdf(this.ck, ikm, 2);
    this.ck = ck;
    this.cipher = new CipherState(tempK.subarray(0, 32));
  }

  mixHash(data: Uint8Array): void {
    this.h = hashBlake2s(concatBytes(this.h, data));
  }

  mixKeyAndHash(ikm: Uint8Array): void {
    const [ck, tempH, tempK] = hkdf(this.ck, ikm, 3);
    this.ck = ck;
    this.mixHash(tempH);
    this.cipher = new CipherState(tempK.subarray(0, 32));
  }

  encryptAndHash(plaintext: Uint8Array): Uint8Array {
    const c = this.cipher.encryptWithAd(this.h, plaintext);
    this.mixHash(c);
    return c;
  }

  decryptAndHash(ciphertext: Uint8Array): Uint8Array {
    const p = this.cipher.decryptWithAd(this.h, ciphertext);
    this.mixHash(ciphertext);
    return p;
  }

  split(): [CipherState, CipherState] {
    const [k1, k2] = hkdf(this.ck, new Uint8Array(0), 2);
    return [new CipherState(k1.subarray(0, 32)), new CipherState(k2.subarray(0, 32))];
  }
}

export type NoisePattern = 'IK' | 'XXpsk3';

const PATTERNS: Record<NoisePattern, { pre: string[]; messages: string[][] }> = {
  IK: { pre: ['s'], messages: [['e', 'es', 's', 'ss'], ['e', 'ee', 'se']] },
  XXpsk3: { pre: [], messages: [['e'], ['e', 'ee', 's', 'es'], ['s', 'se', 'psk']] },
};

const utf8 = new TextEncoder();

export class HandshakeState {
  public pattern: NoisePattern;
  public initiator: boolean;
  private psk: Uint8Array | null;
  private pskMode: boolean;
  private s: { priv: Uint8Array; pub: Uint8Array } | null;
  private fixedE: Uint8Array | null;
  private e: { priv: Uint8Array; pub: Uint8Array } | null = null;
  private rs: Uint8Array | null;
  private re: Uint8Array | null = null;
  private ss: SymmetricState;
  private messages: string[][];
  private step = 0;

  constructor(opts: {
    pattern: NoisePattern;
    initiator: boolean;
    prologue: Uint8Array;
    sPriv?: Uint8Array | null;
    rs?: Uint8Array | null;
    psk?: Uint8Array | null;
    ePriv?: Uint8Array | null;
  }) {
    this.pattern = opts.pattern;
    this.initiator = opts.initiator;
    this.psk = opts.psk ?? null;
    this.pskMode = opts.pattern.includes('psk');
    if (this.pskMode && (!this.psk || this.psk.length !== 32)) {
      throw new Error('нужен psk 32 байта');
    }
    this.s = opts.sPriv ? { priv: opts.sPriv, pub: publicFromPrivate(opts.sPriv) } : null;
    this.fixedE = opts.ePriv ?? null;
    this.rs = opts.rs ?? null;

    const name = utf8.encode(`Noise_${opts.pattern}_25519_ChaChaPoly_BLAKE2s`);
    this.ss = new SymmetricState(name);
    this.ss.mixHash(opts.prologue);

    const spec = PATTERNS[opts.pattern];
    this.messages = spec.messages;
    for (const tok of spec.pre) {
      if (tok === 's') {
        const key = !this.initiator ? this.s?.pub : this.rs;
        if (!key) throw new Error('IK: инициатору нужен открытый ключ ответчика');
        this.ss.mixHash(key);
      }
    }
  }

  get complete(): boolean {
    return this.step >= this.messages.length;
  }

  get remoteStatic(): Uint8Array | null {
    return this.rs;
  }

  private myTurn(): boolean {
    return (this.step % 2 === 0) === this.initiator;
  }

  private dhFor(tok: string): Uint8Array {
    const i = this.initiator;
    if (tok === 'ee') return dh(this.e!.priv, this.re!);
    if (tok === 'ss') return dh(this.s!.priv, this.rs!);
    if (tok === 'es') return i ? dh(this.e!.priv, this.rs!) : dh(this.s!.priv, this.re!);
    if (tok === 'se') return i ? dh(this.s!.priv, this.re!) : dh(this.e!.priv, this.rs!);
    throw new Error(`Unknown DH token ${tok}`);
  }

  write(payload: Uint8Array = new Uint8Array(0)): Uint8Array {
    if (this.complete || !this.myTurn()) {
      throw new NoiseError('не наша очередь писать');
    }
    const chunks: Uint8Array[] = [];
    for (const tok of this.messages[this.step]) {
      if (tok === 'e') {
        this.e = this.fixedE
          ? { priv: this.fixedE, pub: publicFromPrivate(this.fixedE) }
          : generateKeypair();
        chunks.push(this.e.pub);
        this.ss.mixHash(this.e.pub);
        if (this.pskMode) this.ss.mixKey(this.e.pub);
      } else if (tok === 's') {
        chunks.push(this.ss.encryptAndHash(this.s!.pub));
      } else if (tok === 'psk') {
        this.ss.mixKeyAndHash(this.psk!);
      } else {
        this.ss.mixKey(this.dhFor(tok));
      }
    }
    chunks.push(this.ss.encryptAndHash(payload));
    const buf = concatBytes(...chunks);
    if (buf.length > MAX_MESSAGE) {
      throw new NoiseError('сообщение рукопожатия слишком велико');
    }
    this.step += 1;
    return buf;
  }

  read(message: Uint8Array): Uint8Array {
    if (this.complete || this.myTurn()) {
      throw new NoiseError('не наша очередь читать');
    }
    let pos = 0;
    for (const tok of this.messages[this.step]) {
      if (tok === 'e') {
        if (message.length - pos < DHLEN) throw new NoiseError('короткое сообщение');
        this.re = message.subarray(pos, pos + DHLEN);
        pos += DHLEN;
        this.ss.mixHash(this.re);
        if (this.pskMode) this.ss.mixKey(this.re);
      } else if (tok === 's') {
        const n = DHLEN + (this.ss.cipher.hasKey() ? 16 : 0);
        if (message.length - pos < n) throw new NoiseError('короткое сообщение');
        this.rs = this.ss.decryptAndHash(message.subarray(pos, pos + n));
        pos += n;
      } else if (tok === 'psk') {
        this.ss.mixKeyAndHash(this.psk!);
      } else {
        this.ss.mixKey(this.dhFor(tok));
      }
    }
    const payload = this.ss.decryptAndHash(message.subarray(pos));
    this.step += 1;
    return payload;
  }

  split(): [CipherState, CipherState] {
    if (!this.complete) throw new NoiseError('рукопожатие не завершено');
    const [c1, c2] = this.ss.split();
    return this.initiator ? [c1, c2] : [c2, c1];
  }
}

/**
 * Спаривание (PROTOCOL.md §3.4–3.5): 8 слов → PSK, разбор QR-ссылки sakura-pair://1, отпечатки.
 * Порт desktop/core/securechannel/pairing.py и keys.py.
 */

import { blake2s } from '@noble/hashes/blake2.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { concatBytes } from './noise';

const utf8 = new TextEncoder();
const PSK_PREFIX = utf8.encode('sakura-pair/1\x00');
export const PAIRING_WORDS_COUNT = 8;

export class PairingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PairingError';
  }
}

export function normalizeWords(text: string): string {
  const t = (text || '').toLowerCase().replace(/ё/g, 'е');
  const matches = t.match(/\p{L}+/gu);
  return matches ? matches.join(' ') : '';
}

export function wordsToPsk(words: string): Uint8Array {
  const norm = normalizeWords(words);
  const parts = norm ? norm.split(' ') : [];
  if (parts.length !== PAIRING_WORDS_COUNT) {
    throw new PairingError(`нужно ровно 8 слов (введено ${parts.length})`);
  }
  return blake2s(concatBytes(PSK_PREFIX, utf8.encode(norm)), { dkLen: 32 });
}

export function b64u(data: Uint8Array): string {
  let bin = '';
  for (let i = 0; i < data.length; i++) {
    bin += String.fromCharCode(data[i]);
  }
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function unb64u(text: string): Uint8Array {
  const clean = (text || '').trim().replace(/-/g, '+').replace(/_/g, '/');
  const padLen = (4 - (clean.length % 4)) % 4;
  const padded = clean + '='.repeat(padLen);
  const bin = atob(padded);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) {
    out[i] = bin.charCodeAt(i);
  }
  return out;
}

export function fingerprint(pub: Uint8Array): string {
  const h = blake2s(pub, { dkLen: 32 }).subarray(0, 8);
  let hex = '';
  for (let i = 0; i < h.length; i++) {
    hex += h[i].toString(16).padStart(2, '0');
  }
  return hex.match(/.{1,4}/g)?.join(' ') ?? hex;
}

export function sha256Hex(pub: Uint8Array): string {
  const h = sha256(pub);
  let hex = '';
  for (let i = 0; i < h.length; i++) {
    hex += h[i].toString(16).padStart(2, '0');
  }
  return hex;
}

export interface ParsedQrPair {
  url: string;
  serverPub: Uint8Array;
  words: string;
  expires: number;
}

export function parseQrUri(uri: string): ParsedQrPair {
  const raw = (uri || '').trim();
  if (!raw.toLowerCase().startsWith('sakura-pair://1')) {
    throw new PairingError('это не QR-ссылка спаривания Сакуры (sakura-pair://1)');
  }
  const qIndex = raw.indexOf('?');
  if (qIndex === -1) {
    throw new PairingError('в QR не хватает параметров');
  }
  const query = raw.slice(qIndex + 1);
  const params = new Map<string, string>();
  for (const part of query.split('&')) {
    const eq = part.indexOf('=');
    if (eq > 0) {
      const k = decodeURIComponent(part.slice(0, eq));
      const v = decodeURIComponent(part.slice(eq + 1).replace(/\+/g, ' '));
      params.set(k, v);
    }
  }

  let serverPub: Uint8Array;
  let words: string;
  let expires: number;
  let url: string;
  try {
    const kParam = params.get('k');
    const wParam = params.get('w');
    const uParam = params.get('u');
    if (!kParam || !wParam || !uParam) {
      throw new Error('missing');
    }
    serverPub = unb64u(kParam);
    words = normalizeWords(wParam.replace(/-/g, ' '));
    expires = Number(params.get('e') || '0');
    url = uParam;
  } catch {
    throw new PairingError('в QR не хватает данных');
  }

  if (serverPub.length !== 32) {
    throw new PairingError('в QR неверный ключ сервера');
  }
  if (expires && Date.now() / 1000 > expires) {
    throw new PairingError('срок кода спаривания истёк — получите новый в Telegram (/pair)');
  }
  return { url, serverPub, words, expires };
}

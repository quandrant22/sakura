/**
 * Клиент неофициального REST API Яндекс.Музыки для мобильного приложения.
 * Работает напрямую по OAuth-токену (YANDEX_MUSIC_TOKEN) без промежуточного сервера.
 */

import * as Crypto from 'expo-crypto';

const API_BASE = 'https://api.music.yandex.net';
const SIGN_SALT = 'XGRlBW9FXlekgbPrRHuSiA';

export interface YandexTrack {
  id: string;
  title: string;
  artist: string;
  album?: string;
  durationMs: number;
  coverUrl: string | null;
  liked?: boolean;
  batchId?: string;
}

export interface YandexAccountInfo {
  uid: number;
  login: string;
  displayName: string;
  hasPlus: boolean;
}

function headers(token: string): Record<string, string> {
  return {
    Authorization: `OAuth ${token.trim()}`,
    'X-Yandex-Music-Client': 'YandexMusicAndroid/24023621',
    Accept: 'application/json',
  };
}

function formatCover(uri?: string | null, size = '400x400'): string | null {
  if (!uri) return null;
  const clean = uri.replace('%%', size);
  return clean.startsWith('http') ? clean : `https://${clean}`;
}

function mapTrack(raw: any, batchId?: string): YandexTrack | null {
  if (!raw || !raw.id) return null;
  const t = raw.track || raw;
  const artists = Array.isArray(t.artists)
    ? t.artists.map((a: any) => a?.name).filter(Boolean).join(', ')
    : '';
  const coverUri = t.coverUri || t.albums?.[0]?.coverUri || t.ogImage;
  return {
    id: String(t.id),
    title: String(t.title || 'Без названия'),
    artist: artists || 'Неизвестный исполнитель',
    album: t.albums?.[0]?.title,
    durationMs: Number(t.durationMs || 0),
    coverUrl: formatCover(coverUri),
    batchId,
  };
}

export async function checkYandexAccount(token: string): Promise<YandexAccountInfo> {
  const clean = token.trim();
  if (!clean) throw new Error('Токен не указан');
  const res = await fetch(`${API_BASE}/account/status`, { headers: headers(clean) });
  if (res.status === 401) throw new Error('Токен не принят (401)');
  if (!res.ok) throw new Error(`Ошибка Яндекс.Музыки (${res.status})`);
  const json = await res.json();
  const acc = json?.result?.account;
  if (!acc?.uid) throw new Error('Не удалось получить профиль Яндекса');
  return {
    uid: Number(acc.uid),
    login: String(acc.login || ''),
    displayName: String(acc.displayName || acc.fullName || acc.login || 'Аккаунт'),
    hasPlus: Boolean(json?.result?.plus?.hasPlus),
  };
}

export async function getMyWaveTracks(token: string, queueId?: string): Promise<YandexTrack[]> {
  const q = queueId ? `?queue=${encodeURIComponent(queueId)}` : '';
  const res = await fetch(`${API_BASE}/rotor/station/user:onyourwave/tracks${q}`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Моя волна недоступна (${res.status})`);
  const json = await res.json();
  const batchId = json?.result?.batchId;
  const seq = json?.result?.sequence || [];
  return seq.map((item: any) => mapTrack(item, batchId)).filter(Boolean) as YandexTrack[];
}

export async function getLikedTracks(
  token: string,
  uid: number,
  limit = 40
): Promise<YandexTrack[]> {
  const likesRes = await fetch(`${API_BASE}/users/${uid}/likes/tracks`, {
    headers: headers(token),
  });
  if (!likesRes.ok) throw new Error(`Не удалось загрузить лайки (${likesRes.status})`);
  const likesJson = await likesRes.json();
  const rawList: any[] = likesJson?.result?.library?.tracks || [];
  const ids = rawList
    .slice(0, limit)
    .map((x) => (x.albumId ? `${x.id}:${x.albumId}` : String(x.id)))
    .filter(Boolean);

  if (ids.length === 0) return [];

  const body = new URLSearchParams({ 'track-ids': ids.join(',') }).toString();
  const tracksRes = await fetch(`${API_BASE}/tracks`, {
    method: 'POST',
    headers: {
      ...headers(token),
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  });
  if (!tracksRes.ok) throw new Error(`Ошибка загрузки треков (${tracksRes.status})`);
  const tracksJson = await tracksRes.json();
  const list: any[] = tracksJson?.result || [];
  return list
    .map((t) => {
      const mapped = mapTrack(t);
      if (mapped) mapped.liked = true;
      return mapped;
    })
    .filter(Boolean) as YandexTrack[];
}

export async function searchYandexTracks(token: string, query: string): Promise<YandexTrack[]> {
  const q = query.trim();
  if (!q) return [];
  const url = `${API_BASE}/search?text=${encodeURIComponent(q)}&page=0&type=track`;
  const res = await fetch(url, { headers: headers(token) });
  if (!res.ok) throw new Error(`Ошибка поиска (${res.status})`);
  const json = await res.json();
  const results: any[] = json?.result?.tracks?.results || [];
  return results.map((t) => mapTrack(t)).filter(Boolean) as YandexTrack[];
}

export async function getTrackStreamUrl(
  token: string,
  trackId: string,
  highQuality = true
): Promise<string> {
  const res = await fetch(`${API_BASE}/tracks/${trackId}/download-info`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Нет потока трека (${res.status})`);
  const json = await res.json();
  const infos: any[] = json?.result || [];
  const mp3s = infos.filter((i) => i.codec === 'mp3');
  const pool = mp3s.length > 0 ? mp3s : infos;
  pool.sort((a, b) => (highQuality ? b.bitrateInKbps - a.bitrateInKbps : a.bitrateInKbps - b.bitrateInKbps));

  const chosen = pool[0];
  if (!chosen?.downloadInfoUrl) throw new Error('Ссылка на поток не найдена');

  const xmlRes = await fetch(`${chosen.downloadInfoUrl}&format=json`, {
    headers: headers(token),
  });
  if (!xmlRes.ok) throw new Error(`Ошибка download-info (${xmlRes.status})`);

  let host = '';
  let path = '';
  let ts = '';
  let s = '';
  const text = await xmlRes.text();
  if (text.trim().startsWith('{')) {
    const info = JSON.parse(text);
    host = info.host;
    path = info.path;
    ts = info.ts;
    s = info.s;
  } else {
    const tag = (name: string) => text.match(new RegExp(`<${name}>([^<]+)</${name}>`))?.[1] || '';
    host = tag('host');
    path = tag('path');
    ts = tag('ts');
    s = tag('s');
  }

  if (!host || !path || !ts || !s) {
    throw new Error('Некорректный формат download-info');
  }

  const sign = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.MD5,
    `${SIGN_SALT}${path.slice(1)}${s}`
  );
  return `https://${host}/get-mp3/${sign}/${ts}${path}`;
}

export async function setTrackLike(
  token: string,
  uid: number,
  trackId: string,
  like: boolean
): Promise<void> {
  const op = like ? 'add-multiple' : 'remove';
  const body = new URLSearchParams({ 'track-ids': trackId }).toString();
  await fetch(`${API_BASE}/users/${uid}/likes/tracks/${op}`, {
    method: 'POST',
    headers: {
      ...headers(token),
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  });
}

export async function sendWaveFeedback(
  token: string,
  type: 'trackStarted' | 'trackFinished' | 'skip',
  trackId: string,
  batchId?: string,
  totalPlayedSeconds = 0
): Promise<void> {
  try {
    const q = batchId ? `?batch-id=${encodeURIComponent(batchId)}` : '';
    await fetch(`${API_BASE}/rotor/station/user:onyourwave/feedback${q}`, {
      method: 'POST',
      headers: {
        ...headers(token),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        type,
        timestamp: new Date().toISOString(),
        trackId,
        totalPlayedSeconds,
      }),
    });
  } catch {}
}

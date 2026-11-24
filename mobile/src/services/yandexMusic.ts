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
  artistId?: string;
  album?: string;
  albumId?: string;
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

export interface YandexPlaylist {
  kind: number;
  title: string;
  trackCount: number;
  coverUrl: string | null;
  ownerUid: number;
}

export interface YandexAlbum {
  id: string;
  title: string;
  artist: string;
  year?: number;
  trackCount: number;
  coverUrl: string | null;
}

export interface YandexArtist {
  id: string;
  name: string;
  coverUrl: string | null;
}

export interface YandexStation {
  id: string;
  name: string;
  coverUrl: string | null;
}

export type WaveMood = 'all' | 'active' | 'fun' | 'calm' | 'sad';
export type WaveDiversity = 'default' | 'favorite' | 'discover' | 'popular';

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
  const t = raw?.track || raw;
  if (!t || !t.id) return null;
  const artistsArr = Array.isArray(t.artists) ? t.artists : [];
  const artists = artistsArr.map((a: any) => a?.name).filter(Boolean).join(', ');
  const firstAlbum = t.albums?.[0];
  const coverUri = t.coverUri || firstAlbum?.coverUri || t.ogImage;
  return {
    id: String(t.id),
    title: String(t.title || 'Без названия'),
    artist: artists || 'Неизвестный исполнитель',
    artistId: artistsArr[0]?.id ? String(artistsArr[0].id) : undefined,
    album: firstAlbum?.title,
    albumId: firstAlbum?.id ? String(firstAlbum.id) : undefined,
    durationMs: Number(t.durationMs || 0),
    coverUrl: formatCover(coverUri),
    liked: Boolean(raw?.liked ?? t.liked),
    batchId,
  };
}

function mapAlbum(raw: any): YandexAlbum | null {
  if (!raw || !raw.id) return null;
  const artists = Array.isArray(raw.artists)
    ? raw.artists.map((a: any) => a?.name).filter(Boolean).join(', ')
    : '';
  return {
    id: String(raw.id),
    title: String(raw.title || 'Альбом'),
    artist: artists || 'Исполнитель',
    year: typeof raw.year === 'number' ? raw.year : undefined,
    trackCount: Number(raw.trackCount || 0),
    coverUrl: formatCover(raw.coverUri || raw.ogImage),
  };
}

function mapArtist(raw: any): YandexArtist | null {
  if (!raw || !raw.id) return null;
  return {
    id: String(raw.id),
    name: String(raw.name || 'Исполнитель'),
    coverUrl: formatCover(raw.cover?.uri || raw.ogImage),
  };
}

async function fetchTracksByIds(token: string, ids: string[]): Promise<YandexTrack[]> {
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
  return list.map((t) => mapTrack(t)).filter(Boolean) as YandexTrack[];
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

export async function getStationTracks(
  token: string,
  stationId = 'user:onyourwave',
  queueId?: string
): Promise<YandexTrack[]> {
  const q = queueId ? `?queue=${encodeURIComponent(queueId)}` : '';
  const res = await fetch(`${API_BASE}/rotor/station/${encodeURIComponent(stationId)}/tracks${q}`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Волна недоступна (${res.status})`);
  const json = await res.json();
  const batchId = json?.result?.batchId;
  const seq = json?.result?.sequence || [];
  return seq.map((item: any) => mapTrack(item, batchId)).filter(Boolean) as YandexTrack[];
}

export async function getMyWaveTracks(token: string, queueId?: string): Promise<YandexTrack[]> {
  return getStationTracks(token, 'user:onyourwave', queueId);
}

export async function setWaveSettings(
  token: string,
  moodEnergy: WaveMood,
  diversity: WaveDiversity
): Promise<void> {
  const res = await fetch(`${API_BASE}/rotor/station/user:onyourwave/settings2`, {
    method: 'POST',
    headers: {
      ...headers(token),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ moodEnergy, diversity }),
  });
  if (!res.ok) throw new Error(`Не удалось обновить Мою волну (${res.status})`);
}

export async function getRotorStations(token: string): Promise<YandexStation[]> {
  const res = await fetch(`${API_BASE}/rotor/stations/list`, { headers: headers(token) });
  if (!res.ok) throw new Error(`Станции недоступны (${res.status})`);
  const json = await res.json();
  const list: any[] = Array.isArray(json?.result) ? json.result : [];
  return list
    .filter((x) => x?.station?.id?.type && x?.station?.id?.tag)
    .slice(0, 30)
    .map((x) => ({
      id: `${x.station.id.type}:${x.station.id.tag}`,
      name: String(x.station.name || x.station.id.tag),
      coverUrl: formatCover(x.station.fullImageUrl || x.station.icon?.imageUrl || null),
    }));
}

export async function getLikedTrackIds(token: string, uid: number): Promise<string[]> {
  const likesRes = await fetch(`${API_BASE}/users/${uid}/likes/tracks`, {
    headers: headers(token),
  });
  if (!likesRes.ok) throw new Error(`Не удалось загрузить лайки (${likesRes.status})`);
  const likesJson = await likesRes.json();
  const rawList: any[] = likesJson?.result?.library?.tracks || [];
  return rawList.map((x) => String(x.id)).filter(Boolean);
}

export async function getLikedTracks(
  token: string,
  uid: number,
  onProgress?: (tracks: YandexTrack[], totalCount: number) => void
): Promise<YandexTrack[]> {
  const likesRes = await fetch(`${API_BASE}/users/${uid}/likes/tracks`, {
    headers: headers(token),
  });
  if (!likesRes.ok) throw new Error(`Не удалось загрузить лайки (${likesRes.status})`);
  const likesJson = await likesRes.json();
  const rawList: any[] = likesJson?.result?.library?.tracks || [];
  const ids = rawList
    .map((x) => (x.albumId ? `${x.id}:${x.albumId}` : String(x.id)))
    .filter(Boolean);

  if (ids.length === 0) return [];

  const firstBatchIds = ids.slice(0, 60);
  const firstTracks = (await fetchTracksByIds(token, firstBatchIds)).map((t) => ({
    ...t,
    liked: true,
  }));
  const all: YandexTrack[] = [...firstTracks];
  onProgress?.([...all], ids.length);

  const CHUNK = 250;
  for (let i = 60; i < ids.length; i += CHUNK * 2) {
    const slice1 = ids.slice(i, i + CHUNK);
    const slice2 = ids.slice(i + CHUNK, i + CHUNK * 2);
    const [b1, b2] = await Promise.all([
      fetchTracksByIds(token, slice1),
      slice2.length > 0 ? fetchTracksByIds(token, slice2) : Promise.resolve([]),
    ]);
    for (const tr of [...b1, ...b2]) {
      all.push({ ...tr, liked: true });
    }
    onProgress?.([...all], ids.length);
  }
  return all;
}

export async function getUserPlaylists(token: string, uid: number): Promise<YandexPlaylist[]> {
  const res = await fetch(`${API_BASE}/users/${uid}/playlists/list`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Не удалось загрузить плейлисты (${res.status})`);
  const json = await res.json();
  const rawList: any[] = Array.isArray(json?.result) ? json.result : [];
  return rawList
    .filter((pl) => pl && typeof pl.kind === 'number')
    .map((pl) => {
      const coverUri = pl.cover?.uri || pl.ogImage || pl.cover?.itemsUri?.[0] || null;
      return {
        kind: Number(pl.kind),
        title: String(pl.title || 'Плейлист'),
        trackCount: Number(pl.trackCount || 0),
        coverUrl: formatCover(coverUri),
        ownerUid: Number(pl.owner?.uid || uid),
      };
    });
}

export async function getPlaylistTracks(
  token: string,
  uid: number,
  kind: number,
  onProgress?: (tracks: YandexTrack[], totalCount: number) => void
): Promise<YandexTrack[]> {
  const res = await fetch(`${API_BASE}/users/${uid}/playlists/${kind}`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Не удалось открыть плейлист (${res.status})`);
  const json = await res.json();
  const items: any[] = json?.result?.tracks || [];
  if (items.length === 0) return [];

  const resolved: (YandexTrack | null)[] = items.map((item) =>
    item?.track ? mapTrack(item) : null
  );
  const missingIndices: number[] = [];
  const missingIds: string[] = [];
  for (let i = 0; i < items.length; i++) {
    if (!resolved[i] && items[i]?.id) {
      missingIndices.push(i);
      missingIds.push(
        items[i].albumId ? `${items[i].id}:${items[i].albumId}` : String(items[i].id)
      );
    }
  }

  const readyNow = resolved.filter(Boolean) as YandexTrack[];
  if (missingIds.length === 0) {
    onProgress?.(readyNow, items.length);
    return readyNow;
  }
  if (readyNow.length > 0) {
    onProgress?.(readyNow, items.length);
  }

  const CHUNK = 250;
  const byId = new Map<string, YandexTrack>();
  for (let i = 0; i < missingIds.length; i += CHUNK) {
    const chunk = await fetchTracksByIds(token, missingIds.slice(i, i + CHUNK));
    for (const tr of chunk) {
      byId.set(tr.id, tr);
    }
  }
  for (let k = 0; k < missingIndices.length; k++) {
    const idx = missingIndices[k];
    const fetched = byId.get(String(items[idx].id));
    if (fetched) resolved[idx] = fetched;
  }
  const finalOut = resolved.filter(Boolean) as YandexTrack[];
  onProgress?.(finalOut, items.length);
  return finalOut;
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

export async function searchYandexAll(
  token: string,
  query: string
): Promise<{
  tracks: YandexTrack[];
  albums: YandexAlbum[];
  artists: YandexArtist[];
}> {
  const q = query.trim();
  if (!q) return { tracks: [], albums: [], artists: [] };
  const url = `${API_BASE}/search?text=${encodeURIComponent(q)}&page=0&type=all`;
  const res = await fetch(url, { headers: headers(token) });
  if (!res.ok) throw new Error(`Ошибка поиска (${res.status})`);
  const json = await res.json();
  const r = json?.result || {};
  return {
    tracks: (r.tracks?.results || []).map((t: any) => mapTrack(t)).filter(Boolean) as YandexTrack[],
    albums: (r.albums?.results || []).map((a: any) => mapAlbum(a)).filter(Boolean) as YandexAlbum[],
    artists: (r.artists?.results || []).map((a: any) => mapArtist(a)).filter(Boolean) as YandexArtist[],
  };
}

export async function getChartTracks(token: string): Promise<YandexTrack[]> {
  const res = await fetch(`${API_BASE}/landing3/chart`, { headers: headers(token) });
  if (!res.ok) throw new Error(`Чарт недоступен (${res.status})`);
  const json = await res.json();
  const list: any[] = json?.result?.chart?.tracks || [];
  return list.map((item) => mapTrack(item)).filter(Boolean) as YandexTrack[];
}

export async function getAlbumTracks(
  token: string,
  albumId: string
): Promise<{ album: YandexAlbum | null; tracks: YandexTrack[] }> {
  const res = await fetch(`${API_BASE}/albums/${albumId}/with-tracks`, { headers: headers(token) });
  if (!res.ok) throw new Error(`Альбом недоступен (${res.status})`);
  const json = await res.json();
  const raw = json?.result;
  const album = mapAlbum(raw);
  const volumes: any[][] = raw?.volumes || [];
  const tracks: YandexTrack[] = [];
  for (const vol of volumes) {
    if (!Array.isArray(vol)) continue;
    for (const item of vol) {
      const mapped = mapTrack(item);
      if (mapped) tracks.push(mapped);
    }
  }
  return { album, tracks };
}

export async function getArtistTracks(token: string, artistId: string): Promise<YandexTrack[]> {
  const res = await fetch(`${API_BASE}/artists/${artistId}/tracks?page=0&page-size=40`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Треки исполнителя недоступны (${res.status})`);
  const json = await res.json();
  const list: any[] = json?.result?.tracks || [];
  return list.map((t) => mapTrack(t)).filter(Boolean) as YandexTrack[];
}

export async function getLikedArtists(token: string, uid: number): Promise<YandexArtist[]> {
  const res = await fetch(`${API_BASE}/users/${uid}/likes/artists`, { headers: headers(token) });
  if (!res.ok) return [];
  const json = await res.json();
  const list: any[] = Array.isArray(json?.result) ? json.result : [];
  return list.map((a) => mapArtist(a)).filter(Boolean) as YandexArtist[];
}

export async function getTrackLyrics(token: string, trackId: string): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/tracks/${trackId}/supplement`, { headers: headers(token) });
    if (!res.ok) return null;
    const json = await res.json();
    const text = json?.result?.lyrics?.fullLyrics;
    return typeof text === 'string' && text.trim() ? text.trim() : null;
  } catch {
    return null;
  }
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
  type: 'trackStarted' | 'trackFinished' | 'skip' | 'dislike',
  trackId: string,
  batchId?: string,
  totalPlayedSeconds = 0,
  stationId = 'user:onyourwave'
): Promise<void> {
  try {
    const q = batchId ? `?batch-id=${encodeURIComponent(batchId)}` : '';
    await fetch(`${API_BASE}/rotor/station/${encodeURIComponent(stationId)}/feedback${q}`, {
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

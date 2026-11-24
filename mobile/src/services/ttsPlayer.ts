/**
 * Sakura TTS Player — собирает чанки PCM16 24kHz (tts_chunk) в WAV и воспроизводит
 * голосовой ответ Сакуры через expo-audio с автоматическим приглушением музыки (ducking).
 */

import { AudioPlayer, createAudioPlayer } from 'expo-audio';
import { File, Paths } from 'expo-file-system';
import { Platform } from 'react-native';

function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) {
    out[i] = bin.charCodeAt(i);
  }
  return out;
}

function buildWav(pcmBytes: Uint8Array, sampleRate = 24000): Uint8Array {
  const numChannels = 1;
  const bitsPerSample = 16;
  const byteRate = (sampleRate * numChannels * bitsPerSample) / 8;
  const blockAlign = (numChannels * bitsPerSample) / 8;
  const dataSize = pcmBytes.length;
  const wav = new Uint8Array(44 + dataSize);
  const view = new DataView(wav.buffer);

  const writeAscii = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) wav[off + i] = s.charCodeAt(i);
  };

  writeAscii(0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeAscii(8, 'WAVE');
  writeAscii(12, 'fmt ');
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // PCM format
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeAscii(36, 'data');
  view.setUint32(40, dataSize, true);
  wav.set(pcmBytes, 44);
  return wav;
}

class TtsPlayerService {
  private chunks: Uint8Array[] = [];
  private sampleRate = 24000;
  private activeTurnId: string | null = null;
  private player: AudioPlayer | null = null;
  private statusSub: { remove: () => void } | null = null;
  private onSpeakingChange: ((speaking: boolean) => void) | null = null;
  private onDuckMusic: ((duck: boolean) => void) | null = null;

  setCallbacks(opts: {
    onSpeakingChange?: (speaking: boolean) => void;
    onDuckMusic?: (duck: boolean) => void;
  }) {
    this.onSpeakingChange = opts.onSpeakingChange || null;
    this.onDuckMusic = opts.onDuckMusic || null;
  }

  feedChunk(audioB64: string, sampleRate = 24000, turnId?: string) {
    if (!audioB64) return;
    if (turnId && this.activeTurnId && turnId !== this.activeTurnId) {
      this.chunks = [];
    }
    this.activeTurnId = turnId || this.activeTurnId;
    this.sampleRate = sampleRate || 24000;
    try {
      this.chunks.push(base64ToBytes(audioB64));
    } catch {}
  }

  async finishTurn(opts: { enabled: boolean; speed?: number; duckMusic?: boolean }) {
    const parts = this.chunks;
    const sr = this.sampleRate;
    this.chunks = [];
    this.activeTurnId = null;

    if (!opts.enabled || parts.length === 0) {
      return;
    }

    let totalLen = 0;
    for (const p of parts) totalLen += p.length;
    if (totalLen < 64) return;

    const pcm = new Uint8Array(totalLen);
    let offset = 0;
    for (const p of parts) {
      pcm.set(p, offset);
      offset += p.length;
    }

    const wav = buildWav(pcm, sr);

    try {
      let uri: string;
      if (Platform.OS === 'web') {
        const blob = new Blob([wav.buffer as ArrayBuffer], { type: 'audio/wav' });
        uri = URL.createObjectURL(blob);
      } else {
        const f = new File(Paths.cache, `sakura_tts_${Date.now()}.wav`);
        f.write(wav);
        uri = f.uri;
      }

      this.stop();
      if (opts.duckMusic) this.onDuckMusic?.(true);
      this.onSpeakingChange?.(true);

      const player = createAudioPlayer({ uri }, { updateInterval: 250 });
      if (opts.speed && opts.speed !== 1.0) {
        try {
          player.setPlaybackRate(opts.speed);
        } catch {}
      }

      this.player = player;
      this.statusSub = player.addListener('playbackStatusUpdate', (status) => {
        if (status.didJustFinish) {
          this.onSpeakingChange?.(false);
          if (opts.duckMusic) this.onDuckMusic?.(false);
          this.stop();
        }
      });

      player.play();
    } catch (e) {
      console.warn('[TtsPlayer] playback failed:', e);
      this.onSpeakingChange?.(false);
      if (opts.duckMusic) this.onDuckMusic?.(false);
    }
  }

  stop() {
    try {
      this.statusSub?.remove();
      this.statusSub = null;
      this.player?.remove();
      this.player = null;
    } catch {}
  }
}

export const ttsPlayer = new TtsPlayerService();

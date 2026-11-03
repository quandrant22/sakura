"""Генератор маленьких медиафайлов для тестов без ffmpeg: WAV (stdlib), MP3 (тихие
кадры MPEG-1 Layer III), FLAC (STREAMINFO без аудиокадров); теги — mutagen."""
import struct
import wave
from pathlib import Path


def make_wav(path: Path, seconds: float = 0.5, rate: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def make_mp3(path: Path, frames: int = 40, title=None, artist=None, album=None, track=None,
             cover: bytes | None = None) -> Path:
    """MPEG-1 Layer III 128 кбит/с 44.1 кГц, кадр 417 байт ≈ 26 мс."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    path.write_bytes(frame * frames)
    if any(v is not None for v in (title, artist, album, track, cover)):
        from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK
        tags = ID3()
        if title:
            tags.add(TIT2(encoding=3, text=title))
        if artist:
            tags.add(TPE1(encoding=3, text=artist))
        if album:
            tags.add(TALB(encoding=3, text=album))
        if track:
            tags.add(TRCK(encoding=3, text=str(track)))
        if cover:
            tags.add(APIC(encoding=3, mime="image/png", type=3, desc="cover", data=cover))
        tags.save(str(path))
    return path


def make_flac(path: Path, seconds: int = 2, rate: int = 44100, **tags) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = seconds * rate
    bits = (rate << 44) | ((2 - 1) << 41) | ((16 - 1) << 36) | total  # 20+3+5+36 = 64 бита
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6 + bits.to_bytes(8, "big") + b"\x00" * 16
    path.write_bytes(b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo)
    if tags:
        from mutagen.flac import FLAC
        f = FLAC(str(path))
        for k, v in tags.items():
            f[k] = str(v)
        f.save()
    return path


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8ffff3f0005fe02fea7d6a4"
    "0d0000000049454e44ae426082")

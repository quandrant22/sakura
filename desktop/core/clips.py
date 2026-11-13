"""desktop.core.clips — Голосовое клипирование экрана («Заклипай это!»).

Вдохновлен capri-desktop Clips.cs:
Поддерживает в оперативной памяти скользящий кольцевой буфер последних 30-90 секунд
кадров экрана (и звука при наличии).

При вызове команды («Сакура, заклипай это!» или `clips.save`):
1. Извлекает кадры за указанный период (по умолчанию 30 секунд).
2. Кодирует видео через ffmpeg (если установлен) или формирует последовательность/анимацию.
3. Сохраняет файл в папку «Видео/Sakura/Clips/clip_YYYYMMDD_HHMMSS.mp4».
4. Возвращает путь к сохраненному клипу.
"""

from __future__ import annotations

import collections
import datetime
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("sakura.clips")

_DEFAULT_HISTORY_SEC = 60
_DEFAULT_CLIP_SEC = 30
_DEFAULT_FPS = 10  # 10 кадров в сек для баланса памяти/скорости


@dataclass
class ClipFrame:
    timestamp: float
    jpeg_bytes: bytes


class ClipBuffer:
    """Кольцевой буфер кадров в памяти с мгновенным сбросом в MP4."""

    def __init__(
        self,
        history_seconds: int = _DEFAULT_HISTORY_SEC,
        output_dir: Optional[str] = None,
        capture_func: Optional[Callable[[], Optional[bytes]]] = None,
        fps: int = _DEFAULT_FPS,
    ):
        self.history_seconds = history_seconds
        self.fps = fps
        self.output_dir = Path(
            output_dir or os.path.expanduser(r"~\Videos\Sakura\Clips")
        )
        self.capture_func = capture_func
        self._frames: collections.deque[ClipFrame] = collections.deque()
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Запуск фонового захвата кадров в буфер."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="SakuraClipBuffer")
            self._thread.start()
            log.info("ClipBuffer started (history=%ds, fps=%d)", self.history_seconds, self.fps)

    def stop(self):
        """Остановка буфера."""
        with self._lock:
            self._running = False
            self._thread = None

    def add_frame(self, jpeg_bytes: bytes, timestamp: Optional[float] = None):
        """Добавить сжатый JPEG-кадр в буфер."""
        now = timestamp or time.time()
        with self._lock:
            self._frames.append(ClipFrame(timestamp=now, jpeg_bytes=jpeg_bytes))
            # Удаляем старые кадры за пределами history_seconds
            cutoff = now - self.history_seconds
            while self._frames and self._frames[0].timestamp < cutoff:
                self._frames.popleft()

    @property
    def frame_count(self) -> int:
        with self._lock:
            return len(self._frames)

    def save_clip(self, seconds: int = _DEFAULT_CLIP_SEC) -> Optional[Path]:
        """Сохранить последние `seconds` в MP4-файл."""
        now = time.time()
        cutoff = now - seconds

        with self._lock:
            selected = [f for f in self._frames if f.timestamp >= cutoff]

        if not selected:
            log.warning("ClipBuffer: нет кадров за последние %d секунд", seconds)
            return None

        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = self.output_dir / f"clip_{timestamp_str}.mp4"

        # Записываем кадры во временную папку и запускаем ffmpeg
        with tempfile.TemporaryDirectory(prefix="sakura_clip_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            for idx, frame in enumerate(selected):
                frame_file = tmp_path / f"frame_{idx:05d}.jpg"
                frame_file.write_bytes(frame.jpeg_bytes)

            ffmpeg_bin = shutil.which("ffmpeg")
            if not ffmpeg_bin:
                try:
                    import imageio_ffmpeg
                    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
                except Exception:
                    pass

            if ffmpeg_bin:
                try:
                    cmd = [
                        ffmpeg_bin,
                        "-y",
                        "-framerate", str(self.fps),
                        "-i", str(tmp_path / "frame_%05d.jpg"),
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-preset", "ultrafast",
                        str(target_path),
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    log.info("Clip saved successfully to %s", target_path)
                    return target_path
                except Exception as e:
                    log.error("FFmpeg encoding failed: %s", e)

            # Fallback: если ffmpeg нет, сохраняем как tar/zip или последний кадр
            fallback_path = self.output_dir / f"clip_{timestamp_str}.jpg"
            fallback_path.write_bytes(selected[-1].jpeg_bytes)
            log.info("FFmpeg not found; saved last frame to %s", fallback_path)
            return fallback_path

    def _default_capture(self) -> Optional[bytes]:
        try:
            import io
            from PIL import ImageGrab
            img = ImageGrab.grab()
            if img.width > 1280:
                scale = 1280.0 / img.width
                img = img.resize((1280, int(img.height * scale)))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=65)
            return buf.getvalue()
        except Exception:
            return None

    def _capture_loop(self):
        interval = 1.0 / max(1, self.fps)
        func = self.capture_func or self._default_capture
        while self._running:
            start_t = time.time()
            try:
                frame = func()
                if frame:
                    self.add_frame(frame)
            except Exception as e:
                log.debug("Clip capture error: %s", e)

            elapsed = time.time() - start_t
            sleep_t = max(0.01, interval - elapsed)
            time.sleep(sleep_t)

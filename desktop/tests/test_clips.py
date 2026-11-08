"""Тесты для desktop.core.clips"""

import time
from pathlib import Path
import pytest
from desktop.core.clips import ClipBuffer


def test_clip_buffer_add_and_prune(tmp_path):
    buffer = ClipBuffer(history_seconds=2, output_dir=str(tmp_path), fps=10)

    dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF"

    buffer.add_frame(dummy_jpeg, timestamp=10.0)
    buffer.add_frame(dummy_jpeg, timestamp=10.5)
    buffer.add_frame(dummy_jpeg, timestamp=11.0)
    assert buffer.frame_count == 3

    # Add frame at timestamp 13.0, cutoff should be 11.0 (13 - 2)
    buffer.add_frame(dummy_jpeg, timestamp=13.0)
    # Timestamps 10.0 and 10.5 should be pruned
    assert buffer.frame_count == 2


def test_clip_buffer_save(tmp_path):
    buffer = ClipBuffer(history_seconds=10, output_dir=str(tmp_path))
    dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"

    buffer.add_frame(dummy_jpeg, timestamp=time.time() - 1.0)
    buffer.add_frame(dummy_jpeg, timestamp=time.time())

    saved = buffer.save_clip(seconds=5)
    assert saved is not None
    assert saved.exists()
    assert saved.stat().st_size > 0

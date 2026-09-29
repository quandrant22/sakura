"""Benchmark voice-model latency, token usage, and image input."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import struct
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODELS = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemma-4-26b-a4b-it",
    "gemma-4-31b-it",
)
PHRASES = (
    ("command", "Включи музыку и сделай звук потише."),
    ("question", "Почему после дождя воздух кажется свежее?"),
    ("chatter", "Сегодня такой спокойный вечер, хочется просто поболтать."),
)
IMAGE_PROMPT = "Опиши скриншот: назови цвет верхней панели и фигуры в центральной и нижней областях."


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def make_screenshot() -> bytes:
    """Create a small synthetic UI screenshot with distinctive colored shapes."""
    width, height = 320, 180
    pixels = bytearray([240, 242, 244] * width * height)

    def fill(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        row = bytes(color) * (x1 - x0)
        for y in range(y0, y1):
            start = (y * width + x0) * 3
            pixels[start:start + len(row)] = row

    fill(0, 0, width, 22, (220, 55, 65))
    fill(12, 34, 78, 168, (255, 255, 255))
    fill(90, 34, 308, 105, (255, 255, 255))
    fill(112, 52, 176, 91, (45, 112, 220))
    fill(190, 52, 280, 91, (248, 190, 45))
    fill(90, 117, 308, 168, (255, 255, 255))
    fill(110, 130, 160, 155, (45, 165, 95))
    fill(174, 130, 286, 155, (220, 55, 65))

    raw = b"".join(b"\x00" + pixels[y * width * 3:(y + 1) * width * 3]
                   for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0))
            + _png_chunk(b"IDAT", zlib.compress(raw))
            + _png_chunk(b"IEND", b""))


class _ModelsProxy:
    def __init__(self, models):
        self._models = models
        self.usage = None

    def __getattr__(self, name):
        operation = getattr(self._models, name)
        if name != "generate_content_stream":
            return operation

        def capture_usage(**kwargs):
            for chunk in operation(**kwargs):
                metadata = getattr(chunk, "usage_metadata", None)
                if metadata is not None:
                    self.usage = metadata
                yield chunk

        return capture_usage


class _ClientProxy:
    def __init__(self, client):
        self.models = _ModelsProxy(client.models)


def _usage_counts(metadata) -> tuple[int | None, int | None]:
    if metadata is None:
        return None, None
    return (
        getattr(metadata, "prompt_token_count", None),
        getattr(metadata, "candidates_token_count", None),
    )


def _error_code(error: Exception) -> str:
    if str(error) == "empty stream":
        return "EMPTY_STREAM"
    for attr in ("status_code", "code"):
        value = getattr(error, attr, None)
        if value is not None:
            name = getattr(value, "name", None)
            return f"{value}/{name}" if name else str(value)
    match = re.search(r"\b(400|401|403|404|408|429|500|502|503|504)\b", str(error))
    if match:
        status = match.group(1)
        label = re.search(r"\b(UNAVAILABLE|RESOURCE_EXHAUSTED|INTERNAL)\b", str(error))
        return f"{status}/{label.group(1)}" if label else status
    return type(error).__name__


async def _run_call(llm, key: str, model: str, system: str, contents,
                    kind: str, phrase_type: str, index: int) -> tuple[dict, str]:
    original_get_client = llm.get_client
    proxy = _ClientProxy(original_get_client(key))
    llm.get_client = lambda _key: proxy
    started = time.perf_counter()
    first_token = None
    pieces = []
    error = None
    try:
        async for token in llm.stream_tokens(
            contents, system=system, model=model, max_tokens=180,
            timeout=120, api_key=key,
        ):
            if first_token is None:
                first_token = time.perf_counter() - started
            pieces.append(token)
    except Exception as exc:
        error = exc
    finally:
        llm.get_client = original_get_client

    elapsed = time.perf_counter() - started
    text = "".join(pieces).strip()
    if not text and error is None:
        error = RuntimeError("empty stream")
    prompt_tokens, candidate_tokens = _usage_counts(proxy.models.usage)
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "kind": kind,
        "phrase_type": phrase_type,
        "index": index,
        "ttft_s": round(first_token, 3) if first_token is not None else None,
        "total_s": round(elapsed, 3),
        "prompt_token_count": prompt_tokens,
        "candidates_token_count": candidate_tokens,
        "error_code": _error_code(error) if error else None,
        "error_type": type(error).__name__ if error else None,
    }
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return record, text


async def _build_system_without_memory(prompt, query: str) -> str:
    from memory import db

    original = db.get_memory_context
    db.get_memory_context = lambda: ""
    try:
        return await prompt._build_system(query=query)
    finally:
        db.get_memory_context = original


def _summary(records: list[dict], model: str, kind: str) -> tuple[float | None, ...]:
    selected = [r for r in records if r["model"] == model and r["kind"] == kind]
    ttft = sorted(r["ttft_s"] for r in selected if r["ttft_s"] is not None)
    p90 = ttft[max(0, math.ceil(0.9 * len(ttft)) - 1)] if ttft else None
    full = [r["total_s"] for r in selected]
    prompt = [r["prompt_token_count"] for r in selected
              if r["prompt_token_count"] is not None]
    errors = sum(r["error_code"] is not None or r["ttft_s"] is None for r in selected)
    return (
        median(ttft) if ttft else None,
        p90,
        median(full) if full else None,
        mean(prompt) if prompt else None,
        errors / len(selected) if selected else None,
    )


def _fmt(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.2f}{suffix}"


async def run(output: Path, dry_run: bool) -> None:
    import config
    import sakura_core.llm as llm
    import sakura_core.prompt as prompt
    from google.genai import types

    from config import get_active_key

    if not config.GEMINI_KEYS:
        raise SystemExit("No GEMINI_KEY_* configured; benchmark not started.")
    api_key = get_active_key()
    if not api_key:
        raise SystemExit("No active Gemini API key; benchmark not started.")

    image_bytes = make_screenshot()
    records: list[dict] = []
    print(f"Models: {', '.join(MODELS)}; calls planned: 46", flush=True)
    if dry_run:
        query = PHRASES[0][1]
        system = await prompt._build_system(query=query)
        contents = llm._build_contents(query, history_limit=config.VOICE_HISTORY_LIMIT)
        no_memory = await _build_system_without_memory(prompt, query)
        print(json.dumps({
            "dry_run": True,
            "voice_history_limit": config.VOICE_HISTORY_LIMIT,
            "history_content_count": len(contents),
            "system_chars": len(system),
            "system_without_memory_chars": len(no_memory),
            "generated_png_bytes": len(image_bytes),
        }, ensure_ascii=False))
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("", encoding="utf-8")

    async def perform(model: str, kind: str, index: int, query: str,
                      phrase_type: str, no_memory: bool = False,
                      with_image: bool = False) -> str:
        system = (await _build_system_without_memory(prompt, query) if no_memory
                  else await prompt._build_system(query=query))
        contents = llm._build_contents(
            query, history_limit=config.VOICE_HISTORY_LIMIT,
        )
        if with_image:
            contents[-1].parts.append(types.Part.from_bytes(
                data=image_bytes, mime_type="image/png",
            ))
        record, text = await _run_call(
            llm, api_key, model, system, contents, kind, phrase_type, index,
        )
        records.append(record)
        with output.open("a", encoding="utf-8") as result_file:
            result_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return text

    for model in MODELS:
        count = 10 if model.startswith("gemini-") else 6
        for index in range(count):
            phrase_type, query = PHRASES[index % len(PHRASES)]
            await perform(model, "baseline", index + 1, query, phrase_type)
            if model.startswith("gemini-") and index + 1 < count:
                await asyncio.sleep(5)
            elif (not model.startswith("gemini-") and (index + 1) % 2 == 0
                  and index + 1 < count):
                await asyncio.sleep(65)

    memory_model = "gemma-4-26b-a4b-it"
    for index in range(6):
        phrase_type, query = PHRASES[index % len(PHRASES)]
        await perform(memory_model, "without_memory", index + 1, query, phrase_type,
                      no_memory=True)
        if (index + 1) % 2 == 0 and index + 1 < 6:
            await asyncio.sleep(65)

    for model in MODELS:
        for index in range(2):
            text = await perform(model, "image", index + 1, IMAGE_PROMPT, "image",
                                 with_image=True)
            print(f"VISION {model} #{index + 1}: {text or '[empty response]'}", flush=True)
            if model.startswith("gemini-") and index == 0:
                await asyncio.sleep(5)

    print("\nBaseline summary (median, p90 TTFT; median total; avg input; errors):")
    print("| Model | TTFT median | TTFT p90 | Total median | Input avg | Errors |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for model in MODELS:
        ttft, p90, total, input_avg, error_rate = _summary(records, model, "baseline")
        print(f"| {model} | {_fmt(ttft, 's')} | {_fmt(p90, 's')} | "
              f"{_fmt(total, 's')} | {_fmt(input_avg)} | "
              f"{_fmt(error_rate * 100 if error_rate is not None else None, '%')} |")

    baseline_mem = _summary(records, memory_model, "baseline")[3]
    without_mem = _summary(records, memory_model, "without_memory")[3]
    print(f"\nGemma memory ablation: baseline avg input={_fmt(baseline_mem)}, "
          f"without memory={_fmt(without_mem)}, delta="
          f"{_fmt(baseline_mem - without_mem if baseline_mem is not None and without_mem is not None else None)} tokens.")
    for model in MODELS:
        base_input = _summary(records, model, "baseline")[3]
        image_input = _summary(records, model, "image")[3]
        delta = image_input - base_input if image_input is not None and base_input is not None else None
        print(f"Image {model}: avg input={_fmt(image_input)}, added vs baseline={_fmt(delta)} tokens.")
    print(f"Raw measurements: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "scripts" / "bench_models_results.jsonl")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build the real prompt/history/image without calling Gemini")
    args = parser.parse_args()
    asyncio.run(run(args.output, args.dry_run))


if __name__ == "__main__":
    main()
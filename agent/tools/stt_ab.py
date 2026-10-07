"""A/B-стенд сравнения STT-движков.

Режимы:
  record — запись фраз с микрофона в agent/stt_samples/NNN.wav
           (та же MIC_RATE и Silero VAD, что в core.hearing),
           после записи спрашивает метку: q=вопрос, c=команда, s=реплика;
  run    — прогоняет все WAV через движки и печатает таблицу
           (файл, метка, текст каждого движка, время распознавания),
           полный результат сохраняет в agent/stt_samples/results.json.

Движки:
  A — текущий агент: gigaam v2_ctc + _post_process (рабочий venv);
  B — gigaam v3_e2e_ctc (только agent/venv-stt-test);
  C — gigaam v3_ctc + _post_process (только agent/venv-stt-test).

Запуск (из каталога agent):
  venv\Scripts\python.exe tools\stt_ab.py record
  venv\Scripts\python.exe tools\stt_ab.py run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

SAMPLES_DIR = AGENT_ROOT / "stt_samples"
LABELS_PATH = SAMPLES_DIR / "labels.json"
RESULTS_PATH = SAMPLES_DIR / "results.json"
VENV_WORK_PY = AGENT_ROOT / "venv" / "Scripts" / "python.exe"
VENV_TEST_PY = AGENT_ROOT / "venv-stt-test" / "Scripts" / "python.exe"

# engine -> (описание, python.exe, нужен отдельный venv)
ENGINES = {
    "A": ("gigaam v2_ctc + _post_process (рабочий venv)", VENV_WORK_PY, False),
    "B": ("gigaam v3_e2e_ctc (venv-stt-test)", VENV_TEST_PY, True),
    "C": ("gigaam v3_ctc + _post_process (venv-stt-test)", VENV_TEST_PY, True),
}


# ── метки ─────────────────────────────────────────────────────────

def _load_labels() -> dict:
    if LABELS_PATH.is_file():
        return json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    return {}


def _save_labels(labels: dict) -> None:
    LABELS_PATH.write_text(
        json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _next_path() -> Path:
    n = 1
    while (SAMPLES_DIR / f"{n:03d}.wav").exists():
        n += 1
    return SAMPLES_DIR / f"{n:03d}.wav"


# ── record ────────────────────────────────────────────────────────

def _capture(vad):
    """Повторяет hearing._capture: старт по VAD, конец по тишине.

    Возвращает bytes (int16 PCM) или None, если речь не началась.
    """
    import config
    import sounddevice as sd
    from core import hearing

    vad.reset()
    pcm = bytearray()
    speaking = False
    silence = 0.0
    start = time.monotonic()
    frame_dur = hearing.SileroVAD.FRAME / config.MIC_RATE

    with sd.RawInputStream(samplerate=config.MIC_RATE, channels=1,
                           dtype="int16", blocksize=config.MIC_BLOCK) as stream:
        while True:
            data = bytes(stream.read(config.MIC_BLOCK)[0])
            elapsed = time.monotonic() - start
            if vad.speech_prob(data) >= config.VAD_THRESHOLD:
                speaking = True
                silence = 0.0
                pcm.extend(data)
            elif speaking:
                pcm.extend(data)
                silence += frame_dur
                if silence >= config.VAD_END_SILENCE:
                    break
            elif elapsed >= config.VAD_START_TIMEOUT:
                return None
            if elapsed >= config.MAX_UTTER_SEC:
                break
    return bytes(pcm)


def cmd_record() -> None:
    import config
    from core import hearing

    SAMPLES_DIR.mkdir(exist_ok=True)
    labels = _load_labels()
    vad = hearing.SileroVAD()
    print(f"Запись в {SAMPLES_DIR} (MIC_RATE={config.MIC_RATE}, "
          f"VAD_THRESHOLD={config.VAD_THRESHOLD}, "
          f"VAD_END_SILENCE={config.VAD_END_SILENCE}s).")
    print("Запущенный агент тоже слушает микрофон — не говорите слово "
          "для пробуждения, чтобы его не дёргать.")

    while True:
        try:
            cmd = input("[Enter — запись, q — выход]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if cmd in ("q", "quit", "выход"):
            break
        if cmd:
            continue

        print("  ...запись, говорите...")
        try:
            pcm = _capture(vad)
        except KeyboardInterrupt:
            print("  прервано")
            continue
        if not pcm:
            print("  речь не обнаружена, повторите")
            continue

        path = _next_path()
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(config.MIC_RATE)
            w.writeframes(pcm)

        dur = len(pcm) / 2 / config.MIC_RATE
        while True:
            label = input(
                f"  {path.name} ({dur:.1f}с) метка "
                "[q=вопрос, c=команда, s=реплика]: ",
            ).strip().lower()
            if label in ("q", "c", "s"):
                break
            print("    нужна q, c или s")
        labels[path.name] = label
        _save_labels(labels)
        print(f"  сохранено {path.name} ({dur:.1f}с, метка {label})")


# ── движки (работают в своём venv; запускаются как subprocess) ────

def _read_wav(path: Path):
    """WAV → float32 mono 16 kHz (как в hearing)."""
    import numpy as np

    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path}: нужен 16-бит WAV, sampwidth={width}")
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        a = a.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        # Запись стенда всегда 16 kHz; страховка для чужих WAV.
        n_out = max(1, int(len(a) * 16000 / rate))
        a = np.interp(np.linspace(0, len(a) - 1, n_out),
                      np.arange(len(a)), a).astype(np.float32)
    return a


def _versions(extra: dict | None = None) -> dict:
    import importlib.metadata as md
    import platform

    info = {"python": platform.python_version()}
    try:
        info["torch"] = __import__("torch").__version__
    except Exception:
        info["torch"] = "-"
    try:
        info["gigaam"] = md.version("gigaam")
    except Exception:
        info["gigaam"] = "-"
    if extra:
        info.update(extra)
    return info


def _decode_v3(model, audio, engine: str) -> str:
    """Распознавание v3 через forward+decoding (путь как в hearing)."""
    import torch

    wav = torch.from_numpy(audio).unsqueeze(0)
    length = torch.tensor([wav.shape[-1]])
    with torch.inference_mode():
        enc, enc_len = model.forward(wav, length)
        dec = model.decoding.decode(model.head, enc, enc_len)[0]
    # gigaam 0.2.0: decode() возвращает (text, token_ids, frames);
    # в 0.1.0 это была сразу строка — обрабатываем оба варианта.
    text = dec[0] if isinstance(dec, tuple) else dec
    text = (text or "").strip()
    if engine == "C":
        from core import hearing
        text = hearing._post_process(text)
    return text


def _emit(obj: dict) -> None:
    """Одна JSON-строка в stdout — так subprocess отдаёт результат."""
    print(json.dumps(obj, ensure_ascii=True))


def _run_engine(engine: str, files: list[Path]) -> None:
    """Внутренний режим: печатает meta-строку и строку на каждый файл."""
    load_s = None
    if engine == "A":
        from core import hearing

        t0 = time.monotonic()
        model = hearing._get_gigaam_model()
        load_s = time.monotonic() - t0
        if model is None:
            _emit({"kind": "meta", "engine": engine,
                   "error": "gigaam недоступен в рабочем venv"})
            return
        rec = hearing.SpeechRecognizer.__new__(hearing.SpeechRecognizer)  # без __init__
        import config
        meta = {"kind": "meta", "engine": engine,
                "model": getattr(config, "GIGAAM_MODEL", "v2_ctc"),
                "load_s": round(load_s, 3)}
        meta.update(_versions())
        _emit(meta)

        def decode(audio):
            # тот же путь, что у агента: v2_ctc + _post_process внутри
            return rec._run_gigaam(model, audio)
    else:
        import torch

        torch.set_num_threads(1)  # как в core.hearing при импорте
        import gigaam

        name = "v3_e2e_ctc" if engine == "B" else "v3_ctc"
        t0 = time.monotonic()
        model = gigaam.load_model(name, device="cpu")
        load_s = time.monotonic() - t0
        meta = {"kind": "meta", "engine": engine, "model": name,
                "load_s": round(load_s, 3)}
        meta.update(_versions())
        _emit(meta)

        def decode(audio):
            return _decode_v3(model, audio, engine)

    for path in files:
        audio = _read_wav(path)
        t0 = time.monotonic()
        try:
            text = decode(audio)
            err = None
        except Exception as e:  # чтобы упавший файл не ронял пакет
            text, err = "", f"{type(e).__name__}: {e}"
        rec_s = time.monotonic() - t0
        row = {"kind": "row", "engine": engine, "file": path.name,
               "text": text, "rec_s": round(rec_s, 3)}
        if err:
            row["error"] = err
        _emit(row)


# ── run (оркестратор) ─────────────────────────────────────────────

def _spawn_engine(engine: str, py: Path, files: list[Path]):
    """Запускает движок в subprocess. Возвращает (meta, rows, error)."""
    import os
    import subprocess

    cmd = [str(py), str(Path(__file__).resolve()), "_engine", engine,
           "--files", *[str(p) for p in files]]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            cwd=str(AGENT_ROOT), env=env, timeout=1800,
        )
    except OSError as e:
        return None, {}, f"не удалось запустить {py}: {e}"

    meta, rows = None, {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("kind") == "meta":
            meta = obj
        elif obj.get("kind") == "row":
            rows[obj["file"]] = obj

    err = None
    if proc.returncode != 0 and not rows:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        err = f"exit {proc.returncode}: {tail[-1] if tail else 'нет вывода'}"
    elif meta and meta.get("error"):
        err = meta["error"]
    return meta, rows, err


def _cell(text: str, width: int = 36) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def cmd_run() -> None:
    wavs = sorted(SAMPLES_DIR.glob("*.wav"))
    if not wavs:
        print(f"Нет WAV в {SAMPLES_DIR} — сначала режим record.")
        return
    labels = _load_labels()

    metas: dict = {}
    all_rows: dict = {}
    errors: dict = {}
    for eng, (desc, py, needs_test_venv) in ENGINES.items():
        if needs_test_venv and not py.is_file():
            errors[eng] = f"нет {py} — создайте venv-stt-test"
            print(f"[{eng}] пропущен: {errors[eng]}")
            continue
        exe = py if py.is_file() else Path(sys.executable)
        print(f"[{eng}] {desc} ...")
        meta, rows, err = _spawn_engine(eng, exe, wavs)
        metas[eng], all_rows[eng] = meta, rows
        if err:
            errors[eng] = err
            print(f"   ошибка: {err}")
        elif meta:
            print(f"   модель {meta.get('model')}, загрузка {meta.get('load_s')}с, "
                  f"python {meta.get('python')}, torch {meta.get('torch')}, "
                  f"gigaam {meta.get('gigaam')}")

    print()
    header = (f"{'файл':<9} {'м':<2} | {'A текст':<36} {'A,с':>5} | "
              f"{'B текст':<36} {'B,с':>5} | {'C текст':<36} {'C,с':>5}")
    print(header)
    print("-" * min(len(header), 200))
    rows_out = []
    for p in wavs:
        name = p.name
        label = labels.get(name, "-")
        line = f"{name:<9} {label:<2} | "
        row = {"file": name, "label": label}
        for eng in ("A", "B", "C"):
            r = all_rows.get(eng, {}).get(name)
            if r:
                line += f"{_cell(r['text']):<36} {r['rec_s']:>5.2f} | "
                row[eng] = {"text": r["text"], "rec_s": r["rec_s"]}
                if r.get("error"):
                    row[eng]["error"] = r["error"]
            else:
                line += f"{'—':<36} {'—':>5} | "
                row[eng] = None
        rows_out.append(row)
        print(line)

    for eng, err in errors.items():
        print(f"{eng}: {err}")

    payload = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "engines": {
            eng: {"desc": desc, "meta": metas.get(eng),
                  "error": errors.get(eng)}
            for eng, (desc, _py, _sep) in ENGINES.items()
        },
        "rows": rows_out,
    }
    SAMPLES_DIR.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"\nПолный результат: {RESULTS_PATH}")


# ── CLI ───────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="A/B-стенд STT")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("record", help="запись фраз с метками q/c/s")
    sub.add_parser("run", help="прогон всех WAV через движки A/B/C")
    p_eng = sub.add_parser("_engine")
    p_eng.add_argument("engine", choices=("A", "B", "C"))
    p_eng.add_argument("--files", nargs="+", type=Path, required=True)
    args = ap.parse_args()

    if args.cmd == "record":
        cmd_record()
    elif args.cmd == "run":
        cmd_run()
    else:
        _run_engine(args.engine, args.files)


if __name__ == "__main__":
    main()

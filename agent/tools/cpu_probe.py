"""Sample Sakura process CPU usage for one 60-second operating mode."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

import psutil

AGENT_ROOT = Path(__file__).resolve().parents[1]


def _find_agent_pid() -> int:
    candidates = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
        try:
            info = process.info
            command = info.get("cmdline") or []
            cwd = info.get("cwd")
            if not cwd or Path(cwd).resolve() != AGENT_ROOT:
                continue
            if not any(Path(arg.strip('"')).name.lower() == "sakura.py" for arg in command):
                continue
            if "python" not in (info.get("name") or "").lower():
                continue
            candidates.append(process)
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue

    candidate_pids = {process.pid for process in candidates}
    parent_pids = set()
    for process in candidates:
        try:
            parent_pid = process.ppid()
            if parent_pid in candidate_pids:
                parent_pids.add(parent_pid)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    leaves = [process.pid for process in candidates if process.pid not in parent_pids]
    if len(leaves) != 1:
        choices = ", ".join(map(str, leaves)) or "none"
        raise RuntimeError(f"Could not uniquely identify Sakura process; candidate PIDs: {choices}. Pass --pid.")
    return leaves[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("idle-no-music", "idle-with-music", "gaming"),
        help="Operating mode to label this 60-second sample",
    )
    parser.add_argument("--pid", type=int, help="Sakura PID; autodetected if omitted")
    parser.add_argument("--interval", type=float, default=60.0,
                        help="Sample duration in seconds (default: 60)")
    args = parser.parse_args()

    if args.interval <= 0:
        parser.error("--interval must be positive")

    try:
        pid = args.pid or _find_agent_pid()
        process = psutil.Process(pid)
        if not process.is_running():
            raise RuntimeError(f"Process {pid} is not running")
        cores = psutil.cpu_count(logical=True) or 1
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"Sampling mode={args.mode} pid={pid} interval_s={args.interval:g}; keep this mode unchanged.", flush=True)
        process.cpu_percent(interval=None)
        time.sleep(args.interval)
        raw_percent = process.cpu_percent(interval=None)
        normalized_percent = raw_percent / cores
        ended = datetime.now(timezone.utc).isoformat(timespec="seconds")
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, RuntimeError) as exc:
        print(f"CPU probe failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"mode={args.mode} pid={pid} started_utc={started} ended_utc={ended} "
        f"sample_s={args.interval:g} logical_cores={cores} "
        f"process_cpu_pct={raw_percent:.2f} "
        f"normalized_cpu_pct={normalized_percent:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Sakura Agent v2 — Launcher

Starts Rust core, Python executor, and UI overlay.
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
import threading
from pathlib import Path

BASE_DIR = Path(__file__).parent
if sys.platform == "win32":
    RUST_BINARY = BASE_DIR / "core" / "target" / "release" / "sakura-core.exe"
else:
    RUST_BINARY = BASE_DIR / "core" / "target" / "release" / "sakura-core"
PYTHON_EXECUTOR = BASE_DIR / "executor" / "main.py"


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def check_rust_binary() -> bool:
    return RUST_BINARY.exists()


def build_rust():
    print("Building Rust core...")
    ret = subprocess.run(
        ["cargo", "build", "--release"],
        cwd=BASE_DIR / "core",
    )
    return ret.returncode == 0


def run_with_ui():
    """Run with PyQt6 overlay."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QSharedMemory, QTimer
    from ui.overlay import SakuraOverlay

    app = QApplication(sys.argv)
    app.setApplicationName("Sakura")
    app.setQuitOnLastWindowClosed(False)

    # Singleton guard
    guard = QSharedMemory("sakura-agent-v2")
    if not guard.create(1):
        print("Sakura already running")
        return

    overlay = SakuraOverlay()
    overlay.show()

    # Start Rust core
    rust_proc = None
    if check_rust_binary():
        logging.info(f"Starting Rust core: {RUST_BINARY}")
        logging.info(f"File exists: {RUST_BINARY.exists()}")
        logging.info(f"File size: {RUST_BINARY.stat().st_size if RUST_BINARY.exists() else 'N/A'}")
        
        try:
            rust_proc = subprocess.Popen(
                [str(RUST_BINARY)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(BASE_DIR / "core" / "target" / "release"),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            logging.info(f"Rust core started: PID {rust_proc.pid}")
            overlay.set_connected(True)
        except Exception as e:
            logging.error(f"Failed to start Rust core: {e}")
            logging.info("Trying without creationflags...")
            rust_proc = subprocess.Popen(
                [str(RUST_BINARY)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(BASE_DIR / "core" / "target" / "release"),
            )

    # Start Python executor
    python_proc = None
    if rust_proc:
        python_proc = subprocess.Popen(
            [sys.executable, str(PYTHON_EXECUTOR)],
            stdin=rust_proc.stdout,
            stdout=rust_proc.stdin,
            stderr=subprocess.PIPE,
        )
        logging.info(f"Python executor started: PID {python_proc.pid}")

    # Monitor processes
    def check_processes():
        if rust_proc and rust_proc.poll() is not None:
            # Read stderr for crash info
            if rust_proc.stderr:
                stderr_data = rust_proc.stderr.read()
                if stderr_data:
                    logging.error(f"Rust core stderr: {stderr_data.decode('utf-8', errors='replace')}")
            overlay.set_connected(False)
            logging.error(f"Rust core crashed with code: {rust_proc.returncode}")
        if python_proc and python_proc.poll() is not None:
            logging.error("Python executor crashed")

    monitor_timer = QTimer()
    monitor_timer.timeout.connect(check_processes)
    monitor_timer.start(5000)

    # Shutdown handler
    def shutdown():
        if rust_proc:
            rust_proc.terminate()
        if python_proc:
            python_proc.terminate()
        app.quit()

    import atexit
    atexit.register(shutdown)

    sys.exit(app.exec())


def run_headless():
    """Run without UI."""
    if not check_rust_binary():
        print("Rust binary not found. Building...")
        if not build_rust():
            print("Build failed. Running Python only...")
            os.execv(sys.executable, [sys.executable, str(PYTHON_EXECUTOR)])
            return

    rust_proc = subprocess.Popen(
        [str(RUST_BINARY)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    python_proc = subprocess.Popen(
        [sys.executable, str(PYTHON_EXECUTOR)],
        stdin=rust_proc.stdout,
        stdout=rust_proc.stdin,
        stderr=subprocess.PIPE,
    )

    logging.info(f"Rust core: PID {rust_proc.pid}")
    logging.info(f"Python executor: PID {python_proc.pid}")

    def shutdown(sig, frame):
        rust_proc.terminate()
        python_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            if rust_proc.poll() is not None or python_proc.poll() is not None:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown(None, None)


def main():
    parser = argparse.ArgumentParser(description="Sakura Agent v2")
    parser.add_argument("--python-only", action="store_true",
                        help="Run without Rust core")
    parser.add_argument("--headless", action="store_true",
                        help="Run without UI")
    parser.add_argument("--build", action="store_true",
                        help="Build Rust core only")

    args = parser.parse_args()
    setup_logging()

    if args.build:
        if build_rust():
            print("Build successful!")
        else:
            print("Build failed!")
        return

    if args.python_only:
        os.execv(sys.executable, [sys.executable, str(PYTHON_EXECUTOR)])
        return

    if args.headless:
        run_headless()
        return

    # Default: run with UI
    try:
        run_with_ui()
    except ImportError:
        print("PyQt6 not found, running headless...")
        run_headless()


if __name__ == "__main__":
    main()

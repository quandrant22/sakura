# Sakura Agent v2

High-performance voice assistant agent with Rust audio core.

## Architecture

```
┌─────────────────────────────────────┐
│  Rust Core (audio + NLU + protocol)│
│  - VAD: 32ms latency               │
│  - STT: Vosk streaming             │
│  - Commands: TOML + fuzzy matching │
│  - Lua: Scripting engine           │
└──────────┬──────────────────────────┘
           │ stdin/stdout JSON
┌──────────▼──────────────────────────┐
│  Python Executor (Windows APIs)     │
│  - apps, browser, music, system    │
│  - screenshot, volume              │
└─────────────────────────────────────┘
```

## Installation

### 1. Install Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Build Rust core

```bash
cargo build --release
```

### 4. Download Vosk models

Download from https://alphacephei.com/vosk/models:
- `vosk-model-small-ru-0.22`
- `vosk-model-ru-0.42`

Place in `~/.local/share/sakura/` (Linux) or `%LOCALAPPDATA%/sakura/` (Windows).

### 5. Configure

Edit `config/default.toml`:
```toml
[agent]
device_id = "pc"
vps_url = "ws://your-vps:8765"
ws_token = "your-token"
```

## Usage

```bash
python launch.py              # Start with Rust core
python launch.py --python-only  # Python only
python launch.py --build        # Build Rust core
```

## Adding Commands

Create a TOML file in `commands/`:

```toml
[[commands]]
id = "my_command"
action = "my_action"
args = "{param}"
priority = 10

[commands.phrases]
ru = ["моя команда {param}"]

[commands.slots.param]
entity = "parameter name"
```

## Project Structure

```
sakura-agent/
├── core/               # Rust audio core
│   ├── src/
│   │   ├── main.rs
│   │   ├── audio/      # Capture, ring buffer, VAD
│   │   ├── stt/        # Wake word, STT
│   │   ├── nlu/        # Intent, slots
│   │   ├── commands/   # TOML registry
│   │   ├── lua/        # Scripting
│   │   ├── protocol/   # IPC
│   │   └── ipc/        # Communication
│   └── Cargo.toml
├── executor/           # Python Windows APIs
├── commands/           # TOML commands
├── config/             # Configuration
├── launch.py           # Launcher
└── requirements.txt
```

## License

Proprietary

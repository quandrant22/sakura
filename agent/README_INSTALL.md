# Sakura Agent — PC Agent for Sakura Voice Assistant

High-performance PC agent with Rust audio core and Python Windows integration.

## Architecture

```
┌─────────────────────────────────────┐
│  Rust Core (audio + NLU + protocol)│
│  - VAD: 32ms latency               │
│  - STT: Vosk streaming             │
│  - Command matching: fuzzy + slots │
│  - IPC: WebSocket to VPS           │
└──────────┬──────────────────────────┘
           │ stdin/stdout JSON
┌──────────▼──────────────────────────┐
│  Python Executor (Windows APIs)     │
│  - apps, browser, music, kettle    │
│  - screenshot, dictate             │
└─────────────────────────────────────┘
```

## Installation

### 1. Install Rust

```bash
# Windows/Linux/Mac
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

### 2. Install Python dependencies

```bash
cd agent
pip install -r requirements.txt
```

### 3. Build Rust audio core

```bash
cd agent/core-rust
cargo build --release
```

The binary will be at `target/release/sakura-audio-core`.

### 4. Download Vosk models

Download from https://alphacephei.com/vosk/models:
- `vosk-model-small-ru-0.22` (wake word detection)
- `vosk-model-ru-0.42` (speech recognition)

Place them in:
- Windows: `%LOCALAPPDATA%/sakura/`
- Linux: `~/.local/share/sakura/`

### 5. Configure

Create `.env` file in `agent/` directory:

```
VPS_WS_URL=ws://your-vps:8765
DEVICE_ID=pc
WS_TOKEN=your-token-here
```

## Usage

### Start with Rust audio core (recommended)

```bash
cd agent
python launch.py
```

### Start with Python audio only

```bash
cd agent
python launch.py --python-only
```

### Build Rust core only

```bash
cd agent
python launch.py --build
```

### Headless mode (no UI)

```bash
cd agent
python launch.py --headless
```

## Development

### Project structure

```
agent/
├── core/
│   ├── protocol.py      # Typed IPC protocol
│   ├── commands.py      # TOML command registry
│   ├── settings.py      # Persistent settings
│   ├── bridge.py        # Python ↔ Rust bridge
│   ├── agent.py         # Main agent logic
│   ├── hearing.py       # Python audio (legacy)
│   ├── voice.py         # TTS playback
│   ├── hands.py         # Command execution
│   ├── browser.py       # Browser control
│   ├── music.py         # Music control
│   ├── kettle.py        # Smart kettle
│   └── ...
├── commands/            # TOML command definitions
│   ├── browser/
│   ├── music/
│   ├── system/
│   └── ...
├── core-rust/           # Rust audio core
│   ├── src/
│   │   ├── audio/       # Audio capture + ring buffer
│   │   ├── vad/         # Voice Activity Detection
│   │   ├── stt/         # Speech-to-Text
│   │   ├── commands/    # Command matching
│   │   ├── protocol/    # IPC protocol
│   │   └── ipc/         # Communication
│   └── Cargo.toml
├── ui/                  # PyQt6 overlay
├── launch.py            # Launcher script
└── requirements.txt
```

### Adding new commands

1. Create a TOML file in `commands/` directory:

```toml
[[commands]]
id = "my_command"
type = "action"
action = "my_action"
args = "{param}"
priority = 10
description = "My custom command"

phrases.ru = [
    "моя команда {param}",
]

keywords = ["关键词"]

[commands.slots.param]
entity = "parameter name"
```

2. The command will be automatically loaded on startup.

### IPC Protocol

Events (agent → VPS):
- `registered` — Agent registered
- `ping` — Heartbeat
- `voice_command` — Voice command recognized
- `command_result` — Command executed
- `speech_recognized` — Speech transcribed

Actions (VPS → agent):
- `command` — Execute command
- `tts_chunk` — TTS audio
- `tts_end` — End of TTS
- `reply` — Text reply
- `mood_update` — Mood update

## Troubleshooting

### "No input device available"

Check microphone permissions and audio drivers.

### "Vosk model not found"

Download models from https://alphacephei.com/vosk/models and place in the correct directory.

### "Rust binary not found"

Run `python launch.py --build` to compile the Rust core.

### Audio crackling

Try adjusting `MIC_BLOCK` in `config.py` (default 512 = 32ms).

## License

See LICENSE.txt

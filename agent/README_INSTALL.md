# Sakura Agent — PC Agent for Sakura Voice Assistant

Python PC agent: Vosk + Silero VAD (`core/hearing.py`), PyQt6 overlay,
полное управление Windows (apps, browser, music, kettle, screenshot, dictate).

## Architecture

```
┌─────────────────────────────────────┐
│  Python Agent (sakura.py)           │
│  - hearing.py: Vosk STT + Silero VAD│
│  - agent.py: WS-клиент VPS          │
│  - hands/browser/music: исполнение  │
│  - ui/: PyQt6 overlay + tray        │
└──────────┬──────────────────────────┘
           │ WebSocket
┌──────────▼──────────────────────────┐
│  VPS (Сакура: main.py + ws_handlers)│
└─────────────────────────────────────┘
```

Экспериментальное ядро на Rust не подключено — см. `docs/experimental/`.

## Installation

### 1. Install Python dependencies

```bash
cd agent
pip install -r requirements.txt
```

### 2. Download Vosk models

Download from https://alphacephei.com/vosk/models:
- `vosk-model-small-ru-0.22` (wake word detection)
- `vosk-model-ru-0.42` (speech recognition)

Place them in:
- Windows: `%LOCALAPPDATA%/sakura/`
- Linux: `~/.local/share/sakura/`

### 3. Configure

Create `.env` file in `agent/` directory:

```
VPS_WS_URL=ws://your-vps:8765
DEVICE_ID=pc
WS_TOKEN=your-token-here
```

## Usage

Единственная поддерживаемая точка входа — `sakura.py` (QApplication + tray);
сборка — `build.bat` (см. BUILD.md).

```bash
cd agent
python sakura.py
```

## Development

### Project structure

```
agent/
├── sakura.py             # Точка входа (QApplication, Agent, Overlay, tray)
├── core/
│   ├── agent.py          # Main agent logic + WS-цикл
│   ├── hearing.py        # Vosk STT + Silero VAD
│   ├── voice.py          # TTS playback
│   ├── hands.py          # Command execution
│   ├── browser.py        # Browser control
│   ├── music.py          # Music control (SMTC + YM API)
│   ├── kettle.py         # Smart kettle
│   └── ...
├── commands/             # TOML command definitions
│   ├── browser/
│   ├── music/
│   ├── system/
│   └── ...
├── extension/            # MV3 browser extension
├── ui/                   # PyQt6 overlay
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

[commands.slots.param]
entity = "parameter name"
```

2. The command will be automatically loaded on startup.

### IPC Protocol

Events (agent → VPS):
- `register` — Agent registered
- `ping` — Heartbeat
- `command_result` — Command executed
- `screen_context` — Periodic screenshot for awareness

Actions (VPS → agent):
- `command` — Execute command
- `tts_chunk` / `tts_end` — TTS audio
- `reply` — Text reply

### Экспериментальное: ядро на Rust

Заготовка VAD/STT-ядра на Rust и старый лаунчер перенесены в
`docs/experimental/` — не подключены, не собирать. Что нужно для
подключения: `docs/experimental/README.md`.

## Troubleshooting

### "No input device available"

Check microphone permissions and audio drivers.

### "Vosk model not found"

Download models from https://alphacephei.com/vosk/models and place in the correct directory.

### Audio crackling

Try adjusting `MIC_BLOCK` in `config.py` (default 512 = 32ms).

## License

See LICENSE.txt

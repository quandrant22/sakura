# ТЗ: Игровой режим Сакуры — Агент (Windows)

## Обзор

Расширение агента для полноценного игрового режима:
- Минималистичный оверлей с лепестками сакуры
- Контекстные подсказки и гайды
- Умное управление музыкой и уведомлениями
- Запись хайлайтов
- Профили производительности

## Архитектура

```
Сервер (VPS)                    Агент (Windows)
┌─────────────────┐             ┌─────────────────────────┐
│ game_hub.py     │◄── ping ───│ agent.py (heartbeat)     │
│ (контекст, LLM) │             │                         │
│                 │── command ─►│ _run_command()           │
│                 │             │   ├─ overlay.py          │
│                 │             │   ├─ game_recorder.py    │
│                 │             │   ├─ notification_mgr.py │
│                 │             │   └─ perf_profiles.py    │
└─────────────────┘             └─────────────────────────┘
```

---

## 1. Оверлей «Sakura Game HUD»

### 1.1 Текущее состояние
- `overlay.py:801` — `set_game_mode()` скрывает все виджеты, оставляет только `SphereCore`
- Размер: 150×150px, click-through включён
- Лепестки уже анимируются в `SphereCore`

### 1.2 Что нужно реализовать

#### 1.2.1 Цветовая полоса настроения
**Файл:** `agent/ui/overlay.py` — метод `SphereCore.paintEvent()`

Добавить в игровой режим тонкую горизонтальную полосу под ядром:
```python
# В paintEvent, после отрисовки ядра:
if self._game_mode:
    # Полоса настроения — 3px высотой, 80% ширины
    bar_y = h - 20
    bar_w = w * 0.8
    bar_x = (w - bar_w) / 2
    
    # Цвет от mood_color (передаётся с сервера)
    mood_c = self._mood_color or QColor("#9a7fb5")
    mood_c.setAlpha(180)
    
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(mood_c)
    p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, 3), 1.5, 1.5)
    
    # Мягкое свечение
    glow = QColor(mood_c)
    glow.setAlpha(40)
    p.setBrush(glow)
    p.drawRoundedRect(QRectF(bar_x - 2, bar_y - 2, bar_w + 4, 7), 3, 3)
```

#### 1.2.2 Лепестки при уведомлениях
**Файл:** `agent/ui/overlay.py` — метод `show_notification()`

Уже есть `_Petal` класс. При уведомлении — увеличить скорость и количество:
```python
def show_notification(self, text: str, duration_ms: int = 4000, burst: bool = False):
    # ... существующий код ...
    
    if burst:
        # Burst-анимация: временно увеличиваем количество лепестков
        self._notification_burst = True
        QTimer.singleShot(2000, lambda: setattr(self, '_notification_burst', False))
```

В `SphereCore._tick()`:
```python
# В начале _tick:
target_petals = 7
if getattr(self, '_notification_burst', False):
    target_petals = 20

while len(self._petals) < target_petals:
    self._petals.append(_Petal(self.width(), self.height(), top=True))
while len(self._petals) > target_petals:
    self._petals.pop()
```

#### 1.2.3 Мини-текст в игровом режиме
**Файл:** `agent/ui/overlay.py` — новый виджет `GameMiniLabel`

```python
class GameMiniLabel(QLabel):
    """Минималистичный текст в игровом режиме — под ядром."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Segoe UI", 8))
        self.setStyleSheet("color: rgba(200,180,220,160); background: transparent;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMaximumWidth(140)
        self.setWordWrap(True)
    
    def update_text(self, text: str):
        self.setText(text)
        self.adjustSize()
```

Размещение: под ядром, по центру. Обновляется при:
- Смене настроения игры
- Получении уведомления
- Команде сервера `overlay_text`

---

## 2. Запись хайлайтов (`game_recorder.py`)

### 2.1 Назначение
Автоматический захват последних 30 секунд экрана при наступлении игровых событий.

### 2.2 Реализация

**Файл:** `agent/core/game_recorder.py`

```python
"""
game_recorder.py — Кольцевой буфер скриншотов для хайлайтов.

Сохраняет последние N скриншотов в RAM.
При событии — дампит в файл.
"""
import asyncio
import base64
import os
import time
from collections import deque
from pathlib import Path

class GameRecorder:
    def __init__(self, max_frames: int = 30, fps: float = 1.0):
        self._buffer: deque = deque(maxlen=max_frames)
        self._fps = fps
        self._last_capture = 0.0
        self._recording = False
        self._save_dir = Path("recordings")
        self._save_dir.mkdir(exist_ok=True)
    
    def start(self):
        self._recording = True
        self._last_capture = time.time()
    
    def stop(self):
        self._recording = False
        self._buffer.clear()
    
    def capture_frame(self, screenshot_b64: str):
        """Вызывается при каждом скриншоте."""
        if not self._recording:
            return
        now = time.time()
        if now - self._last_capture < 1.0 / self._fps:
            return
        self._buffer.append({
            "time": now,
            "data": screenshot_b64,
        })
        self._last_capture = now
    
    def save_highlight(self, reason: str = "event") -> str | None:
        """Сохраняет буфер в файл. Возвращает путь."""
        if not self._buffer:
            return None
        
        ts = time.strftime("%Y%m%d_%H%M%S")
        folder = self._save_dir / f"highlight_{ts}"
        folder.mkdir(exist_ok=True)
        
        # Сохраняем скриншоты
        for i, frame in enumerate(self._buffer):
            img_data = base64.b64decode(frame["data"])
            path = folder / f"frame_{i:03d}.jpg"
            path.write_bytes(img_data)
        
        # Сохраняем метаданные
        meta = {
            "reason": reason,
            "frames": len(self._buffer),
            "time_range": [
                self._buffer[0]["time"],
                self._buffer[-1]["time"],
            ],
        }
        import json
        (folder / "meta.json").write_text(json.dumps(meta, indent=2))
        
        self._buffer.clear()
        log.info(f"[recorder] Хайлайт сохранён: {folder}")
        return str(folder)


# Глобальный экземпляр
_recorder: GameRecorder | None = None

def get_recorder() -> GameRecorder:
    global _recorder
    if _recorder is None:
        _recorder = GameRecorder()
    return _recorder
```

### 2.3 Интеграция с агентом

**Файл:** `agent/core/agent.py` — в `_recv_loop()`:

```python
# При получении скриншота от сервера:
elif kind == "command" and data.get("action") == "screenshot:":
    # Сохраняем в кольцевой буфер
    try:
        from core.game_recorder import get_recorder
        recorder = get_recorder()
        if recorder._recording:
            # Скриншот уже в pending — нужно перехватить
            pass
    except Exception:
        pass
```

### 2.4 Серверная команда

**Сервер:** `main.py` — новые команды:
- `game_record:start` — начать запись
- `game_record:stop` — остановить
- `game_record:save` — сохранить хайлайт

---

## 3. Умная музыка (`game_music.py`)

### 3.1 Назначение
Автоматическая смена музыки в зависимости от контекста игры.

### 3.2 Логика

| Настроение игры | Музыка |
|----------------|--------|
| calm (исследование) | Спокойные треки, ambient |
| intense (бой) | Энергичные треки, рок/электро |
| farming | Фоновая музыка, lo-fi |
| boss | Интенсивная, эпичная |
| victory | Радостная, победная |

### 3.3 Реализация

**Файл:** `agent/core/game_music.py`

```python
"""
game_music.py — Контекстная музыка для игрового режима.

Сервер передаёт mood → агент переключает плейлист.
"""
import logging
from core.music import music_command

log = logging.getLogger("sakura.game_music")

# Маппинг настроения → плейлист/жанр
_MOOD_PLAYLISTS = {
    "calm":        {"query": "ambient calm gaming", "action": "music_search"},
    "intense":     {"query": "epic intense gaming", "action": "music_search"},
    "farming":     {"query": "lo-fi chill gaming", "action": "music_search"},
    "boss":        {"query": "boss battle epic", "action": "music_search"},
    "exploration": {"query": "adventure exploration", "action": "music_search"},
    "victory":     {"query": "victory celebration", "action": "music_search"},
}

_current_mood = None

async def on_mood_change(new_mood: str):
    """Вызывается при смене настроения игры."""
    global _current_mood
    if new_mood == _current_mood:
        return
    
    old = _current_mood
    _current_mood = new_mood
    
    playlist = _MOOD_PLAYLISTS.get(new_mood)
    if playlist:
        log.info(f"[game_music] {old} → {new_mood}: {playlist['query']}")
        try:
            # Только если музыка уже играет — переключаем
            # Если не играет — не трогаем (пусть решает пользователь)
            pass  # Пока логируем, позже добавим auto-switch
        except Exception as e:
            log.error(f"[game_music] Ошибка: {e}")
```

### 3.4 Серверная команда

**Сервер:** `main.py` — при смене `game_hub.mood`:
```python
# В обработчике голоса, после set_game_mood():
if new_mood != old_mood and ws_dev:
    await ws_dev.send(json.dumps({
        "type": "command",
        "action": f"game_mood:{new_mood}",
    }))
```

---

## 4. Фильтрация уведомлений (`notification_mgr.py`)

### 4.1 Назначение
Во время игры — пропускать только важные уведомления, остальное в очередь.

### 4.2 Приоритеты

| Приоритет | Примеры | Действие |
|-----------|---------|----------|
| CRITICAL | Вылет игры, ошибка системы | Сразу показать |
| HIGH | Сообщение от VIP,deadline | Показать через 5 сек |
| NORMAL | Обычные сообщения | В очередь |
| LOW | Проактивные, рекомендации | Не показывать |

### 4.3 Реализация

**Файл:** `agent/core/notification_mgr.py`

```python
"""
notification_mgr.py — Умная фильтрация уведомлений в игровом режиме.
"""
import time
from dataclasses import dataclass, field
from enum import IntEnum

class Priority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3

@dataclass
class QueuedNotification:
    text: str
    priority: Priority
    timestamp: float
    source: str = ""

class NotificationManager:
    def __init__(self):
        self._queue: list[QueuedNotification] = []
        self._game_mode = False
        self._max_queue = 20
        self._flush_interval = 300  # 5 минут
    
    def set_game_mode(self, on: bool):
        self._game_mode = on
        if not on:
            self._flush_queue()
    
    def push(self, text: str, priority: Priority = Priority.NORMAL, source: str = ""):
        notif = QueuedNotification(
            text=text, priority=priority,
            timestamp=time.time(), source=source,
        )
        
        if not self._game_mode:
            # Не в игре — показываем сразу
            return notif
        
        if priority >= Priority.CRITICAL:
            return notif  # Показать сразу
        
        if priority >= Priority.HIGH:
            # Показать через 5 сек (если не появится критичнее)
            self._queue.append(notif)
            return None
        
        # NORMAL/LOW — в очередь
        if len(self._queue) < self._max_queue:
            self._queue.append(notif)
        return None
    
    def _flush_queue(self):
        """Показать все queued уведомления."""
        if not self._queue:
            return
        
        # Сортируем по приоритету
        self._queue.sort(key=lambda n: n.priority, reverse=True)
        
        # Показываем топ-3
        for notif in self._queue[:3]:
            # Emit через bus
            pass
        
        self._queue.clear()
    
    def get_queue_info(self) -> dict:
        return {
            "count": len(self._queue),
            "top": self._queue[0].text if self._queue else None,
        }
```

---

## 5. Профили производительности (`perf_profiles.py`)

### 5.1 Назначение
Автоматическое переключение профилей Windows под конкретную игру.

### 5.2 Профили

| Профиль | CPU | GPU | Приоритет |
|---------|-----|-----|-----------|
| Balanced | 50% | Auto | По умолчанию |
| Performance | 100% | Max | Тяжёлые игры |
| Quiet | 30% | Low | Лёгкие игры/фарм |
| Battery | 20% | Min | Нет розетки |

### 5.3 Реализация

**Файл:** `agent/core/perf_profiles.py`

```python
"""
perf_profiles.py — Управление профилями производительности.

Использует PowerShell для переключения плана электропитания.
"""
import asyncio
import logging
import subprocess

log = logging.getLogger("sakura.perf")

# GUID планов электропитания Windows
_PROFILES = {
    "balanced":    "381b4222-f694-41f0-9685-ff5bb260df2e",
    "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "saver":       "a1841308-3541-4fab-bc81-f71556f20b4a",
}

async def set_profile(profile: str):
    """Переключает план электропитания."""
    guid = _PROFILES.get(profile)
    if not guid:
        log.warning(f"[perf] Неизвестный профиль: {profile}")
        return False
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "powercfg", "/setactive", guid,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        log.info(f"[perf] Профиль: {profile}")
        return True
    except Exception as e:
        log.error(f"[perf] Ошибка: {e}")
        return False

async def get_current_profile() -> str:
    """Определяет текущий профиль."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "powercfg", "/getactivescheme",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        active_guid = out.decode().strip().split()[1]
        for name, guid in _PROFILES.items():
            if guid == active_guid:
                return name
    except Exception:
        pass
    return "balanced"

# Маппинг игр → профили
_GAME_PROFILES = {
    "minecraft": "balanced",
    "cyberpunk": "performance",
    "elden ring": "performance",
    "cs2": "performance",
    "valorant": "performance",
    "terraria": "quiet",
    "stardew valley": "quiet",
}

async def auto_set_for_game(game_name: str):
    """Автоматически выбирает профиль по игре."""
    profile = _GAME_PROFILES.get(game_name.lower(), "balanced")
    await set_profile(profile)
    log.info(f"[perf] Авто-профиль для {game_name}: {profile}")
```

---

## 6. Интеграция: WebSocket протокол

### 6.1 Новые типы сообщений

**Сервер → Агент:**

| Тип | Описание | Пример |
|-----|----------|--------|
| `game_mood:{mood}` | Смена настроения игры | `game_mood:intense` |
| `game_highlight` | Сохранить хайлайт | `{"type":"game_highlight","reason":"boss_fight"}` |
| `overlay_text:{text}` | Текст под ядром | `overlay_text:В битве с боссом` |
| `perf_profile:{name}` | Смена профиля | `perf_profile:performance` |
| `notification:{text}` | Уведомление с приоритетом | `{"type":"notification","text":"...","priority":"high"}` |

**Агент → Сервер:**

| Тип | Описание | Пример |
|-----|----------|--------|
| `game_event` | Игровое событие | `{"type":"game_event","event":"boss_spawn","game":"Elden Ring"}` |
| `game_stats` | Статистика сессии | `{"type":"game_stats","duration":3600,"highlights":5}` |

### 6.2 Обработка на агенте

**Файл:** `agent/core/agent.py` — в `_recv_loop()`:

```python
elif kind == "game_mood":
    mood = data.get("mood", data.get("action", "").replace("game_mood:", ""))
    if mood:
        self.bus.emit("game_mood", mood=mood)
        try:
            from core.game_music import on_mood_change
            await on_mood_change(mood)
        except Exception:
            pass

elif kind == "game_highlight":
    reason = data.get("reason", "manual")
    try:
        from core.game_recorder import get_recorder
        path = get_recorder().save_highlight(reason)
        if path:
            log.info(f"[game] Хайлайт: {path}")
    except Exception:
        pass

elif kind == "overlay_text":
    text = data.get("text", "")
    self.bus.emit("overlay_text", text=text)

elif kind == "perf_profile":
    profile = data.get("profile", data.get("action", "").replace("perf_profile:", ""))
    if profile:
        try:
            from core.perf_profiles import set_profile
            await set_profile(profile)
        except Exception:
            pass

elif kind == "notification":
    text = data.get("text", "")
    priority = data.get("priority", "normal")
    self.bus.emit("notification", text=text, priority=priority)
```

---

## 7. Требования к реализации

### 7.1 Приоритеты

| # | Фича | Сложность | Приоритет |
|---|-------|-----------|-----------|
| 1 | Цветовая полоса в оверлее | Низкая | Высокий |
| 2 | Уведомления с burst-лепестками | Низкая | Высокий |
| 3 | Мини-текст под ядром | Низкая | Средний |
| 4 | Кольцевой буфер (хайлайты) | Средняя | Средний |
| 5 | Умная фильтрация уведомлений | Средняя | Средний |
| 6 | Профили производительности | Низкая | Низкий |
| 7 | Контекстная музыка | Средняя | Низкий |

### 7.2 Зависимости

- PyQt6 (уже есть)
- `powercfg` (встроенный Windows)
- Новые файлы: `game_recorder.py`, `notification_mgr.py`, `perf_profiles.py`, `game_music.py`

### 7.3 Тестирование

1. Включить игровой режим → проверить что полоса появляется
2. Отправить уведомление → проверить burst-лепестки
3. Запустить запись → сделать скриншот → проверить буфер
4. Переключить профиль → проверить `powercfg /getactivescheme`

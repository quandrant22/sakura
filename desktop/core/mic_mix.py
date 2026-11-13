"""desktop.core.mic_mix — Маршрутизация голоса Сакуры в микрофон (VB-CABLE / Steam Mic).

Вдохновлен capri-desktop MicMix.cs:
Позволяет собеседникам в Discord, Telegram, Zoom, Teams и играх слышать Сакуру:
1. Обнаруживает виртуальные аудиоустройства (VB-Audio Virtual Cable, Steam Streaming Mic).
2. Позволяет воспроизводить TTS Сакуры напрямую в виртуальный кабель.
3. Может смешивать реальный микрофон пользователя с голосом Сакуры, чтобы один CABLE Output служил единым микрофоном в Discord.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger("sakura.mic_mix")

_CABLE_KEYWORDS = ("cable input", "vb-audio", "steam streaming microphone", "virtual audio cable")


@dataclass
class AudioDevice:
    name: str
    id: str
    is_cable: bool = False
    is_input: bool = True


class MicMixManager:
    """Управление виртуальным кабелем и микшированием голоса."""

    def __init__(self, chosen_cable: Optional[str] = None):
        self.chosen_cable = chosen_cable
        self.active_cable_device: Optional[AudioDevice] = None

    def find_virtual_cables(self) -> List[AudioDevice]:
        """Поиск установленных виртуальных аудиокабелей в системе."""
        devices: List[AudioDevice] = []
        if platform.system() != "Windows":
            return devices

        try:
            # Проверяем через PowerShell WMI / PnP устройства
            cmd = "Get-CimInstance Win32_SoundDevice | Select-Object Name, DeviceID | ConvertTo-Json"
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                import json
                try:
                    data = json.loads(proc.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    for item in data:
                        name = item.get("Name", "")
                        dev_id = item.get("DeviceID", "")
                        is_cable = any(k in name.lower() for k in _CABLE_KEYWORDS)
                        devices.append(AudioDevice(name=name, id=dev_id, is_cable=is_cable))
                except Exception as e:
                    log.debug("Error parsing sound devices JSON: %s", e)
        except Exception as e:
            log.warning("Could not query sound devices: %s", e)

        return devices

    def get_preferred_cable(self) -> Optional[AudioDevice]:
        """Возвращает предпочтительный кабель для вывода речи Сакуры."""
        cables = [d for d in self.find_virtual_cables() if d.is_cable]
        if not cables:
            return None
        if self.chosen_cable:
            for c in cables:
                if self.chosen_cable.lower() in c.name.lower():
                    return c
        return cables[0]

    def is_cable_available(self) -> bool:
        return self.get_preferred_cable() is not None

"""desktop.core.game_hud.telemetry.scrap_mechanic — Нативный двусторонний телеметрия-мост для Scrap Mechanic.

Включает:
  - Чтение $SURVIVAL_DATA/sakura_state.json (координаты игрока, взгляд, HP, рюкзаки, лифты, боты)
  - Вычисление относительной навигации относительно взгляда («прямо», «чуть левее», «налево на 90°», «сзади»)
  - Запись команд в $SURVIVAL_DATA/sakura_cmd.json (tp_to_bag, tp_to_elevator, heal, godmode_on/off, kill_nearby_bots)
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from desktop.core.game_hud.telemetry.base import TelemetryProvider
from desktop.core.game_hud.types import GameState

log = logging.getLogger("sakura.game_hud.scrap_mechanic")

DEFAULT_SM_PATHS = [
    r"C:\Games\Scrap Mechanic",
    r"D:\Games\Scrap Mechanic",
    r"E:\Games\Scrap Mechanic",
    r"C:\Program Files (x86)\Steam\steamapps\common\Scrap Mechanic",
    r"D:\SteamLibrary\steamapps\common\Scrap Mechanic",
]


def find_scrap_mechanic_dir() -> Optional[str]:
    """Поиск корневой директории игры Scrap Mechanic."""
    # 1. Проверяем apps_cache.json
    try:
        from desktop.core import config
        cache_path = os.path.join(os.path.dirname(config.APPS_FILE) or ".", "apps_cache.json")
        if os.path.isfile(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            exe_path = data.get("scrapmechanic") or data.get("release")
            if exe_path and os.path.isfile(exe_path):
                # exe находится в <root>/Release/ScrapMechanic.exe
                root = os.path.dirname(os.path.dirname(os.path.abspath(exe_path)))
                if os.path.isdir(os.path.join(root, "Survival")):
                    return root
    except Exception as e:
        log.debug("[scrap_mechanic] Ошибка проверки apps_cache: %s", e)

    # 2. Проверяем стандартные пути
    for p in DEFAULT_SM_PATHS:
        if os.path.isdir(os.path.join(p, "Survival")):
            return p

    return None


def calculate_relative_navigation(
    px: float, py: float, pz: float,
    dx: float, dy: float, dz: float,
    tx: float, ty: float, tz: float,
) -> Tuple[str, float, str]:
    """
    Вычисляет человекочитаемое направление от текущего взгляда игрока до цели.
    
    Возвращает:
      (direction_str, distance_m, height_str)
      - direction_str: "прямо", "чуть правее", "направо на 90°", "сзади", "чуть левее", "налево на 90°" и т.д.
      - distance_m: дистанция в метрах (округлена до 1 знака)
      - height_str: "на этом этаже", "выше на X м", "ниже на X м"
    """
    # Вектор от игрока к цели
    vx = tx - px
    vy = ty - py
    vz = tz - pz

    dist = math.sqrt(vx * vx + vy * vy + vz * vz)
    dist_round = round(dist, 1)

    # Высота (Scrap Mechanic Z — вертикаль)
    if abs(vz) < 2.5:
        height_str = "на этом этаже"
    elif vz >= 2.5:
        height_str = f"выше на {abs(vz):.1f}м"
    else:
        height_str = f"ниже на {abs(vz):.1f}м"

    # Горизонтальный угол
    # Нормализуем горизонтальный вектор взгляда (dx, dy)
    len_look_2d = math.sqrt(dx * dx + dy * dy)
    len_target_2d = math.sqrt(vx * vx + vy * vy)

    if len_look_2d < 1e-4 or len_target_2d < 1e-4:
        return "прямо", dist_round, height_str

    ndx = dx / len_look_2d
    ndy = dy / len_look_2d

    nvx = vx / len_target_2d
    nvy = vy / len_target_2d

    # Скалярное и векторное произведение в плоскости XY
    # Положительный угол — поворот направо, отрицательный — налево
    dot = ndx * nvx + ndy * nvy
    cross_right = ndy * nvx - ndx * nvy

    angle_rad = math.atan2(cross_right, dot)
    angle_deg = math.degrees(angle_rad)

    # Определение направления
    abs_ang = abs(angle_deg)
    if abs_ang <= 12.0:
        dir_str = "прямо"
    elif 12.0 < angle_deg <= 65.0:
        dir_str = "чуть правее"
    elif 65.0 < angle_deg <= 115.0:
        dir_str = "направо на 90°"
    elif 115.0 < angle_deg <= 160.0:
        dir_str = "сзади справа"
    elif -65.0 <= angle_deg < -12.0:
        dir_str = "чуть левее"
    elif -115.0 <= angle_deg < -65.0:
        dir_str = "налево на 90°"
    elif -160.0 <= angle_deg < -115.0:
        dir_str = "сзади слева"
    else:
        dir_str = "сзади"

    return dir_str, dist_round, height_str


class ScrapMechanicTelemetryProvider(TelemetryProvider):
    """Адаптер нативной телеметрии и команд для Scrap Mechanic."""

    def __init__(self, game_dir: Optional[str] = None):
        self.game_dir = game_dir or find_scrap_mechanic_dir()
        self.active = False
        self._last_state: Optional[GameState] = None
        self._last_mtime: float = 0.0
        self._last_read_time: float = 0.0

    @property
    def state_file_path(self) -> Optional[str]:
        if not self.game_dir:
            self.game_dir = find_scrap_mechanic_dir()
        if self.game_dir:
            return os.path.join(self.game_dir, "Survival", "sakura_state.json")
        return None

    @property
    def cmd_file_path(self) -> Optional[str]:
        if not self.game_dir:
            self.game_dir = find_scrap_mechanic_dir()
        if self.game_dir:
            return os.path.join(self.game_dir, "Survival", "sakura_cmd.json")
        return None

    def find_newest_game_log(self) -> Optional[str]:
        """Поиск самого свежего лог-файла Scrap Mechanic."""
        candidates: List[str] = []
        if self.game_dir:
            logs_dir = os.path.join(self.game_dir, "Logs")
            if os.path.isdir(logs_dir):
                for f in os.listdir(logs_dir):
                    if f.startswith("game-") and f.endswith(".log"):
                        candidates.append(os.path.join(logs_dir, f))
        appdata_logs = os.path.expandvars(r"%APPDATA%\Axolot Games\Scrap Mechanic\Logs")
        if os.path.isdir(appdata_logs):
            for f in os.listdir(appdata_logs):
                if f.startswith("game-") and f.endswith(".log"):
                    candidates.append(os.path.join(appdata_logs, f))
        if not candidates:
            return None
        return max(candidates, key=os.path.getmtime)

    def _read_state_from_log(self, log_path: str) -> Optional[dict]:
        """Считывает последнюю строку [SAKURA_STATE] из хвоста лог-файла игры."""
        try:
            with open(log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                read_size = min(size, 65536)
                f.seek(size - read_size, os.SEEK_SET)
                chunk = f.read(read_size)
            lines = chunk.decode("utf-8", errors="replace").splitlines()
            for line in reversed(lines):
                idx = line.find("[SAKURA_STATE]")
                if idx != -1:
                    raw_json = line[idx + len("[SAKURA_STATE]"):].strip()
                    data = json.loads(raw_json)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            log.debug("[scrap_mechanic] Ошибка парсинга [SAKURA_STATE] из %s: %s", log_path, e)
        return None

    def _get_latest_raw_state(self) -> Optional[dict]:
        """Получает самое свежее состояние игры из game-*.log или sakura_state.json."""
        log_path = self.find_newest_game_log()
        log_data = self._read_state_from_log(log_path) if log_path else None

        json_data = None
        path = self.state_file_path
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    json_data = json.load(f)
            except Exception:
                pass

        if log_data and json_data:
            t_log = float(log_data.get("timestamp", 0.0))
            t_json = float(json_data.get("timestamp", 0.0))
            return log_data if t_log >= t_json else json_data
        return log_data or json_data

    def is_available(self) -> bool:
        """Проверяет, запущен ли Scrap Mechanic или обновляется ли файл телеметрии / лог."""
        path = self.state_file_path
        if path and os.path.isfile(path):
            try:
                if (time.time() - os.path.getmtime(path)) < 15.0:
                    return True
            except OSError:
                pass

        log_path = self.find_newest_game_log()
        if log_path and os.path.isfile(log_path):
            try:
                if (time.time() - os.path.getmtime(log_path)) < 15.0:
                    return True
            except OSError:
                pass

        return False

    def start(self) -> None:
        self.active = True
        log.info("[scrap_mechanic] Провайдер нативной телеметрии Scrap Mechanic запущен")

    def stop(self) -> None:
        self.active = False
        log.info("[scrap_mechanic] Провайдер Scrap Mechanic остановлен")

    def send_command(self, cmd: str, extra: Optional[Dict[str, Any]] = None) -> bool:
        """Отправляет команду внутрь игры через sakura_cmd.json."""
        cmd_path = self.cmd_file_path
        if not cmd_path:
            log.warning("[scrap_mechanic] Не удалось определить путь к sakura_cmd.json")
            return False

        cmd_id = f"cmd_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        payload = {
            "cmd": cmd,
            "cmd_id": cmd_id,
            "id": cmd_id,
            "timestamp": time.time(),
            "processed": False,
        }
        if extra:
            payload.update(extra)

        try:
            os.makedirs(os.path.dirname(cmd_path), exist_ok=True)
            tmp_path = cmd_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, cmd_path)
            log.info("[scrap_mechanic] Отправлена команда в игру: %s (cmd_id=%s)", cmd, cmd_id)
            return True
        except Exception as e:
            log.error("[scrap_mechanic] Ошибка записи команды %s: %s", cmd, e)
            return False

    def tp_to_bag(self) -> bool:
        """Телепортировать игрока к ближайшему рюкзаку."""
        return self.send_command("tp_to_bag")

    def tp_to_elevator(self) -> bool:
        """Телепортировать игрока к ближайшему лифту склада."""
        return self.send_command("tp_to_elevator")

    def heal(self) -> bool:
        """Восстановить здоровье, дыхание и показатели на 100%."""
        return self.send_command("heal")

    def godmode(self, on: bool = True) -> bool:
        """Включить или выключить бессмертие."""
        return self.send_command("godmode_on" if on else "godmode_off")

    def kill_nearby_bots(self) -> bool:
        """Уничтожить всех враждебных роботов в радиусе 30 метров."""
        return self.send_command("kill_nearby_bots")

    def get_state(self) -> Optional[GameState]:
        """Считывает данные телеметрии (из лога или файла) и генерирует GameState с навигацией."""
        now = time.time()
        # Ограничиваем частоту чтения с диска до ~5 раз в сек
        if now - self._last_read_time < 0.18 and self._last_state:
            return self._last_state

        raw_data = self._get_latest_raw_state()
        if not raw_data:
            return self._last_state

        try:
            self._last_read_time = now

            player = raw_data.get("player") or {}
            px = float(player.get("x", 0.0))
            py = float(player.get("y", 0.0))
            pz = float(player.get("z", 0.0))

            dx = float(player.get("dir_x", 0.0))
            dy = float(player.get("dir_y", 1.0))
            dz = float(player.get("dir_z", 0.0))

            hp = float(player.get("hp", 100.0))
            maxhp = float(player.get("maxhp", 100.0))
            breath = float(player.get("breath", 100.0))
            food = float(player.get("food", 100.0))
            water = float(player.get("water", 100.0))
            godmode = bool(player.get("godmode", False))
            world_id = player.get("world_id", 0)

            bags = raw_data.get("bags") or []
            elevators = raw_data.get("elevators") or []
            nearby_bots = raw_data.get("nearby_bots") or []

            # 1. Навигация к рюкзаку
            bag_nav_str = "нет потерянных вещей"
            closest_bag_dist = 99999.0
            closest_bag_dir = ""
            closest_bag_height = ""

            # Ищем ближайший рюкзак в текущем мире
            current_world_bags = [b for b in bags if b.get("in_current_world", True)]
            target_bags = current_world_bags if current_world_bags else bags

            if target_bags:
                # Сортируем по дистанции
                sorted_bags = sorted(target_bags, key=lambda b: float(b.get("distance", 99999.0)))
                cb = sorted_bags[0]
                bx = float(cb.get("x", px))
                by = float(cb.get("y", py))
                bz = float(cb.get("z", pz))

                b_dir, b_dist, b_h = calculate_relative_navigation(px, py, pz, dx, dy, dz, bx, by, bz)
                closest_bag_dist = b_dist
                closest_bag_dir = b_dir
                closest_bag_height = b_h
                bag_nav_str = f"{b_dir}, {b_dist:.0f}м, {b_h}"

            # 2. Навигация к лифту склада
            elev_nav_str = "лифтов не найдено"
            closest_elev_dist = 99999.0
            closest_elev_dir = ""
            closest_elev_height = ""

            current_world_elevs = [e for e in elevators if e.get("in_current_world", True)]
            target_elevs = current_world_elevs if current_world_elevs else elevators

            if target_elevs:
                sorted_elevs = sorted(target_elevs, key=lambda e: float(e.get("distance", 99999.0)))
                ce = sorted_elevs[0]
                ex = float(ce.get("x", px))
                ey = float(ce.get("y", py))
                ez = float(ce.get("z", pz))

                e_dir, e_dist, e_h = calculate_relative_navigation(px, py, pz, dx, dy, dz, ex, ey, ez)
                closest_elev_dist = e_dist
                closest_elev_dir = e_dir
                closest_elev_height = e_h
                elev_nav_str = f"{e_dir}, {e_dist:.0f}м, {e_h}"

            # 3. Враги (боты)
            nearest_bot_str = "чисто"
            nearest_bot_dist = 99999.0
            nearest_bot_dir = ""
            bot_warning = ""

            if nearby_bots:
                sorted_bots = sorted(nearby_bots, key=lambda b: float(b.get("distance", 99999.0)))
                nb = sorted_bots[0]
                nb_type = nb.get("type", "Робот")
                nb_x = float(nb.get("x", px))
                nb_y = float(nb.get("y", py))
                nb_z = float(nb.get("z", pz))

                n_dir, n_dist, n_h = calculate_relative_navigation(px, py, pz, dx, dy, dz, nb_x, nb_y, nb_z)
                nearest_bot_dist = n_dist
                nearest_bot_dir = n_dir
                nearest_bot_str = f"{nb_type} ({n_dir}, {n_dist:.0f}м, {n_h})"

                if "Tapebot" in nb_type:
                    bot_warning = f"Осторожно! Тейпбот {n_dir} ({n_dist:.0f}м)!"
                elif n_dist < 10.0:
                    bot_warning = f"Враг рядом: {nb_type} ({n_dir}, {n_dist:.0f}м)!"

            metrics: Dict[str, Any] = {
                "hp": hp,
                "maxhp": maxhp,
                "breath": breath,
                "food": food,
                "water": water,
                "godmode": godmode,
                "player_x": round(px, 1),
                "player_y": round(py, 1),
                "player_z": round(pz, 1),
                "bags_count": len(bags),
                "bag_nav": bag_nav_str,
                "bag_dist": closest_bag_dist if closest_bag_dist < 90000 else 0.0,
                "bag_dir": closest_bag_dir,
                "bag_height": closest_bag_height,
                "elevator_nav": elev_nav_str,
                "elevator_dist": closest_elev_dist if closest_elev_dist < 90000 else 0.0,
                "elevator_dir": closest_elev_dir,
                "elevator_height": closest_elev_height,
                "nearby_bots_count": len(nearby_bots),
                "nearest_bot": nearest_bot_str,
                "nearest_bot_dist": nearest_bot_dist if nearest_bot_dist < 90000 else 0.0,
                "nearest_bot_dir": nearest_bot_dir,
                "bot_warning": bot_warning,
            }

            trends: Dict[str, str] = {}
            if self._last_state:
                old_hp = self._last_state.metrics.get("hp", 100.0)
                if old_hp - hp >= 20.0:
                    trends["hp"] = "damage_spike"
                elif hp - old_hp >= 20.0:
                    trends["hp"] = "healed"

            # Формируем компактное человекочитаемое резюме для Сакуры
            summary_parts = [f"HP: {hp:.0f}"]
            if godmode:
                summary_parts.append("Бессмертие: ВКЛ")
            if target_bags:
                summary_parts.append(f"Рюкзак: {bag_nav_str}")
            if target_elevs:
                summary_parts.append(f"Лифт: {elev_nav_str}")
            if nearby_bots:
                summary_parts.append(f"Враги: {len(nearby_bots)} шт. (Ближайший: {nearest_bot_str})")
            else:
                summary_parts.append("Врагов рядом нет")

            summary = "Scrap Mechanic | " + " | ".join(summary_parts)

            self._last_state = GameState(
                game_id="scrapmechanic",
                game_name="Scrap Mechanic",
                metrics=metrics,
                trends=trends,
                timestamp=now,
                source="telemetry",
                summary=summary,
            )
            return self._last_state

        except Exception as e:
            log.warning("[scrap_mechanic] Ошибка чтения телеметрии: %s", e)
            return self._last_state

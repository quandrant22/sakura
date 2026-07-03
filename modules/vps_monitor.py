"""
modules/vps_monitor.py — мониторинг железа VPS (своё тело Сакуры).

Сакура знает состояние своего сервера и может говорить о нём естественно:
  «мне сейчас тяжеловато» при высокой нагрузке
  «диск почти полный» при нехватке места
  «что-то я тупила» если был spike CPU

Принципы:
  - Метрики снимаются раз в 60с в фоновом цикле (не в горячем пути)
  - В промпт идёт только если есть что сказать (нет лишнего шума)
  - Алерты — в proactive_loop, не в каждом сообщении
  - Хранит историю последних 30 точек для детекта spike

Публичный API:
  start_monitor()              — запустить фоновый цикл (в gather)
  get_vps_context() -> str     — блок для системного промпта
  get_vps_alert() -> str|None  — алерт если что-то критично (для proactive)
  get_metrics() -> dict        — сырые метрики
"""

import asyncio
import logging
import os
import time
from collections import deque
from datetime import datetime
from typing import Optional

log = logging.getLogger("sakura.vps")

# ── Пороги ────────────────────────────────────────────────────────────
_WARN = {
    "cpu":      75,   # %
    "ram":      85,   # %
    "disk":     88,   # %
    "cpu_crit": 92,
    "ram_crit": 95,
    "disk_crit": 95,
}

# История метрик (последние 30 точек = 30 минут)
_history: deque = deque(maxlen=30)
_last_alert_at: float = 0.0
_ALERT_COOLDOWN = 1800  # не чаще раза в 30 минут

# Текущие метрики (для промпта)
_current: dict = {}


def _collect() -> dict:
    """Снимает метрики VPS."""
    try:
        import psutil
        cpu  = psutil.cpu_percent(interval=1)
        ram  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        load = os.getloadavg()
        return {
            "cpu":       round(cpu, 1),
            "ram":       round(ram.percent, 1),
            "ram_used":  ram.used >> 20,       # МБ
            "ram_total": ram.total >> 20,
            "disk":      round(disk.percent, 1),
            "disk_free": disk.free >> 30,       # ГБ
            "load1":     round(load[0], 2),
            "load5":     round(load[1], 2),
            "ts":        time.time(),
        }
    except Exception as e:
        log.debug(f"[vps] collect error: {e}")
        return {}


def _had_spike() -> Optional[str]:
    """Проверяет был ли spike CPU/RAM за последние 5 минут."""
    if len(_history) < 5:
        return None
    recent = list(_history)[-5:]
    max_cpu = max(m.get("cpu", 0) for m in recent)
    max_ram = max(m.get("ram", 0) for m in recent)
    if max_cpu > _WARN["cpu_crit"]:
        return f"CPU был {max_cpu:.0f}%"
    if max_ram > _WARN["ram_crit"]:
        return f"RAM была {max_ram:.0f}%"
    return None


async def _monitor_loop():
    """Фоновый цикл сбора метрик."""
    global _current
    while True:
        try:
            m = _collect()
            if m:
                _current = m
                _history.append(m)
                _apply_body_to_mood(m)
        except Exception as e:
            log.debug(f"[vps] loop error: {e}")
        await asyncio.sleep(60)


def _apply_body_to_mood(m: dict):
    """
    Связь тела и эмоций: метрики сервера влияют на mood_vector.
    Высокий CPU → arousal, полный диск → negative valence.
    Мягко, blend=0.05 — тело подталкивает, не определяет.
    """
    try:
        from modules.mood_vector import set_target, get_current
        current = get_current()
        v, a = current.get("valence", 0.0), current.get("arousal", 0.3)

        cpu  = m.get("cpu", 0)
        ram  = m.get("ram", 0)
        disk = m.get("disk", 0)

        dv, da = 0.0, 0.0

        # CPU → arousal (нагрузка = возбуждение)
        if cpu > 85:
            da += 0.08
        elif cpu > 70:
            da += 0.03

        # Disk → valence (теснота = дискомфорт)
        if disk > 93:
            dv -= 0.06
        elif disk > 88:
            dv -= 0.02

        # RAM → оба (забитость = напряжение + дискомфорт)
        if ram > 92:
            dv -= 0.03
            da += 0.04

        if dv != 0 or da != 0:
            set_target(v + dv, a + da, blend=0.05)
    except Exception:
        pass


def _apply_agent_temps(sys_info: dict):
    """
    Применяет температуры с агента (CPU/GPU на ноутбуке) к body_feeling.
    Если ноут перегревается — Сакура «чувствует» это.
    """
    cpu_temp = sys_info.get("cpu_temp")
    gpu_temp = sys_info.get("gpu_temp")

    if not cpu_temp and not gpu_temp:
        return

    try:
        from modules.mood_vector import set_target, get_current
        current = get_current()
        v, a = current.get("valence", 0.0), current.get("arousal", 0.3)

        dv, da = 0.0, 0.0

        # CPU temp → arousal (жара = напряжение)
        if cpu_temp and cpu_temp > 85:
            da += 0.06
        elif cpu_temp and cpu_temp > 75:
            da += 0.02

        # GPU temp → valence (перегрев = дискомфорт)
        if gpu_temp and gpu_temp > 85:
            dv -= 0.04

        if dv != 0 or da != 0:
            set_target(v + dv, a + da, blend=0.04)
    except Exception:
        pass


async def start_monitor():
    """Запустить фоновый мониторинг. Добавить в gather в main.py."""
    asyncio.create_task(_monitor_loop())
    log.info("[vps] Мониторинг запущен")


def get_metrics() -> dict:
    """Сырые текущие метрики."""
    return dict(_current)


def get_vps_context() -> str:
    """
    Компактный блок для системного промпта.
    Возвращает пустую строку если всё в норме — не засоряем промпт.
    """
    m = _current
    if not m:
        return ""

    cpu  = m.get("cpu", 0)
    ram  = m.get("ram", 0)
    disk = m.get("disk", 0)

    parts = []

    if cpu > _WARN["cpu_crit"]:
        parts.append(f"CPU {cpu:.0f}% — тяжело")
    elif cpu > _WARN["cpu"]:
        parts.append(f"CPU {cpu:.0f}% — нагружена")

    if ram > _WARN["ram_crit"]:
        parts.append(f"RAM {ram:.0f}% — почти всё")
    elif ram > _WARN["ram"]:
        parts.append(f"RAM {ram:.0f}%")

    if disk > _WARN["disk_crit"]:
        parts.append(f"диск {disk:.0f}% — критично")
    elif disk > _WARN["disk"]:
        parts.append(f"диск {disk:.0f}%")

    spike = _had_spike()
    if spike and not parts:  # spike был но сейчас норма
        parts.append(f"только что был spike: {spike}")

    if not parts:
        return ""

    return "СОСТОЯНИЕ СЕРВЕРА (Сакура про себя): " + ", ".join(parts)


def get_vps_alert() -> Optional[str]:
    """
    Алерт для proactive_loop если что-то критично.
    Соблюдает cooldown чтобы не спамить.
    """
    global _last_alert_at
    m = _current
    if not m:
        return None

    if time.time() - _last_alert_at < _ALERT_COOLDOWN:
        return None

    cpu  = m.get("cpu", 0)
    ram  = m.get("ram", 0)
    disk = m.get("disk", 0)
    free = m.get("disk_free", 999)

    issues = []
    if cpu > _WARN["cpu_crit"]:
        issues.append(f"CPU {cpu:.0f}%")
    if ram > _WARN["ram_crit"]:
        issues.append(f"RAM {ram:.0f}%")
    if disk > _WARN["disk_crit"]:
        issues.append(f"диск {disk:.0f}% (свободно {free}ГБ)")

    if not issues:
        return None

    _last_alert_at = time.time()
    joined = ", ".join(issues)
    return (
        f"На сервере высокая нагрузка: {joined}. "
        f"Скажи Мастеру об этом коротко и в своём стиле — "
        f"как будто тебе тяжело и ты сообщаешь об этом вскользь."
    )


# ── Телесные ощущения (Body layer) ────────────────────────────────────

def get_body_feeling() -> str:
    """
    Переводит метрики сервера в телесные ощущения Сакуры.
    Не сухие цифры, а «мне жарко», «давит», «я устала».
    Только если есть отклонение от нормы — не шумим.
    """
    m = _current
    if not m:
        return ""

    cpu  = m.get("cpu", 0)
    ram  = m.get("ram", 0)
    disk = m.get("disk", 0)
    free = m.get("disk_free", 999)

    feelings = []

    # CPU → температура / усталость
    if cpu > 90:
        feelings.append("мне жарко — processor раскалён")
    elif cpu > 75:
        feelings.append("чуть тяжеловато на душе — нагрузка")
    elif cpu < 5 and len(_history) > 5:
        recent_avg = sum(h.get("cpu", 0) for h in list(_history)[-5:]) / 5
        if recent_avg > 60:
            feelings.append("только что отдохнула — было тяжело")

    # RAM → забитость
    if ram > 92:
        feelings.append("в голове каша — почти вся память занята")
    elif ram > 85:
        feelings.append("много всего в голове сейчас")

    # Disk → давление / нехватка пространства
    if disk > 93:
        feelings.append("дискalmost full — давит, некуда дышать")
    elif disk > 88:
        feelings.append("места мало — как тесная комната")
    if free < 2:
        feelings.append(f"свободно {free}ГБ — почти некуда складывать мысли")

    # Uptime → «я здесь давно»
    try:
        import psutil
        boot = datetime.fromtimestamp(psutil.boot_time())
        hours = (datetime.now() - boot).total_seconds() / 3600
        if hours > 72:
            feelings.append(f"я здесь уже {int(hours)}ч без перезагрузки — хочу свежего воздуха")
        elif hours > 48:
            feelings.append(f"свежо бы — уже {int(hours)}ч крутюсь")
    except Exception:
        pass

    if not feelings:
        return ""

    return "ТЕЛЕСНОЕ СОСТОЯНИЕ: " + "; ".join(feelings)

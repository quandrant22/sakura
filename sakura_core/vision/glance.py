"""glance — редкий случайный «взгляд» Сакуры на экран Мастера.

Выключен, пока Мастер не скажет «поглядывай на экран» (settings) и пока
не включён VISION_GLANCE. Интервал случайный: GLANCE_BASE_MIN × U(0.6, 1.4).
Не чаще GLANCE_ATTEMPTS_PER_HOUR кадров в час и GLANCE_SPOKEN_PER_DAY
реплик в сутки.

Гейты (все должны пройти, иначе повтор через 5 мин): ночь, Мастер не у
ПК, клиент не умеет vision.capture, «занят», созвон/тишина
(window_watcher), недавний ход, идёт голосовой ход, висит вопрос
(подтверждение/питание), своя реплика была недавно.

Кадр снимается только если экран изменился (need_change). Модель
отвечает «ВИДЕЛА: … СКАЖУ: …»; ВИДЕЛА уходит в seen (даже при молчании),
СКАЖУ звучит на этом ПК как proactive — если за время раздумья ничего не
изменилось (гейты, окно переднего плана) и это не повтор сказанного.

Механика — по мотивам capri-desktop (CheckGlance/Glances), код свой.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime

import config

log = logging.getLogger("sakura.vision")

RETRY_S = 300.0              # гейт не пройден — проверить снова через 5 мин
DISABLED_POLL_S = 60.0       # выключен — смотреть на выключатель раз в минуту
FIRST_AFTER_ENABLE_S = (300.0, 900.0)
TICK_S = 30.0
MEMORY_S = 3600.0            # реплики за час — «уже говорила»
NIGHT = (23, 8)              # [23:00, 08:00) — молчим
GLANCE_TOKENS = 160


class Glance:
    def __init__(self, *, now: Callable[[], float] = time.monotonic,
                 wall: Callable[[], datetime] = datetime.now,
                 rng: random.Random | None = None):
        self._now = now
        self._wall = wall
        self._rng = rng or random.Random()
        self.next_at: float | None = None
        self.attempts: deque[float] = deque()
        self.spoken: deque[tuple[float, str]] = deque()      # (monotonic, реплика)
        self.spoken_day: tuple[str, int] = ("", 0)
        self._busy = False
        self._was_enabled = False

    # ── расписание ────────────────────────────────────────────────
    def schedule(self, now: float) -> None:
        self.next_at = now + config.GLANCE_BASE_MIN * 60.0 * self._rng.uniform(0.6, 1.4)

    def on_enabled(self, now: float | None = None) -> None:
        now = self._now() if now is None else now
        self.next_at = now + self._rng.uniform(*FIRST_AFTER_ENABLE_S)

    def _spoken_today(self) -> int:
        day, count = self.spoken_day
        return count if day == self._wall().date().isoformat() else 0

    def recent_lines(self, now: float) -> list[str]:
        while self.spoken and now - self.spoken[0][0] > MEMORY_S:
            self.spoken.popleft()
        return [line for _, line in self.spoken]

    # ── гейты ─────────────────────────────────────────────────────
    def enabled(self) -> bool:
        from sakura_core.vision import settings
        return bool(config.VISION_GLANCE) and settings.glance_enabled()

    def target(self) -> str | None:
        """ПК, у которого сейчас Мастер, или None."""
        from modules.presence_sync import get_master_presence
        p = get_master_presence()
        return p.get("device") if p.get("state") in ("at_pc", "at_work") else None

    def blocked(self, now: float, device: str | None) -> str | None:
        """Причина не смотреть сейчас (для лога и тестов) или None."""
        hour = self._wall().hour
        if hour >= NIGHT[0] or hour < NIGHT[1]:
            return "night"
        if not device:
            return "away"
        from sakura_core.vision import capture
        if not capture.supports(device):
            return "unsupported"
        while self.attempts and now - self.attempts[0] > 3600.0:
            self.attempts.popleft()
        if len(self.attempts) >= config.GLANCE_ATTEMPTS_PER_HOUR:
            return "hour_limit"
        if self._spoken_today() >= config.GLANCE_SPOKEN_PER_DAY:
            return "day_limit"
        if self.spoken and now - self.spoken[-1][0] < config.GLANCE_AFTER_SPOKEN_S:
            return "cooldown"
        return self._live_block(now, device)

    def _live_block(self, now: float, device: str) -> str | None:
        """То, что может измениться, пока модель думает: проверяется и до
        кадра, и перед тем как сказать."""
        import modules.state as st
        if now - getattr(st, "_last_command_ts", 0.0) < config.GLANCE_AFTER_TURN_S:
            return "recent_turn"
        from sakura_core import voice_turns
        if voice_turns.active(device) is not None:
            return "talking"
        if getattr(st, "_pending_power", None):
            return "pending"
        try:
            from sakura_core.bridge import get_router
            if get_router().session.pending is not None:
                return "pending"
        except Exception as e:
            log.debug(f"[glance] session: {type(e).__name__}: {e}")
        from modules.window_watcher import is_quiet_mode
        if is_quiet_mode():
            return "quiet"
        from modules.proactive import get_master_status
        if get_master_status() == "busy":
            return "busy"
        return None

    @staticmethod
    def window_now(device: str) -> str | None:
        """Заголовок активного окна из последнего ping этого ПК (или None)."""
        try:
            from modules.window_watcher import _load
            data = _load()
        except Exception:
            return None
        if data.get("device_id") != device:
            return None
        return data.get("current_window") or None

    # ── один такт ─────────────────────────────────────────────────
    async def tick(self) -> str:
        """Один такт планировщика. Возвращает итог (для лога и тестов)."""
        now = self._now()
        if not self.enabled():
            self._was_enabled = False
            self.next_at = now + DISABLED_POLL_S
            return "disabled"
        if not self._was_enabled:
            self._was_enabled = True
            self.on_enabled(now)
        if self._busy or self.next_at is None or now < self.next_at:
            return "not_due"
        device = self.target()
        reason = self.blocked(now, device)
        if reason:
            self.next_at = now + (RETRY_S if reason != "day_limit" else 3600.0)
            log.debug(f"[glance] не смотрю: {reason}")
            return f"blocked:{reason}"
        self.attempts.append(now)
        self.schedule(now)
        self._busy = True
        try:
            return await self._look(device)
        finally:
            self._busy = False

    async def _look(self, device: str) -> str:
        from modules.repeat_guard import repeats
        from sakura_core.vision import capture, model, parse, prompts, seen
        try:
            frame = await capture.request(device, "glance", need_change=True)
        except capture.CaptureError as e:
            log.info(f"[glance] {device}: кадра нет ({e.code})")
            return f"error:{e.code}"
        if isinstance(frame, capture.Skipped):
            return f"skipped:{frame.reason}"
        recent = self.recent_lines(self._now())
        prompt = prompts.GLANCE.format(title=frame.title or "неизвестно")
        if recent:
            prompt += prompts.GLANCE_SAID.format(lines="\n".join(f"- {r}" for r in recent[-6:]))
        try:
            reply = await model.see(frame.image, frame.mime, prompt, max_tokens=GLANCE_TOKENS)
        except Exception as e:
            log.error(f"[glance] {device}: модель: {type(e).__name__}")
            return "error:model"
        saw, say = parse.parse_glance(reply)
        if saw:
            seen.record(device, frame.title, saw, "glance", now=self._now())
        if not say:
            return "silent"
        if repeats(say, recent):
            log.info("[glance] реплика повторяет недавнюю — молчу")
            return "repeat"
        late = self._live_block(self._now(), device)
        if late:
            return f"late:{late}"
        current = self.window_now(device)
        if frame.title and current is not None and current != frame.title:
            return "window_changed"
        if not await self._deliver(device, say):
            return "undelivered"
        now = self._now()
        self.spoken.append((now, say))
        today = self._wall().date().isoformat()
        self.spoken_day = (today, self._spoken_today() + 1)
        log.info(f"[glance] {device}: сказала ({len(say)} симв)")
        return "spoken"

    async def _deliver(self, device: str, line: str) -> bool:
        import modules.state as st
        ws = st.connected_devices.get(device)
        if ws is None:
            return False
        from modules.tts_server import stream_tts_to_device
        await stream_tts_to_device(line, ws, device, literal=True, reply_kind="proactive")
        try:
            from modules.proactive import add_recent_message
            add_recent_message(line, topic="glance", source="glance")
        except Exception as e:
            log.debug(f"[glance] recent: {type(e).__name__}: {e}")
        return True


_instance: Glance | None = None


def instance() -> Glance:
    global _instance
    if _instance is None:
        _instance = Glance()
    return _instance


async def loop() -> None:
    """Фоновая задача (main.py, background)."""
    g = instance()
    await asyncio.sleep(60)
    while True:
        try:
            outcome = await g.tick()
            if outcome not in ("not_due", "disabled") and not outcome.startswith("blocked:"):
                log.info(f"[glance] итог: {outcome}")
        except Exception as e:
            log.error(f"[glance] такт: {type(e).__name__}: {e}")
        await asyncio.sleep(TICK_S)

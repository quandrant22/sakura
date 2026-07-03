"""
modules/discord_bot.py — Discord бот Сакуры.

Архитектура: discord.py + discord-ext-voice-recv в ОДНОМ event loop.
Никаких отдельных потоков, никаких патчей py-cord.

Система приоритетов:
  Сакура в ГС + мастер не замучен → голос в Discord (все слышат)
  Сакура в ГС + мастер замучен   → голос через агент (только мастер)
  Сакура не в ГС                 → голос через агент
"""

import asyncio
import io
import logging
import os
import tempfile
import time
import wave
from typing import Optional

import threading
import discord
from discord.ext import commands, voice_recv

log = logging.getLogger("sakura.discord")

# Глушим спам от voice_recv
logging.getLogger("discord.ext.voice_recv.reader").setLevel(logging.WARNING)
logging.getLogger("discord.ext.voice_recv.gateway").setLevel(logging.WARNING)

# ── Конфиг ───────────────────────────────────────────────────────────
_TOKEN     = os.getenv("DISCORD_TOKEN", "")
_MASTER_ID = int(os.getenv("DISCORD_MASTER_ID", "0"))
_VIP_IDS:       set[int] = set()
_AUTO_CHANNELS: set[int] = set()

# ── Состояние мастера ─────────────────────────────────────────────────
_master_muted = False
_sakura_in_vc = False

# ── Антидублирование ──────────────────────────────────────────────────
_last_source: Optional[str] = None
_last_source_at: float      = 0.0
_DEDUP_WINDOW = 12.0

# ── Войс ──────────────────────────────────────────────────────────────
_vc: Optional[voice_recv.VoiceRecvClient] = None
_vc_guild_id: Optional[int]               = None
_vc_text_channel                          = None
_processing = False

# Whisper модель в памяти (предзагружается при старте)
_whisper_model = None
_whisper_lock  = threading.Lock()

# Оптимизированные настройки STT
WHISPER_MODEL    = "medium"      # "small" → "medium" для лучшего качества
WHISPER_DEVICE   = "cpu"
WHISPER_COMPUTE  = "int8"        # Квантизация для скорости на CPU
WHISPER_BEAM     = 5             # Beam search для точности
WHISPER_LANGUAGE = "ru"          # Язык по умолчанию
WHISPER_VAD      = True          # VAD для пропуска тишины
WHISPER_INITIAL  = "Сакура, привет, как дела, хорошо, отлично, спасибо"  # Контекст для русского


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                from faster_whisper import WhisperModel
                log.info(f"[Discord STT] Загружаю Whisper {WHISPER_MODEL}...")
                _whisper_model = WhisperModel(
                    WHISPER_MODEL,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE
                )
                log.info("[Discord STT] Whisper готов")
    return _whisper_model

# ── История ───────────────────────────────────────────────────────────
_history: list[dict] = []


# ── Публичное API для main.py ─────────────────────────────────────────

def is_discord_priority() -> bool:
    """True если Discord должен получить голосовой ответ."""
    return _sakura_in_vc and not _master_muted


def register_agent_request() -> bool:
    """
    Агент сообщает что получил голосовой запрос.
    Возвращает True если агент может отвечать голосом.
    """
    global _last_source, _last_source_at
    now = time.monotonic()
    if _last_source == "discord" and now - _last_source_at < _DEDUP_WINDOW:
        log.debug("[discord] агент заблокирован — discord в приоритете")
        return False
    _last_source    = "agent"
    _last_source_at = now
    return True


def _claim_discord() -> bool:
    global _last_source, _last_source_at
    now = time.monotonic()
    if _last_source == "agent" and now - _last_source_at < _DEDUP_WINDOW:
        log.debug("[discord] discord заблокирован — агент в приоритете")
        return False
    _last_source    = "discord"
    _last_source_at = now
    return True


# ── Helpers ───────────────────────────────────────────────────────────

def _is_master(uid: int) -> bool:
    return bool(_MASTER_ID and uid == _MASTER_ID)


def _is_vip(uid: int) -> bool:
    return _is_master(uid) or uid in _VIP_IDS


def _add_history(role: str, text: str):
    _history.append({"role": role, "content": text[:200]})
    if len(_history) > 20:
        del _history[:-20]


def _hist_str() -> str:
    if not _history:
        return ""
    return "ИСТОРИЯ:\n" + "\n".join(
        f"{'М' if m['role']=='user' else 'С'}: {m['content'][:60]}"
        for m in _history[-4:]
    )


# ── Бот ──────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members          = True
intents.voice_states     = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    log.info(f"[Discord] {bot.user} готов")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name="Мастера")
    )


@bot.event
async def on_voice_state_update(member, before, after):
    global _master_muted, _sakura_in_vc
    if _is_master(member.id):
        _master_muted = bool(after.self_mute)
        log.debug(f"[discord] мастер muted={_master_muted}")
    if bot.user and member.id == bot.user.id:
        _sakura_in_vc = after.channel is not None
        log.debug(f"[discord] сакура в гс={_sakura_in_vc}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    await bot.process_commands(message)

    ch        = message.channel
    is_dm     = isinstance(ch, discord.DMChannel)
    mentioned = bot.user in message.mentions
    in_auto   = ch.id in _AUTO_CHANNELS

    if not (is_dm or mentioned or in_auto):
        return

    text = message.content
    for u in message.mentions:
        text = text.replace(f"<@{u.id}>", "").replace(f"<@!{u.id}>", "")
    text = text.strip()
    if not text:
        return

    async with ch.typing():
        reply = await _get_reply(text, message.author, is_voice=False)

    if not reply:
        return

    for chunk in [reply[i:i+1900] for i in range(0, len(reply), 1900)]:
        await message.reply(chunk, mention_author=False)


# ── Генерация ответа ──────────────────────────────────────────────────

async def _get_reply(text: str, author, is_voice: bool = False) -> str:
    import importlib
    ask = importlib.import_module("main").ask_gemini

    master = _is_master(author.id)
    ctx    = "Это Мастер в Discord." if master else f"Это {author.display_name} в Discord."
    ctx   += " Ты — Сакура, говори от женского лица."
    if is_voice:
        ctx += " Отвечай коротко, 1-2 предложения."

    _add_history("user", f"{author.display_name}: {text}")
    try:
        reply = await ask(
            f"{text}\n\n[{ctx}]\n{_hist_str()}",
            save_history=master
        )
    except Exception as e:
        log.error(f"[discord reply] {e}")
        reply = ""
    _add_history("assistant", reply or "")
    return reply or ""


# ── TTS → ogg файл ────────────────────────────────────────────────────

async def _send_tts(text: str, channel=None):
    """Синтезирует TTS и воспроизводит прямо в войс-канале."""
    global _vc
    if not _vc or not _vc.is_connected():
        return
    try:
        from modules.tts_server import _synthesize, split_into_chunks
        pcm = bytearray()
        for chunk in split_into_chunks(text):
            for pkt in await _synthesize(chunk):
                pcm.extend(pkt)
        if not pcm:
            return

        # PCM 24кГц mono → WAV → FFmpegPCMAudio в войс
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_wav = f.name
            with wave.open(f, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(bytes(pcm))

        # Ждём пока предыдущее воспроизведение закончится
        waited = 0
        while _vc.is_playing() and waited < 30:
            await asyncio.sleep(0.5)
            waited += 1

        log.info(f"[discord TTS] vc connected={_vc.is_connected()}, playing={_vc.is_playing()}")
        source = discord.FFmpegPCMAudio(
            tmp_wav,
            options="-af aresample=48000"
        )
        source = discord.PCMVolumeTransformer(source, volume=0.85)

        def _after(err):
            try: os.unlink(tmp_wav)
            except: pass
            if err:
                log.error(f"[discord voice] {err}")

        _vc.play(source, after=_after)
        log.info(f"[discord TTS] воспроизведение: {text[:50]}")

    except Exception as e:
        log.error(f"[discord TTS] {e}")


# ── Голосовой приём (discord-ext-voice-recv) ──────────────────────────

class SakuraSink(voice_recv.AudioSink):
    """Принимает PCM от каждого пользователя, детектирует тишину → STT."""

    def __init__(self, text_channel):
        super().__init__()
        self._ch        = text_channel
        self._bufs:  dict[int, bytearray] = {}
        self._times: dict[int, float]     = {}
        self._task = asyncio.create_task(self._silence_loop())

    def wants_opus(self) -> bool:
        return False  # хотим PCM

    def write(self, user, data: voice_recv.VoiceData):
        if user is None:
            return
        try:
            pcm = data.pcm
            if not pcm:
                return
        except Exception:
            return  # игнорируем corrupted stream
        uid = user.id
        if uid not in self._bufs:
            self._bufs[uid] = bytearray()
        self._bufs[uid].extend(pcm)
        self._times[uid] = time.monotonic()

    def cleanup(self):
        self._task.cancel()

    async def _silence_loop(self):
        while True:
            await asyncio.sleep(0.5)
            global _processing
            if _processing:
                continue
            now = time.monotonic()
            for uid, last_t in list(self._times.items()):
                if now - last_t < 1.8:
                    continue
                buf = self._bufs.pop(uid, None)
                self._times.pop(uid, None)
                if not buf or len(buf) < 8000:  # 0.5с минимум
                    continue
                _processing = True
                asyncio.create_task(self._process(uid, bytes(buf)))

    async def _process(self, uid: int, pcm: bytes):
        global _processing
        try:
            if not _claim_discord():
                return

            # STT
            text = await asyncio.to_thread(_whisper_transcribe_pcm, pcm)
            if not text or len(text.strip()) < 3:
                return

            guild = _vc.guild if _vc else None
            member = guild.get_member(uid) if guild else None
            name   = member.display_name if member else str(uid)

            log.info(f"[discord STT] {name}: {text!r}")

            if self._ch:
                await self._ch.send(f"🎙️ **{name}:** {text}", delete_after=30)

            reply = await _get_reply(text, member or type('U', (), {'id': uid, 'display_name': name})(), is_voice=True)
            if not reply:
                return

            if self._ch:
                await self._ch.send(f"**Сакура:** {reply}", delete_after=60)

            # Голос в Discord если мастер не замучен
            if _sakura_in_vc and not _master_muted and self._ch:
                await _send_tts(reply, self._ch)

        except Exception as e:
            log.error(f"[discord recv] {e}")
        finally:
            _processing = False

# Whisper модель в памяти (предзагружается при старте)
_whisper_model = None
_whisper_lock  = threading.Lock()


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                from faster_whisper import WhisperModel
                log.info(f"[Discord STT] Загружаю Whisper {WHISPER_MODEL}...")
                _whisper_model = WhisperModel(
                    WHISPER_MODEL,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE
                )
                log.info("[Discord STT] Whisper готов")
    return _whisper_model


def _whisper_transcribe_pcm(pcm: bytes) -> str:
    """
    STT из raw PCM.
    discord.opus.Decoder выдаёт: 48000 Гц, 2 канала, int16 interleaved.
    SAMPLE_SIZE=4 → каждые 4 байта = 1 стерео-семпл (L int16 + R int16).
    """
    import numpy as np
    try:
        # int16 interleaved stereo
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

        # Stereo → mono: reshape в (N, 2), берём среднее
        if len(audio) % 2 != 0:
            audio = audio[:-1]
        audio = audio.reshape(-1, 2).mean(axis=1)

        # 48000 → 16000: децимация в 3 раза
        audio = audio[::3]

        duration = len(audio) / 16000
        if duration < 0.5:
            return ""

        log.info(f"[STT] обрабатываю {duration:.1f}с аудио ({len(pcm)} байт)")

        m = _get_whisper()
        segs, _ = m.transcribe(
            audio,
            language=WHISPER_LANGUAGE,
            beam_size=WHISPER_BEAM,
            vad_filter=WHISPER_VAD,
            initial_prompt=WHISPER_INITIAL,
        )
        result = " ".join(s.text for s in segs).strip()
        log.info(f"[STT] {duration:.1f}с → {result!r}")
        return result
    except Exception as e:
        log.error(f"[STT] {e}")
        return ""


# ── Команды ───────────────────────────────────────────────────────────

@bot.command(name="войди", aliases=["join"])
async def join_voice(ctx: commands.Context):
    global _vc, _vc_guild_id, _vc_text_channel
    if not _is_vip(ctx.author.id):
        await ctx.reply("Только для VIP.")
        return
    if not ctx.author.voice:
        await ctx.reply("Зайди в голосовой канал.")
        return

    if _vc and _vc.is_connected():
        _vc.stop_listening()
        await _vc.disconnect()

    try:
        _vc = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
        _vc_guild_id    = ctx.guild.id
        _vc_text_channel = ctx.channel
        _vc.listen(SakuraSink(ctx.channel))
        await ctx.reply(f"Зашла в **{ctx.author.voice.channel.name}**. Слушаю.")
        log.info(f"[discord] подключена к {ctx.author.voice.channel.name}")
    except Exception as e:
        await ctx.reply(f"Ошибка: {e}")
        log.error(f"[discord] connect: {e}")


@bot.command(name="выйди", aliases=["leave"])
async def leave_voice(ctx: commands.Context):
    global _vc, _vc_guild_id, _vc_text_channel
    if not _is_vip(ctx.author.id):
        return
    if _vc and _vc.is_connected():
        _vc.stop_listening()
        await _vc.disconnect()
        _vc = _vc_guild_id = _vc_text_channel = None
    await ctx.reply("Ушла.")


@bot.command(name="скажи")
async def say_cmd(ctx: commands.Context, *, text: str):
    if not _is_master(ctx.author.id):
        return
    if _vc_text_channel:
        await _send_tts(text, _vc_text_channel)
    else:
        await _send_tts(text, ctx.channel)
    await ctx.message.add_reaction("🔊")


@bot.command(name="авто")
async def auto_cmd(ctx: commands.Context):
    if not _is_master(ctx.author.id):
        return
    if ctx.channel.id in _AUTO_CHANNELS:
        _AUTO_CHANNELS.discard(ctx.channel.id)
        await ctx.reply("Авто-ответ выключен.")
    else:
        _AUTO_CHANNELS.add(ctx.channel.id)
        await ctx.reply("Авто-ответ включён.")


@bot.command(name="вип")
async def vip_cmd(ctx: commands.Context, member: discord.Member):
    if not _is_master(ctx.author.id):
        return
    _VIP_IDS.add(member.id)
    await ctx.reply(f"{member.display_name} — VIP.")


@bot.command(name="статус")
async def status_cmd(ctx: commands.Context):
    if not _is_master(ctx.author.id):
        return
    pri = "Discord" if is_discord_priority() else "Агент"
    vc_name = _vc.channel.name if _vc and _vc.is_connected() else "нет"
    await ctx.reply(
        f"**Сакура в Discord**\n"
        f"Войс: {vc_name}\n"
        f"Мастер замучен: {_master_muted}\n"
        f"Приоритет: {pri}"
    )


# ── Запуск ────────────────────────────────────────────────────────────

async def start_bot():
    """Запускает бота в текущем event loop — никаких потоков."""
    if not _TOKEN:
        log.warning("[Discord] DISCORD_TOKEN не задан.")
        return
    log.info("[Discord] Запуск в основном event loop...")
    # Предзагружаем Whisper в фоне
    asyncio.create_task(asyncio.to_thread(_get_whisper))
    asyncio.create_task(bot.start(_TOKEN))
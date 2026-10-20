"""Спаривание нового устройства (PROTOCOL.md §3.3–3.5): /pair в Telegram.

Код спаривания = 8 слов из словаря 256 слов (64 бита), одноразовый, живёт
10 минут, не больше 5 попыток. Из слов выводится PSK для Noise_XXpsk3:

    psk = BLAKE2s(b"sakura-pair/1\\x00" + normalize(words), 32)

Сервер хранит только psk (хеш слов), сами слова — нигде, кроме сообщения
Мастеру в Telegram. QR несёт те же слова, адрес сервера и его открытый ключ
(клиент сверяет ключ из XX_2 с ним до отправки XX_3).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from securechannel.keys import b64url, fingerprint, unb64url

WORDS = 8
CODE_TTL_S = 600.0
MAX_ATTEMPTS = 5
PSK_CONTEXT = b"sakura-pair/1\x00"
QR_SCHEME = "sakura-pair"

WORDLIST: tuple[str, ...] = tuple(
    w.strip() for w in (Path(__file__).with_name("wordlist_ru.txt")
                        .read_text(encoding="utf-8").splitlines()) if w.strip())
assert len(WORDLIST) == 256 and len(set(WORDLIST)) == 256


def normalize_words(text: str) -> str:
    """Нижний регистр, ё → е, всё не-буквенное — разделитель, один пробел."""
    t = (text or "").lower().replace("ё", "е")
    return " ".join(w for w in re.split(r"[^a-zа-я]+", t) if w)


def words_to_psk(words: str) -> bytes:
    return hashlib.blake2s(PSK_CONTEXT + normalize_words(words).encode("utf-8"),
                           digest_size=32).digest()


def new_words(rng=secrets) -> str:
    return " ".join(WORDLIST[rng.randbelow(256)] for _ in range(WORDS))


def make_qr_uri(server_url: str, server_pub: bytes, words: str, expires: float) -> str:
    return (f"{QR_SCHEME}://1?u={quote(server_url, safe='')}&k={b64url(server_pub)}"
            f"&w={quote('-'.join(normalize_words(words).split()), safe='-')}"
            f"&e={int(expires)}")


def parse_qr_uri(uri: str) -> dict:
    parts = urlsplit(uri)
    if parts.scheme != QR_SCHEME or parts.netloc != "1":
        raise ValueError("не код спаривания sakura-pair/1")
    q = {k: v[0] for k, v in parse_qs(parts.query, strict_parsing=True).items()}
    pub = unb64url(q["k"])
    if len(pub) != 32:
        raise ValueError("ключ сервера не 32 байта")
    words = normalize_words(q["w"].replace("-", " "))
    if len(words.split()) != WORDS:
        raise ValueError("нужно 8 слов")
    return {"url": q["u"], "server_pub": pub, "server_fp": fingerprint(pub),
            "words": words, "expires": int(q["e"])}


class PairingCode:
    def __init__(self, psk: bytes, expires: float):
        self.psk = psk
        self.expires = expires
        self.attempts = 0
        self.used = False


class PairingManager:
    """Один активный код за раз: новый /pair отменяет прежний."""

    def __init__(self, clock=time.time, ttl: float = CODE_TTL_S,
                 max_attempts: int = MAX_ATTEMPTS):
        self._clock = clock
        self.ttl = ttl
        self.max_attempts = max_attempts
        self._lock = threading.Lock()
        self._code: PairingCode | None = None

    def create(self) -> tuple[str, float]:
        """Новый код: (8 слов, срок). Слова отдаются только Мастеру."""
        words = new_words()
        expires = self._clock() + self.ttl
        with self._lock:
            self._code = PairingCode(words_to_psk(words), expires)
        return words, expires

    def active_psk(self) -> bytes | None:
        """PSK для XX-ответчика или None (кода нет, истёк, исчерпан, использован)."""
        with self._lock:
            c = self._code
            if c is None or c.used or c.attempts >= self.max_attempts \
                    or self._clock() > c.expires:
                return None
            return c.psk

    def failed(self, psk: bytes) -> None:
        """Неудачная попытка с этим кодом (не тот PSK, обрыв после XX_2)."""
        with self._lock:
            c = self._code
            if c is not None and hmac.compare_digest(c.psk, psk):
                c.attempts += 1

    def consume(self, psk: bytes) -> bool:
        """Успешное спаривание: код больше не действует."""
        with self._lock:
            c = self._code
            if c is not None and hmac.compare_digest(c.psk, psk) and not c.used:
                c.used = True
                return True
        return False

    def cancel(self) -> None:
        with self._lock:
            self._code = None

    def status(self) -> dict | None:
        with self._lock:
            c = self._code
            if c is None:
                return None
            return {"expires": c.expires, "attempts": c.attempts, "used": c.used}

"""Спаривание (PROTOCOL.md §3.4–3.5): 8 слов → PSK, разбор QR-ссылки sakura-pair://1."""
import base64
import hashlib
import re
import time
from urllib.parse import parse_qs, quote, urlparse

PSK_PREFIX = b"sakura-pair/1\x00"
WORDS = 8


class PairingError(ValueError):
    pass


def normalize_words(text: str) -> str:
    """Нижний регистр, ё → е, всё не-буквенное — разделитель, слова через один пробел."""
    t = (text or "").lower().replace("ё", "е")
    return " ".join(w for w in re.split(r"[^\w]|[\d_]", t) if w)


def words_to_psk(words: str) -> bytes:
    norm = normalize_words(words)
    if len(norm.split()) != WORDS:
        raise PairingError("нужно ровно 8 слов")
    return hashlib.blake2s(PSK_PREFIX + norm.encode("utf-8"), digest_size=32).digest()


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_qr_uri(url: str, server_pub: bytes, words: str, expires: float) -> str:
    w = "-".join(normalize_words(words).split())
    return f"sakura-pair://1?u={quote(url, safe='')}&k={b64u(server_pub)}&w={quote(w)}&e={int(expires)}"


def parse_qr_uri(uri: str, clock=time.time) -> dict:
    p = urlparse((uri or "").strip())
    if p.scheme != "sakura-pair" or p.netloc != "1":
        raise PairingError("это не QR спаривания Сакуры")
    q = {k: v[0] for k, v in parse_qs(p.query).items()}
    try:
        key = unb64u(q["k"])
        words = q["w"].replace("-", " ")
        expires = float(q.get("e", 0))
        url = q["u"]
    except (KeyError, ValueError) as e:
        raise PairingError("в QR не хватает данных") from e
    if len(key) != 32:
        raise PairingError("в QR неверный ключ сервера")
    if expires and clock() > expires:
        raise PairingError("срок кода спаривания истёк — получите новый в Telegram (/pair)")
    return {"url": url, "server_pub": key, "words": normalize_words(words), "expires": expires}

"""
core/pairing.py — спаривание агента с сервером (ТЗ-4, PROTOCOL §3.3–3.5).

    result = await pair_device("sakura-pair://1?u=…&k=…&w=…&e=…")   # QR-строка
    result = await pair_device("слово слово … слово")               # 8 слов
    # result.device_id, result.server_fp, result.mode ("qr" | "words")

Код берётся из /pair в Telegram. QR-строка несёт ключ сервера: он сверяется
с ключом из XX_2 ДО отправки XX_3 (securechannel.client.pair) — подмена
сервера обрывает спаривание. По одним словам ключ сервера заранее не
известен: отпечаток показывается после спаривания, его нужно сверить с
Telegram (FORMAL §3.2 — поэтому основной путь QR, DECISIONS CV16).

Неудача не трогает прежние ключи: новые сохраняются только после PAIRED.
Ключ устройства, PSK, слова и QR-строка в журнал не попадают.

Из консоли (без трея): python -m core.pairing
"""

from __future__ import annotations

import asyncio
import base64
import logging
import socket
import time
from dataclasses import dataclass

import websockets

from core import transport

log = logging.getLogger("sakura.agent")

PAIR_TIMEOUT_S = 15.0


class PairingError(Exception):
    """Спаривание не удалось; текст — для пользователя, без секретов."""


@dataclass
class PairResult:
    device_id: str
    server_fp: str
    mode: str


@dataclass
class _Code:
    words: str
    server_pub: bytes | None
    url: str | None
    mode: str


def parse_code(text: str, now: float | None = None) -> _Code:
    """QR-строка sakura-pair://… или 8 слов → что нужно для XXpsk3."""
    transport._ensure_securechannel_path()
    from securechannel.pairing import WORDLIST, WORDS, normalize_words, parse_qr_uri

    text = (text or "").strip()
    if not text:
        raise PairingError("код не введён")
    if text.lower().startswith("sakura-pair:"):
        try:
            qr = parse_qr_uri(text)
        except (ValueError, KeyError) as e:
            raise PairingError("QR-строка не распознана") from e
        if qr["expires"] < (time.time() if now is None else now):
            raise PairingError("код истёк — запросите новый /pair")
        return _Code(qr["words"], qr["server_pub"], qr["url"], "qr")
    words = normalize_words(text).split()
    if len(words) != WORDS:
        raise PairingError(f"нужно {WORDS} слов, введено {len(words)}")
    unknown = [w for w in words if w not in WORDLIST]
    if unknown:
        raise PairingError(f"неизвестных слов: {len(unknown)} — проверьте написание")
    return _Code(" ".join(words), None, None, "words")


async def pair_device(text: str, *, server_url: str | None = None, name: str | None = None,
                      device_id_hint: str | None = None, store=None, connect=None,
                      timeout: float = PAIR_TIMEOUT_S) -> PairResult:
    """Спарить устройство; при успехе — ключи в хранилище."""
    import config

    transport._ensure_securechannel_path()
    from securechannel.client import pair
    from securechannel.handshake import generate_keypair
    from securechannel.keys import fingerprint

    code = parse_code(text)
    # Адрес — тот, по которому агент и так ходит; адрес из QR — запасной.
    url = server_url or str(getattr(config, "VPS_WS_URL", "") or "") or code.url
    if not url:
        raise PairingError("не задан адрес сервера (VPS_WS_URL)")
    hint = device_id_hint or str(getattr(config, "DEVICE_ID", "") or "")
    name = name or f"агент {hint or socket.gethostname()}"
    if store is None:
        from core import secure_store as store
    connect = connect or websockets.connect

    priv, pub = generate_keypair()
    try:
        ws = await asyncio.wait_for(connect(url, **transport._WS_KWARGS), timeout)
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:
        raise PairingError(f"сервер недоступен ({type(e).__name__})") from None
    try:
        paired = await asyncio.wait_for(
            pair(ws, code.words, priv, expected_server_pub=code.server_pub,
                 name=name, kind="pc", device_id_hint=hint, timeout=timeout),
            timeout)
    except asyncio.TimeoutError:
        raise PairingError("сервер не ответил — код неверный, истёк или исчерпан") from None
    except Exception as e:  # noqa: BLE001 — любая неудача рукопожатия = отказ, без деталей
        reason = str(e) if "подмена" in str(e) or "PAIRED" in str(e) else type(e).__name__
        log.warning("[pairing] не удалось (%s): %s", code.mode, reason)
        if "подмена" in str(e):
            raise PairingError("ключ сервера не совпал с QR — спаривание прервано "
                               "(возможна подмена)") from None
        raise PairingError("сервер отклонил код — неверный, истёк или исчерпан") from None
    finally:
        await transport._quiet_close(ws)

    server_pub = paired["server_pub_bytes"]
    fp = fingerprint(server_pub)
    device_id = str(paired.get("device_id") or hint)
    store.save(_keys(device_id, priv, pub, url, server_pub, fp))
    log.info("[pairing] спарено (%s): устройство %s, сервер %s", code.mode, device_id, fp)
    return PairResult(device_id=device_id, server_fp=fp, mode=code.mode)


def _keys(device_id, priv, pub, url, server_pub, fp):
    from core.secure_store import DeviceKeys
    b64 = lambda b: base64.b64encode(b).decode()
    return DeviceKeys(device_id=device_id, priv=b64(priv), pub=b64(pub), server_url=url,
                      server_pub=b64(server_pub), server_fp=fp, paired_at=time.time())


def describe(result: PairResult) -> str:
    """Текст для пользователя после спаривания."""
    tail = ("ключ сервера сверен с QR" if result.mode == "qr"
            else "сверьте отпечаток с сообщением /pair в Telegram; "
                 "не совпадает — «Сбросить спаривание»")
    return f"Спарено: {result.device_id}, отпечаток сервера {result.server_fp} — {tail}"


def main() -> int:
    import getpass
    code = getpass.getpass("QR-строка или 8 слов из /pair (ввод скрыт): ")
    try:
        result = asyncio.run(pair_device(code))
    except PairingError as e:
        print(f"Не удалось: {e}")
        return 1
    print(describe(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

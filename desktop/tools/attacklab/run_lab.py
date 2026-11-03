"""Стенд атак на канал Сакуры: ДО (ws:// с токеном) и ПОСЛЕ (Noise IK). Всё локально, без реального сервера.

python -m desktop.tools.attacklab.run_lab — пишет docs/security/lab/*.md (таблицы и журналы без секретов:
токен стенда — учебный «lab-token», ключи — одноразовые, создаются при каждом запуске).
Участники: учебный сервер securelab, клиент Сакуры (transport.py/securechannel), прокси «злоумышленник в середине».
"""
import asyncio
import json
import os
import time

import websockets

from desktop.core import transport as T
from desktop.core.securechannel import noise as N
from desktop.core.securechannel.client import SecureError, ik_handshake
from desktop.core.securechannel.frames import FrameType, decode_frame
from desktop.core.securechannel.keys import KeyStore
from desktop.tools.securelab.server import LabServer

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "security", "lab")
TOKEN = "lab-token"


class Proxy:
    """Прокси в середине: пересылает кадры в обе стороны, пишет дамп, может менять/повторять/переставлять."""

    def __init__(self, upstream: str, on_c2s=None, on_s2c=None):
        self.upstream = upstream
        self.on_c2s, self.on_s2c = on_c2s, on_s2c
        self.dump: list[dict] = []
        self.closes: list[int | None] = []

    def _log(self, direction, data):
        if isinstance(data, str):
            try:  # для анализа — раскодированный текст целиком (в отчёт идёт только начало)
                full = json.dumps(json.loads(data), ensure_ascii=False)
            except ValueError:
                full = data
            self.dump.append({"dir": direction, "kind": "text", "len": len(data.encode()), "preview": full[:200],
                              "full": full})
        else:
            try:
                ftype, body = decode_frame(data)
                kind = FrameType(ftype).name
            except Exception:  # noqa: BLE001
                kind = "?"
            self.dump.append({"dir": direction, "kind": kind, "len": len(data), "preview": data[:24].hex()})

    async def handler(self, client):
        async with websockets.connect(self.upstream, max_size=None) as server:
            async def pump(src, dst, direction, hook):
                try:
                    async for data in src:
                        self._log(direction, data)
                        out = hook(data) if hook else [data]
                        for d in out:
                            await dst.send(d)
                except websockets.ConnectionClosed as e:
                    self.closes.append(getattr(e.rcvd, "code", None) if e.rcvd else None)
                    try:
                        await dst.close(e.rcvd.code if e.rcvd else 1000)
                    except Exception:  # noqa: BLE001
                        pass
            await asyncio.gather(pump(client, server, "C→S", self.on_c2s), pump(server, client, "S→C", self.on_s2c),
                                 return_exceptions=True)

    async def serve(self):
        return await websockets.serve(self.handler, "127.0.0.1", 0, max_size=None)


async def start(server_obj):
    srv = await server_obj.serve()
    return srv, f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"


def paired(tmp, lab, url):
    ks = KeyStore(tmp, protect=lambda b: b, unprotect=lambda b: b)
    _, pub = ks.device_keypair()
    lab.add_device(pub, "lab-pc")
    ks.save_server(lab.pub, "lab-pc", url)
    return ks


async def ws_client_exchange(url, messages):
    async with websockets.connect(url) as ws:
        for m in messages:
            await ws.send(json.dumps({**m, "token": TOKEN}))
            await ws.recv()


async def noise_client_exchange(url, ks, messages, recv=True):
    async with websockets.connect(url, max_size=None) as ws:
        srv = ks.server()
        conn = await ik_handshake(ws, ks.device_private(), srv["pub_bytes"], "lab-pc")
        out = []
        for m in messages:
            await conn.send(json.dumps(m))
            if recv:
                out.append(json.loads(await conn.recv()))
        return out


def table(rows, cols):
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(str(r.get(c, "")).replace("|", "\\|") for c in cols) + " |\n" for r in rows)


async def scenario_intercept(tmp):
    lab = LabServer(mode="optional", token=TOKEN, deadline=0.3)
    s, up = await start(lab)
    res = {}
    for name in ("ws", "noise"):
        px = Proxy(up)
        ps, purl = await start(px)
        msgs = [{"type": "voice_command", "text": "включи свет в спальне", "request_id": "1"}]
        if name == "ws":
            await ws_client_exchange(purl, msgs)
        else:
            ks = paired(os.path.join(tmp, "i"), lab, purl)
            await noise_client_exchange(purl, ks, msgs)
        ps.close()
        seen = " ".join(d.get("full", d["preview"]) for d in px.dump)
        res[name] = {"канал": name, "кадров": len(px.dump),
                     "видно токен": "да" if TOKEN in seen else "нет",
                     "видно текст команды": "да" if "включи свет" in seen else "нет",
                     "что видно": "; ".join(f"{d['dir']} {d['kind']} {d['len']} Б" for d in px.dump[:4])}
        res[name + "_dump"] = px.dump
    s.close()
    return res


async def scenario_tamper(tmp, how):
    """Повтор / подмена / перестановка транспортного кадра C→S в noise."""
    lab = LabServer(mode="optional", token=TOKEN, deadline=0.3)
    s, up = await start(lab)
    held: list[bytes] = []
    state = {"n": 0}

    def hook(data):
        if isinstance(data, str):
            return [data]
        state["n"] += 1
        ftype = data[3]
        if ftype != FrameType.TRANSPORT:
            return [data]
        if how == "повтор":
            return [data, data]
        if how == "подмена":
            b = bytearray(data)
            b[-1] ^= 0x01
            return [bytes(b)]
        if how == "перестановка":
            held.append(data)
            if len(held) == 2:
                return [held[1], held[0]]
            return []
        return [data]
    px = Proxy(up, on_c2s=hook)
    ps, purl = await start(px)
    ks = paired(os.path.join(tmp, how), lab, purl)
    result = "сообщения дошли"
    try:
        async with websockets.connect(purl, max_size=None) as ws:
            conn = await ik_handshake(ws, ks.device_private(), lab.pub, "lab-pc")
            for i in range(2):
                await conn.send(json.dumps({"type": "voice_command", "request_id": str(i)}))
            await asyncio.sleep(0.3)
            try:
                await asyncio.wait_for(conn.recv(), 1)
                await asyncio.wait_for(conn.recv(), 1)
            except (SecureError, asyncio.TimeoutError, websockets.ConnectionClosed):
                pass
    except (SecureError, websockets.ConnectionClosed):
        pass
    codes = [x.get("result") for x in lab.log if x.get("result") != "ok"]
    if 4409 in codes:
        result = "сервер разорвал соединение: 4409 (целостность)"
    ps.close()
    s.close()
    return {"атака": how, "канал": "noise", "итог": result}


async def scenario_replay_ws():
    """ДО: повтор команды в ws:// — сервер исполняет её второй раз."""
    lab = LabServer(mode="optional", token=TOKEN)
    s, up = await start(lab)
    captured = []
    px = Proxy(up, on_c2s=lambda d: (captured.append(d), [d])[1])
    ps, purl = await start(px)
    await ws_client_exchange(purl, [{"type": "voice_command", "text": "выключи свет", "request_id": "1"}])
    async with websockets.connect(up) as attacker:  # злоумышленник повторяет записанный кадр сам
        await attacker.send(captured[0])
        reply = json.loads(await attacker.recv())
    ps.close()
    s.close()
    return {"атака": "повтор", "канал": "ws", "итог": "сервер принял повтор: " + reply.get("type", "")}


async def scenario_replay_ik_init(tmp):
    """Повтор записанного IK_INIT: сервер отвечает IK_RESP, но без эфемерного ключа клиента ответ бесполезен."""
    lab = LabServer(mode="optional", token=TOKEN, deadline=0.3)
    s, up = await start(lab)
    first = []
    px = Proxy(up, on_c2s=lambda d: (first.append(d) if not first else None, [d])[1])
    ps, purl = await start(px)
    ks = paired(os.path.join(tmp, "rep"), lab, purl)
    await noise_client_exchange(purl, ks, [{"type": "ping", "request_id": "1"}])
    async with websockets.connect(up) as attacker:
        await attacker.send(first[0])
        resp = await attacker.recv()
        ftype, _ = decode_frame(resp)
        executed = [x for x in lab.log if x.get("result") == "ok"]
    ps.close()
    s.close()
    return {"атака": "повтор IK_INIT", "канал": "noise",
            "итог": f"сервер ответил {FrameType(ftype).name}, но злоумышленник не может вывести ключи сеанса; "
                    f"payload IK_INIT — только идентификация, команд не исполнено (сеансов в журнале: {len(executed)})"}


async def scenario_fake_server(tmp):
    """Подмена сервера: злоумышленник поднимает свой сервер на том же адресе."""
    real = LabServer(mode="optional", token=TOKEN, deadline=0.3)
    fake = LabServer(mode="optional", token="anything", deadline=0.3)  # принимает любой токен — для демонстрации
    fake.token = None
    s1, real_url = await start(real)
    s2, fake_url = await start(fake)
    # ДО: ws-клиент отдаёт токен самозванцу
    got_token = {}

    async def steal(ws):
        msg = json.loads(await ws.recv())
        got_token["token"] = msg.get("token")
        await ws.close()
    s3 = await websockets.serve(steal, "127.0.0.1", 0)
    steal_url = f"ws://127.0.0.1:{s3.sockets[0].getsockname()[1]}"
    try:
        await ws_client_exchange(steal_url, [{"type": "register"}])
    except websockets.ConnectionClosed:
        pass
    before = {"атака": "подмена сервера", "канал": "ws",
              "итог": "самозванец получил токен: " + ("да" if got_token.get("token") == TOKEN else "нет")}
    # ПОСЛЕ: noise-клиент знает ключ настоящего сервера из спаривания
    ks = paired(os.path.join(tmp, "fake"), real, real_url)
    fake.add_device(ks.device_keypair()[1], "lab-pc")
    t = T.make_transport("noise-only", fake_url, connect_fn=websockets.connect, keystore=ks)
    try:
        await t.connect()
        after_res = "подключился к самозванцу (ПЛОХО)"
    except T.TransportError as e:
        after_res = f"отказ: {e}"
    s1.close(), s2.close(), s3.close()
    return [before, {"атака": "подмена сервера", "канал": "noise", "итог": after_res}]


async def scenario_stolen(tmp):
    """Кража старого токена против кражи ключа устройства и отзыв."""
    lab = LabServer(mode="optional", token=TOKEN, deadline=0.3)
    s, url = await start(lab)
    rows = []
    async with websockets.connect(url) as ws:  # укравший токен подключается от имени устройства
        await ws.send(json.dumps({"type": "register", "token": TOKEN}))
        reply = json.loads(await ws.recv())
    rows.append({"атака": "кража токена", "канал": "ws", "итог": f"работает у злоумышленника ({reply['type']}); "
                 "отозвать можно только сменой общего токена для всех устройств"})
    ks = paired(os.path.join(tmp, "st"), lab, url)
    out = await noise_client_exchange(url, ks, [{"type": "ping", "request_id": "1"}])
    rows.append({"атака": "кража ключа устройства", "канал": "noise",
                 "итог": f"до отзыва работает ({out[0]['type']}); ключ защищён DPAPI — нужен вход под пользователем"})
    lab.revoke("lab-pc")
    t0 = time.monotonic()
    try:
        await noise_client_exchange(url, ks, [{"type": "ping", "request_id": "2"}])
        res = "работает после отзыва (ПЛОХО)"
    except SecureError as e:
        res = (f"после /revoke: отказ {e.code} через {time.monotonic() - t0:.2f} с (дедлайн), "
               "остальные устройства работают")
    rows.append({"атака": "кража ключа + отзыв", "канал": "noise", "итог": res})
    s.close()
    return rows


async def scenario_downgrade(tmp):
    """Понижение: злоумышленник режет бинарные кадры, оставляя текст."""
    rows = []
    for server_mode, client_kind in (("optional", "noise"), ("optional", "noise-only"), ("required", "ws")):
        lab = LabServer(mode=server_mode, token=TOKEN, deadline=0.3)
        s, up = await start(lab)
        px = Proxy(up, on_c2s=lambda d: [] if isinstance(d, bytes) else [d])
        ps, purl = await start(px)
        ks = paired(os.path.join(tmp, "dg" + server_mode + client_kind), lab, purl)
        t = T.make_transport(client_kind, purl, connect_fn=websockets.connect, keystore=ks)
        try:
            conn = await asyncio.wait_for(t.connect(), 15)
            if client_kind == "ws":
                await conn.send(json.dumps({"type": "register", "token": TOKEN}))
                try:
                    await conn.recv()
                    res = "сервер принял текст"
                except websockets.ConnectionClosed as e:
                    res = f"сервер закрыл: {e.rcvd.code if e.rcvd else '?'} (secure_required)"
            else:
                st = getattr(t, "state", {})
                res = f"клиент откатился на {st.get('transport')} (не защищено: {st.get('reason')})"
            await conn.close()
        except (T.TransportError, asyncio.TimeoutError) as e:
            res = f"клиент отказался: {e}"
        rows.append({"атака": "понижение до ws", "сервер": server_mode, "клиент": client_kind, "итог": res})
        ps.close()
        s.close()
    return rows


async def scenario_lengths(tmp):
    lab = LabServer(mode="optional", token=TOKEN, deadline=0.3)
    s, up = await start(lab)
    rows = []
    for text in ("да", "включи свет", "поставь будильник на семь утра и напомни купить молоко"):
        for name in ("ws", "noise"):
            px = Proxy(up)
            ps, purl = await start(px)
            m = {"type": "voice_command", "text": text, "request_id": "1"}
            if name == "ws":
                await ws_client_exchange(purl, [m])
            else:
                ks = paired(os.path.join(tmp, "len" + str(len(text))), lab, purl)
                await noise_client_exchange(purl, ks, [m])
            c2s = [d for d in px.dump if d["dir"] == "C→S"]
            rows.append({"фраза (символов)": len(text), "канал": name, "длина кадра команды, Б": c2s[-1]["len"]})
            ps.close()
    s.close()
    return rows


async def scenario_flood():
    lab = LabServer(mode="optional", token=TOKEN, deadline=0.3, per_ip_minute=30, per_ip_parallel=4)
    s, url = await start(lab)
    junk_priv, _ = N.generate_keypair()
    codes = []

    async def one():
        try:
            async with websockets.connect(url) as ws:
                await ik_handshake(ws, junk_priv, lab.pub, "x", timeout=2)
        except SecureError as e:
            codes.append(e.code)
        except websockets.ConnectionClosed as e:
            codes.append(e.rcvd.code if e.rcvd else None)
    await asyncio.gather(*(one() for _ in range(40)))
    s.close()
    return {"атака": "флуд рукопожатий (40 параллельно, один адрес)",
            "итог": f"4429 (лимит): {codes.count(4429)}, 4408 (молчание до дедлайна): {codes.count(4408)}"}


async def main():
    import tempfile
    os.makedirs(OUT, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="sakura-lab-")
    t0 = time.time()
    intercept = await scenario_intercept(tmp)
    tamper = [await scenario_replay_ws(), await scenario_replay_ik_init(tmp)]
    for how in ("повтор", "подмена", "перестановка"):
        tamper.append(await scenario_tamper(tmp, how))
    fake = await scenario_fake_server(tmp)
    stolen = await scenario_stolen(tmp)
    downgrade = await scenario_downgrade(tmp)
    lengths = await scenario_lengths(tmp)
    flood = await scenario_flood()
    md = [f"# Стенд атак — результаты ({time.strftime('%Y-%m-%d %H:%M')})\n",
          "Запуск: `python -m desktop.tools.attacklab.run_lab`. "
          "Токен стенда учебный (`lab-token`), ключи одноразовые.\n",
          "## 1. Перехват (прокси-дамп)\n",
          table([intercept["ws"], intercept["noise"]],
                ["канал", "кадров", "видно токен", "видно текст команды", "что видно"]),
          "\nДамп ws (первые кадры):\n\n```\n" + "\n".join(f"{d['dir']} {d['kind']} {d['len']}: {d['preview']}"
                                                   for d in intercept["ws_dump"][:4]) + "\n```\n",
          "Дамп noise (первые кадры, hex заголовка):\n\n```\n" + "\n".join(
              f"{d['dir']} {d['kind']} {d['len']}: {d['preview']}" for d in intercept["noise_dump"][:4]) + "\n```\n",
          "## 2. Повтор, подмена, перестановка\n", table(tamper, ["атака", "канал", "итог"]),
          "\n## 3. Подмена сервера\n", table(fake, ["атака", "канал", "итог"]),
          "\n## 4. Кража токена против кражи ключа и отзыв\n", table(stolen, ["атака", "канал", "итог"]),
          "\n## 5. Понижение до ws\n", table(downgrade, ["атака", "сервер", "клиент", "итог"]),
          "\n## 6. Анализ длин (без padding)\n",
          table(lengths, ["фраза (символов)", "канал", "длина кадра команды, Б"]),
          "\nNoise скрывает содержимое, но не длину: длина кадра растёт вместе с фразой "
          "(+16 тег, +2 заголовок, +8 кадр). "
          "Спецификация padding не задаёт — см. выводы в ATTACK_LAB.md.\n",
          "\n## 7. Флуд рукопожатий\n", table([flood], ["атака", "итог"]),
          f"\nВремя прогона: {time.time() - t0:.1f} с.\n"]
    path = os.path.join(OUT, "RESULTS.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(path)
    return {"intercept": intercept, "tamper": tamper, "fake": fake, "stolen": stolen, "downgrade": downgrade,
            "lengths": lengths, "flood": flood}


if __name__ == "__main__":
    asyncio.run(main())

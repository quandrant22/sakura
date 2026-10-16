"""Измерения канала: ws, wss (TLS 1.3, самоподписанный сертификат стенда) и noise (securechannel/1).

python -m desktop.tools.bench.run_bench — пишет docs/security/lab/bench.json и графики bench_*.png
(для графиков нужен matplotlib; без него — только таблицы). Всё на 127.0.0.1: сеть не участвует,
меряется стоимость протокола (рукопожатие, шифрование, кадры), а не задержка интернета.
"""
import asyncio
import base64
import datetime
import ipaddress
import json
import os
import ssl
import statistics
import tempfile
import time

import psutil
import websockets

from desktop.core.securechannel.client import ik_handshake
from desktop.core.securechannel.keys import KeyStore
from desktop.tools.securelab.server import LabServer

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "security", "lab")
HANDSHAKES = 60
# ws/wss — как сейчас в Сакуре (permessage-deflate по умолчанию); -nc — без сжатия; noise — всегда без сжатия
KINDS = ("ws", "ws-nc", "wss", "wss-nc", "noise")
SIZES = (256, 4096, 65536, 1048576)
PER_SIZE = {256: 400, 4096: 300, 65536: 60, 1048576: 8}


def self_signed():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .sign(key, hashes.SHA256()))
    d = tempfile.mkdtemp(prefix="bench-")
    cp, kp = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
    open(cp, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
    open(kp, "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    srv = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    srv.minimum_version = ssl.TLSVersion.TLSv1_3
    srv.load_cert_chain(cp, kp)
    cli = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cli.minimum_version = ssl.TLSVersion.TLSv1_3
    cli.load_verify_locations(cp)
    return srv, cli


def stats(xs):
    xs = sorted(xs)
    return {"median": round(statistics.median(xs), 3), "p95": round(xs[int(0.95 * (len(xs) - 1))], 3),
            "stdev": round(statistics.pstdev(xs), 3), "n": len(xs)}


class Bench:
    def __init__(self):
        self.lab = LabServer(mode="optional", token="lab-token", deadline=1.0, per_ip_minute=10**6, per_ip_parallel=64)
        self.ks = KeyStore(tempfile.mkdtemp(prefix="bench-ks-"), protect=lambda b: b, unprotect=lambda b: b)
        _, pub = self.ks.device_keypair()
        self.lab.add_device(pub, "bench")
        self.ks.save_server(self.lab.pub, "bench", "")
        self.srv_ssl, self.cli_ssl = self_signed()

    async def start(self):
        self.plain = await websockets.serve(self.lab.handler, "127.0.0.1", 0, max_size=None)
        self.tls = await websockets.serve(self.lab.handler, "127.0.0.1", 0, max_size=None, ssl=self.srv_ssl)
        self.url = f"ws://127.0.0.1:{self.plain.sockets[0].getsockname()[1]}"
        self.urls = f"wss://127.0.0.1:{self.tls.sockets[0].getsockname()[1]}"

    async def connect(self, kind):
        """Соединение готово к первой команде приложения (рукопожатие транспорта + register/echo)."""
        if kind == "noise":
            ws = await websockets.connect(self.url, max_size=None, compression=None)
            conn = await ik_handshake(ws, self.ks.device_private(), self.lab.pub, "bench")
            return conn, ws
        comp = {"compression": None} if kind.endswith("-nc") else {}
        if kind.startswith("wss"):
            ws = await websockets.connect(self.urls, ssl=self.cli_ssl, max_size=None, **comp)
        else:
            ws = await websockets.connect(self.url, max_size=None, **comp)

        class Plain:
            async def send(self, m):
                d = json.loads(m)
                d["token"] = "lab-token"
                await ws.send(json.dumps(d))

            async def recv(self):
                return await ws.recv()
        return Plain(), ws

    async def handshake(self, kind):
        times = []
        for _ in range(HANDSHAKES):
            t = time.perf_counter()
            conn, ws = await self.connect(kind)
            await conn.send(json.dumps({"type": "register", "request_id": "r"}))
            await conn.recv()
            times.append((time.perf_counter() - t) * 1000)
            await ws.close()
        return stats(times)

    async def throughput(self, kind, size):
        conn, ws = await self.connect(kind)
        # несжимаемые данные (как скриншот/аудио): сравнение ws и noise без выигрыша deflate на «xxxx»
        payload = json.dumps({"type": "blob", "request_id": "b",
                              "data": base64.b64encode(os.urandom(size * 3 // 4)).decode()})
        n = PER_SIZE[size]
        proc = psutil.Process()
        cpu0 = proc.cpu_times()
        t = time.perf_counter()
        lat = []
        for _ in range(n):
            t1 = time.perf_counter()
            await conn.send(payload)
            await conn.recv()
            lat.append((time.perf_counter() - t1) * 1000)
        dt = time.perf_counter() - t
        cpu1 = proc.cpu_times()
        await ws.close()
        cpu = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)
        return {"size": size, "msgs": n, "MiB_s": round(n * size / dt / 2**20, 2), "rtt_ms": stats(lat),
                "cpu_ms_per_msg": round(cpu * 1000 / n, 3)}


async def main():
    b = Bench()
    await b.start()
    proc = psutil.Process()
    res = {"handshake_ms": {}, "throughput": {}, "memory_kib": {}, "env": {
        "python": os.sys.version.split()[0], "websockets": websockets.__version__, "cpu": psutil.cpu_count(),
        "when": time.strftime("%Y-%m-%d %H:%M")}}
    for kind in KINDS:
        res["handshake_ms"][kind] = await b.handshake(kind)
        res["throughput"][kind] = [await b.throughput(kind, s) for s in SIZES]
        import gc
        import tracemalloc
        gc.collect()
        tracemalloc.start()
        m0 = tracemalloc.get_traced_memory()[0]
        conns = [await b.connect(kind) for _ in range(50)]
        gc.collect()
        res["memory_kib"][kind] = round((tracemalloc.get_traced_memory()[0] - m0) / 50 / 1024, 1)  # на соединение
        tracemalloc.stop()
        for _, ws in conns:
            await ws.close()
    b.plain.close()
    b.tls.close()
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(os.path.join(OUT, "bench.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        plot(res)
    except ImportError:
        print("matplotlib нет — графики пропущены")
    print(json.dumps(res["handshake_ms"], ensure_ascii=False))
    return res


def plot(res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    kinds = KINDS
    colors = {"ws": "#8a8a99", "ws-nc": "#55556a", "wss": "#3b82f6", "wss-nc": "#1e40af", "noise": "#d946ef"}
    fig, ax = plt.subplots(figsize=(6, 3.4))
    med = [res["handshake_ms"][k]["median"] for k in kinds]
    p95 = [res["handshake_ms"][k]["p95"] for k in kinds]
    ax.bar(kinds, med, color=[colors[k] for k in kinds], label="медиана")
    ax.errorbar(kinds, med, yerr=[[0] * len(kinds), [p - m for p, m in zip(p95, med, strict=True)]], fmt="none", ecolor="#333",
                capsize=5, label="до p95")
    ax.set_ylabel("мс")
    ax.set_title("Установление соединения до первого ответа (127.0.0.1)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "bench_handshake.png"), dpi=130)
    fig, ax = plt.subplots(figsize=(6, 3.4))
    for k in kinds:
        ax.plot([t["size"] for t in res["throughput"][k]], [t["MiB_s"] for t in res["throughput"][k]], "o-",
                color=colors[k], label=k)
    ax.set_xscale("log", base=2)
    ax.set_xlabel("размер сообщения, Б")
    ax.set_ylabel("МиБ/с (эхо туда-обратно)")
    ax.set_title("Пропускная способность")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "bench_throughput.png"), dpi=130)


if __name__ == "__main__":
    asyncio.run(main())

"""Иллюстрации к Пяти Свиткам — тушь на бумаге васи (PNG, 1600×900).

  media/images/charts/river-of-time.png                 — Река Времени: коммиты по месяцам (из git)
  media/images/diagrams/scroll-1-path-of-hearing.png    — Путь Слуха
  media/images/diagrams/scroll-2-two-mirrors.png        — Живой голос и Два Зеркала Памяти
  media/images/diagrams/scroll-3-hundred-forty-arts.png — свиток умений (из sakura_core/capabilities.yaml)
  media/images/diagrams/scroll-4-invisible-armor.png    — Незримый Доспех
  media/images/diagrams/scroll-5-three-gifts.png        — Три Дара и 3 383 испытания

Запуск из корня репозитория: python site/tools/generate_diagrams_and_charts.py
"""

from __future__ import annotations

import collections
import math
import random
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import legend_common as L

W, H = 1600, 900
INK = L.SUMI + (255,)
INK_SOFT = L.SUMI_SOFT + (255,)
RED = L.VERMILION + (255,)

MONTHS_RU = {"07": "Июль", "08": "Август", "09": "Сентябрь", "10": "Октябрь", "11": "Ноябрь", "12": "Декабрь"}
DOMAINS_RU = {
    "music": "Музыка", "youtube": "YouTube", "browser": "Браузер", "companion": "Спутница в играх",
    "window": "Окна", "steam": "Steam", "files": "Файлы", "coding": "Код", "system": "Система",
    "kettle": "Чайник", "schedule": "Расписание", "ui": "Облик", "vision": "Зрение",
}


# ── бумага и кисть ──────────────────────────────────────────────────────
def paper(seed=1) -> Image.Image:
    """Бумага без мелкого зерна: волокна крупные и мягкие — PNG остаётся лёгким."""
    rng = np.random.default_rng(seed)
    base = np.ones((H, W, 3), dtype=np.float32) * np.array(L.PAPER, dtype=np.float32)
    fib = rng.normal(0, 1, (H // 24 + 1, W // 60 + 1)).astype(np.float32)
    fib = np.asarray(Image.fromarray(((fib + 3) * 40).clip(0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
                     .filter(ImageFilter.GaussianBlur(6)), dtype=np.float32) / 255 - 0.5
    yy = np.linspace(-1, 1, H)[:, None]
    xx = np.linspace(-1, 1, W)[None, :]
    base += (fib * 14)[..., None]
    base *= (1 - 0.07 * (xx ** 2 + yy ** 2))[..., None]
    img = Image.fromarray(base.clip(0, 255).round().astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    d.rectangle([24, 24, W - 25, H - 25], outline=L.SUMI_SOFT, width=2)
    d.rectangle([32, 32, W - 33, H - 33], outline=L.PAPER_SHADE, width=1)
    return img


def brush(d: ImageDraw.ImageDraw, pts, w0: float, w1: float, color=INK, taper=True, seed=0):
    """Мазок кистью: плотная цепочка кругов с меняющейся толщиной и «сухими» краями."""
    rnd = random.Random(seed)
    dense = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(2, int(math.hypot(x1 - x0, y1 - y0) / 1.5))
        dense += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n)]
    dense.append(pts[-1])
    total = len(dense)
    for i, (x, y) in enumerate(dense):
        u = i / max(1, total - 1)
        w = w0 + (w1 - w0) * u
        if taper:
            w *= min(1.0, u * 8 + 0.25) * min(1.0, (1 - u) * 6 + 0.15)
        w *= 0.92 + 0.16 * rnd.random()
        r = max(0.6, w / 2)
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


def curve(p0, p1, p2, n=40):
    """Квадратичная кривая Безье p0→p2 через p1."""
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / n for i in range(n + 1))]


def enso(d, cx, cy, r, width=14, gap=0.5, start=-1.9, color=INK, seed=1):
    """Круг дзэн 円相 — одним движением, с разрывом."""
    n = 120
    pts = [(cx + r * math.cos(start + (math.tau - gap) * i / n), cy + r * math.sin(start + (math.tau - gap) * i / n))
           for i in range(n + 1)]
    brush(d, pts, width * 1.15, width * 0.55, color, seed=seed)


def arrow(d, pts, color=INK, w=5, head=16, seed=0):
    brush(d, pts, w, w * 0.8, color, taper=False, seed=seed)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    a = math.atan2(y1 - y0, x1 - x0)
    for s in (-1, 1):
        brush(d, [(x1, y1), (x1 - head * math.cos(a + s * 0.45), y1 - head * math.sin(a + s * 0.45))],
              w, w * 0.6, color, taper=False, seed=seed + s)


def petals_scatter(d, n, seed, box=(40, 40, W - 40, H - 40), alpha=170):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.uniform(box[0], box[2]), rnd.uniform(box[1], box[3])
        col = rnd.choice([L.SAKURA, L.SAKURA_PALE, (238, 150, 180)])
        d.polygon(L.petal_polygon(x, y, rnd.uniform(6, 12), rnd.uniform(0, 6.3), rnd.uniform(0.4, 1), 8),
                  fill=col + (alpha,))


def header(img, d, num: str, title: str, subtitle: str):
    L.paste(img, L.seal((num,), 92, seed=ord(num)), (98, 98))
    L.text(d, (162, 64), title, L.font("serif_bold", 44), INK)
    L.text(d, (164, 124), subtitle, L.font("serif", 25), INK_SOFT)


def footer(img, d, s: dict):
    txt = f"Печать Времени {s['seal']} · {s['date']}"
    fnt = L.font("serif", 22)
    L.text(d, (W - 116, H - 66), txt, fnt, INK_SOFT, anchor="rm")
    L.paste(img, L.seal((s["seal"][:4], s["seal"][4:]), 64, seed=9), (W - 74, H - 70))


def label_block(d, x, y, head: str, body: str, width: int, head_size=30, body_size=22, align="mm"):
    fh, fb = L.font("serif_bold", head_size), L.font("serif", body_size)
    L.text(d, (x, y), head, fh, INK, anchor="mt")
    yy = y + head_size * 1.45
    for line in L.wrap(body, fb, width):
        L.text(d, (x, yy), line, fb, INK_SOFT, anchor="mt")
        yy += body_size * 1.45
    return yy


def stamp(img, kanji: str, center, size, round_seal=True, seed=3):
    L.paste(img, L.seal((kanji,), size, round_seal=round_seal, seed=seed), center)


# ── данные ──────────────────────────────────────────────────────────────
def commits_by_month() -> list[tuple[str, int]]:
    try:
        out = subprocess.run(["git", "-C", str(L.ROOT), "log", "--format=%ad", "--date=format:%Y-%m"],
                             capture_output=True, text=True, check=True).stdout.split()
        c = collections.Counter(out)
        return sorted(c.items())
    except (OSError, subprocess.CalledProcessError):
        return [("2026-07", 30), ("2026-08", 35), ("2026-09", 183), ("2026-10", 302), ("2026-11", 133)]


def capability_domains() -> list[tuple[str, int]]:
    import yaml
    data = yaml.safe_load((L.ROOT / "sakura_core" / "capabilities.yaml").read_text(encoding="utf-8"))
    c = collections.Counter(item["id"].split(".")[0] for item in data)
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))


# ── 1. Река Времени ─────────────────────────────────────────────────────
def river_of_time():
    months = commits_by_month()
    total = sum(n for _, n in months)
    img = paper(11)
    d = ImageDraw.Draw(img, "RGBA")
    L.paste(img, L.seal(("時",), 92, seed=5), (98, 98))
    L.text(d, (162, 64), "Река Времени · 時の川", L.font("serif_bold", 44), INK)
    L.text(d, (164, 124), f"{total} Печатей Времени — коммиты по месяцам, июль — ноябрь 2026",
           L.font("serif", 25), INK_SOFT)

    # река внизу
    river = [(40, 728), (300, 708), (600, 742), (900, 712), (1200, 738), (1560, 716)]
    for off, a in ((0, 60), (10, 90), (-8, 70)):
        pts = []
        for (x0, y0), (x1, y1) in zip(river, river[1:]):
            pts += curve((x0, y0 + off), ((x0 + x1) / 2, (y0 + y1) / 2 + 26 + off), (x1, y1 + off), 20)
        brush(d, pts, 9, 7, (92, 112, 140, a), taper=False, seed=off + 40)

    peak = max(n for _, n in months)
    xs = np.linspace(260, 1340, len(months))
    base_y, top_y = 640, 290
    rnd = random.Random(8)
    for i, ((ym, n), x) in enumerate(zip(months, xs)):
        h = (base_y - top_y) * n / peak
        y_top = base_y - h
        # ствол-столбец из туши
        brush(d, [(x + rnd.uniform(-3, 3), base_y), (x + rnd.uniform(-5, 5), (base_y + y_top) / 2), (x, y_top)],
              max(9, min(26, h * 0.12)), max(5, min(12, h * 0.06)), (30, 24, 30, 225), taper=False, seed=i + 3)
        for j in range(3 if h > 160 else 0):  # веточки
            yb = base_y - h * (0.35 + 0.2 * j)
            sgn = -1 if j % 2 else 1
            brush(d, [(x, yb), (x + sgn * 34, yb - 26)], 7, 2, (30, 24, 30, 210), seed=i * 7 + j)
        for k in range(3 + n // 25):  # цветы на вершине — чем больше печатей, тем пышнее
            ox, oy = rnd.uniform(-55, 55), rnd.uniform(-45, 25)
            L.blossom(d, x + ox, y_top + oy, rnd.uniform(11, 19), rnd.choice([L.SAKURA, L.SAKURA_PALE, L.SAKURA]), 250,
                      rnd.uniform(0, 6))
        L.text(d, (x, y_top - 66), str(n), L.font("serif_bold", 44), INK, anchor="ms")
        L.text(d, (x, base_y + 44), MONTHS_RU.get(ym[5:], ym), L.font("serif_bold", 28), INK, anchor="ms")
        if i < len(L.SCROLLS):
            s = L.SCROLLS[i]
            stamp(img, s["num"], (x, 790), 66, seed=20 + i)
            L.text(d, (x, 850), s["seal"], L.font("mono", 20), RED, anchor="ms")
    petals_scatter(d, 26, 4, box=(1380, 160, 1560, 680))
    L.save_png(img, L.CHARTS_DIR / "river-of-time.png")


# ── 2. Путь Слуха ───────────────────────────────────────────────────────
def path_of_hearing():
    s = L.SCROLLS[0]
    img = paper(21)
    d = ImageDraw.Draw(img, "RGBA")
    header(img, d, s["num"], "Путь Слуха · 聴く道", "Как дух учился отличать шум ветра от голоса Мастера")
    stations = [("風", "Ветер", "шум мира: шаги, музыка, чужие голоса"),
                ("耳", "Слух", "внимание отделяет тишину от речи"),
                ("名", "Зов", "имя «Сакура» пробуждает дух"),
                ("心", "Сердце", "state_arbiter знает, что происходит вокруг"),
                ("声", "Голос", "ответ рождается из понимания")]
    xs = [210, 505, 800, 1095, 1390]
    y = 430
    path = []
    for x0, x1 in zip(xs, xs[1:]):
        path += curve((x0, y), ((x0 + x1) / 2, y + (40 if x0 % 2 else -40)), (x1, y), 24)
    brush(d, path, 10, 6, INK, seed=2)
    for k in range(6):  # ветер слева — рваные завитки
        yy = 250 + k * 22
        brush(d, curve((60, yy), (150, yy - 30 + k * 6), (260 - k * 10, yy + 8)), 4, 1, (60, 54, 70, 150), seed=k)
    for k in range(3):  # волны речи над слухом
        r = 70 + k * 26
        d.arc([505 - r, y - r, 505 + r, y + r], 205, 335, fill=(196, 58, 50, 170 - k * 40), width=4)
    for (kanji, head, body), x in zip(stations, xs):
        stamp(img, kanji, (x, y), 118, seed=ord(kanji))
        label_block(d, x, y + 92, head, body, 230)
    L.text(d, (800, 735), "Из тысячи звуков дух выбирает один — голос Мастера.", L.font("serif_bold", 30), INK, anchor="mm")
    petals_scatter(d, 18, 5, box=(1200, 150, 1550, 330))
    footer(img, d, s)
    L.save_png(img, L.DIAGRAMS_DIR / "scroll-1-path-of-hearing.png")


# ── 3. Живой голос и Два Зеркала ────────────────────────────────────────
def two_mirrors():
    s = L.SCROLLS[1]
    img = paper(31)
    d = ImageDraw.Draw(img, "RGBA")
    header(img, d, s["num"], "Живой Голос и Два Зеркала · 二つの鏡", "В речь вплелись чувства, а память разделилась надвое")
    # голос: три тона
    tones = [("柔", "Нежность"), ("諧", "Ирония"), ("厳", "Строгость")]
    L.text(d, (300, 215), "Три тона живого голоса", L.font("serif_bold", 28), INK, anchor="mm")
    for i, (k, name) in enumerate(tones):
        x = 160 + i * 140
        stamp(img, k, (x, 300), 92, seed=50 + i)
        L.text(d, (x, 368), name, L.font("serif", 23), INK_SOFT, anchor="mt")
    arrow(d, curve((560, 300), (700, 262), (840, 285)), seed=4)
    L.text(d, (1200, 230), "Каждое слово окрашено чувством,", L.font("serif", 26), INK_SOFT, anchor="mm")
    L.text(d, (1200, 268), "а ремарка о тоне не звучит вслух.", L.font("serif", 26), INK_SOFT, anchor="mm")
    brush(d, [(80, 430), (1520, 430)], 2, 2, (78, 66, 72, 120), taper=False, seed=1)

    # зеркало мгновения
    mx, my = 300, 540
    d.ellipse([mx - 92, my - 92, mx + 92, my + 92], fill=(214, 222, 228, 255))
    enso(d, mx, my, 95, 12, 0.25, seed=3)
    brush(d, [(mx, my + 98), (mx, my + 140)], 16, 10, (74, 44, 34, 255), taper=False, seed=6)
    for k in range(3):
        d.line([mx - 60 + k * 30, my - 50 + k * 8, mx - 20 + k * 30, my - 70 + k * 8], fill=(255, 255, 255, 200), width=5)
    label_block(d, mx, my + 158, "Зеркало мгновения", "последние слова, открытое окно, текущая игра", 320)

    # врата записи (тории)
    gx, gy = 800, 600
    col = L.VERMILION + (255,)
    brush(d, [(gx - 150, gy - 150), (gx, gy - 165), (gx + 150, gy - 150)], 22, 22, col, taper=False, seed=7)
    brush(d, [(gx - 120, gy - 115), (gx + 120, gy - 115)], 12, 12, col, taper=False, seed=8)
    for sx in (-95, 95):
        brush(d, [(gx + sx, gy - 150), (gx + sx * 1.06, gy + 40)], 18, 20, col, taper=False, seed=9)
    label_block(d, gx, gy + 60, "Врата записи", "в глубину проходит лишь то, что стоит помнить", 320)

    # озеро вечности
    lx, ly = 1270, 545
    d.ellipse([lx - 230, ly - 95, lx + 230, ly + 95], fill=(96, 116, 146, 255))
    d.ellipse([lx - 200, ly - 76, lx + 200, ly + 76], fill=(70, 88, 120, 255))
    for k in range(4):
        rx, ry = 50 + k * 42, 16 + k * 14
        d.ellipse([lx - rx, ly - ry, lx + rx, ly + ry], outline=(220, 228, 240, 150 - k * 30), width=2)
    L.blossom(d, lx + 60, ly - 18, 16, L.SAKURA_PALE, 255, 1)
    label_block(d, lx, ly + 115, "Озеро вечных воспоминаний", "то, что дух хранит месяцами и годами", 360)

    arrow(d, curve((410, 540), (520, 500), (640, 530)), seed=11)
    arrow(d, curve((955, 530), (995, 500), (1030, 535)), seed=12)
    footer(img, d, s)
    L.save_png(img, L.DIAGRAMS_DIR / "scroll-2-two-mirrors.png")


# ── 4. Сто сорок одно искусство ─────────────────────────────────────────
def _spread(items, min_gap, lo, hi):
    """Разводит подписи по вертикали, чтобы они не наезжали друг на друга."""
    items.sort(key=lambda it: it[1])
    for i in range(1, len(items)):
        if items[i][1] - items[i - 1][1] < min_gap:
            items[i][1] = items[i - 1][1] + min_gap
    overflow = items[-1][1] - hi if items else 0
    if overflow > 0:
        for it in items:
            it[1] -= overflow
        for i in range(len(items) - 2, -1, -1):
            if items[i + 1][1] - items[i][1] < min_gap:
                items[i][1] = items[i + 1][1] - min_gap
    for it in items:
        it[1] = max(lo, it[1])
    return items


def hundred_forty_arts():
    s = L.SCROLLS[2]
    domains = capability_domains()
    total = sum(n for _, n in domains)
    img = paper(41)
    d = ImageDraw.Draw(img, "RGBA")
    header(img, d, s["num"], "Свиток Умений · 百四十の術",
           f"{total} искусство в {len(domains)} родах — и отклик быстрее взмаха клинка")
    cx, cy, r_in, r_out = 565, 520, 118, 262
    enso(d, cx, cy, 100, 13, 0.45, seed=5)
    L.text(d, (cx, cy - 12), "術", L.font("serif_bold", 92), INK, anchor="mm")
    L.text(d, (cx, cy + 58), str(total), L.font("serif_bold", 32), RED, anchor="mm")
    rings = 4
    radii = np.linspace(r_in + 42, r_out, rings)
    angle = -math.pi / 2
    labels = []
    for gi, (dom, n) in enumerate(domains):
        span = math.tau * n / total
        rows = min(rings, n)
        per_row = math.ceil(n / rows)
        off = gi % (rings - rows + 1)  # мелкие роды раскладываем по разным кольцам
        col = L.SAKURA if gi % 2 == 0 else L.SAKURA_DEEP
        for k in range(n):  # род — сектор, искусство — цветок в его сетке
            row, colm = k % rows, k // rows
            in_row = min(per_row, n - row) if n % rows == 0 else (n // rows + (1 if row < n % rows else 0))
            a = angle + span * (colm + 0.5) / max(in_row, 1)
            rr = radii[off + row]
            L.blossom(d, cx + rr * math.cos(a), cy + rr * math.sin(a), 9, col, 245, a)
        if dom in DOMAINS_RU:
            labels.append((angle + span / 2, f"{DOMAINS_RU[dom]} · {n}"))
        angle += span
    fnt = L.font("serif", 21)
    right = [[a, cy + (r_out + 52) * math.sin(a), t] for a, t in labels if math.cos(a) >= 0]
    left = [[a, cy + (r_out + 52) * math.sin(a), t] for a, t in labels if math.cos(a) < 0]
    for side, sign in ((right, 1), (left, -1)):
        for a, ly, txt in _spread(side, 30, 190, 790):
            x1, y1 = cx + (r_out + 18) * math.cos(a), cy + (r_out + 18) * math.sin(a)
            x2 = cx + sign * (r_out + 70)
            d.line([x1, y1, x2 - sign * 12, ly, x2, ly], fill=INK_SOFT, width=1)
            L.text(d, (x2 + sign * 6, ly), txt, fnt, INK, anchor="lm" if sign > 0 else "rm")
    others = len(domains) - len(labels)
    L.text(d, (cx, cy + r_out + 70), f"и ещё {others} малых родов", L.font("serif", 22), INK_SOFT, anchor="mm")

    # клинок: молниеносный отклик
    bx = 1365
    brush(d, [(1120, 360), (1320, 270), (1540, 210)], 5, 22, INK, seed=13)
    brush(d, [(1126, 372), (1546, 221)], 1, 2, L.VERMILION + (170,), taper=True, seed=14)
    L.text(d, (bx, 420), "быстрее", L.font("serif", 30), INK_SOFT, anchor="mm")
    L.text(d, (bx, 495), "1.8 мс", L.font("serif_bold", 82), RED, anchor="mm")
    yy = 585
    fnt_p = L.font("serif", 22)
    for para in ["Простые просьбы дух понимает с полуслова — без нейросети.",
                 "Для сложных на печати ceee791 к чутью пришёл разум-классификатор."]:
        for line in L.wrap(para, fnt_p, 370):
            L.text(d, (bx, yy), line, fnt_p, INK_SOFT, anchor="mm")
            yy += 33
        yy += 12
    footer(img, d, s)
    L.save_png(img, L.DIAGRAMS_DIR / "scroll-3-hundred-forty-arts.png")


# ── 5. Незримый доспех ──────────────────────────────────────────────────
def invisible_armor():
    s = L.SCROLLS[3]
    img = paper(51)
    d = ImageDraw.Draw(img, "RGBA")
    header(img, d, s["num"], "Незримый Доспех · 見えざる鎧", "Две вести, общая тайна и узы Kizune-Ryoiki")
    hx, px, gy = 230, 1370, 600
    d.rectangle([hx - 80, gy - 80, hx + 80, gy], fill=INK)
    d.polygon([(hx - 120, gy - 74), (hx, gy - 150), (hx + 120, gy - 74), (hx + 80, gy - 86), (hx, gy - 132),
               (hx - 80, gy - 86)], fill=INK)
    d.rectangle([hx - 45, gy - 60, hx - 15, gy - 26], fill=L.GOLD_PALE + (255,))
    d.rectangle([hx + 15, gy - 60, hx + 45, gy - 26], fill=L.GOLD_PALE + (255,))
    L.text(d, (hx, gy + 36), "主 · Мастер", L.font("serif_bold", 28), INK, anchor="mm")
    y = gy
    for bw, th in ((96, 70), (76, 60), (56, 54)):
        d.rectangle([px - bw * 0.6, y - th, px + bw * 0.6, y], fill=INK)
        d.rectangle([px - 10, y - th * 0.7, px + 10, y - th * 0.2], fill=L.GOLD_PALE + (255,))
        d.polygon([(px - bw - 28, y - th + 12), (px - bw * 0.7, y - th - 22), (px + bw * 0.7, y - th - 22),
                   (px + bw + 28, y - th + 12)], fill=INK)
        y -= th + 20
    d.line([px, y, px, y - 50], fill=INK, width=5)
    L.text(d, (px, gy + 36), "社 · Святилище", L.font("serif_bold", 28), INK, anchor="mm")

    dcx, dcy, rx, ry = 800, gy + 8, 690, 340
    size = 28
    for col in range(-26, 27):
        for row in range(0, 14):
            x = dcx + col * size * 1.5
            yv = dcy - row * size * math.sqrt(3) - (size * math.sqrt(3) / 2 if col % 2 else 0)
            if ((x - dcx) / rx) ** 2 + ((yv - dcy) / ry) ** 2 < 0.9 and yv < dcy - 8:
                pts = [(x + size * 0.9 * math.cos(i * math.pi / 3), yv + size * 0.9 * math.sin(i * math.pi / 3))
                       for i in range(7)]
                d.line(pts, fill=L.GOLD + (120,), width=2)
    d.arc([dcx - rx, dcy - ry, dcx + rx, dcy + ry], 180, 360, fill=L.GOLD + (255,), width=4)

    def tags(points, labels, color):
        for (x, yv), t_ in zip(points, labels):
            fnt = L.font("serif_bold", 24)
            w = fnt.getlength(t_) + 26
            d.rounded_rectangle([x - w / 2, yv - 18, x + w / 2, yv + 18], radius=18, fill=L.PAPER + (255,),
                                outline=color, width=2)
            L.text(d, (x, yv), t_, fnt, color, anchor="mm")

    L.text(d, (800, 205), "Первая весть: мимолётный ключ и сокрытое имя Мастера", L.font("serif", 24), RED, anchor="mm")
    top = curve((hx + 90, gy - 150), (800, 220), (px - 90, gy - 250), 60)
    arrow(d, top, RED, 4, 18, seed=21)
    tags([top[i] for i in (16, 24, 32, 40)], ["e", "es", "s", "ss"], RED)
    low = curve((px - 90, gy - 140), (800, 370), (hx + 90, gy - 110), 60)
    arrow(d, low, INK, 4, 18, seed=22)
    tags([low[i] for i in (20, 30, 40)], ["e", "ee", "se"], INK)
    L.text(d, (800, 512), "Ответ Святилища: ключи сплетаются в общую тайну", L.font("serif", 24), INK, anchor="mm")
    for i in range(5):  # запечатанные кадры
        x = 560 + i * 120
        d.rounded_rectangle([x - 16, gy - 46, x + 16, gy - 14], radius=4, fill=RED)
        L.text(d, (x, gy - 30), "SK", L.font("sans_bold", 14), L.PAPER + (255,), anchor="mm")

    facts = [("鍵", "Ключ устройства", "хранится в защищённом хранилище ПК"),
             ("八", "Восемь слов или QR", "спаривание по Noise XXpsk3"),
             ("拒", "Отказ при повторе", "а также при перестановке и подмене вести"),
             ("証", "Доказано в ProVerif", "тайна и подлинность рукопожатия")]
    for i, (k, head, body) in enumerate(facts):
        x, yv = 150 + (i % 2) * 650, 700 + (i // 2) * 70
        stamp(img, k, (x, yv), 60, seed=70 + i)
        L.text(d, (x + 44, yv - 14), head, L.font("serif_bold", 24), INK, anchor="lm")
        L.text(d, (x + 44, yv + 16), body, L.font("serif", 20), INK_SOFT, anchor="lm")
    L.text(d, (1560, 712), "Noise IK", L.font("serif_bold", 26), INK, anchor="rm")
    L.text(d, (1560, 746), "Curve25519 · ChaChaPoly · BLAKE2s", L.font("serif", 20), INK_SOFT, anchor="rm")
    footer(img, d, s)
    L.save_png(img, L.DIAGRAMS_DIR / "scroll-4-invisible-armor.png")


# ── 6. Три дара ─────────────────────────────────────────────────────────
def three_gifts():
    s = L.SCROLLS[4]
    img = paper(61)
    d = ImageDraw.Draw(img, "RGBA")
    header(img, d, s["num"], "Три Дара Пятого Свитка · 三つの賜物", "Зрение, свет и чутьё — и три тысячи пройденных испытаний")
    gifts = [("目", "Зрение", "по просьбе Мастера дух смотрит на экран и понимает игру изнутри"),
             ("光", "Свет", "рисунки светом поверх экрана: сердце, звезда, кот — больше 35 фигур"),
             ("心", "Чутьё", "отличает беседу от приказа и разбирает составные просьбы")]
    for i, (k, head, body) in enumerate(gifts):
        x = 330 + i * 470
        enso(d, x, 315, 100, 13, 0.5, start=-1.6 + i, seed=30 + i)
        L.text(d, (x, 310), k, L.font("serif_bold", 100), INK if i != 1 else RED, anchor="mm")
        label_block(d, x, 440, head, body, 380, 32, 22)
    cols, cell = 226, 5.2
    x0, y0 = 110, 700
    for i in range(3383):  # полоса испытаний: ровно 3 383 точки
        r, c = divmod(i, cols)
        x, yv = x0 + c * cell, y0 + r * cell
        d.ellipse([x, yv, x + 3.6, yv + 3.6], fill=(L.SAKURA_DEEP if (i * 7) % 13 == 0 else L.SAKURA) + (255,))
    stamp(img, "合格", (1440, 738), 128, round_seal=False, seed=81)
    L.text(d, (x0, y0 - 22), "3 383 испытания — каждое стало раскрывшимся лепестком", L.font("serif_bold", 26), INK,
           anchor="ls")
    footer(img, d, s)
    L.save_png(img, L.DIAGRAMS_DIR / "scroll-5-three-gifts.png")


def main():
    print("[схемы] тушь на васи")
    river_of_time()
    path_of_hearing()
    two_mirrors()
    hundred_forty_arts()
    invisible_armor()
    three_gifts()


if __name__ == "__main__":
    main()

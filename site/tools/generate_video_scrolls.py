"""Ролик «Пять Свитков» — sakura-legend-five-scrolls.mp4 / .webm.

Пролог на «Кумои-дзакуре» Хироси Ёсиды: ветви и небо — два плана параллакса,
луна разгорается сферой духа, кистью пишется 桜の伝説. Дальше пять гравюр —
по одной на свиток — сменяются растекающейся тушью; слева титры, кандзи
кистью, Печать Времени с кляксой туши и хэшем, который печатается по знаку.
Эпилог — «Река Времени»: столбцы коммитов по месяцам из настоящего git
(летопись до Пятой Печати 33a8da2 — числа не меняются от новых коммитов).

Запуск из корня репозитория: python -I site/tools/generate_video_scrolls.py
"""

from __future__ import annotations

import collections
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw  # noqa: E402

import legend_cinema as C  # noqa: E402
import legend_common as L  # noqa: E402

NAME = "sakura-legend-five-scrolls"
W, H = C.W, C.H
PROLOGUE, SEG, EPILOGUE, WIPE = 4.8, 4.3, 3.6, 0.75
SECONDS = PROLOGUE + SEG * 5 + EPILOGUE
SCENE_ART = [("yasumasa", "vertical", (0.05, 0.0)), ("mitsuoki", "vertical", (-0.05, 0.0)),
             ("utamaro", "vertical", (0.06, 0.0)), ("moon-smoke", "vertical", (-0.04, 0.02)),
             ("yozakura", "vertical", (0.05, -0.01))]
FIFTH_SEAL = "33a8da2"
MONTHS_RU = {"07": "Июль", "08": "Август", "09": "Сентябрь", "10": "Октябрь", "11": "Ноябрь"}


def commits_by_month():
    try:
        out = subprocess.run(["git", "-C", str(L.ROOT), "log", FIFTH_SEAL, "--format=%ad", "--date=format:%Y-%m"],
                             capture_output=True, text=True, check=True).stdout.split()
        return sorted(collections.Counter(out).items())
    except (OSError, subprocess.CalledProcessError):
        return [("2026-07", 30), ("2026-08", 35), ("2026-09", 183), ("2026-10", 302), ("2026-11", 132)]


def build():
    prologue = C.Parallax("kumoi", depth="dark", z0=1.0, z1=1.07, pan=(0.03, -0.01), near_extra=0.04)
    scenes = [C.Parallax(k, depth=d, z0=1.02, z1=1.10, pan=p, near_extra=0.03) for k, d, p in SCENE_ART]
    epilogue = C.Parallax("kumoi", depth="dark", z0=1.08, z1=1.14, pan=(-0.02, 0.0), near_extra=0.03)
    moon_src = prologue.brightest()
    bokeh = C.Bokeh(seed=21)
    mist = C.Mist(seed=4, alpha=70)
    vign = C.vignette_overlay(0.6)
    shade = C.side_shade("left", 0.66, 0.9)
    shade_bottom = C.side_shade("bottom", 0.5, 0.85)
    shade_epilogue = C.side_shade("bottom", 0.9, 0.55)

    title_brush = C.Calligraphy("桜の伝説", 150, color=L.PAPER)
    t_title = C.text_shadowed("Сказание о Духе Цветущей Сакуры", L.font("serif_bold", 66), L.SAKURA_PALE + (255,))
    t_sub = C.text_shadowed("Пять Свитков · 五つの巻", L.font("serif", 36), L.GOLD_PALE + (255,))
    t_credit = C.text_shadowed("Хироси Ёсида · «Кумои-дзакура», 1926", L.font("serif", 22), (200, 190, 200, 255), blur=4)

    f_period, f_head, f_line, f_cap = L.font("sans_bold", 25), L.font("serif_bold", 56), L.font("serif", 31), L.font("serif", 24)
    scrolls = []
    for s in L.SCROLLS:
        heads = L.wrap(s["title"], f_head, 640)
        lines = [ln for raw in s["lines"] for ln in L.wrap(raw, f_line, 640)]
        scrolls.append(dict(
            brush=C.Calligraphy(s["kan"], 112, color=L.PAPER),
            period=C.text_shadowed(s["period"].upper(), f_period, L.GOLD + (255,), blur=4),
            heads=[C.text_shadowed(h_, f_head, L.SAKURA_PALE + (255,)) for h_ in heads],
            lines=[C.text_shadowed(ln, f_line, (226, 214, 228, 255), blur=5) for ln in lines],
            seal=L.seal((s["seal"][:4], s["seal"][4:]), 150, seed=7 + len(scrolls)),
            date=C.text_shadowed(s["date"], L.font("serif_bold", 30), L.PAPER + (255,), blur=4),
            cap=C.text_shadowed("Печать Времени", f_cap, (200, 186, 204, 255), blur=4),
            hash=s["seal"]))
    jp_vertical = [[C.text_shadowed(ch, L.font("serif", 30), L.GOLD_PALE + (255,), blur=3) for ch in s["jp"]]
                   for s in L.SCROLLS]
    blade = C.text_shadowed("быстрее 1.8 мс", L.font("serif_bold", 44), L.GOLD_PALE + (255,))

    months = commits_by_month()
    total = sum(n for _, n in months)
    peak = max(n for _, n in months)
    end_title = C.text_shadowed("Сказание продолжается", L.font("serif_bold", 60), L.SAKURA_PALE + (255,))
    end_sub = C.text_shadowed(f"{total} Печатей Времени до Пятой Печати · июль — ноябрь 2026", L.font("serif", 32),
                              L.GOLD_PALE + (255,))
    month_lbl = [C.text_shadowed(MONTHS_RU.get(m[5:], m), L.font("serif_bold", 28), L.PAPER + (255,), blur=4)
                 for m, _ in months]
    end_seals = [L.seal((s["num"],), 74, round_seal=True, seed=30 + i) for i, s in enumerate(L.SCROLLS)]

    def scene_frame(idx: int, t: float) -> Image.Image:
        """Фон сцены idx (-1 — пролог, 5 — эпилог) в момент t от её начала."""
        if idx < 0:
            return prologue.frame(t / (PROLOGUE + WIPE))
        if idx >= 5:
            return epilogue.frame(t / EPILOGUE)
        return scenes[idx].frame(t / (SEG + WIPE))

    def scene_at(t: float):
        if t < PROLOGUE:
            return -1, t
        if t < PROLOGUE + SEG * 5:
            j = int((t - PROLOGUE) // SEG)
            return j, t - PROLOGUE - j * SEG
        return 5, t - PROLOGUE - SEG * 5

    def draw_scroll_titles(f: Image.Image, light: Image.Image, j: int, local: float):
        sc = scrolls[j]
        k_out = L.smooth((SEG - local) / 0.45)
        L.paste(f, shade, (W / 2, H / 2), L.smooth((local - 0.15) / 0.6) * k_out)
        brush = sc["brush"].sprite(L.clamp01((local - 0.35) / 1.1))
        L.paste(f, brush, (190, 150 + brush.height / 2), k_out)
        for i, ch in enumerate(jp_vertical[j]):
            L.paste(f, ch, (300, 168 + i * 34), L.smooth((local - 0.9 - i * 0.05) / 0.4) * k_out)
        x0, y = 380, 196
        k = L.smooth((local - 0.6) / 0.5) * k_out
        L.paste(f, sc["period"], (x0 + sc["period"].width / 2, y - C.rise(k)), k)
        y += 58
        for i, sp in enumerate(sc["heads"]):
            k = L.smooth((local - 0.75 - i * 0.12) / 0.55) * k_out
            L.paste(f, sp, (x0 + sp.width / 2 - 10, y + sp.height / 2 - C.rise(k)), k)
            y += 70
        d = ImageDraw.Draw(light)
        line_k = L.smooth((local - 1.05) / 0.6) * k_out
        if line_k > 0:
            d.line([x0, y + 14, x0 + 220 * line_k, y + 14], fill=L.GOLD + (int(230 * line_k),), width=3)
        y += 44
        for i, sp in enumerate(sc["lines"]):
            k = L.smooth((local - 1.25 - i * 0.12) / 0.55) * k_out
            L.paste(f, sp, (x0 + sp.width / 2 - 10, y + sp.height / 2 - C.rise(k, 14)), k)
            y += 46
        # Печать Времени: удар, клякса, хэш по знаку
        stamp = L.clamp01((local - 1.9) / 0.2)
        sx, sy = x0 + 70, 860
        if stamp > 0:
            splash = C.ink_splash(330, L.VERMILION, seed=j + 2)
            L.paste(f, splash, (sx + 6, sy + 4), 0.55 * L.smooth((local - 1.95) / 0.25) * k_out)
            sc_k = 1 + 0.5 * (1 - L.ease_out(stamp))
            seal = sc["seal"].resize((int(150 * sc_k), int(150 * sc_k)), Image.LANCZOS)
            L.paste(f, seal, (sx, sy), stamp * k_out)
            L.glow(light, (sx, sy), 150, L.VERMILION, 0.35 * stamp * L.clamp01(1 - (local - 2.1) / 1.0))
            n = int(L.clamp01((local - 2.1) / 0.7) * 7)
            if n:
                typed = C.text_shadowed(sc["hash"][:n], L.font("mono", 30), L.GOLD_PALE + (255,), blur=3)
                L.paste(f, sc["cap"], (sx + 110 + sc["cap"].width / 2, sy - 34), k_out)
                L.paste(f, typed, (sx + 110 + typed.width / 2, sy + 4), k_out)
                L.paste(f, sc["date"], (sx + 110 + sc["date"].width / 2, sy + 44),
                        L.smooth((local - 2.6) / 0.4) * k_out)

    def frame(t: float) -> Image.Image:
        idx, local = scene_at(t)
        f = scene_frame(idx, local + (WIPE if idx >= 0 else 0))
        if 0 <= idx <= 5 and local < WIPE:                       # переход тушью из прошлой сцены
            prev = scene_frame(idx - 1, (PROLOGUE if idx == 0 else SEG) + local + (WIPE if idx >= 1 else 0))
            f = C.ink_wipe(prev, f, L.smooth(local / WIPE), seed=idx + 3)
        f = f.convert("RGB")
        light = C.glow_layer()
        mist.draw(f, t, speed=26, k=0.9)

        if idx < 0:                                              # пролог
            mx, my = prologue.to_frame(*moon_src, t / (PROLOGUE + WIPE))
            L.glow(light, (mx, my), 120, (255, 236, 200), 0.6 * L.smooth(t / 2.0))
            L.paste(f, shade_bottom, (W / 2, H / 2), L.smooth((t - 0.6) / 1.0))
            brush = title_brush.sprite(L.clamp01((t - 0.4) / 2.2))
            L.paste(f, brush, (1640, 120 + brush.height / 2), L.smooth((PROLOGUE + 0.3 - t) / 0.5))
            k = L.smooth((t - 1.6) / 0.7) * L.smooth((PROLOGUE + 0.3 - t) / 0.5)
            L.paste(f, t_title, (W / 2, 850 - C.rise(k)), k)
            k2 = L.smooth((t - 2.1) / 0.7) * L.smooth((PROLOGUE + 0.3 - t) / 0.5)
            L.paste(f, t_sub, (W / 2, 925 - C.rise(k2)), k2)
            L.paste(f, t_credit, (W - 30 - t_credit.width / 2, H - 34), k2 * 0.85)
        elif idx < 5:
            draw_scroll_titles(f, light, idx, local)
            if idx == 2:                                         # молниеносный росчерк
                strike = L.clamp01((local - 1.4) / 0.22)
                fade = L.clamp01(1 - (local - 1.9) / 1.4)
                if strike > 0 and fade > 0:
                    d = ImageDraw.Draw(light)
                    x1, y1, x2, y2 = 1180, 820, 1820, 300
                    xe, ye = x1 + (x2 - x1) * strike, y1 + (y2 - y1) * strike
                    d.line([x1, y1, xe, ye], fill=(255, 200, 120, int(120 * fade)), width=16)
                    d.line([x1, y1, xe, ye], fill=(255, 246, 220, int(255 * fade)), width=5)
                L.paste(f, blade, (1480, 650), L.smooth((local - 1.6) / 0.5) * L.smooth((SEG - local) / 0.4))
            if idx == 3:                                         # капля света — сфера духа
                k = L.smooth((local - 0.8) / 0.8) * L.smooth((SEG - local) / 0.4)
                L.spirit_sphere(f, (1390, 540), 74, L.STATE["idle"], t, level=0.35, rings=3, satellites=3, k=k)
                L.glow(light, (1390, 540), 240, L.STATE["idle"], 0.45 * k)
        else:                                                    # эпилог: Река Времени
            e = local
            L.paste(f, shade_bottom, (W / 2, H / 2), L.smooth(e / 0.6))
            L.paste(f, shade_epilogue, (W / 2, H / 2), L.smooth(e / 0.6))
            d = ImageDraw.Draw(light)
            base, gap = 700, 210
            x_first = W / 2 - 2 * gap
            for i, ((m, n), lbl) in enumerate(zip(months, month_lbl)):
                g = L.ease_out(L.clamp01((e - 0.2 - i * 0.12) / 0.9))
                hgt = 290 * n / peak * g
                x = x_first + i * gap
                if g > 0:
                    for wdt, a in ((26, 70), (12, 170), (4, 255)):
                        d.line([x, base, x, base - hgt], fill=(255, 196, 214, int(a * min(1.0, g * 1.5))), width=wdt)
                    L.glow(light, (x, base - hgt), 46, L.SAKURA, 0.9 * g)
                num = C.text_shadowed(str(int(round(n * g))), L.font("serif_bold", 38), L.MOON + (255,), blur=4)
                L.paste(f, num, (x, base - hgt - 40), L.smooth((e - 0.3 - i * 0.12) / 0.4))
                L.paste(f, lbl, (x, base + 38), L.smooth((e - 0.2 - i * 0.12) / 0.4))
                if i < 5:
                    L.paste(f, end_seals[i], (x, base + 100), L.smooth((e - 0.6 - i * 0.12) / 0.3))
            k = L.smooth((e - 1.3) / 0.6)
            L.paste(f, end_title, (W / 2, 205 - C.rise(k)), k)
            L.paste(f, end_sub, (W / 2, 275 - C.rise(k)), L.smooth((e - 1.6) / 0.6))

        f = C.bloom(f, light, radius=26, strength=1.0)
        bokeh.draw(f, t, k=0.95, gust=12 * math.sin(t * 0.3))
        L.paste(f, vign, (W / 2, H / 2), 1.0)
        return C.fade_to(f, L.smooth(t / 0.6) * L.smooth((SECONDS - t) / 0.6))

    return frame


def main():
    L.render_video(NAME, build(), SECONDS, poster_at=PROLOGUE + 3.2)


if __name__ == "__main__":
    main()

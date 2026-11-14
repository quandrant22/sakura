"""Ролик «Три Тысячи Испытаний» — sakura-legend-3383-trials.mp4 / .webm.

Фон — ночная фотография замка Хиросаки в цвету (параллакс: цветущие ветви
ближе замка). Поверх — поле из 3 383 бутонов: каждое испытание раскрывается
светящимся лепестком, счётчик бежит до конца, пять вех пути загораются по
очереди, а в финале ложится печать 合格 с кляксой туши.

Запуск из корня репозитория: python -I site/tools/generate_video_trials.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

import legend_cinema as C  # noqa: E402
import legend_common as L  # noqa: E402

NAME = "sakura-legend-3383-trials"
W, H = C.W, C.H
SECONDS = 20.0
TRIALS = 3383
COLS, ROWS = 97, 35
CELL = 14
GX0 = (W - COLS * CELL) // 2
GY0 = 330
T0, T1 = 3.0, 14.5
STAMP = 15.0


def _inv_smooth(x):
    """Обратная smoothstep: медленный разгон, быстрый ход, мягкий финиш."""
    return 0.5 - np.sin(np.arcsin(1 - 2 * x) / 3)


def build():
    rng = np.random.default_rng(3383)
    bg = C.Parallax("hirosaki", depth="pink", z0=1.02, z1=1.12, pan=(-0.04, 0.01), near_extra=0.04)
    bokeh, mist = C.Bokeh(seed=44), C.Mist(seed=12, alpha=60, y=(0.65, 1.0))
    vign = C.vignette_overlay(0.6)
    night = Image.new("RGB", (W, H), (7, 5, 16))
    gw, gh = COLS * CELL, ROWS * CELL
    field_shade = Image.new("RGBA", (gw + 160, gh + 160), (0, 0, 0, 0))
    fs = np.zeros((gh + 160, gw + 160), dtype=np.float32)
    fs[60:-60, 60:-60] = 1
    fs = np.asarray(Image.fromarray((fs * 200).astype(np.uint8)).filter(ImageFilter.GaussianBlur(40)), dtype=np.uint8)
    field_shade = Image.fromarray(np.dstack([np.full_like(fs, 6), np.full_like(fs, 4), np.full_like(fs, 14), fs]), "RGBA")

    cell_map = np.full((gh, gw), -1, dtype=np.int32)
    yy, xx = np.mgrid[0:CELL, 0:CELL]
    dist = (xx - CELL / 2 + 0.5) ** 2 + (yy - CELL / 2 + 0.5) ** 2
    disk, core = dist <= (CELL * 0.36) ** 2, dist <= (CELL * 0.16) ** 2
    core_map = np.zeros((gh, gw), dtype=bool)
    for i in range(TRIALS):
        r, c = divmod(i, COLS)
        sl = (slice(r * CELL, (r + 1) * CELL), slice(c * CELL, (c + 1) * CELL))
        cell_map[sl][disk] = i
        core_map[sl] |= core
    key = (np.arange(TRIALS) % COLS) / COLS * 0.8 + rng.random(TRIALS) * 0.2
    rank = np.empty(TRIALS)
    rank[np.argsort(key)] = np.arange(TRIALS)
    light = T0 + (T1 - T0) * _inv_smooth(np.clip((rank + 0.5) / TRIALS, 1e-6, 1 - 1e-6))
    light_sorted = np.sort(light)
    light_px = np.where(cell_map >= 0, light[np.maximum(cell_map, 0)], np.inf).astype(np.float32)
    inside = cell_map >= 0
    unlit = np.array([70, 56, 86], dtype=np.float32)
    lit = np.array(L.SAKURA, dtype=np.float32)
    lit_core = np.array(L.SAKURA_DEEP, dtype=np.float32)
    white = np.array([255, 250, 246], dtype=np.float32)

    title = C.Calligraphy("三千の試練", 140, color=L.PAPER, vertical=False, spacing=1.0)
    t_ru = C.text_shadowed("Три Тысячи Испытаний", L.font("serif_bold", 64), L.SAKURA_PALE + (255,))
    t_seal = C.text_shadowed("Свиток V · Печать 33a8da2 · 14 ноября 2026", L.font("serif", 32), L.GOLD_PALE + (255,))
    credit = C.text_shadowed("Фото: замок Хиросаки и ночная сакура (Kojin, public domain)", L.font("serif", 22),
                             (200, 190, 200, 255), blur=4)
    counter_kanji = C.Calligraphy("試練", 64, color=L.GOLD_PALE, vertical=False, spacing=1.0).sprite(1.0)
    label = C.text_shadowed("пройдено испытаний", L.font("serif", 30), L.GOLD_PALE + (255,), blur=4)
    f_cap = L.font("serif", 36)
    captions = [(T0, 6.4, C.text_shadowed("Каждое испытание — бутон, который должен раскрыться", f_cap, L.PAPER + (255,))),
                (6.4, 10.2, C.text_shadowed("Слух, голос, память, отклик и доспех проходят проверку", f_cap, L.PAPER + (255,))),
                (10.2, STAMP, C.text_shadowed("Лепесток за лепестком — и ни один не опал", f_cap, L.PAPER + (255,)))]
    end1 = C.text_shadowed("3 383 испытания · ни одного промаха", L.font("serif_bold", 58), L.SAKURA_PALE + (255,))
    end2 = C.text_shadowed("Печать Времени 33a8da2 · 14 ноября 2026", L.font("serif", 32), L.GOLD_PALE + (255,))
    seal_pass = L.seal(("合格",), 300, seed=77)
    splash = C.ink_splash(560, L.VERMILION, seed=13)
    marks = [L.seal((s["num"],), 96, round_seal=True, seed=60 + i) for i, s in enumerate(L.SCROLLS)]

    def frame(t: float) -> Image.Image:
        f = Image.blend(night, bg.frame(t / SECONDS), 0.78)
        mist.draw(f, t, speed=18, k=0.9)
        glow = C.glow_layer()
        gk = L.smooth((t - 2.4) / 0.9)
        if gk > 0:
            L.paste(f, field_shade, (GX0 + gw / 2, GY0 + gh / 2), gk)
            region = np.asarray(f.crop((GX0, GY0, GX0 + gw, GY0 + gh)), dtype=np.float32)
            age = t - light_px
            is_lit = age >= 0
            col = np.where(is_lit[..., None], lit[None, None, :], unlit[None, None, :])
            col = np.where((is_lit & core_map)[..., None], lit_core[None, None, :], col)
            flash = np.clip(1 - age / 0.45, 0, 1) * is_lit
            pulse = 0.25 * (0.5 + 0.5 * math.sin((t - STAMP) * 3.2)) if t > STAMP else 0.0
            col = col + (white - col) * (flash + pulse)[..., None] * 0.9
            a = inside[..., None] * gk
            region = region * (1 - a) + col * a
            f.paste(Image.fromarray(np.clip(region, 0, 255).astype(np.uint8)), (GX0, GY0))
            # свечение раскрытых бутонов — через общий слой света
            g = np.zeros((gh, gw, 4), dtype=np.uint8)
            g[..., 0], g[..., 1], g[..., 2] = 255, 170, 205
            g[..., 3] = ((is_lit & inside) * (50 + 110 * flash) * gk).clip(0, 255).astype(np.uint8)
            L.paste(glow, Image.fromarray(g, "RGBA"), (GX0 + gw / 2, GY0 + gh / 2), 0.8 + pulse)

            done = int(np.searchsorted(light_sorted, t, side="right"))
            ck = L.smooth((t - 2.6) / 0.8)
            num = C.text_shadowed(f"{done:,}".replace(",", " "), L.font("serif_bold", 104), L.MOON + (255,), blur=6)
            of = C.text_shadowed("/ 3 383", L.font("serif", 44), L.GOLD_PALE + (255,), blur=4)
            L.paste(f, counter_kanji, (W / 2 - 330, 196), ck)
            L.paste(f, num, (W / 2 + 30 - num.width / 2, 186), ck)
            L.paste(f, of, (W / 2 + 60 + of.width / 2, 206), ck)
            L.paste(f, label, (W / 2, 272), ck)
            for i, sp in enumerate(marks):
                idx = min(TRIALS - 1, int(TRIALS * (i + 1) / 5) - 1)
                reached = done > idx
                pop = 1 + 0.35 * (1 - L.ease_out(L.clamp01((t - light_sorted[idx]) / 0.3))) if reached else 1.0
                spr = sp if pop == 1.0 else sp.resize((int(96 * pop), int(96 * pop)), Image.LANCZOS)
                k_m = ck * (1.0 if reached else 0.3) * (1 - L.smooth((t - STAMP - 0.3) / 0.5))
                L.paste(f, spr, (W / 2 + (i - 2) * 130, 1000), k_m)
                if reached:
                    L.glow(glow, (W / 2 + (i - 2) * 130, 1000), 90, L.VERMILION, 0.45 * k_m)
            for start, end, sp in captions:
                L.paste(f, sp, (W / 2, 912), L.window(t, start, end, 0.5))

        tk = L.window(t, 0.2, 2.9, 0.6)
        if tk:
            L.paste(f, title.sprite(L.clamp01((t - 0.3) / 1.4)), (W / 2, 400), tk)
            L.paste(f, t_ru, (W / 2, 545 - C.rise(L.smooth((t - 1.0) / 0.6))), tk * L.smooth((t - 1.0) / 0.6))
            L.paste(f, t_seal, (W / 2, 615), tk * L.smooth((t - 1.4) / 0.6))
            L.paste(f, credit, (W - 30 - credit.width / 2, H - 34), tk * 0.85)

        if t >= STAMP:
            e = t - STAMP
            st = L.clamp01(e / 0.24)
            k_end = L.smooth((SECONDS - t) / 0.6)
            L.paste(f, splash, (W / 2 + 10, GY0 + gh / 2 + 8), 0.65 * st * k_end)
            sc = 1 + 0.6 * (1 - L.ease_out(st))
            L.paste(f, seal_pass.resize((int(300 * sc), int(300 * sc)), Image.LANCZOS), (W / 2, GY0 + gh / 2), st * k_end)
            L.glow(glow, (W / 2, GY0 + gh / 2), 520, (255, 120, 90), 0.5 * L.clamp01(1 - (e - 0.24) / 1.2) * st)
            L.paste(f, end1, (W / 2, 905 - C.rise(L.smooth((e - 0.5) / 0.6))), L.smooth((e - 0.5) / 0.6) * k_end)
            L.paste(f, end2, (W / 2, 968), L.smooth((e - 0.8) / 0.6) * k_end)

        f = C.bloom(f, glow, radius=22, strength=0.9)
        bokeh.draw(f, t, k=0.8, gust=6)
        L.paste(f, vign, (W / 2, H / 2), 1.0)
        return C.fade_to(f, L.smooth(t / 0.6) * L.smooth((SECONDS - t) / 0.6))

    return frame


def main():
    L.render_video(NAME, build(), SECONDS, poster_at=12.0)


if __name__ == "__main__":
    main()

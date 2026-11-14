"""Ролик «Три Тысячи Испытаний» — sakura-legend-3383-trials.mp4 / .webm.

Сетка из 3 383 бутонов: каждое испытание раскрывается лепестком, счётчик
бежит до конца, пять свитков-вех загораются по мере пути, а в финале на
поле ложится киноварная печать 合格.

Запуск из корня репозитория: python site/tools/generate_video_trials.py
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import legend_common as L

NAME = "sakura-legend-3383-trials"
W, H = 1920, 1080
SECONDS = 20.0
TRIALS = 3383
COLS, ROWS = 97, 35
CELL = 14
GX0 = (W - COLS * CELL) // 2
GY0 = 318
T0, T1 = 3.0, 14.5
STAMP = 15.0


def _inv_smooth(x):
    """Обратная smoothstep: медленный разгон, быстрый ход, мягкий финиш."""
    return 0.5 - np.sin(np.arcsin(1 - 2 * x) / 3)


def build():
    rng = np.random.default_rng(3383)
    bg = L.night_sky(W, H, seed=27, moon=(0.9, 0.13), horizon=0.88)
    dim = Image.new("RGBA", (W, H), (6, 4, 14, 90))
    bg.paste(dim, (0, 0), dim)
    petals = L.Petals(36, W, H, seed=44, size=(6, 12), speed=(25, 60))

    # карта клеток: пиксель → номер испытания (-1 — пусто)
    gw, gh = COLS * CELL, ROWS * CELL
    cell_map = np.full((gh, gw), -1, dtype=np.int32)
    yy, xx = np.mgrid[0:CELL, 0:CELL]
    disk = (xx - CELL / 2 + 0.5) ** 2 + (yy - CELL / 2 + 0.5) ** 2 <= (CELL * 0.36) ** 2
    core = (xx - CELL / 2 + 0.5) ** 2 + (yy - CELL / 2 + 0.5) ** 2 <= (CELL * 0.16) ** 2
    core_map = np.zeros((gh, gw), dtype=bool)
    for i in range(TRIALS):
        r, c = divmod(i, COLS)
        sl = (slice(r * CELL, (r + 1) * CELL), slice(c * CELL, (c + 1) * CELL))
        cell_map[sl][disk] = i
        core_map[sl] |= core
    cols = np.arange(TRIALS) % COLS
    key = cols / COLS * 0.8 + rng.random(TRIALS) * 0.2
    rank = np.empty(TRIALS)
    rank[np.argsort(key)] = np.arange(TRIALS)
    light = T0 + (T1 - T0) * _inv_smooth(np.clip((rank + 0.5) / TRIALS, 1e-6, 1 - 1e-6))
    light_px = np.where(cell_map >= 0, light[np.maximum(cell_map, 0)], np.inf).astype(np.float32)
    inside = cell_map >= 0

    unlit = np.array([72, 58, 86], dtype=np.float32)
    lit = np.array(L.SAKURA, dtype=np.float32)
    lit_core = np.array(L.SAKURA_DEEP, dtype=np.float32)
    white = np.array([255, 250, 246], dtype=np.float32)

    f_count = L.font("serif_bold", 96)
    f_of = L.font("serif", 44)
    f_cap = L.font("serif", 36)
    title_k = L.text_sprite("三千の試練", L.font("serif_bold", 132), L.MOON + (255,))
    title_r = L.text_sprite("Три Тысячи Испытаний", L.font("serif_bold", 64), L.SAKURA_PALE + (255,))
    title_s = L.text_sprite("Свиток V · Печать 33a8da2 · 14 ноября 2026", L.font("serif", 32), L.GOLD_PALE + (255,))
    label = L.text_sprite("試練 · пройдено испытаний", L.font("serif", 30), L.GOLD_PALE + (255,))
    captions = [
        (T0, 6.4, L.text_sprite("Каждое испытание — бутон, который должен раскрыться", f_cap, L.PAPER + (255,))),
        (6.4, 10.2, L.text_sprite("Слух, голос, память, отклик и доспех проходят проверку", f_cap, L.PAPER + (255,))),
        (10.2, STAMP, L.text_sprite("Лепесток за лепестком — и ни один не опал", f_cap, L.PAPER + (255,))),
    ]
    end1 = L.text_sprite("3 383 испытания · ни одного промаха", L.font("serif_bold", 56), L.SAKURA_PALE + (255,))
    end2 = L.text_sprite("Печать Времени 33a8da2 · 14 ноября 2026", L.font("serif", 32), L.GOLD_PALE + (255,))
    seal_pass = L.seal(("合格",), 300, seed=77)
    marks = [L.seal((s["num"],), 96, round_seal=True, seed=60 + i) for i, s in enumerate(L.SCROLLS)]

    def frame(t):
        f = bg.copy()
        petals.draw(f, t, gust=4, k=0.6)

        gk = L.smooth((t - 2.4) / 0.9)
        if gk > 0:
            region = np.asarray(f.crop((GX0, GY0, GX0 + gw, GY0 + gh)), dtype=np.float32)
            age = t - light_px
            is_lit = age >= 0
            col = np.where(is_lit[..., None], lit[None, None, :], unlit[None, None, :])
            col = np.where((is_lit & core_map)[..., None], lit_core[None, None, :], col)
            flash = np.clip(1 - age / 0.45, 0, 1) * is_lit
            pulse = 0.0
            if t > STAMP:
                pulse = 0.25 * (0.5 + 0.5 * math.sin((t - STAMP) * 3.2))
            col = col + (white - col) * (flash + pulse)[..., None] * 0.9
            a = inside[..., None] * gk
            region = region * (1 - a) + col * a
            # мягкое свечение раскрытых бутонов
            mask = Image.fromarray((is_lit * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(7))
            g = np.asarray(mask, dtype=np.float32)[..., None] / 255 * (0.22 + pulse * 0.6) * gk
            region = region + (lit[None, None, :] - region * 0.3) * g * 0.5
            f.paste(Image.fromarray(np.clip(region, 0, 255).astype(np.uint8)), (GX0, GY0))

            done = int(np.count_nonzero(light <= t))
            num = f"{done:,}".replace(",", " ")
            d = ImageDraw.Draw(f, "RGBA")
            ck = L.smooth((t - 2.6) / 0.8)
            L.text(d, (W / 2 + 40, 190), num, f_count, L.MOON + (int(255 * ck),), anchor="rs")
            L.text(d, (W / 2 + 56, 190), "/ 3 383", f_of, L.GOLD_PALE + (int(230 * ck),), anchor="ls")
            L.paste(f, label, (W / 2, 248), ck)
            L.spirit_sphere(f, (W / 2 - 330, 160), 46, L.mix(L.SAKURA, L.STATE["thinking"], L.clamp01((t - T1) / 1.5)),
                            t, level=0.2 + 0.4 * (done / TRIALS), rings=2, satellites=3, k=ck)
            for i, sp in enumerate(marks):  # пять вех пути
                reached = done >= TRIALS * (i + 1) / 5 - 1
                pop = 1.0
                if reached:
                    when = float(np.sort(light)[min(TRIALS - 1, int(TRIALS * (i + 1) / 5) - 1)])
                    pop = 1 + 0.35 * (1 - L.ease_out(L.clamp01((t - when) / 0.3)))
                spr = sp if pop == 1.0 else sp.resize((int(96 * pop), int(96 * pop)), Image.LANCZOS)
                L.paste(f, spr, (W / 2 + (i - 2) * 130, 1000),
                        ck * (1.0 if reached else 0.28) * (1 - L.smooth((t - STAMP - 0.3) / 0.5)))
            for start, end, sp in captions:
                L.paste(f, sp, (W / 2, 905), L.window(t, start, end, 0.5))

        tk = L.window(t, 0.2, 2.9, 0.6)
        if tk:
            L.paste(f, title_k, (W / 2, 400), tk)
            L.paste(f, title_r, (W / 2, 540), tk)
            L.paste(f, title_s, (W / 2, 612), tk)

        if t >= STAMP:
            e = t - STAMP
            st = L.clamp01(e / 0.24)
            sc = 1 + 0.6 * (1 - L.ease_out(st))
            k_end = L.smooth((SECONDS - t) / 0.6)
            L.paste(f, seal_pass.resize((int(300 * sc), int(300 * sc)), Image.LANCZOS), (W / 2, GY0 + gh / 2), st * k_end)
            if 0.24 < e < 1.2:
                d = ImageDraw.Draw(f, "RGBA")
                rr = 170 + (e - 0.24) * 520
                d.ellipse([W / 2 - rr, GY0 + gh / 2 - rr, W / 2 + rr, GY0 + gh / 2 + rr],
                          outline=L.VERMILION + (int(170 * (1 - (e - 0.24) / 0.96)),), width=4)
            L.paste(f, end1, (W / 2, 900), L.smooth((e - 0.5) / 0.6) * k_end)
            L.paste(f, end2, (W / 2, 958), L.smooth((e - 0.8) / 0.6) * k_end)

        fade = L.smooth(t / 0.6) * L.smooth((SECONDS - t) / 0.6)
        if fade < 1:
            f = Image.blend(Image.new("RGB", f.size, L.NIGHT_TOP), f, fade)
        return f

    return frame


def main():
    L.render_video(NAME, build(), SECONDS, poster_at=12.0)


if __name__ == "__main__":
    main()

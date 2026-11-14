"""Ролик «Незримый Доспех» — sakura-legend-invisible-armor.mp4 / .webm.

Фон — «Канбара: вечерний снег» Хиросигэ с параллаксом (деревня ближе неба).
Дом Мастера (деревня слева) и Святилище Kizune-Ryoiki (дом в центре)
обмениваются двумя вестями рукопожатия Noise IK (→ e, es, s, ss и ← e, ee, se),
над ними смыкается светящийся шестигранный доспех, а ворон Каванабэ Кёсая
с повторённой вестью разбивается о него — печать 拒 и клякса туши.

Запуск из корня репозитория: python -I site/tools/generate_video_armor.py
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw  # noqa: E402

import legend_cinema as C  # noqa: E402
import legend_common as L  # noqa: E402

NAME = "sakura-legend-invisible-armor"
W, H = C.W, C.H
SECONDS = 21.0
M1, M2 = (3.2, 7.0), (7.0, 10.6)
ARMOR, CROW, HIT, FINAL = 10.6, (14.2, 18.0), 16.0, 18.0
HOUSE, SANCT = (500, 600), (1180, 470)
DOME_C, DOME_RX, DOME_RY = (840, 900), 800, 600
HIT_PT = (620, 330)


def tag_sprite(label: str) -> Image.Image:
    fnt = L.font("serif_bold", 34)
    L.check_glyphs(label, fnt)
    w = int(fnt.getlength(label)) + 46
    img = Image.new("RGBA", (w, 58), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, w - 2, 56], radius=28, fill=(30, 16, 44, 225), outline=L.GOLD + (255,), width=2)
    d.text((w / 2, 29), label, font=fnt, fill=L.GOLD_PALE + (255,), anchor="mm")
    return img


def arc(a, b, u, lift):
    return a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u - 4 * lift * u * (1 - u)


def build():
    rnd = random.Random(5)
    bg = C.Parallax("kanbara", depth="vertical", z0=1.05, z1=1.12, pan=(0.03, 0.0), near_extra=0.03)
    bokeh, mist = C.Bokeh(seed=33), C.Mist(seed=9, alpha=80, color=(170, 170, 210), y=(0.6, 1.0))
    vign = C.vignette_overlay(0.62)
    shade_b = C.side_shade("bottom", 0.32, 0.9)
    night = Image.new("RGB", (W, H), (8, 8, 26))
    crow = C.crow()
    crow = crow.resize((300, int(300 * crow.height / crow.width)), Image.LANCZOS)

    title = C.Calligraphy("見えざる鎧", 150, color=L.PAPER, vertical=False, spacing=1.0)
    t_ru = C.text_shadowed("Незримый Доспех", L.font("serif_bold", 64), L.SAKURA_PALE + (255,))
    t_seal = C.text_shadowed("Свиток IV · Печать bef6346 · 16 октября 2026", L.font("serif", 32), L.GOLD_PALE + (255,))
    f_cap = L.font("serif", 38)
    caps = {k: C.text_shadowed(v, f_cap, L.PAPER + (255,)) for k, v in {
        "m1": "Первая весть: мимолётный ключ и сокрытое имя Мастера",
        "m2": "Ответ Святилища: ключи сплетаются в общую тайну",
        "armor": "Тайну знают лишь двое — доспех сомкнулся",
        "crow": "Повторённую весть узнали и отвергли у самых врат",
        "final": "Тайна и подлинность подтверждены доказательствами ProVerif"}.items()}
    tech = C.text_shadowed("Noise IK · Curve25519 · ChaChaPoly · BLAKE2s · кадры «SK»", L.font("sans", 24), L.GOLD + (255,), blur=4)
    lbl_house = C.text_shadowed("主 · Дом Мастера", L.font("serif_bold", 30), L.PAPER + (255,), blur=5)
    lbl_sanct = C.text_shadowed("社 · Святилище Kizune-Ryoiki", L.font("serif_bold", 30), L.PAPER + (255,), blur=5)
    credit = C.text_shadowed("Утагава Хиросигэ · «Канбара: вечерний снег» · ворон — Каванабэ Кёсай",
                             L.font("serif", 22), (200, 190, 200, 255), blur=4)
    tags1, tags2 = [tag_sprite(s) for s in ("e", "es", "s", "ss")], [tag_sprite(s) for s in ("e", "ee", "se")]
    seal_reject, seal_proof = L.seal(("拒",), 160, round_seal=True, seed=41), L.seal(("証",), 200, seed=42)
    splash = C.ink_splash(420, L.VERMILION, seed=9)
    end_title = C.Calligraphy("見えざる鎧", 96, color=L.PAPER, vertical=False, spacing=1.0)

    hexes, size = [], 38
    for col in range(-24, 25):
        for row in range(0, 18):
            x = DOME_C[0] + col * size * 1.5
            y = DOME_C[1] - row * size * math.sqrt(3) - (size * math.sqrt(3) / 2 if col % 2 else 0)
            nx, ny = (x - DOME_C[0]) / DOME_RX, (y - DOME_C[1]) / DOME_RY
            r = nx * nx + ny * ny
            if r < 0.92 and y < DOME_C[1] - 20:
                hexes.append((x, y, math.sqrt(r) * 0.9 + rnd.uniform(0, 0.18), rnd.uniform(0, 6.3)))

    def armor(light, t, hit_k):
        d = ImageDraw.Draw(light)
        built = (t - ARMOR) / 1.8
        for x, y, delay, ph in hexes:
            a = L.clamp01((built - delay) * 3)
            if a <= 0:
                continue
            shimmer = 0.55 + 0.45 * math.sin(t * 2.2 + ph)
            col = L.GOLD_PALE
            if hit_k > 0:
                ring = math.exp(-((math.hypot(x - HIT_PT[0], y - HIT_PT[1]) - hit_k * 520) / 70) ** 2) * (1 - hit_k)
                col = L.mix(L.GOLD_PALE, (255, 90, 70), min(1.0, ring * 2.5))
                shimmer += ring * 1.6
            pts = [(x + size * 0.9 * math.cos(i * math.pi / 3), y + size * 0.9 * math.sin(i * math.pi / 3)) for i in range(7)]
            d.line(pts, fill=col + (int(min(255, 150 * a * shimmer)),), width=2)
        edge = L.clamp01(built)
        if edge > 0:
            box = [DOME_C[0] - DOME_RX, DOME_C[1] - DOME_RY, DOME_C[0] + DOME_RX, DOME_C[1] + DOME_RY]
            d.arc(box, 270 - 90 * edge, 270 + 90 * edge, fill=(255, 226, 170, 235), width=5)

    def frame(t: float) -> Image.Image:
        f = Image.blend(night, bg.frame(t / SECONDS), 0.6)
        light = C.glow_layer()
        mist.draw(f, t, speed=20, k=1.0)
        L.paste(f, shade_b, (W / 2, H / 2), 1.0)
        L.glow(light, (HOUSE[0] - 60, HOUSE[1] + 40), 160, (255, 190, 120), 0.35 + 0.06 * math.sin(t * 1.7))
        L.glow(light, (SANCT[0] - 30, SANCT[1] + 140), 190, (255, 180, 130), 0.32 + 0.06 * math.sin(t * 1.3))
        lab_k = L.smooth((t - 2.6) / 0.6) * L.smooth((FINAL - t) / 0.6)
        L.paste(f, lbl_house, (HOUSE[0] - 80, HOUSE[1] + 190), lab_k)
        L.paste(f, lbl_sanct, (SANCT[0] + 40, SANCT[1] + 300), lab_k)

        tk = L.window(t, 0.2, 3.2, 0.6)
        if tk:
            sp = title.sprite(L.clamp01((t - 0.3) / 1.6))
            L.paste(f, sp, (W / 2, 330), tk)
            L.paste(f, t_ru, (W / 2, 480 - C.rise(L.smooth((t - 1.2) / 0.6))), tk * L.smooth((t - 1.2) / 0.6))
            L.paste(f, t_seal, (W / 2, 550), tk * L.smooth((t - 1.6) / 0.6))
            L.paste(f, credit, (W - 30 - credit.width / 2, H - 34), tk * 0.85)

        d = ImageDraw.Draw(light)
        for (start, end), a, b, tags, lift, key in ((M1, HOUSE, SANCT, tags1, 330, "m1"), (M2, SANCT, HOUSE, tags2, 260, "m2")):
            if start - 0.2 <= t <= end + 0.6:
                vis = L.window(t, start, end + 0.4, 0.4)
                u = L.smooth((t - start - 0.3) / (end - start - 1.0))
                trail = [arc(a, b, uu / 80 * u, lift) for uu in range(81)]
                if u > 0.01:
                    d.line(trail, fill=(255, 186, 210, int(110 * vis)), width=8, joint="curve")
                    d.line(trail, fill=(255, 236, 244, int(230 * vis)), width=3, joint="curve")
                for i, sp in enumerate(tags):
                    ut = u - 0.105 * ((len(tags) - i) if b[0] > a[0] else (i + 1))
                    if ut > 0:
                        L.paste(f, sp, arc(a, b, ut, lift + 70), vis)
                px, py = arc(a, b, u, lift)
                L.glow(light, (px, py), 110, L.SAKURA, 1.0 * vis)
                L.blossom(d, px, py, 22, L.SAKURA_PALE, int(255 * vis), t * 3)
                L.paste(f, caps[key], (W / 2, 975), L.window(t, start + 0.2, end, 0.5))

        if t >= ARMOR:
            hit_k = L.clamp01((t - HIT) / 1.3) if t >= HIT else 0.0
            armor(light, t, hit_k)
            sk = L.smooth((t - ARMOR - 0.6) / 1.2)
            L.spirit_sphere(f, (W / 2 - 120, 640), 62, L.STATE["idle"], t, level=0.35, rings=2, satellites=3, k=sk)
            L.glow(light, (W / 2 - 120, 640), 220, L.STATE["idle"], 0.4 * sk)
            for i in range(6):
                ph = ((t - ARMOR) * 0.32 + i / 6) % 1.0
                a, b = (HOUSE, SANCT) if i % 2 == 0 else (SANCT, HOUSE)
                px, py = arc(a, b, ph, 240)
                L.glow(light, (px, py), 50, L.VERMILION, 0.8 * sk)
                d.rounded_rectangle([px - 10, py - 10, px + 10, py + 10], radius=3, fill=(230, 80, 66, int(255 * sk)))
            if t < CROW[0] + 0.3:
                L.paste(f, caps["armor"], (W / 2, 975), L.window(t, ARMOR + 0.5, CROW[0] + 0.3, 0.5))
            L.paste(f, tech, (W / 2, 1036), L.smooth((t - ARMOR - 1.0) / 0.8) * L.smooth((SECONDS - t) / 0.6))

        if CROW[0] <= t <= CROW[1]:
            if t < HIT:
                u = L.smooth((t - CROW[0]) / (HIT - CROW[0]))
                cx, cy = -200 + (HIT_PT[0] - 60 + 200) * u, 60 + (HIT_PT[1] - 110 - 60) * u + 18 * math.sin(t * 9)
                ck, rot, cr = 1.0, -8 + 6 * math.sin(t * 7), crow
            else:
                u = (t - HIT) / (CROW[1] - HIT)
                cx, cy = HIT_PT[0] - 80 - 380 * u, HIT_PT[1] - 130 - 260 * u
                ck, rot, cr = L.clamp01(1 - u * 1.3), 25 + 40 * u, crow.transpose(Image.FLIP_LEFT_RIGHT)
            L.paste(f, cr.rotate(rot, resample=Image.BICUBIC, expand=True), (cx, cy), ck)
            if t < HIT:
                L.blossom(ImageDraw.Draw(f, "RGBA"), cx + 120, cy + 70, 16, (170, 160, 180), int(220 * ck), t)
            else:
                flash = L.clamp01(1 - (t - HIT) / 0.6)
                L.glow(light, HIT_PT, 260, (255, 80, 60), flash)
                L.paste(f, splash, (HIT_PT[0] + 10, HIT_PT[1] - 100), 0.6 * L.window(t, HIT, CROW[1] + 0.4, 0.2))
                sc = 1 + 0.5 * (1 - L.ease_out(L.clamp01((t - HIT) / 0.25)))
                L.paste(f, seal_reject.resize((int(160 * sc), int(160 * sc)), Image.LANCZOS),
                        (HIT_PT[0] + 10, HIT_PT[1] - 110), L.window(t, HIT, CROW[1] + 0.4, 0.2))
            L.paste(f, caps["crow"], (W / 2, 975), L.window(t, CROW[0] + 0.3, CROW[1], 0.5))

        if t >= FINAL - 0.2:
            k = L.window(t, FINAL, SECONDS + 1, 0.5) * L.smooth((SECONDS - t) / 0.6)
            stamp = L.clamp01((t - FINAL - 0.3) / 0.22)
            if stamp > 0:
                L.paste(f, splash, (W / 2, 300), 0.5 * k * stamp)
                sc = 1 + 0.4 * (1 - L.ease_out(stamp))
                L.paste(f, seal_proof.resize((int(200 * sc), int(200 * sc)), Image.LANCZOS), (W / 2, 300), k * stamp)
            sp = end_title.sprite(L.clamp01((t - FINAL - 0.6) / 1.0))
            L.paste(f, sp, (W / 2, 480), k)
            L.paste(f, caps["final"], (W / 2, 975), k)

        f = C.bloom(f, light, radius=24, strength=1.05)
        bokeh.draw(f, t, k=0.7, gust=8)
        L.paste(f, vign, (W / 2, H / 2), 1.0)
        return C.fade_to(f, L.smooth(t / 0.6) * L.smooth((SECONDS - t) / 0.6))

    return frame


def main():
    L.render_video(NAME, build(), SECONDS, poster_at=13.4)


if __name__ == "__main__":
    main()

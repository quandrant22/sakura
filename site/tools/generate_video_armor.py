"""Ролик «Незримый Доспех» — sakura-legend-invisible-armor.mp4 / .webm.

Дом Мастера и Святилище Kizune-Ryoiki обмениваются двумя вестями
(рукопожатие Noise IK: → e, es, s, ss и ← e, ee, se), над ними смыкается
шестигранный доспех, а тень-ворон с повторённой вестью разбивается о него.

Запуск из корня репозитория: python site/tools/generate_video_armor.py
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

import legend_common as L

NAME = "sakura-legend-invisible-armor"
W, H = 1920, 1080
SECONDS = 21.0

HOUSE = (330, 820)
PAGODA = (1590, 820)
DOME_C, DOME_RX, DOME_RY = (960, 840), 800, 540
M1 = (3.2, 7.0)
M2 = (7.0, 10.6)
ARMOR = 10.6
CROW = (14.4, 18.0)
HIT = 16.0
FINAL = 18.0


def draw_house(d: ImageDraw.ImageDraw, x, ground, glow_k=1.0):
    col = (14, 10, 22, 255)
    d.rectangle([x - 120, ground - 120, x + 120, ground], fill=col)
    d.polygon([(x - 175, ground - 112), (x - 120, ground - 150), (x, ground - 215), (x + 120, ground - 150),
               (x + 175, ground - 112), (x + 120, ground - 128), (x, ground - 190), (x - 120, ground - 128)], fill=col)
    for wx in (x - 70, x + 30):
        d.rectangle([wx, ground - 92, wx + 42, ground - 40], fill=(255, 196, 120, int(230 * glow_k)))
        d.line([wx + 21, ground - 92, wx + 21, ground - 40], fill=col, width=3)
        d.line([wx, ground - 66, wx + 42, ground - 66], fill=col, width=3)


def draw_pagoda(d: ImageDraw.ImageDraw, x, ground, glow_k=1.0):
    col = (14, 10, 22, 255)
    y = ground
    for tier, (bw, th) in enumerate(((150, 110), (118, 95), (88, 85))):
        d.rectangle([x - bw * 0.62, y - th, x + bw * 0.62, y], fill=col)
        d.rectangle([x - 18, y - th * 0.72, x + 18, y - th * 0.18], fill=(255, 190, 140, int(220 * glow_k)))
        roof_y = y - th
        d.polygon([(x - bw - 40, roof_y + 18), (x - bw, roof_y - 4), (x + bw, roof_y - 4), (x + bw + 40, roof_y + 18),
                   (x + bw * 0.7, roof_y - 34), (x - bw * 0.7, roof_y - 34)], fill=col)
        y = roof_y - 30
    d.line([x, y, x, y - 90], fill=col, width=8)
    for i in range(5):
        d.ellipse([x - 14, y - 22 - i * 16, x + 14, y - 8 - i * 16], outline=col, width=4)


def tag_sprite(label: str) -> Image.Image:
    fnt = L.font("serif_bold", 32)
    L.check_glyphs(label, fnt)
    w = int(fnt.getlength(label)) + 40
    img = Image.new("RGBA", (w, 54), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, w - 2, 52], radius=26, fill=(36, 20, 54, 230), outline=L.GOLD + (255,), width=2)
    d.text((w / 2, 27), label, font=fnt, fill=L.GOLD_PALE + (255,), anchor="mm")
    return img


def arc_point(a, b, u, lift):
    x = a[0] + (b[0] - a[0]) * u
    y = a[1] + (b[1] - a[1]) * u - 4 * lift * u * (1 - u)
    return x, y


def crow_polygon(cx, cy, s, flap):
    """Силуэт ворона: тело, хвост и машущие крылья."""
    up = math.sin(flap) * 0.9
    body = [(cx - 1.1 * s, cy), (cx - 0.5 * s, cy - 0.22 * s), (cx + 0.6 * s, cy - 0.18 * s), (cx + 1.05 * s, cy - 0.05 * s),
            (cx + 0.6 * s, cy + 0.2 * s), (cx - 0.3 * s, cy + 0.22 * s), (cx - 1.5 * s, cy + 0.35 * s),
            (cx - 1.4 * s, cy + 0.05 * s)]
    wing = [(cx - 0.2 * s, cy - 0.1 * s), (cx + 0.1 * s, cy - (0.9 + up) * s), (cx + 0.55 * s, cy - (1.5 + up * 1.2) * s),
            (cx + 0.45 * s, cy - (0.6 + up * 0.5) * s), (cx + 0.35 * s, cy - 0.12 * s)]
    return body, wing


def build():
    rnd = random.Random(5)
    bg = L.night_sky(W, H, seed=17, moon=(0.5, 0.15), horizon=0.7)
    d = ImageDraw.Draw(bg, "RGBA")
    ground = [(0, H)] + [(x, 835 + 18 * math.sin(x / 260) + 8 * math.sin(x / 70)) for x in range(0, W + 20, 20)] + [(W, H)]
    d.polygon(ground, fill=(10, 7, 16, 255))
    petals = L.Petals(40, W, H, seed=33, size=(6, 13), speed=(30, 70))

    f_cap = L.font("serif", 38)
    f_tech = L.font("sans", 24)
    captions = {
        "m1": L.text_sprite("Первая весть: мимолётный ключ и сокрытое имя Мастера", f_cap, L.PAPER + (255,)),
        "m2": L.text_sprite("Ответ Святилища: ключи сплетаются в общую тайну", f_cap, L.PAPER + (255,)),
        "armor": L.text_sprite("Тайну знают лишь двое — доспех сомкнулся", f_cap, L.PAPER + (255,)),
        "crow": L.text_sprite("Повторённую весть узнали и отвергли у самых врат", f_cap, L.PAPER + (255,)),
        "final": L.text_sprite("Тайна и подлинность подтверждены доказательствами ProVerif", f_cap, L.PAPER + (255,)),
    }
    tech = L.text_sprite("Noise IK · Curve25519 · ChaChaPoly · BLAKE2s · кадры «SK»", f_tech, L.GOLD + (255,))
    title_k = L.text_sprite("見えざる鎧", L.font("serif_bold", 132), L.MOON + (255,))
    title_r = L.text_sprite("Незримый Доспех", L.font("serif_bold", 64), L.SAKURA_PALE + (255,))
    title_s = L.text_sprite("Свиток IV · Печать bef6346 · 16 октября 2026", L.font("serif", 32), L.GOLD_PALE + (255,))
    lbl_house = L.text_sprite("主 · Дом Мастера", L.font("serif_bold", 30), L.PAPER + (230,))
    lbl_pagoda = L.text_sprite("社 · Святилище Kizune-Ryoiki", L.font("serif_bold", 30), L.PAPER + (230,))
    tags1 = [tag_sprite(s) for s in ("e", "es", "s", "ss")]
    tags2 = [tag_sprite(s) for s in ("e", "ee", "se")]
    seal_reject = L.seal(("拒",), 150, round_seal=True, seed=41)
    seal_proof = L.seal(("証",), 190, seed=42)
    end_title = L.text_sprite("見えざる鎧 · Незримый Доспех", L.font("serif_bold", 56), L.SAKURA_PALE + (255,))

    house_pt = (HOUSE[0] + 60, HOUSE[1] - 230)
    pagoda_pt = (PAGODA[0] - 40, PAGODA[1] - 380)

    # шестигранники доспеха и время их появления
    hexes = []
    size = 36
    hx_step, hy_step = size * 1.5, size * math.sqrt(3)
    for col in range(-30, 31):
        for row in range(0, 20):
            x = DOME_C[0] + col * hx_step
            y = DOME_C[1] - row * hy_step - (hy_step / 2 if col % 2 else 0)
            nx, ny = (x - DOME_C[0]) / DOME_RX, (y - DOME_C[1]) / DOME_RY
            r = nx * nx + ny * ny
            if r < 0.93 and y < DOME_C[1] - 10:
                hexes.append((x, y, min(abs(nx), 1.0) * 0.4 + (1 - min(abs(nx), 1)) * 1.2 * math.sqrt(r) + rnd.uniform(0, 0.15),
                              rnd.uniform(0, math.tau)))

    def armor_layer(f, t, k, hit_k=0.0, hit_pt=None):
        d = ImageDraw.Draw(f, "RGBA")
        built = (t - ARMOR) / 1.8
        for x, y, delay, ph in hexes:
            a = L.clamp01((built - delay) * 3)
            if a <= 0:
                continue
            shimmer = 0.65 + 0.35 * math.sin(t * 2.4 + ph)
            col = L.GOLD
            if hit_pt is not None and hit_k > 0:
                dist = math.hypot(x - hit_pt[0], y - hit_pt[1])
                ring = math.exp(-((dist - hit_k * 420) / 60) ** 2) * (1 - hit_k)
                col = L.mix(L.GOLD, L.VERMILION, min(1.0, ring * 2.5))
                shimmer += ring * 1.5
            pts = [(x + size * 0.92 * math.cos(i * math.pi / 3), y + size * 0.92 * math.sin(i * math.pi / 3)) for i in range(7)]
            d.polygon(pts[:6], fill=(255, 210, 160, int(16 * a * k * shimmer)))
            d.line(pts, fill=col + (int(min(255, 120 * a * k * shimmer)),), width=2)
        edge = L.clamp01(built)
        if edge > 0:
            box = [DOME_C[0] - DOME_RX, DOME_C[1] - DOME_RY, DOME_C[0] + DOME_RX, DOME_C[1] + DOME_RY]
            span = 90 * edge
            d.arc(box, 270 - span, 270 + span, fill=L.GOLD_PALE + (int(220 * k),), width=4)

    def frame(t):
        f = bg.copy()
        petals.draw(f, t, gust=6, k=0.75)
        d = ImageDraw.Draw(f, "RGBA")
        house_glow = 0.8 + 0.2 * math.sin(t * 1.7)
        draw_house(d, *HOUSE, house_glow)
        draw_pagoda(d, *PAGODA, 0.85 + 0.15 * math.sin(t * 1.3 + 1))
        L.glow(f, (HOUSE[0] - 20, HOUSE[1] - 66), 120, (255, 190, 120), 0.35)
        L.glow(f, (PAGODA[0], PAGODA[1] - 200), 160, (255, 180, 140), 0.3)
        L.paste(f, lbl_house, (HOUSE[0], HOUSE[1] + 52), 0.9)
        L.paste(f, lbl_pagoda, (PAGODA[0], PAGODA[1] + 52), 0.9)

        # заглавие
        tk = L.window(t, 0.2, 3.2, 0.6)
        if tk:
            L.paste(f, title_k, (W / 2, 330), tk)
            L.paste(f, title_r, (W / 2, 470), tk)
            L.paste(f, title_s, (W / 2, 540), tk)

        # две вести
        for (start, end), a, b, tags, lift, key in ((M1, house_pt, pagoda_pt, tags1, 190, "m1"),
                                                     (M2, pagoda_pt, house_pt, tags2, 170, "m2")):
            if start - 0.2 <= t <= end + 0.6:
                u = L.smooth((t - start - 0.3) / (end - start - 1.0))
                trail = [arc_point(a, b, uu / 60 * u, lift) for uu in range(61)]
                if len(trail) > 1:
                    d.line(trail, fill=L.SAKURA + (int(150 * L.window(t, start, end + 0.5, 0.4)),), width=3, joint="curve")
                for i, sp in enumerate(tags):
                    # слева направо ярлыки читаются по порядку (e, es, s, ss)
                    ut = u - 0.07 * ((len(tags) - i) if b[0] > a[0] else (i + 1))
                    if ut > 0:
                        L.paste(f, sp, arc_point(a, b, ut, lift + 60), L.window(t, start + 0.3, end, 0.4))
                px, py = arc_point(a, b, u, lift)
                L.glow(f, (px, py), 90, L.SAKURA, 0.9 * L.window(t, start, end, 0.3))
                L.blossom(d, px, py, 24, L.SAKURA_PALE, int(255 * L.window(t, start, end, 0.3)), t * 3)
                L.paste(f, captions[key], (W / 2, 975), L.window(t, start + 0.2, end, 0.5))

        # доспех, сфера и запечатанные кадры
        if t >= ARMOR:
            hit_k = L.clamp01((t - HIT) / 1.2) if t >= HIT else 0.0
            armor_layer(f, t, 1.0, hit_k, (DOME_C[0] - 180, DOME_C[1] - DOME_RY + 40))
            sk = L.smooth((t - ARMOR - 0.6) / 1.2)
            L.spirit_sphere(f, (W / 2, 610), 70, L.STATE["idle"], t, level=0.35, rings=2, satellites=3, k=sk)
            for i in range(6):  # запечатанные лепестки ходят по дуге
                ph = ((t - ARMOR) * 0.33 + i / 6) % 1.0
                a, b = (house_pt, pagoda_pt) if i % 2 == 0 else (pagoda_pt, house_pt)
                px, py = arc_point(a, b, ph, 180)
                L.glow(f, (px, py), 40, L.GOLD, 0.7 * sk)
                d.rounded_rectangle([px - 9, py - 9, px + 9, py + 9], radius=3, fill=L.VERMILION + (int(230 * sk),))
            if t < CROW[0] + 0.3:
                L.paste(f, captions["armor"], (W / 2, 975), L.window(t, ARMOR + 0.5, CROW[0] + 0.3, 0.5))
            L.paste(f, tech, (W / 2, 1035), L.smooth((t - ARMOR - 1.0) / 0.8) * L.smooth((SECONDS - t) / 0.6))

        # ворон с повторённой вестью
        if CROW[0] <= t <= CROW[1]:
            hit_pt = (DOME_C[0] - 180, DOME_C[1] - DOME_RY + 40)
            if t < HIT:
                u = L.smooth((t - CROW[0]) / (HIT - CROW[0]))
                cx, cy = -120 + (hit_pt[0] + 40 + 120) * u, 120 + (hit_pt[1] - 60 - 120) * u
                ck = 1.0
            else:
                u = (t - HIT) / (CROW[1] - HIT)
                cx, cy = hit_pt[0] - 60 - 300 * u, hit_pt[1] - 90 - 220 * u
                ck = L.clamp01(1 - u * 1.4)
            body, wing = crow_polygon(cx, cy, 62, t * 9)
            d.polygon(body, fill=(6, 3, 10, int(250 * ck)))
            d.polygon(wing, fill=(6, 3, 10, int(250 * ck)))
            d.ellipse([cx + 0.62 * 62 - 5, cy - 0.12 * 62 - 5, cx + 0.62 * 62 + 5, cy - 0.12 * 62 + 5],
                      fill=(230, 40, 40, int(255 * ck)))
            if t < HIT:  # украденный лепесток-копия в когтях
                L.blossom(d, cx + 10, cy + 30, 14, (160, 150, 170), int(220 * ck), t)
            if t >= HIT:
                flash = L.clamp01(1 - (t - HIT) / 0.5)
                L.glow(f, hit_pt, 200, L.VERMILION, flash)
                sc = 1 + 0.5 * (1 - L.ease_out(L.clamp01((t - HIT) / 0.25)))
                L.paste(f, seal_reject.resize((int(150 * sc), int(150 * sc)), Image.LANCZOS),
                        (hit_pt[0] - 10, hit_pt[1] - 120), L.window(t, HIT, CROW[1] + 0.4, 0.25))
            L.paste(f, captions["crow"], (W / 2, 975), L.window(t, CROW[0] + 0.3, CROW[1], 0.5))

        # финал
        if t >= FINAL - 0.2:
            k = L.window(t, FINAL, SECONDS + 1, 0.5) * L.smooth((SECONDS - t) / 0.6)
            sc = 1 + 0.4 * (1 - L.ease_out(L.clamp01((t - FINAL - 0.3) / 0.25)))
            if t > FINAL + 0.3:
                L.paste(f, seal_proof.resize((int(190 * sc), int(190 * sc)), Image.LANCZOS), (W / 2, 330), k)
            L.paste(f, end_title, (W / 2, 470), k)
            L.paste(f, captions["final"], (W / 2, 975), k)

        fade = L.smooth(t / 0.6) * L.smooth((SECONDS - t) / 0.6)
        if fade < 1:
            f = Image.blend(Image.new("RGB", f.size, L.NIGHT_TOP), f, fade)
        return f

    return frame


def main():
    L.render_video(NAME, build(), SECONDS, poster_at=13.6)


if __name__ == "__main__":
    main()

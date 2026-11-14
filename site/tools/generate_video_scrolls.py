"""Ролик «Пять Свитков» — sakura-legend-five-scrolls.mp4 / .webm.

Пролог с вертикальным заглавием 桜の伝説, затем пять свитков: каждый
разворачивается, проявляет текст и получает киноварную Печать Времени
(настоящий хэш коммита), а сфера духа меняет цвет и жест под свою эпоху.
Эпилог собирает пять печатей в ряд.

Запуск из корня репозитория: python site/tools/generate_video_scrolls.py
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

import legend_common as L

NAME = "sakura-legend-five-scrolls"
W, H = 1920, 1080
PROLOGUE = 4.5
SEG = 4.2
EPILOGUE = 3.5
SECONDS = PROLOGUE + SEG * len(L.SCROLLS) + EPILOGUE

SCROLL_C = (1300, 540)
SCROLL_W, SCROLL_H = 1100, 760
SPHERE_HOME = (W / 2, 450)
SPHERE_SIDE = (330, 520)


def build():
    bg = L.night_sky(W, H, seed=7, moon=(0.86, 0.17))
    L.branch(bg, (-30, 70), 0.28, 840, 26, seed=3, scale=1.7)
    petals = L.Petals(70, W, H, seed=21, size=(8, 17))

    f_title = L.font("serif_bold", 70)
    f_sub = L.font("serif", 38)
    f_kanji_big = L.font("serif_bold", 100)
    t_title = L.text_sprite("Сказание о Духе Цветущей Сакуры", f_title, L.SAKURA_PALE + (255,))
    t_sub = L.text_sprite("Пять Свитков · 五つの巻", f_sub, L.GOLD_PALE + (255,))
    t_end1 = L.text_sprite("Сказание продолжается", L.font("serif_bold", 60), L.SAKURA_PALE + (255,))
    t_end2 = L.text_sprite("683 Печати Времени · июль — ноябрь 2026", L.font("serif", 34), L.GOLD_PALE + (255,))
    kanji_title = [L.text_sprite(ch, f_kanji_big, L.MOON + (255,)) for ch in "桜の伝説"]

    # содержимое каждого свитка рисуется один раз — на бумаге без валиков
    f_kan = L.font("serif_bold", 74)
    f_jp = L.font("serif", 38)
    f_period = L.font("sans_bold", 26)
    f_cap = L.font("serif", 27)
    contents, seals, small_seals = [], [], []
    for s in L.SCROLLS:
        right = SCROLL_W - 130
        x0, text_w = 110, SCROLL_W - 130 - 110 - 150
        for head_size, line_size in ((48, 30), (44, 28), (40, 26)):  # подбор, чтобы текст не лёг на печать
            f_head, f_line = L.font("serif_bold", head_size), L.font("serif", line_size)
            heads = L.wrap(s["title"], f_head, text_w)
            body = [ln for raw in s["lines"] for ln in L.wrap(raw, f_line, text_w)]
            bottom = 92 + 50 + len(heads) * head_size * 1.28 + 44 + len(body) * line_size * 1.45
            if bottom < SCROLL_H - 235:
                break
        else:
            raise ValueError(f"текст свитка {s['kan']} не помещается")
        layer = Image.new("RGBA", (SCROLL_W, SCROLL_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        L.vertical_text(d, right + 20, 80, s["kan"], f_kan, L.SUMI + (255,))
        L.vertical_text(d, right - 62, 92, s["jp"], f_jp, L.SUMI_SOFT + (235,), spacing=1.05)
        y = 92
        L.text(d, (x0, y), s["period"].upper(), f_period, L.VERMILION + (255,))
        y += 50
        for line in heads:
            L.text(d, (x0, y), line, f_head, L.SUMI + (255,))
            y += head_size * 1.28
        y += 14
        d.line([x0, y, x0 + 140, y], fill=L.VERMILION + (200,), width=3)
        y += 30
        for line in body:
            L.text(d, (x0, y), line, f_line, L.SUMI_SOFT + (255,))
            y += line_size * 1.45
        L.text(d, (x0 + 210, SCROLL_H - 158), "Печать Времени", f_cap, L.SUMI_SOFT + (255,))
        L.text(d, (x0 + 210, SCROLL_H - 120), s["date"], L.font("serif_bold", 30), L.SUMI + (255,))
        contents.append(layer)
        seals.append(L.seal((s["seal"][:4], s["seal"][4:]), 168, seed=len(seals) + 3))
        small_seals.append(L.seal((s["num"],), 112, round_seal=True, seed=len(small_seals) + 11))

    def scene_color(t):
        if t < PROLOGUE:
            return L.STATE["idle"]
        j = min(len(L.SCROLLS) - 1, int((t - PROLOGUE) // SEG))
        local = t - PROLOGUE - j * SEG
        cur = L.SCROLLS[j]["color"] if t < PROLOGUE + SEG * len(L.SCROLLS) else L.STATE["idle"]
        prev = L.SCROLLS[j - 1]["color"] if j > 0 else L.STATE["idle"]
        return L.mix(prev, cur, L.smooth(local / 0.8))

    def sphere_pos(t):
        if t < PROLOGUE:
            rise = L.ease_out(t / 2.2)
            return SPHERE_HOME[0], SPHERE_HOME[1] + 120 * (1 - rise)
        end = PROLOGUE + SEG * len(L.SCROLLS)
        if t < end:
            k = L.smooth((t - PROLOGUE + 0.2) / 1.0)
            return (SPHERE_HOME[0] + (SPHERE_SIDE[0] - SPHERE_HOME[0]) * k,
                    SPHERE_HOME[1] + (SPHERE_SIDE[1] - SPHERE_HOME[1]) * k)
        k = L.smooth((t - end) / 1.0)
        return (SPHERE_SIDE[0] + (SPHERE_HOME[0] - SPHERE_SIDE[0]) * k,
                SPHERE_SIDE[1] + (SPHERE_HOME[1] - 60 - SPHERE_SIDE[1]) * k)

    def motif(f, j, local, pos, color, t):
        """Жест сферы для каждой эпохи."""
        cx, cy = pos
        d = ImageDraw.Draw(f, "RGBA")
        vis = L.window(local, 0.6, SEG - 0.3, 0.5)
        if vis <= 0:
            return
        if j == 0:  # слух: волны расходятся от сферы
            for i in range(4):
                ph = ((t * 0.7 + i / 4) % 1.0)
                r = 120 + ph * 260
                a = int(230 * (1 - ph) * vis)
                d.arc([cx - r, cy - r, cx + r, cy + r], 200, 340, fill=color + (a,), width=3)
                d.arc([cx - r, cy - r, cx + r, cy + r], 20, 160, fill=color + (a // 2,), width=2)
        elif j == 1:  # два зеркала: малое мгновенное и глубокое озеро
            mx, my = cx + 210, cy - 150
            d.ellipse([mx - 48, my - 48, mx + 48, my + 48], outline=L.GOLD + (int(220 * vis),), width=4)
            d.ellipse([mx - 40, my - 40, mx + 40, my + 40], fill=(200, 220, 255, int(60 * vis)))
            L.glow(f, (mx, my), 70, color, 0.5 * vis)
            lake_y = cy + 210
            d.ellipse([cx - 220, lake_y - 38, cx + 220, lake_y + 38], fill=(30, 40, 90, int(170 * vis)),
                      outline=L.GOLD + (int(160 * vis),), width=2)
            L.glow(f, (cx, lake_y), 90, color, 0.55 * vis * (0.7 + 0.3 * math.sin(t * 2)))
            for i in range(3):
                rr = 60 + ((t * 30 + i * 50) % 150)
                d.ellipse([cx - rr, lake_y - rr * 0.17, cx + rr, lake_y + rr * 0.17],
                          outline=(220, 230, 255, int(90 * vis * (1 - rr / 210))), width=1)
        elif j == 2:  # клинок: молниеносный росчерк
            strike = L.clamp01((local - 1.0) / 0.25)
            fade = 1 - L.clamp01((local - 1.6) / 1.2)
            if strike > 0 and fade > 0:
                x1, y1 = cx - 260, cy + 180
                x2, y2 = cx + 260, cy - 200
                xe, ye = x1 + (x2 - x1) * strike, y1 + (y2 - y1) * strike
                for wdt, a in ((16, 60), (8, 140), (3, 255)):
                    d.line([x1, y1, xe, ye], fill=(255, 250, 230, int(a * fade * vis)), width=wdt)
            L.paste(f, t_blade, (cx, cy + 230), vis)
        elif j == 3:  # доспех: два шестиугольника вращаются навстречу
            for k_, (r, sp, col) in enumerate(((175, 0.35, L.GOLD), (205, -0.25, color))):
                pts = [(cx + r * math.cos(sp * t + i * math.pi / 3), cy + r * math.sin(sp * t + i * math.pi / 3))
                       for i in range(7)]
                d.line(pts, fill=col + (int(200 * vis),), width=3, joint="curve")
            for i in range(6):
                a = 0.35 * t + i * math.pi / 3
                d.line([cx + 175 * math.cos(a), cy + 175 * math.sin(a), cx + 205 * math.cos(-0.25 * t + i * math.pi / 3),
                        cy + 205 * math.sin(-0.25 * t + i * math.pi / 3)], fill=L.GOLD + (int(90 * vis),), width=1)
        elif j == 4:  # интуиция: цветок, нарисованный светом
            draw_k = L.clamp01((local - 0.7) / 2.0)
            n = 220
            pts = []
            for i in range(int(n * draw_k)):
                a = i / n * math.tau
                r = 200 + 40 * math.cos(5 * a)
                pts.append((cx + r * math.cos(a - math.pi / 2), cy + r * math.sin(a - math.pi / 2)))
            if len(pts) > 1:
                d.line(pts, fill=(255, 240, 250, int(230 * vis)), width=4, joint="curve")
                L.glow(f, pts[-1], 60, (255, 255, 255), 0.9 * vis)

    t_blade = L.text_sprite("быстрее 1.8 мс", L.font("serif_bold", 40), L.GOLD_PALE + (255,))

    def frame(t):
        f = bg.copy()
        color = scene_color(t)
        pos = sphere_pos(t)
        end = PROLOGUE + SEG * len(L.SCROLLS)
        petals.draw(f, t, gust=10 * math.sin(t * 0.4), k=0.9)

        level = 0.25 + 0.2 * abs(math.sin(t * 2.3))
        j = int((t - PROLOGUE) // SEG) if PROLOGUE <= t < end else -1
        local = t - PROLOGUE - j * SEG if j >= 0 else 0
        if j >= 0:
            motif(f, j, local, pos, color, t)
        L.spirit_sphere(f, pos, 104, color, t, level=level, k=L.smooth(t / 1.6))

        if t < PROLOGUE + 0.6:  # пролог
            for i, sp in enumerate(kanji_title):
                L.paste(f, sp, (1700, 340 + i * 112), L.window(t, 0.5 + i * 0.35, PROLOGUE, 0.6))
            L.paste(f, t_title, (W / 2, 790), L.window(t, 1.4, PROLOGUE, 0.7))
            L.paste(f, t_sub, (W / 2, 872), L.window(t, 2.0, PROLOGUE, 0.7))

        if j >= 0:
            unroll = L.clamp01(local / 0.9) if local < SEG - 0.5 else L.clamp01((SEG - local) / 0.5)
            alpha = L.smooth(local / 0.3) * L.smooth((SEG - local) / 0.15)
            box = L.scroll(f, SCROLL_C, SCROLL_W, SCROLL_H, unroll, alpha)
            ck = L.window(local, 0.75, SEG - 0.45, 0.45)
            if ck > 0:
                x0 = SCROLL_C[0] - SCROLL_W / 2
                vis_w = int((box[2] - box[0]))
                layer = contents[j]
                left = int(box[0] - x0)
                crop = layer.crop((left, 0, left + vis_w, SCROLL_H))
                L.paste(f, crop, ((box[0] + box[2]) / 2, SCROLL_C[1]), ck)
            stamp = L.clamp01((local - 1.5) / 0.22)
            if stamp > 0 and ck > 0:
                sc = 1.0 + 0.55 * (1 - L.ease_out(stamp))
                sp = seals[j].resize((int(168 * sc), int(168 * sc)), Image.LANCZOS)
                sx, sy = SCROLL_C[0] - SCROLL_W / 2 + 195, SCROLL_C[1] + SCROLL_H / 2 - 138
                L.paste(f, sp, (sx, sy), ck * stamp)
                if stamp >= 1 and local < 2.3:  # круги от удара печати
                    d = ImageDraw.Draw(f, "RGBA")
                    rr = 90 + (local - 1.72) * 260
                    a = int(140 * L.clamp01(1 - (local - 1.72) / 0.6))
                    d.ellipse([sx - rr, sy - rr, sx + rr, sy + rr], outline=L.VERMILION + (a,), width=3)

        if t >= end - 0.2:  # эпилог: пять печатей в ряд
            e = t - end
            for i, sp in enumerate(small_seals):
                k = L.window(e, 0.3 + i * 0.22, EPILOGUE + 1, 0.35)
                L.paste(f, sp, (W / 2 + (i - 2) * 150, 690), k * L.smooth((SECONDS - t) / 0.6))
            L.paste(f, t_end1, (W / 2, 820), L.window(e, 0.9, EPILOGUE + 1, 0.6) * L.smooth((SECONDS - t) / 0.6))
            L.paste(f, t_end2, (W / 2, 892), L.window(e, 1.2, EPILOGUE + 1, 0.6) * L.smooth((SECONDS - t) / 0.6))

        # мягкий вход и выход — ролик бесшовно крутится по кругу
        fade = L.smooth(t / 0.6) * L.smooth((SECONDS - t) / 0.6)
        if fade < 1:
            f = Image.blend(Image.new("RGB", f.size, L.NIGHT_TOP), f, fade)
        return f

    return frame


def main():
    L.render_video(NAME, build(), SECONDS, poster_at=PROLOGUE + SEG * 2 + 2.6)


if __name__ == "__main__":
    main()

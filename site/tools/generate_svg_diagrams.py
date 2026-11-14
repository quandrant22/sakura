"""Векторные свитки (SVG) для сайта.

  media/images/diagrams/five-scrolls-path.svg — Путь Пяти Печатей: эпохи, даты и хэши коммитов
  media/images/diagrams/armor-handshake.svg   — Незримый Доспех: две вести рукопожатия Noise IK

Надписи в SVG рисует браузер, поэтому в font-family перечислены шрифты
с кириллицей и кандзи для всех систем.

Запуск из корня репозитория: python site/tools/generate_svg_diagrams.py
"""

from __future__ import annotations

from xml.sax.saxutils import escape

import legend_common as L

FONT = "'Noto Serif CJK JP','Noto Serif JP','Source Han Serif JP','Yu Mincho','Hiragino Mincho ProN',serif"
PAPER = "#F2E9D8"
INK = "#1E181E"
INK_SOFT = "#4E4248"
RED = "#C43A32"
GOLD = "#D6B26C"
SAKURA = "#F6B0C7"


def rgb(c):
    return "#%02X%02X%02X" % tuple(c)


def t(x, y, s, size, fill=INK, weight=400, anchor="middle", extra=""):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" {extra}>{escape(s)}</text>')


def blossom(x, y, r, fill=SAKURA):
    petals = "".join(
        f'<ellipse cx="{x}" cy="{y - r * 0.55}" rx="{r * 0.42}" ry="{r * 0.6}" fill="{fill}" '
        f'transform="rotate({k * 72} {x} {y})"/>' for k in range(5))
    return petals + f'<circle cx="{x}" cy="{y}" r="{r * 0.2}" fill="#DE6291"/>'


def five_scrolls_path() -> str:
    w, h = 1600, 480
    xs = [180, 490, 800, 1110, 1420]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="{FONT}" role="img" '
        f'aria-labelledby="t d">',
        '<title id="t">Путь Пяти Печатей</title>',
        '<desc id="d">Пять эпох истории Сакуры с июля по ноябрь 2026 года и Печати Времени — хэши коммитов</desc>',
        f'<rect x="0" y="0" width="{w}" height="{h}" rx="22" fill="{PAPER}"/>',
        f'<rect x="14" y="14" width="{w - 28}" height="{h - 28}" rx="14" fill="none" stroke="{INK_SOFT}" stroke-width="1.5"/>',
        t(60, 70, "Путь Пяти Печатей · 五つの巻", 34, INK, 700, "start"),
        t(60, 108, "Каждая печать — настоящий коммит, с которого началась эпоха", 20, INK_SOFT, 400, "start"),
        # река-путь
        f'<path d="M 60 250 C 300 190, 380 310, 640 240 S 1000 190, 1240 250 S 1460 300, 1540 240" '
        f'fill="none" stroke="{INK}" stroke-width="7" stroke-linecap="round" opacity="0.88"/>',
        f'<path d="M 60 262 C 300 202, 380 322, 640 252 S 1000 202, 1240 262 S 1460 312, 1540 252" '
        f'fill="none" stroke="{GOLD}" stroke-width="2" stroke-dasharray="2 10" stroke-linecap="round"/>',
    ]
    for x, s in zip(xs, L.SCROLLS):
        parts += [
            f'<g>',
            f'<circle cx="{x}" cy="248" r="62" fill="{rgb(s["color"])}" opacity="0.18"/>',
            f'<rect x="{x - 44}" y="204" width="88" height="88" rx="8" fill="{RED}"/>',
            f'<rect x="{x - 37}" y="211" width="74" height="74" rx="5" fill="none" stroke="{PAPER}" stroke-width="2.5"/>',
            t(x, 266, s["num"], 50, PAPER, 700),
            t(x, 172, s["period"], 19, RED, 700),
            t(x, 334, s["kan"] + " · " + s["seal"], 20, INK, 700),
            t(x, 362, s["date"], 18, INK_SOFT),
        ]
        words = s["title"].split()
        lines, cur = [], ""
        for word in words:  # перенос названия по ~22 символа
            if len(cur) + len(word) + 1 > 22 and cur:
                lines.append(cur)
                cur = word
            else:
                cur = (cur + " " + word).strip()
        lines.append(cur)
        for i, line in enumerate(lines[:3]):
            parts.append(t(x, 392 + i * 22, line, 17, INK_SOFT, 400, "middle", 'font-style="italic"'))
        parts.append("</g>")
    parts += [blossom(1500, 78, 16), blossom(1534, 104, 11), blossom(1468, 112, 9), "</svg>"]
    return "\n".join(parts)


def armor_handshake() -> str:
    w, h = 1600, 846
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="{FONT}" role="img" '
        f'aria-labelledby="t d">',
        '<title id="t">Незримый Доспех</title>',
        '<desc id="d">Две вести рукопожатия Noise IK между Мастером и Святилищем Kizune-Ryoiki и доспех над ними</desc>',
        '<defs><pattern id="hex" width="54" height="31.2" patternUnits="userSpaceOnUse">'
        f'<path d="M 0 15.6 L 9 0 L 27 0 L 36 15.6 L 27 31.2 L 9 31.2 Z" fill="none" stroke="{GOLD}" '
        'stroke-width="1.4" opacity="0.55"/></pattern>'
        '<clipPath id="dome"><path d="M 110 600 A 690 380 0 0 1 1490 600 Z"/></clipPath>'
        f'<marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="9" markerHeight="9" orient="auto">'
        f'<path d="M 0 0 L 10 5 L 0 10 Z" fill="context-stroke"/></marker></defs>',
        f'<rect x="0" y="0" width="{w}" height="{h}" rx="22" fill="{PAPER}"/>',
        f'<rect x="14" y="14" width="{w - 28}" height="{h - 28}" rx="14" fill="none" stroke="{INK_SOFT}" stroke-width="1.5"/>',
        t(60, 72, "Незримый Доспех · 見えざる鎧", 36, INK, 700, "start"),
        t(60, 110, "Свиток IV · Печать bef6346 · 16 октября 2026", 20, INK_SOFT, 400, "start"),
        '<rect x="0" y="0" width="1600" height="600" fill="url(#hex)" clip-path="url(#dome)"/>',
        f'<path d="M 110 600 A 690 380 0 0 1 1490 600" fill="none" stroke="{GOLD}" stroke-width="4"/>',
        # дом мастера
        f'<g fill="{INK}"><rect x="150" y="520" width="160" height="80"/>'
        '<path d="M 110 526 L 230 450 L 350 526 L 310 514 L 230 468 L 150 514 Z"/></g>',
        f'<rect x="185" y="540" width="30" height="34" fill="{GOLD}"/><rect x="245" y="540" width="30" height="34" fill="{GOLD}"/>',
        t(230, 640, "主 · Мастер", 26, INK, 700),
        # святилище
        f'<g fill="{INK}"><rect x="1312" y="530" width="116" height="70"/><path d="M 1246 542 L 1303 508 L 1437 508 L 1494 542 Z"/>'
        '<rect x="1324" y="440" width="92" height="60"/><path d="M 1266 452 L 1317 418 L 1423 418 L 1474 452 Z"/>'
        '<rect x="1336" y="366" width="68" height="54"/><path d="M 1286 378 L 1331 344 L 1409 344 L 1454 378 Z"/>'
        '<rect x="1367" y="292" width="6" height="52"/></g>',
        t(1330, 640, "社 · Святилище Kizune-Ryoiki", 26, INK, 700),
        # первая весть
        f'<path d="M 320 450 Q 800 210 1280 350" fill="none" stroke="{RED}" stroke-width="4" marker-end="url(#ah)"/>',
        t(800, 196, "Первая весть: мимолётный ключ и сокрытое имя Мастера", 22, RED, 700),
    ]
    for (x, y), lab in zip(((540, 351), (700, 314), (860, 305), (1020, 318)), ("e", "es", "s", "ss")):
        parts += [f'<rect x="{x - 26}" y="{y - 17}" width="52" height="34" rx="17" fill="{PAPER}" stroke="{RED}" stroke-width="2"/>',
                  t(x, y + 7, lab, 20, RED, 700)]
    parts += [
        f'<path d="M 1280 460 Q 800 360 320 490" fill="none" stroke="{INK}" stroke-width="4" marker-end="url(#ah)"/>',
        t(800, 482, "Ответ Святилища: ключи сплетаются в общую тайну", 22, INK, 700),
    ]
    for (x, y), lab in zip(((1040, 423), (800, 410), (560, 435)), ("e", "ee", "se")):
        parts += [f'<rect x="{x - 26}" y="{y - 17}" width="52" height="34" rx="17" fill="{PAPER}" stroke="{INK}" stroke-width="2"/>',
                  t(x, y + 7, lab, 20, INK, 700)]
    for i in range(5):
        x = 560 + i * 120
        parts += [f'<rect x="{x - 17}" y="538" width="34" height="34" rx="5" fill="{RED}"/>', t(x, 561, "SK", 14, PAPER, 700)]
    facts = [("鍵", "Ключ устройства хранится в защищённом хранилище ПК"),
             ("八", "Спаривание: восемь слов или QR (Noise XXpsk3)"),
             ("拒", "Повтор, перестановка и подмена вести отвергаются"),
             ("証", "Тайна и подлинность доказаны в ProVerif")]
    for i, (k, txt) in enumerate(facts):
        x, y = 90 + (i % 2) * 740, 700 + (i // 2) * 58
        parts += [f'<circle cx="{x}" cy="{y}" r="22" fill="{RED}"/>', t(x, y + 8, k, 22, PAPER, 700),
                  t(x + 36, y + 7, txt, 20, INK, 400, "start")]
    parts += [t(1540, 812, "Noise IK · Curve25519 · ChaChaPoly · BLAKE2s", 18, INK_SOFT, 400, "end"), "</svg>"]
    return "\n".join(parts)


def main():
    L.DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    for name, svg in (("five-scrolls-path.svg", five_scrolls_path()), ("armor-handshake.svg", armor_handshake())):
        path = L.DIAGRAMS_DIR / name
        path.write_text(svg + "\n", encoding="utf-8")
        print(f"  [ok] {path.relative_to(L.ROOT)} — {path.stat().st_size / 1e3:.1f} КБ")


if __name__ == "__main__":
    main()

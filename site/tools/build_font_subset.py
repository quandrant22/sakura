"""Подмножество шрифта для сайта: styles/fonts/legend-serif-{regular,bold}.woff.

Берёт Noto Serif CJK JP (SIL Open Font License) и оставляет только нужные
глифы: латиницу, кириллицу, знаки препинания и все символы, которые
встречаются в index.html и scripts/app.js (в том числе каждое кандзи).
Запускать после любой правки текста страницы:

    python site/tools/build_font_subset.py
"""

from __future__ import annotations

import re
import shutil
from html import unescape
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

import legend_common as L

OUT = L.SITE / "styles" / "fonts"
SOURCES = [L.SITE / "index.html", L.SITE / "scripts" / "app.js"]
BASE = (
    "".join(chr(c) for c in range(0x20, 0x7F))
    + "".join(chr(c) for c in range(0x410, 0x450)) + "Ёё"
    + "«»—–…·•№„“”‘’ →←×°±"
)
LICENSES = [Path("/usr/share/doc/fonts-noto-cjk/copyright")]


def page_chars() -> str:
    text = ""
    for src in SOURCES:
        raw = src.read_text(encoding="utf-8")
        text += unescape(re.sub(r"<[^>]+>", " ", raw)) if src.suffix == ".html" else raw
    return "".join(sorted(set(text + BASE)))


def build(kind: str, out_name: str, chars: str):
    path, index = L.font_file(kind)
    font = TTFont(path, fontNumber=index)
    opts = subset.Options()
    opts.flavor = "woff"
    opts.layout_features = ["kern", "liga", "vert", "vrt2", "vkna", "palt", "halt"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.hinting = False
    sub = subset.Subsetter(opts)
    sub.populate(text=chars)
    sub.subset(font)
    cmap = font.getBestCmap()
    missing = sorted({c for c in chars if not c.isspace() and ord(c) >= 0x20 and ord(c) not in cmap})
    if missing:
        raise SystemExit(f"в {path} нет глифов: {missing}")
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / out_name
    font.save(dest)
    print(f"  [ok] {dest.relative_to(L.ROOT)} — {dest.stat().st_size / 1e3:.0f} КБ, {len(cmap)} глифов из {Path(path).name}")


def main():
    chars = page_chars()
    print(f"[шрифт] {len(chars)} символов, из них кандзи и каны: "
          f"{sum(1 for c in chars if ord(c) > 0x3000)}")
    build("serif", "legend-serif-regular.woff", chars)
    build("serif_bold", "legend-serif-bold.woff", chars)
    for lic in LICENSES:
        if lic.exists():
            shutil.copy(lic, OUT / "LICENSE-NotoSerifCJK.txt")
            print(f"  [ok] лицензия шрифта → {(OUT / 'LICENSE-NotoSerifCJK.txt').relative_to(L.ROOT)}")


if __name__ == "__main__":
    main()

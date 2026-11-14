"""Обработка гравюр и фото для сайта и роликов (вызывается из fetch_art.py).

Три вида производных:
  plate — репродукция для свитка: поля обрезаны, лёгкая S-кривая, чуть
          насыщенности и тепла, мягкая виньетка; 1600 и 800 px;
  bg    — фон раздела: кадр 16:9, глубокие тени в индиго, тёплые света,
          розовое свечение сакуры, сильная виньетка; 1920 и 960 px;
  video — исходник ролика: тот же кадр 16:9 в 2304×1296, правка мягче
          (поверх ролика ещё лягут свет, лепестки и титры).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import legend_common as L

# где у каждой работы кадр 16:9: центр (cx, cy) и ширина w — доли от обрезанной работы
FRAMES = {
    "kumoi": (0.5, 0.40, 1.0),
    "yasumasa": (0.47, 0.5, 1.0),
    "mitsuoki": (0.42, 0.5, 1.0),
    "utamaro": (0.5, 0.5, 1.0),
    "moon-smoke": (0.5, 0.27, 1.0),
    "yozakura": (0.5, 0.46, 1.0),
    "kanbara": (0.5, 0.56, 1.0),
    "hirosaki": (0.5, 0.56, 1.0),
    "yuzu-scroll": (0.5, 0.5, 1.0),
}
PLATE_CROPS = {
    "kumoi": (0.022, 0.025, 0.978, 0.968),
    "yasumasa": (0.004, 0.018, 0.996, 0.985),
    "mitsuoki": (0.016, 0.03, 0.984, 0.972),
    "utamaro": (0.014, 0.02, 0.99, 0.985),
    "moon-smoke": (0.02, 0.012, 0.98, 0.988),
    "yozakura": (0.025, 0.025, 0.995, 0.975),
    "kanbara": (0.028, 0.04, 0.975, 0.955),
    "hirosaki": (0.0, 0.0, 1.0, 1.0),
    "yuzu-scroll": (0.0, 0.03, 1.0, 0.97),
}
# что из каждой работы нужно сайту: пластины — в свитках, фоны — в разделах страницы
PLATES = {"yasumasa", "mitsuoki", "utamaro", "moon-smoke", "yozakura"}
BACKDROPS = {"kumoi", "kanbara", "hirosaki", "mitsuoki"}
BG_CROPS = dict(PLATE_CROPS, yozakura=(0.035, 0.03, 0.93, 0.95),   # без картуша справа
                kanbara=(0.03, 0.17, 0.975, 0.955))                # без картуша сверху
INDIGO = np.array([0.045, 0.035, 0.10], dtype=np.float32)
WARM = np.array([1.0, 0.86, 0.78], dtype=np.float32)
PINK = np.array([0.96, 0.60, 0.74], dtype=np.float32)


def _arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0


def _img(a: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def _lum(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def _smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def _vignette(h, w, strength, inner=0.42, outer=1.08):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 * 0.85 + ((yy - h / 2) / (h / 2)) ** 2)
    return 1 - strength * _smooth(inner, outer, r)


def _saturate(a, k):
    lum = _lum(a)[..., None]
    return lum + (a - lum) * k


def _sakura_mask(a):
    """Где на картине розовое/алое — там будет мягкое свечение."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    pinkness = np.clip((r - g) * 2.2, 0, 1) * np.clip((b - g * 0.75) * 3 + 0.4, 0, 1)
    return pinkness * _smooth(0.25, 0.75, _lum(a))


def _bloom(a, radius, amount, mask=None):
    src = a * (mask[..., None] if mask is not None else _smooth(0.55, 0.95, _lum(a))[..., None])
    h, w = a.shape[:2]
    small = _img(src).resize((max(1, w // 4), max(1, h // 4)), Image.BILINEAR)
    glow = _arr(small.filter(ImageFilter.GaussianBlur(radius / 4)).resize((w, h), Image.BILINEAR))
    return 1 - (1 - a) * (1 - glow * amount)            # screen


def grade_plate(img: Image.Image) -> Image.Image:
    a = _arr(img)
    a = np.clip((a - 0.02) / 0.97, 0, 1)
    a = a + 0.10 * np.sin(np.pi * a) * (a - 0.5) * 2         # мягкая S-кривая
    a = _saturate(a, 1.08)
    a = a * np.array([1.015, 1.0, 0.975], dtype=np.float32)
    a = a * _vignette(*a.shape[:2], 0.16)[..., None]
    return _img(a)


def grade_dark(img: Image.Image, depth: float = 1.0) -> Image.Image:
    """Ночная гамма сайта; depth=1 — фон раздела, меньше — исходник ролика."""
    a = _arr(img)
    lum = _lum(a)
    sak = _sakura_mask(a)
    a = _saturate(a, 1.0 - 0.25 * depth)                      # бумага не должна желтеть
    a = np.power(np.clip(a, 0, 1), 1 + 0.45 * depth) * (1 - 0.34 * depth)
    shadow_w = np.power(1 - np.clip(lum, 0, 1), 2.2)[..., None] * (0.55 * depth)
    a = a + (INDIGO - a) * shadow_w
    hi_w = _smooth(0.45, 1.0, lum)[..., None] * 0.22 * depth
    a = a + (a * WARM - a) * hi_w
    a = a + PINK * sak[..., None] * 0.18 * depth                 # сакура светится изнутри
    a = _bloom(a, radius=a.shape[1] / 70, amount=0.35 * depth, mask=np.maximum(sak, _smooth(0.5, 0.9, _lum(a))))
    a = a * _vignette(*a.shape[:2], 0.72 * depth + 0.1)[..., None]
    return _img(a)


def crop_frac(img: Image.Image, box) -> Image.Image:
    w, h = img.size
    return img.crop((round(box[0] * w), round(box[1] * h), round(box[2] * w), round(box[3] * h)))


def frame_16_9(img: Image.Image, frame) -> Image.Image:
    cx, cy, wf = frame
    w, h = img.size
    fw = w * wf
    fh = fw * 9 / 16
    if fh > h:                                                   # кадр выше картины — по высоте
        fh = h
        fw = fh * 16 / 9
    x0 = min(max(cx * w - fw / 2, 0), w - fw)
    y0 = min(max(cy * h - fh / 2, 0), h - fh)
    return img.crop((round(x0), round(y0), round(x0 + fw), round(y0 + fh)))


def save_jpg(img: Image.Image, path: Path, quality=82):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, quality=quality, optimize=True, progressive=True)
    return path


def resize_w(img: Image.Image, w: int) -> Image.Image:
    return img.resize((w, round(img.height * w / img.width)), Image.LANCZOS) if img.width != w else img


def resize_long(img: Image.Image, side: int) -> Image.Image:
    k = side / max(img.size)
    return img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS) if k < 1 else img


def crow_cutout(raw: Image.Image) -> Image.Image:
    """Ворон Кёсая: густая тушь по светлой бумаге → чёрный силуэт с мягкой альфой.

    Ворон написан плотной чёрной тушью, ветка — сухой серой кистью: порог по
    плотности оставляет птицу и растворяет ветку без жёстких масок."""
    w, h = raw.size
    region = raw.crop((round(0.20 * w), round(0.115 * h), round(0.78 * w), round(0.345 * h))).convert("RGB")
    a = _arr(region)
    lum = np.asarray(_img(a).filter(ImageFilter.GaussianBlur(1.2)).convert("L"), dtype=np.float32) / 255
    paper = float(np.percentile(lum, 80))
    ink = float(np.percentile(lum, 2))
    t_lo, t_hi = ink + 0.18 * (paper - ink), ink + 0.42 * (paper - ink)
    alpha = np.clip((t_hi - lum) / (t_hi - t_lo), 0, 1)
    alpha = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8)),
                       dtype=np.float32) / 255
    col = np.clip(a * 0.3, 0, 1)
    out = np.dstack([col, alpha])
    img = Image.fromarray((out * 255).astype(np.uint8), "RGBA")
    img = img.crop(img.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox())
    return img.crop((0, 0, round(img.width * 0.915), img.height))   # справа — обрывки ветки


def scroll_paper(raw: Image.Image) -> Image.Image:
    """Бумага свитков: краски и каллиграфия эмакимоно — едва заметным призраком на васи."""
    img = resize_w(crop_frac(raw, PLATE_CROPS["yuzu-scroll"]), 2000)
    g = _lum(_arr(img))
    g = (g - g.mean()) / (g.std() + 1e-6)
    paper = np.array(L.PAPER, dtype=np.float32) / 255
    ink = np.array([0.36, 0.28, 0.24], dtype=np.float32)
    k = np.clip(-g * 0.07, -0.03, 0.10)[..., None]                    # тёмное — к туши, едва-едва
    a = paper + (ink - paper) * k
    return _img(a)


def process_all(art: dict, raw_dir: Path, video_dir: Path, art_dir: Path):
    art_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)
    credits = []
    for key, spec in art.items():
        raw = Image.open(raw_dir / key / "original.jpg")
        raw.load()
        meta = json.loads((raw_dir / key / "meta.json").read_text(encoding="utf-8"))
        credits.append({"key": key, "artist": spec["artist"], "title": spec["title"], "date": spec["date"],
                        "source": meta["source"], "license": meta["license"], "page": meta["page"]})
        if key == "crow":
            crow = crow_cutout(raw)
            crow.save(video_dir / "crow.png")
            print(f"  [ok] ворон: {crow.size}")
            continue
        if key == "yuzu-scroll":
            save_jpg(scroll_paper(raw), art_dir / "scroll-paper.jpg", 78)
            save_jpg(resize_w(grade_dark(resize_w(crop_frac(raw, PLATE_CROPS[key]), 2400), 0.9), 1920),
                     art_dir / "emaki-band.jpg", 78)
            print("  [ok] бумага свитков и полоса эмакимоно")
            continue
        made = []
        if key in PLATES:
            plate = grade_plate(crop_frac(raw, PLATE_CROPS[key]))
            save_jpg(resize_long(plate, 1600), art_dir / f"{key}-plate.jpg", 84)
            save_jpg(resize_long(plate, 800), art_dir / f"{key}-plate-800.jpg", 82)
            made.append(f"пластина {plate.size}")
        frame = frame_16_9(crop_frac(raw, BG_CROPS[key]), FRAMES[key])
        if key in BACKDROPS:
            bg = grade_dark(resize_w(frame, 1920), 1.0)
            save_jpg(bg, art_dir / f"{key}-bg.jpg", 80)
            save_jpg(resize_w(bg, 960), art_dir / f"{key}-bg-960.jpg", 78)
            made.append("фон раздела")
        vid = grade_dark(frame.resize((2304, 1296), Image.LANCZOS), 0.55)
        save_jpg(vid, video_dir / f"{key}.jpg", 92)
        made.append(f"исходник ролика из кадра {frame.size}")
        print(f"  [ok] {key}: " + ", ".join(made))
    (art_dir / "credits.json").write_text(json.dumps(credits, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

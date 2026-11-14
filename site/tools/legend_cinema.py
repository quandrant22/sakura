"""Кинематографические слои для роликов «Сказания».

  art(key)            — гравюра 2304×1296 из кэша fetch_art.py (уже в гамме сайта);
  Parallax            — два плана одной картины: дальний и ближний движутся
                        с разной скоростью (маска глубины), плюс медленный наезд;
  Mist                — полосы тумана, дрейфующие поперёк кадра;
  Bokeh               — лепестки на трёх глубинах резкости;
  glow_layer / bloom  — свечение светящихся элементов (линии, печати, частицы);
  Calligraphy         — кандзи кистью (Yuji Syuku), «пишутся» сверху вниз;
  ink_splash          — клякса туши для удара печати;
  ink_wipe            — переход между картинами растекающейся тушью.
"""

from __future__ import annotations

import functools
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import legend_common as L

W, H = 1920, 1080
CACHE = Path.home() / ".cache" / "sakura-legend-art"
BRUSH_FONT = CACHE / "fonts" / "yujisyuku" / "YujiSyuku-Regular.ttf"


@functools.lru_cache(maxsize=None)
def art(key: str) -> Image.Image:
    path = CACHE / "video" / f"{key}.jpg"
    if not path.exists():
        raise SystemExit(f"Нет {path}: сначала запустите python -I site/tools/fetch_art.py")
    return Image.open(path).convert("RGB")


@functools.lru_cache(maxsize=None)
def crow() -> Image.Image:
    return Image.open(CACHE / "video" / "crow.png").convert("RGBA")


@functools.lru_cache(maxsize=None)
def brush_font(size: int) -> ImageFont.FreeTypeFont:
    if not BRUSH_FONT.exists():
        raise SystemExit(f"Нет кистевого шрифта {BRUSH_FONT}: запустите fetch_art.py")
    return ImageFont.truetype(str(BRUSH_FONT), size)


def _smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


# ── параллакс ───────────────────────────────────────────────────────────
class Parallax:
    """Наезд с двумя планами. mask — «ближний» план (1) против дальнего (0).

    depth: 'vertical' — низ ближе (земля, деревня); 'dark' — тёмные силуэты
    ближе светлого неба (ветви на фоне луны); 'pink' — цветущие ветви ближе."""

    def __init__(self, key: str, depth: str = "vertical", z0=1.0, z1=1.08, pan=(0.0, 0.0), near_extra=0.035):
        self.img = art(key)
        self.far = self.img.filter(ImageFilter.GaussianBlur(1.6))
        self.z0, self.z1, self.pan, self.near_extra = z0, z1, pan, near_extra
        a = np.asarray(self.img, dtype=np.float32) / 255
        lum = a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722
        h, w = lum.shape
        if depth == "dark":
            m = _smooth((0.42 - lum / max(float(np.percentile(lum, 95)), 1e-3)) / 0.3)
        elif depth == "pink":
            m = _smooth((a[..., 0] - a[..., 1]) * 6 - 0.2) * _smooth(lum * 4)
        else:
            m = np.repeat(_smooth((np.linspace(0, 1, h) - 0.45) / 0.4)[:, None], w, axis=1)
        mask = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(w / 160))
        self.mask = mask

    def _view(self, src: Image.Image, z: float, u: float, resample=Image.BILINEAR) -> Image.Image:
        sw, sh = src.size
        bw, bh = sw / z, sh / z
        cx = sw / 2 + self.pan[0] * sw * (u - 0.5)
        cy = sh / 2 + self.pan[1] * sh * (u - 0.5)
        x0 = min(max(cx - bw / 2, 0), sw - bw)
        y0 = min(max(cy - bh / 2, 0), sh - bh)
        return src.resize((W, H), resample, box=(x0, y0, x0 + bw, y0 + bh))

    def brightest(self) -> tuple[float, float]:
        """Где на картине луна: центр самого яркого пятна (в координатах исходника)."""
        small = self.img.convert("L").resize((self.img.width // 8, self.img.height // 8)).filter(ImageFilter.GaussianBlur(4))
        a = np.asarray(small, dtype=np.float32)
        y, x = np.unravel_index(int(np.argmax(a)), a.shape)
        return x * 8 + 4, y * 8 + 4

    def to_frame(self, px: float, py: float, u: float) -> tuple[float, float]:
        """Точка исходника → координаты кадра на дальнем плане (для свечения луны)."""
        u = min(max(u, 0.0), 1.0)
        e = u * u * (3 - 2 * u) * 0.6 + u * 0.4
        z = self.z0 + (self.z1 - self.z0) * e
        sw, sh = self.img.size
        bw, bh = sw / z, sh / z
        cx = sw / 2 + self.pan[0] * sw * (u - 0.5)
        cy = sh / 2 + self.pan[1] * sh * (u - 0.5)
        x0 = min(max(cx - bw / 2, 0), sw - bw)
        y0 = min(max(cy - bh / 2, 0), sh - bh)
        return (px - x0) * W / bw, (py - y0) * H / bh

    def frame(self, u: float) -> Image.Image:
        """u ∈ [0, 1] — доля сцены."""
        u = min(max(u, 0.0), 1.0)
        e = u * u * (3 - 2 * u) * 0.6 + u * 0.4
        z = self.z0 + (self.z1 - self.z0) * e
        zn = z * (1 + self.near_extra * e)
        far = self._view(self.far, z, u)
        near = self._view(self.img, zn, u)
        mask = self._view(self.mask, zn, u)
        far.paste(near, (0, 0), mask)
        return far


# ── туман ───────────────────────────────────────────────────────────────
class Mist:
    def __init__(self, seed=3, alpha=60, color=(190, 170, 220), y=(0.55, 0.95)):
        rnd = np.random.default_rng(seed)
        tw = W * 2
        noise = rnd.random((H // 24 + 2, tw // 24 + 2)).astype(np.float32)
        tex = Image.fromarray((noise * 255).astype(np.uint8)).resize((tw, H), Image.BICUBIC)
        tex = tex.filter(ImageFilter.GaussianBlur(40))
        n = np.asarray(tex, dtype=np.float32) / 255
        band = _smooth((np.linspace(0, 1, H) - y[0]) / 0.18) * _smooth((y[1] - np.linspace(0, 1, H)) / 0.25)
        a = np.clip((n - 0.35) * 2.2, 0, 1) * band[:, None] * alpha
        rgba = np.zeros((H, tw, 4), dtype=np.uint8)
        rgba[..., :3] = color
        rgba[..., 3] = a.astype(np.uint8)
        self.tex = Image.fromarray(rgba, "RGBA")
        # шов: вторая половина — копия первой, тогда сдвиг по кругу незаметен
        self.tex.paste(self.tex.crop((0, 0, W, H)), (W, 0))

    def draw(self, frame: Image.Image, t: float, speed=24.0, k=1.0):
        off = int(t * speed) % W
        layer = self.tex.crop((off, 0, off + W, H))
        L.paste(frame, layer, (W / 2, H / 2), k)


# ── лепестки на трёх глубинах ───────────────────────────────────────────
@functools.lru_cache(maxsize=64)
def _petal_sprite(size: int, blur: float, tint: int) -> Image.Image:
    s = size * 3
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = [L.SAKURA_PALE, L.SAKURA, (250, 190, 210)][tint % 3]
    d.polygon(L.petal_polygon(s / 2, s / 2 + size * 0.45, size, 0.0, 1.0, 10), fill=col + (235,))
    d.polygon(L.petal_polygon(s / 2, s / 2 + size * 0.45, size * 0.55, 0.0, 1.0, 8), fill=(255, 238, 244, 120))
    return img.filter(ImageFilter.GaussianBlur(blur)) if blur else img


class Bokeh:
    LAYERS = ((40, (7, 11), 1.6, (30, 55), 0.55), (26, (12, 18), 0.0, (55, 95), 0.9), (9, (28, 46), 7.0, (110, 170), 0.65))

    def __init__(self, seed=8):
        rnd = random.Random(seed)
        self.items = []
        for n, sizes, blur, speed, alpha in self.LAYERS:
            for _ in range(n):
                self.items.append(dict(
                    size=int(rnd.uniform(*sizes)), blur=blur, speed=rnd.uniform(*speed), alpha=alpha,
                    x=rnd.uniform(0, W), y=rnd.uniform(0, H), vx=rnd.uniform(-20, 30),
                    rot=rnd.uniform(0, 360), vr=rnd.uniform(-60, 60), sway=rnd.uniform(0, 6.3),
                    tint=rnd.randint(0, 2), flip=rnd.uniform(0, 6.3)))

    def draw(self, frame: Image.Image, t: float, k=1.0, gust=0.0):
        for p in self.items:
            y = (p["y"] + p["speed"] * t) % (H + 160) - 80
            x = (p["x"] + (p["vx"] + gust) * t + 40 * math.sin(p["sway"] + t * 0.9)) % (W + 160) - 80
            sp = _petal_sprite(p["size"], p["blur"], p["tint"])
            squash = 0.35 + 0.65 * abs(math.cos(p["flip"] + t * 1.7))
            sp = sp.resize((sp.width, max(2, int(sp.height * squash))), Image.BILINEAR)
            sp = sp.rotate(p["rot"] + p["vr"] * t, resample=Image.BILINEAR, expand=True)
            L.paste(frame, sp, (x, y), p["alpha"] * k)


# ── свечение ────────────────────────────────────────────────────────────
def glow_layer() -> Image.Image:
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def bloom(frame: Image.Image, light: Image.Image, radius=18, strength=1.0) -> Image.Image:
    """Кладёт слой света и добавляет его размытое сияние (screen)."""
    base = np.asarray(frame, dtype=np.float32) / 255
    la = np.asarray(light, dtype=np.float32) / 255
    rgb, a = la[..., :3], la[..., 3:4]
    base = base * (1 - a) + rgb * a
    small = light.resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(radius / 4))
    g = np.asarray(small.resize((W, H), Image.BILINEAR), dtype=np.float32) / 255
    glow = g[..., :3] * g[..., 3:4] * strength
    out = 1 - (1 - base) * (1 - np.clip(glow, 0, 1))
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), "RGB")


def vignette_overlay(strength=0.55) -> Image.Image:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 * 0.8 + ((yy - H / 2) / (H / 2)) ** 2)
    a = _smooth((r - 0.55) / 0.6) * strength
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[..., :3] = (6, 4, 14)
    rgba[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def side_shade(side="left", width=0.55, strength=0.78) -> Image.Image:
    """Затемнение под титры, чтобы текст читался поверх любой картины."""
    x = np.linspace(0, 1, W)
    if side == "left":
        a = _smooth((width - x) / width)
    elif side == "right":
        a = _smooth((x - (1 - width)) / width)
    else:
        y = np.linspace(0, 1, H)
        a = None
        col = _smooth((y - (1 - width)) / width)
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[..., :3] = (6, 4, 14)
    rgba[..., 3] = ((a[None, :] if a is not None else col[:, None]) * strength * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


# ── каллиграфия ─────────────────────────────────────────────────────────
class Calligraphy:
    """Столбец кандзи кистью: каждый знак проявляется сверху вниз, тушь чуть растекается."""

    def __init__(self, text: str, size: int, color=L.PAPER, glow=(246, 176, 199), vertical=True, spacing=1.04):
        fnt = brush_font(size)
        L.check_glyphs(text, fnt)
        self.chars = []
        rnd = np.random.default_rng(len(text) * 31 + size)
        for ch in text:
            pad = size // 3
            img = Image.new("L", (size + pad * 2, size + pad * 2), 0)
            ImageDraw.Draw(img).text((img.width / 2, img.height / 2), ch, font=fnt, fill=255, anchor="mm")
            dry = rnd.random((img.height, img.width)).astype(np.float32)
            dry = np.asarray(Image.fromarray((dry * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0)),
                             dtype=np.float32) / 255
            a = np.asarray(img, dtype=np.float32) / 255 * np.clip(0.75 + dry * 0.5, 0, 1)
            self.chars.append(a)
        self.size, self.color, self.glow, self.vertical, self.spacing = size, color, glow, vertical, spacing
        self.ramp = None

    def sprite(self, progress: float) -> Image.Image:
        n = len(self.chars)
        cw = self.chars[0].shape[1]
        step = int(self.size * self.spacing)
        if self.vertical:
            canvas = np.zeros((step * (n - 1) + cw, cw), dtype=np.float32)
        else:
            canvas = np.zeros((cw, step * (n - 1) + cw), dtype=np.float32)
        for i, a in enumerate(self.chars):
            k = min(max(progress * n - i, 0.0), 1.0)
            if k <= 0:
                continue
            h = a.shape[0]
            edge = k * (h * 1.15) - h * 0.08
            ramp = np.clip((edge - np.arange(h, dtype=np.float32)) / (h * 0.12), 0, 1)[:, None]
            part = a * ramp
            if self.vertical:
                canvas[i * step:i * step + h, :] = np.maximum(canvas[i * step:i * step + h, :], part)
            else:
                canvas[:, i * step:i * step + h] = np.maximum(canvas[:, i * step:i * step + h], part)
        alpha = Image.fromarray((canvas * 255).astype(np.uint8))
        halo = alpha.filter(ImageFilter.GaussianBlur(self.size / 9))
        out = Image.new("RGBA", alpha.size, self.glow + (0,))
        out.putalpha(halo.point(lambda v: int(v * 0.55)))
        ink = Image.new("RGBA", alpha.size, self.color + (0,))
        ink.putalpha(alpha)
        out.alpha_composite(ink)
        return out


# ── тушь ────────────────────────────────────────────────────────────────
@functools.lru_cache(maxsize=16)
def ink_splash(size: int, color=L.VERMILION, seed=1) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    c = size / 2
    for _ in range(70):
        ang = rnd.uniform(0, math.tau)
        dist = abs(rnd.gauss(0, size * 0.16))
        r = max(2, rnd.uniform(0.01, 0.06) * size * (1 - dist / size))
        x, y = c + math.cos(ang) * dist, c + math.sin(ang) * dist
        d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    for _ in range(26):                                           # брызги-капли
        ang = rnd.uniform(0, math.tau)
        dist = rnd.uniform(0.25, 0.48) * size
        r = rnd.uniform(0.004, 0.016) * size
        x, y = c + math.cos(ang) * dist, c + math.sin(ang) * dist
        d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    img = img.filter(ImageFilter.GaussianBlur(size / 140)).point(lambda v: 255 if v > 110 else int(v * 1.6))
    out = Image.new("RGBA", img.size, color + (0,))
    out.putalpha(img.point(lambda v: int(v * 0.85)))
    return out


@functools.lru_cache(maxsize=4)
def _wipe_noise(seed=5) -> np.ndarray:
    rnd = np.random.default_rng(seed)
    n = rnd.random((H // 40 + 2, W // 40 + 2)).astype(np.float32)
    big = Image.fromarray((n * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(26))
    fine = Image.fromarray((rnd.random((H, W)) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.5))
    a = np.asarray(big, dtype=np.float32) / 255 * 0.8 + np.asarray(fine, dtype=np.float32) / 255 * 0.2
    return (a - a.min()) / (a.max() - a.min())


def ink_wipe(a: Image.Image, b: Image.Image, k: float, seed=5) -> Image.Image:
    """k∈[0,1]: картина b проступает через a пятнами растекающейся туши."""
    if k <= 0:
        return a
    if k >= 1:
        return b
    n = _wipe_noise(seed)
    m = np.clip((k * 1.3 - n) / 0.12 + 0.5, 0, 1)
    edge = 1 - np.abs(m - 0.5) * 2                               # кромка растекающейся туши
    out = (np.asarray(a, dtype=np.float32) * (1 - m[..., None]) + np.asarray(b, dtype=np.float32) * m[..., None])
    out *= (1 - 0.85 * edge ** 1.5)[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def fade_to(frame: Image.Image, k: float, color=L.NIGHT_TOP) -> Image.Image:
    if k >= 0.999:
        return frame
    return Image.blend(Image.new("RGB", frame.size, color), frame, max(0.0, k))


def text_shadowed(s: str, fnt, fill, blur: int = 7, strength: float = 0.85, shadow=(4, 2, 10)) -> Image.Image:
    """Надпись с мягкой тенью — читается поверх любой гравюры."""
    sp = L.text_sprite(s, fnt, fill, pad=blur * 3)
    a = sp.getchannel("A").filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * strength))
    out = Image.new("RGBA", sp.size, shadow + (0,))
    out.putalpha(a)
    out.alpha_composite(sp)
    return out


def rise(k: float, dy: float = 24.0) -> float:
    """Сдвиг вверх при проявлении: k=0 → dy ниже, k=1 → на месте."""
    k = min(max(k, 0.0), 1.0)
    return dy * (1 - (1 - (1 - k) ** 3))

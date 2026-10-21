"""Иконка Сакуры (цветок из логотипа ui/src/components/SakuraLogo.tsx) → desktop/assets/sakura.ico и .png,
значок трея → desktop/ui/electron/assets/tray.png (16 px), tray@2x.png (32 px) и tray.ico (16–48 px).

python -m desktop.tools.make_icon — тот же контур лепестка, пять лепестков через 72°, радиальный
градиент акцента «Сакура-ночь» (#FF6AE3 → #3E0074), сердцевина и пять тычинок. Рисуется в 1024 px
и уменьшается до 16–256 px.
"""
import math
import os

from PIL import Image, ImageDraw

ACCENT, DEEP, INK = (255, 106, 227), (62, 0, 116), (241, 233, 245)
# M0 -2.2 C… — лепесток «вверх» (viewBox -15..15), см. SakuraLogo.tsx
PETAL = [((0, -2.2), (-3.6, -4.6), (-5.6, -9.2), (-3.9, -12.6)),
         ((-3.9, -12.6), (-2.9, -14.5), (-1.2, -14.9), (0, -13.4)),
         ((0, -13.4), (1.2, -14.9), (2.9, -14.5), (3.9, -12.6)),
         ((3.9, -12.6), (5.6, -9.2), (3.6, -4.6), (0, -2.2))]
SIZE = 1024
DESKTOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(DESKTOP, "assets")
TRAY_DIR = os.path.join(DESKTOP, "ui", "electron", "assets")


def _bezier(p0, p1, p2, p3, n=40):
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        yield (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
               u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _to_px(x, y, k=SIZE / 30):
    return ((x + 15) * k, (y + 15) * k)


def _rot(x, y, deg):
    a = math.radians(deg)
    return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))


def render(size=SIZE) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    for ang in range(0, 360, 72):
        pts = [p for seg in PETAL for p in _bezier(*seg)]
        d.polygon([_to_px(*_rot(x, y, ang)) for x, y in pts], fill=255)
    # радиальный градиент: offset 0.15 — ACCENT, 1 — DEEP (r = 15)
    grad = Image.new("RGB", (size, size))
    gp = grad.load()
    c = size / 2
    for yy in range(size):
        for xx in range(size):
            r = math.hypot(xx - c, yy - c) / (size / 2)
            t = min(1.0, max(0.0, (r - 0.15) / 0.85))
            gp[xx, yy] = tuple(round(a + (b - a) * t) for a, b in zip(ACCENT, DEEP, strict=True))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    k = size / 30
    cx, cy = _to_px(0, 0)
    d.ellipse((cx - 2.4 * k, cy - 2.4 * k, cx + 2.4 * k, cy + 2.4 * k), fill=ACCENT + (255,))
    for ang in range(36, 360 + 36, 72):
        x, y = _to_px(*_rot(0, -4, ang))
        d.ellipse((x - 0.7 * k, y - 0.7 * k, x + 0.7 * k, y + 0.7 * k), fill=INK + (204,))
    return img


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    big = render()
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT_DIR, "sakura.png"))
    sizes = [(n, n) for n in (16, 24, 32, 48, 64, 128, 256)]
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT_DIR, "sakura.ico"), sizes=sizes)
    print(os.path.join(OUT_DIR, "sakura.ico"))
    os.makedirs(TRAY_DIR, exist_ok=True)
    big.resize((16, 16), Image.LANCZOS).save(os.path.join(TRAY_DIR, "tray.png"))
    big.resize((32, 32), Image.LANCZOS).save(os.path.join(TRAY_DIR, "tray@2x.png"))
    big.resize((48, 48), Image.LANCZOS).save(os.path.join(TRAY_DIR, "tray.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48)])
    print(os.path.join(TRAY_DIR, "tray.ico"))


if __name__ == "__main__":
    main()

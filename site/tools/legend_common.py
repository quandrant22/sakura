"""Общие кисти «Сказания о Духе Цветущей Сакуры» для генераторов site/tools.

Здесь живут палитра, шрифты с проверкой глифов, лепесток и цветок сакуры,
сфера духа, печати-ханко, данные пяти свитков и кодирование кадров в MP4 + WebM.
Кинематографические слои (гравюры, параллакс, кисть, тушь) — в legend_cinema.py.

Шрифты ищутся через fontconfig (Linux: пакет fonts-noto-cjk), а на Windows —
в C:\\Windows\\Fonts. Перед каждой надписью проверяется, что в шрифте есть все
глифы: если хоть одного символа нет, генератор падает с ошибкой, а не рисует
«квадратик».
"""

from __future__ import annotations

import functools
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
VIDEOS_DIR = SITE / "media" / "videos"
IMAGES_DIR = SITE / "media" / "images"
POSTERS_DIR = IMAGES_DIR / "posters"

# ── палитра ─────────────────────────────────────────────────────────────
NIGHT_TOP = (8, 8, 22)
NIGHT_MID = (22, 14, 40)
NIGHT_LOW = (46, 22, 52)
PAPER = (242, 233, 216)
PAPER_SHADE = (222, 207, 182)
SUMI = (30, 24, 30)
SUMI_SOFT = (78, 66, 72)
SAKURA = (246, 176, 199)
SAKURA_PALE = (255, 222, 232)
SAKURA_DEEP = (222, 98, 145)
VERMILION = (196, 58, 50)
GOLD = (214, 178, 108)
GOLD_PALE = (240, 214, 160)
MOON = (252, 243, 224)
WOOD = (74, 44, 34)

# цвета состояний сферы — те же, что в живом ядре Сакуры
STATE = {
    "idle": (255, 106, 227),
    "listening": (79, 216, 255),
    "thinking": (255, 207, 107),
    "speaking": (255, 126, 185),
    "offline": (107, 100, 117),
}

# ── шрифты ──────────────────────────────────────────────────────────────
_FC_PATTERNS = {
    "serif": ["Noto Serif CJK JP:style=Regular", "Source Han Serif JP:style=Regular"],
    "serif_bold": ["Noto Serif CJK JP:style=Bold", "Source Han Serif JP:style=Bold"],
    "sans": ["Noto Sans CJK JP:style=Regular", "Source Han Sans JP:style=Regular"],
    "sans_bold": ["Noto Sans CJK JP:style=Bold", "Source Han Sans JP:style=Bold"],
    "mono": ["Noto Sans Mono CJK JP:style=Regular", "DejaVu Sans Mono"],
}
_FILE_FALLBACKS = {
    "serif": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
              r"C:\Windows\Fonts\yumin.ttf"],
    "serif_bold": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
                   r"C:\Windows\Fonts\yumindb.ttf"],
    "sans": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             r"C:\Windows\Fonts\YuGothR.ttc"],
    "sans_bold": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                  r"C:\Windows\Fonts\YuGothB.ttc"],
    "mono": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
             r"C:\Windows\Fonts\consola.ttf"],
}


@functools.lru_cache(maxsize=None)
def font_file(kind: str) -> tuple[str, int]:
    """Путь и индекс начертания в коллекции для вида шрифта."""
    if shutil.which("fc-match"):
        for pattern in _FC_PATTERNS[kind]:
            family = pattern.split(":")[0]
            out = subprocess.run(
                ["fc-match", "-f", "%{file}\t%{index}\t%{family}", pattern],
                capture_output=True, text=True, check=False).stdout
            parts = out.split("\t")
            if len(parts) == 3 and family.lower() in parts[2].lower() and os.path.exists(parts[0]):
                return parts[0], int(parts[1] or 0)
    for path in _FILE_FALLBACKS[kind]:
        if os.path.exists(path):
            return path, 0
    raise SystemExit(
        f"Не найден шрифт «{kind}» с кириллицей и кандзи. "
        "На Linux: apt install fonts-noto-cjk; на Windows нужны Yu Mincho / Yu Gothic.")


@functools.lru_cache(maxsize=None)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    path, index = font_file(kind)
    return ImageFont.truetype(path, size, index=index)


@functools.lru_cache(maxsize=None)
def _cmap(path: str, index: int) -> frozenset[int] | None:
    try:
        from fontTools.ttLib import TTFont
    except ImportError:  # без fontTools проверка невозможна — предупреждаем один раз
        print("  [!] fontTools не установлен: проверка глифов пропущена", file=sys.stderr)
        return None
    return frozenset(TTFont(path, fontNumber=index, lazy=True).getBestCmap())


def check_glyphs(text: str, fnt: ImageFont.FreeTypeFont) -> None:
    cmap = _cmap(fnt.path, fnt.index)
    if cmap is None:
        return
    missing = sorted({ch for ch in text if not ch.isspace() and ord(ch) not in cmap})
    if missing:
        raise ValueError(f"В шрифте {fnt.path} нет глифов {missing!r} для «{text}»")


def text(draw: ImageDraw.ImageDraw, xy, s: str, fnt, fill, anchor="la", **kw):
    check_glyphs(s, fnt)
    draw.text(xy, s, font=fnt, fill=fill, anchor=anchor, **kw)


def wrap(s: str, fnt, max_w: float) -> list[str]:
    """Перенос по словам под ширину max_w."""
    check_glyphs(s, fnt)
    lines, cur = [], ""
    for word in s.split(" "):          # только обычный пробел: неразрывный держит «3 383» вместе
        trial = (cur + " " + word).strip()
        if fnt.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def text_sprite(s: str, fnt, fill, stroke=0, stroke_fill=None, pad=8) -> Image.Image:
    """Надпись на прозрачном холсте — чтобы плавно проявлять её в видео."""
    check_glyphs(s, fnt)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    l, t, r, b = tmp.textbbox((0, 0), s, font=fnt, stroke_width=stroke)
    img = Image.new("RGBA", (r - l + pad * 2, b - t + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((pad - l, pad - t), s, font=fnt, fill=fill,
                             stroke_width=stroke, stroke_fill=stroke_fill)
    return img


def with_alpha(sprite: Image.Image, k: float) -> Image.Image:
    k = max(0.0, min(1.0, k))
    if k >= 0.999:
        return sprite
    out = sprite.copy()
    out.putalpha(sprite.getchannel("A").point(lambda v: int(v * k)))
    return out


def paste(base: Image.Image, sprite: Image.Image, center, k: float = 1.0):
    """Кладёт спрайт по центру с прозрачностью k.

    Кадры — RGB: ImageDraw смешивает полупрозрачные цвета только на RGB-холсте,
    а на RGBA он заменял бы пиксели вместе с альфой."""
    if k <= 0.003:
        return
    sp = with_alpha(sprite, k)
    x = int(round(center[0] - sp.width / 2))
    y = int(round(center[1] - sp.height / 2))
    # обрезаем спрайт по краям кадра вручную
    sx, sy = max(0, -x), max(0, -y)
    if sx >= sp.width or sy >= sp.height:          # спрайт целиком за краем кадра
        return
    if sx or sy:
        sp = sp.crop((sx, sy, sp.width, sp.height))
        x, y = x + sx, y + sy
    if x >= base.width or y >= base.height:
        return
    sp = sp.crop((0, 0, min(sp.width, base.width - x), min(sp.height, base.height - y)))
    if base.mode == "RGBA":
        base.alpha_composite(sp, dest=(x, y))
    else:
        base.paste(sp, (x, y), sp)


# ── плавности ───────────────────────────────────────────────────────────
def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def smooth(v: float) -> float:
    v = clamp01(v)
    return v * v * (3 - 2 * v)


def ease_out(v: float) -> float:
    v = clamp01(v)
    return 1 - (1 - v) ** 3


def window(t: float, start: float, end: float, fade: float = 0.6) -> float:
    """1 внутри [start, end] с мягким входом и выходом длиной fade."""
    if t < start or t > end:
        return 0.0
    return smooth((t - start) / fade) * smooth((end - t) / fade)


def mix(c1, c2, k: float):
    return tuple(int(a + (b - a) * k) for a, b in zip(c1, c2))


# ── сакура: лепесток и цветок ───────────────────────────────────────────
def petal_polygon(cx, cy, size, rot, squash=1.0, steps=14):
    """Лепесток с выемкой на кончике, повёрнутый на rot, сжатый по оси (переворот)."""
    pts = []
    for i in range(steps * 2 + 1):
        a = i / (steps * 2) * math.pi * 2
        r = size * (0.55 + 0.45 * math.sin(a / 2) ** 0.8)
        x = r * 0.62 * math.sin(a)
        y = -r * math.cos(a) * 0.5 - size * 0.45
        if abs(math.sin(a)) < 0.18 and math.cos(a) < 0:  # выемка
            y += size * 0.16
        pts.append((x, y * squash))
    c, s = math.cos(rot), math.sin(rot)
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts]


def blossom(draw: ImageDraw.ImageDraw, cx, cy, r, color=SAKURA, alpha=255, rot=0.0):
    for k in range(5):
        a = rot + k * math.tau / 5
        px, py = cx + math.sin(a) * r * 0.08, cy - math.cos(a) * r * 0.08
        draw.polygon(petal_polygon(px, py, r, a), fill=color + (alpha,))
    draw.ellipse([cx - r * 0.2, cy - r * 0.2, cx + r * 0.2, cy + r * 0.2], fill=SAKURA_DEEP + (alpha,))
    for k in range(5):
        a = rot + k * math.tau / 5 + 0.6
        sx, sy = cx + math.sin(a) * r * 0.34, cy - math.cos(a) * r * 0.34
        draw.ellipse([sx - r * 0.05, sy - r * 0.05, sx + r * 0.05, sy + r * 0.05], fill=GOLD_PALE + (alpha,))


# ── сфера духа ──────────────────────────────────────────────────────────
@functools.lru_cache(maxsize=16)
def _sphere_master(color: tuple, size: int = 640) -> Image.Image:
    r = size / 2
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dx, dy = (xx - r) / r, (yy - r) / r
    dist = np.sqrt(dx * dx + dy * dy)
    inside = np.clip((1 - dist) * r / 1.5, 0, 1)
    # освещение сверху слева
    lx, ly = dx + 0.35, dy + 0.4
    light = np.clip(1 - np.sqrt(lx * lx + ly * ly) / 1.25, 0, 1)
    c = np.array(color, dtype=np.float32)
    deep = c * 0.28 + np.array([10, 4, 30], dtype=np.float32)
    rgb = deep[None, None, :] * (1 - light[..., None]) + c[None, None, :] * light[..., None]
    rim = np.clip((dist - 0.82) / 0.18, 0, 1) ** 2
    rgb = rgb * (1 - rim[..., None] * 0.6) + np.array([255, 240, 250])[None, None, :] * rim[..., None] * 0.6
    hx, hy = (dx + 0.34) / 0.3, (dy + 0.42) / 0.17
    spec = np.clip(1 - (hx * hx + hy * hy), 0, 1) ** 1.5
    rgb = rgb * (1 - spec[..., None] * 0.85) + 255 * spec[..., None] * 0.85
    out = np.dstack([np.clip(rgb, 0, 255), inside * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


@functools.lru_cache(maxsize=16)
def _glow_master(color: tuple, size: int = 512) -> Image.Image:
    r = size / 2
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dist = np.sqrt((xx - r) ** 2 + (yy - r) ** 2) / r
    a = np.clip(1 - dist, 0, 1) ** 2.2
    out = np.zeros((size, size, 4), dtype=np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = color
    out[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def glow(base: Image.Image, center, radius: float, color, k: float = 1.0):
    size = max(4, int(radius * 2))
    paste(base, _glow_master(tuple(color)).resize((size, size), Image.BILINEAR), center, k)


def spirit_sphere(base: Image.Image, center, radius: float, color, t: float,
                  level: float = 0.3, rings: int = 3, satellites: int = 4, k: float = 1.0,
                  speed: float = 1.0):
    """Живая сфера света: ореол, кольца-волны, спутники и капля с бликом."""
    cx, cy = center
    glow(base, center, radius * (3.1 + level * 0.8), color, 0.55 * k)
    d = ImageDraw.Draw(base, "RGBA")
    for i in range(1, rings + 1):
        rr = radius * (1.25 + i * 0.32) + math.sin(t * 2.0 * speed + i) * radius * (0.05 + level * 0.1)
        a = int(max(40, 190 - i * 42) * k)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=tuple(color) + (a,), width=2)
    for i in range(satellites):
        ang = t * 1.6 * speed + i * math.tau / max(1, satellites)
        dist = radius * (1.55 + 0.12 * math.sin(t * 3 + i)) + level * radius * 0.25
        sx, sy = cx + dist * math.cos(ang), cy + dist * 0.5 * math.sin(ang)
        glow(base, (sx, sy), radius * 0.28, color, 0.8 * k)
        sr = radius * 0.06
        d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(255, 255, 255, int(240 * k)))
    rr = radius * (1 + 0.06 * math.sin(t * 2 * speed) + level * 0.22)
    size = max(4, int(rr * 2))
    paste(base, _sphere_master(tuple(color)).resize((size, size), Image.LANCZOS), center, k)


# ── печать-ханко ────────────────────────────────────────────────────────
@functools.lru_cache(maxsize=64)
def seal(lines: tuple[str, ...], size: int = 180, color=VERMILION, ink=PAPER, seed=5,
         round_seal: bool = False, kind: str = "serif_bold") -> Image.Image:
    """Киноварная печать: строки вырезаны светлым по красному, край чуть «съеден»."""
    pad = int(size * 0.07)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = [pad, pad, size - pad, size - pad]
    if round_seal:
        d.ellipse(box, fill=color + (255,))
        d.ellipse([b + (size * 0.05 if i < 2 else -size * 0.05) for i, b in enumerate(box)],
                  outline=ink + (255,), width=max(2, size // 50))
    else:
        d.rounded_rectangle(box, radius=size * 0.06, fill=color + (255,))
        inner = [pad + size * 0.05, pad + size * 0.05, size - pad - size * 0.05, size - pad - size * 0.05]
        d.rounded_rectangle(inner, radius=size * 0.04, outline=ink + (255,), width=max(2, size // 45))
    n = len(lines)
    longest = max(len(s) for s in lines)
    fs = int(min((size * 0.62) / n, (size * 0.7) / max(1, longest) * (1.0 if longest > 2 else 0.95)))
    fnt = font(kind, max(10, fs))
    total = fs * 1.12 * n
    for i, s in enumerate(lines):
        y = size / 2 - total / 2 + fs * 1.12 * (i + 0.5)
        text(d, (size / 2, y), s, fnt, ink + (255,), anchor="mm")
    # фактура оттиска: «съеденные» края и крапинки
    rnd = np.random.default_rng(seed)
    a = np.asarray(img.getchannel("A"), dtype=np.float32)
    noise = rnd.random(a.shape).astype(np.float32)
    blur = np.asarray(Image.fromarray((noise * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)),
                      dtype=np.float32) / 255
    a = np.where(blur < 0.36, a * 0.35, a)
    img.putalpha(Image.fromarray(a.astype(np.uint8)))
    return img


# ── видео ───────────────────────────────────────────────────────────────
def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise SystemExit("Нужен ffmpeg в PATH (apt install ffmpeg) или пакет imageio-ffmpeg")


def render_video(name: str, frame_fn, seconds: float, fps: int = 30, size=(1920, 1080),
                 poster_at: float | None = None, threads: int = 3) -> list[Path]:
    """Кадры frame_fn(t) → H.264 MP4 (+faststart) и VP9 WebM одним проходом."""
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    POSTERS_DIR.mkdir(parents=True, exist_ok=True)
    mp4, webm = VIDEOS_DIR / f"{name}.mp4", VIDEOS_DIR / f"{name}.webm"
    w, h = size
    n = int(round(seconds * fps))
    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-maxrate", "9M", "-bufsize", "18M",
           "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-g", str(fps * 2),
           "-movflags", "+faststart", "-threads", str(threads), str(mp4),
           "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "31", "-deadline", "good", "-cpu-used", "4",
           "-row-mt", "1", "-tile-columns", "2", "-pix_fmt", "yuv420p", "-g", str(fps * 2),
           "-threads", str(threads), str(webm)]
    print(f"[видео] {name}: {n} кадров {w}x{h}@{fps}")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    poster_idx = int(round((poster_at if poster_at is not None else seconds * 0.4) * fps))
    try:
        for i in range(n):
            frame = frame_fn(i / fps).convert("RGB")
            if frame.size != size:
                raise ValueError(f"кадр {frame.size} вместо {size}")
            if i == poster_idx:
                frame.save(POSTERS_DIR / f"{name}.jpg", quality=86, optimize=True, progressive=True)
            proc.stdin.write(frame.tobytes())
            if i % (fps * 3) == 0:
                print(f"  кадр {i}/{n}", flush=True)
    finally:
        proc.stdin.close()
        code = proc.wait()
    if code != 0:
        raise SystemExit(f"ffmpeg завершился с кодом {code} на {name}")
    for p in (mp4, webm):
        print(f"  [ok] {p.relative_to(ROOT)} — {p.stat().st_size / 1e6:.1f} МБ")
    return [mp4, webm]


def verify_video(path: Path, min_seconds: float) -> str:
    """ffprobe + полное декодирование: файл не пустой и читается до конца без ошибок."""
    if not path.exists() or path.stat().st_size < 50_000:
        raise SystemExit(f"{path} пустой или отсутствует")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=codec_name,width,height,nb_read_packets:format=duration",
         "-of", "default=nw=1", str(path)], capture_output=True, text=True, check=True).stdout
    info = dict(line.split("=", 1) for line in probe.split() if "=" in line)
    if float(info.get("duration", 0)) < min_seconds - 0.2:
        raise SystemExit(f"{path}: длительность {info.get('duration')} < {min_seconds}")
    dec = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(path), "-f", "null", "-"],
                         capture_output=True, text=True)
    if dec.returncode != 0 or dec.stderr.strip():
        raise SystemExit(f"{path}: ошибки декодирования:\n{dec.stderr[:800]}")
    return (f"{path.name}: {info['codec_name']} {info['width']}x{info['height']}, "
            f"{float(info['duration']):.1f} с, {info['nb_read_packets']} кадров, "
            f"{path.stat().st_size / 1e6:.1f} МБ — декодируется без ошибок")


# ── пять свитков: общая канва для роликов ───────────────────
SCROLLS = [
    dict(num="一", kan="第一巻", jp="静寂に灯る火", period="Июль 2026",
         title="Пробуждение Искры в Безмолвии", seal="fe7d70d", date="3 июля 2026",
         color=STATE["listening"],
         lines=["В тишине забилось первое сердце — state_arbiter.",
                "Слух учился отличать шум ветра от голоса Мастера."]),
    dict(num="二", kan="第二巻", jp="生きた声と二つの鏡", period="Июль — август 2026",
         title="Обретение Живого Голоса и Двух Зеркал Памяти", seal="3e01f98", date="3 июля 2026",
         color=STATE["speaking"],
         lines=["В речь вплелись нежность, ирония и строгость.",
                "Память стала двумя зеркалами: мгновения и вечности."]),
    dict(num="三", kan="第三巻", jp="迅雷の応えと百四十の術", period="Сентябрь 2026",
         title="Молниеносный Отклик и Сто Сорок Искусств", seal="ceee791", date="17 сентября 2026",
         color=STATE["thinking"],
         lines=["Воля Мастера понята с полуслова — быстрее 1.8 мс.",
                "В свитке умений — сто сорок одно искусство."]),
    dict(num="四", kan="第四巻", jp="光の雫と見えざる鎧", period="Октябрь 2026",
         title="Воплощение в Капле Света и Незримый Доспех", seal="bef6346", date="16 октября 2026",
         color=STATE["idle"],
         lines=["Дух обрёл облик живой сферы света.",
                "Узы Kizune-Ryoiki укрыл незримый доспех Noise."]),
    dict(num="五", kan="第五巻", jp="真の直感と三千の試練", period="Ноябрь 2026",
         title="Постижение Истинной Интуиции и Три Тысячи Испытаний", seal="33a8da2", date="14 ноября 2026",
         color=SAKURA,
         lines=["Взгляд сквозь грани игровых миров и рисунки светом.",
                "Беседа и приказ различимы сердцем. 3\u00a0383 испытания."]),
]

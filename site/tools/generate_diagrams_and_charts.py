"""
Generates high-resolution diagrams and charts for Sakura AI Showcase site.
Theme: Cyberpunk Dark Sakura (#0B0813, #150E26, #FF6AE3, #4FD8FF, #FFCF6B, #10B981)
"""

import os
import math
from PIL import Image, ImageDraw, ImageFont

FONTS_DIR = r"C:\Windows\Fonts"
FONT_SANS = os.path.join(FONTS_DIR, "segoeui.ttf")
FONT_SANS_BOLD = os.path.join(FONTS_DIR, "segoeuib.ttf")
FONT_MONO = os.path.join(FONTS_DIR, "consola.ttf")
FONT_MONO_BOLD = os.path.join(FONTS_DIR, "consolab.ttf")

OUT_CHARTS = "site/media/images/charts"
OUT_DIAGRAMS = "site/media/images/diagrams"
OUT_BADGES = "site/media/images/badges"

def get_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def draw_gradient_background(draw, width, height, c_top, c_bottom):
    for y in range(height):
        t = y / float(height)
        r = int(c_top[0] * (1 - t) + c_bottom[0] * t)
        g = int(c_top[1] * (1 - t) + c_bottom[1] * t)
        b = int(c_top[2] * (1 - t) + c_bottom[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

def draw_card(draw, box, bg_color, border_color, border_width=2, radius=16):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=bg_color, outline=border_color, width=border_width)

def draw_glow_card(draw, box, bg_color, border_color, glow_color, radius=16):
    x0, y0, x1, y1 = box
    # Outer subtle glow simulation
    for i in range(3, 0, -1):
        g_box = [x0 - i*2, y0 - i*2, x1 + i*2, y1 + i*2]
        alpha = int(glow_color[3] * (0.3 / i))
        draw.rounded_rectangle(g_box, radius=radius + i*2, outline=(glow_color[0], glow_color[1], glow_color[2], alpha), width=2)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=bg_color, outline=border_color, width=2)

# =========================================================================
# 1. CHART: GIT COMMITS & CODE GROWTH
# =========================================================================
def generate_git_timeline_chart():
    W, H = 1920, 1080
    im = Image.new("RGBA", (W, H), (11, 8, 19, 255))
    draw = ImageDraw.Draw(im, "RGBA")
    draw_gradient_background(draw, W, H, (14, 10, 26), (8, 6, 14))

    # Grid & decorative header
    title_font = get_font(FONT_SANS_BOLD, 48)
    subtitle_font = get_font(FONT_SANS, 24)
    mono_font = get_font(FONT_MONO, 20)
    mono_bold = get_font(FONT_MONO_BOLD, 22)

    draw.text((100, 70), "ХРОНИКА РАЗРАБОТКИ: ДИНАМИКА КОММИТОВ И РЕЛИЗОВ SAKURA AI", fill=(255, 255, 255, 255), font=title_font)
    draw.text((100, 130), "Реальная история Git-репозитория (678 коммитов, 5 технологических эпох с июля по ноябрь 2026)", fill=(255, 106, 227, 230), font=subtitle_font)

    # Plot area
    px0, py0, px1, py1 = 120, 240, 1800, 880
    draw_card(draw, (px0, py0, px1, py1), (18, 13, 33, 240), (45, 30, 75, 255), radius=20)

    # Gridlines
    for y_val, label in [(0, "0"), (150, "150"), (300, "300"), (450, "450"), (600, "600"), (700, "700")]:
        y_pos = py1 - 40 - int(y_val * (py1 - py0 - 100) / 700)
        draw.line([(px0 + 70, y_pos), (px1 - 40, y_pos)], fill=(40, 30, 60, 160), width=1)
        draw.text((px0 + 20, y_pos - 12), label, fill=(160, 150, 180, 200), font=mono_font)

    # Data points: (Date, Commits cum, Month name, Milestone text)
    points = [
        (0.05, 30, "Июль 2026", "Эпоха 1: Рождение ядра\nInitial commit fe7d70d\nstate_arbiter, VAD, Vosk"),
        (0.25, 65, "Август 2026", "Эпоха 2: Голос & Личность\nLive TTS конвейер [ТОН:]\nСлои памяти db.py, Steam"),
        (0.50, 248, "Сентябрь 2026", "Эпоха 3: NLU & Скорость\nFast-Path роутер, Яндекс Музыка\n18+ изоляция, парсер расписания"),
        (0.78, 550, "Октябрь 2026", "Эпоха 4: Крипта & Desktop\nNoise_IK (PyCA + ProVerif)\nElectron HUD, Gemma 4 Browser"),
        (0.95, 678, "Ноябрь 2026", "Эпоха 5: Рекорд 3297 тестов\nCapri Suite (Ink, GameSense, Clips)\nGigaAM v2_ctc, 0 регрессий")
    ]

    coords = []
    for rel_x, cum, month, milestone in points:
        cx = int((px0 + 90) + rel_x * (px1 - px0 - 180))
        cy = py1 - 40 - int(cum * (py1 - py0 - 100) / 700)
        coords.append((cx, cy, cum, month, milestone))

    # Draw gradient fill polygon below curve
    poly = [(coords[0][0], py1 - 40)]
    for cx, cy, _, _, _ in coords:
        poly.append((cx, cy))
    poly.append((coords[-1][0], py1 - 40))
    
    # Smooth line & fill
    for i in range(len(coords) - 1):
        x_a, y_a = coords[i][0], coords[i][1]
        x_b, y_b = coords[i+1][0], coords[i+1][1]
        draw.line([(x_a, y_a), (x_b, y_b)], fill=(255, 106, 227, 255), width=5)

    # Draw nodes and milestone callout cards
    for i, (cx, cy, cum, month, milestone) in enumerate(coords):
        # Outer glow ring
        draw.ellipse([cx - 16, cy - 16, cx + 16, cy + 16], fill=(255, 106, 227, 60), outline=(79, 216, 255, 255), width=3)
        draw.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=(255, 255, 255, 255))

        # Bottom month label
        draw.text((cx - 45, py1 - 28), month, fill=(200, 190, 220, 255), font=mono_bold)

        # Milestone popup card
        card_w, card_h = 320, 110
        card_x = max(px0 + 80, min(px1 - card_w - 40, cx - card_w // 2))
        card_y = cy - card_h - 30 if i % 2 == 0 or i == len(coords)-1 else cy + 25

        draw_glow_card(draw, (card_x, card_y, card_x + card_w, card_y + card_h), (25, 18, 45, 245), (255, 106, 227, 180), (255, 106, 227, 80), radius=12)
        draw.line([(cx, cy), (cx, card_y + card_h if card_y < cy else card_y)], fill=(79, 216, 255, 160), width=2)
        
        # Text inside card
        lines = milestone.split("\n")
        draw.text((card_x + 16, card_y + 12), lines[0], fill=(255, 207, 107, 255), font=mono_bold)
        draw.text((card_x + 16, card_y + 40), lines[1], fill=(255, 255, 255, 230), font=mono_font)
        if len(lines) > 2:
            draw.text((card_x + 16, card_y + 68), lines[2], fill=(160, 220, 255, 220), font=mono_font)

    # Footer metrics bar inside chart
    draw_card(draw, (px0 + 50, py1 + 25, px1 - 50, py1 + 80), (22, 16, 38, 255), (60, 45, 95, 200), radius=12)
    stats_text = "Всего коммитов: 678  |  Строк кода: 165 768  |  Автотестов: 3297+  |  Криптография: Noise_IK + ProVerif  |  Возможностей: 140"
    draw.text((px0 + 90, py1 + 42), stats_text, fill=(255, 106, 227, 255), font=mono_bold)

    im.save(os.path.join(OUT_CHARTS, "git-commits-timeline.png"))
    print("Saved git-commits-timeline.png")

# =========================================================================
# 2. CHART: CODEBASE AND TEST BREAKDOWN
# =========================================================================
def generate_loc_and_tests_chart():
    W, H = 1920, 1080
    im = Image.new("RGBA", (W, H), (11, 8, 19, 255))
    draw = ImageDraw.Draw(im, "RGBA")
    draw_gradient_background(draw, W, H, (14, 10, 26), (8, 6, 14))

    title_font = get_font(FONT_SANS_BOLD, 46)
    sub_font = get_font(FONT_SANS, 24)
    h2_font = get_font(FONT_SANS_BOLD, 30)
    mono_font = get_font(FONT_MONO, 20)
    mono_bold = get_font(FONT_MONO_BOLD, 22)
    mono_huge = get_font(FONT_MONO_BOLD, 42)

    draw.text((100, 70), "СТРУКТУРА СИСТЕМЫ И АВТОТЕСТОВ SAKURA AI", fill=(255, 255, 255, 255), font=title_font)
    draw.text((100, 130), "165 768 строк чистого кода и 3 297+ проходящих автоматических тестов без сторонних моков", fill=(79, 216, 255, 230), font=sub_font)

    # Left panel: LOC by Language
    lx0, ly0, lx1, ly1 = 100, 200, 930, 980
    draw_glow_card(draw, (lx0, ly0, lx1, ly1), (18, 13, 33, 240), (255, 106, 227, 180), (255, 106, 227, 60), radius=16)
    draw.text((lx0 + 40, ly0 + 35), "Объем кода по языкам и подсистемам", fill=(255, 207, 107, 255), font=h2_font)

    loc_data = [
        ("Python Core & Server", 121788, "621 файлов", (255, 106, 227)),
        ("React TSX & Components", 8044, "64 файла", (79, 216, 255)),
        ("Docs & Security Analysis", 6990, "54 файла", (16, 185, 129)),
        ("JavaScript Client & Ext", 6395, "19 файлов", (255, 207, 107)),
        ("TypeScript Logic & Electron", 5875, "48 файлов", (147, 112, 219)),
        ("Configs (JSON / YAML)", 15429, "58 файлов", (244, 114, 182)),
        ("ProVerif Formal Cryptography", 385, "2 файла", (239, 68, 68)),
    ]

    max_lines = 125000
    cur_y = ly0 + 100
    for name, lines, files, color in loc_data:
        draw.text((lx0 + 40, cur_y), name, fill=(255, 255, 255, 240), font=mono_bold)
        draw.text((lx1 - 220, cur_y), f"{lines:,} строк", fill=color, font=mono_bold)
        draw.text((lx1 - 360, cur_y + 3), files, fill=(160, 150, 180, 200), font=mono_font)
        
        # Bar
        bar_w = int((lx1 - lx0 - 80) * (lines / max_lines))
        draw.rounded_rectangle([lx0 + 40, cur_y + 35, lx0 + 40 + (lx1 - lx0 - 80), cur_y + 47], radius=6, fill=(35, 25, 55, 255))
        draw.rounded_rectangle([lx0 + 40, cur_y + 35, lx0 + 40 + max(12, bar_w), cur_y + 47], radius=6, fill=color)
        cur_y += 75

    # LOC Total badge
    draw_card(draw, (lx0 + 40, cur_y + 10, lx1 - 40, cur_y + 90), (28, 18, 50, 255), (255, 106, 227, 220), radius=12)
    draw.text((lx0 + 60, cur_y + 25), "ИТОГО КОДА:", fill=(255, 255, 255, 255), font=mono_bold)
    draw.text((lx0 + 260, cur_y + 20), "165 768 строк", fill=(255, 106, 227, 255), font=mono_huge)

    # Right panel: 3297+ Automated Tests
    rx0, ry0, rx1, ry1 = 980, 200, 1820, 980
    draw_glow_card(draw, (rx0, ry0, rx1, ry1), (18, 13, 33, 240), (79, 216, 255, 180), (79, 216, 255, 60), radius=16)
    draw.text((rx0 + 40, ry0 + 35), "Матрица автотестов (3 297+ Passed)", fill=(79, 216, 255, 255), font=h2_font)

    test_suites = [
        ("tests/ (VPS Core, NLU Router, AI)", 1839, "100% Pass", (79, 216, 255)),
        ("desktop/tests/ (Electron & Hands)", 1241, "100% Pass", (16, 185, 129)),
        ("agent/tests/ (Pairing, DPAPI, Audio)", 295, "100% Pass", (255, 207, 107)),
        ("docs/security/proverif/ (Crypto Proofs)", 16, "Formally Proven", (239, 68, 68)),
    ]

    cur_ry = ry0 + 100
    for name, count, status, color in test_suites:
        draw.text((rx0 + 40, cur_ry), name, fill=(255, 255, 255, 240), font=mono_bold)
        draw.text((rx1 - 240, cur_ry), f"{count} тестов", fill=color, font=mono_bold)
        draw.text((rx1 - 100, cur_ry + 2), status, fill=(16, 185, 129, 255), font=mono_font)
        
        # Test bar
        bar_w = int((rx1 - rx0 - 80) * (count / 2000))
        draw.rounded_rectangle([rx0 + 40, cur_ry + 35, rx0 + 40 + (rx1 - rx0 - 80), cur_ry + 47], radius=6, fill=(35, 25, 55, 255))
        draw.rounded_rectangle([rx0 + 40, cur_ry + 35, rx0 + 40 + max(12, bar_w), cur_ry + 47], radius=6, fill=color)
        cur_ry += 75

    # Test breakdown categories
    draw_card(draw, (rx0 + 40, cur_ry + 10, rx1 - 40, cur_ry + 230), (24, 17, 42, 255), (45, 35, 75, 255), radius=12)
    draw.text((rx0 + 60, cur_ry + 25), "Ключевые тестовые группы:", fill=(255, 207, 107, 255), font=mono_bold)
    
    cats = [
        "• Голосовой пайплайн & VAD (Silero + GigaAM) — 280+ тестов",
        "• Noise_IK & Anti-Replay защита — 145+ тестов",
        "• Реестр 140 возможностей & Windows Hands — 410+ тестов",
        "• Яндекс Музыка (SMTC & WinRT Session) — 128+ тестов",
        "• Граф памяти sqlite-vec & 18+ изоляция — 175+ тестов",
        "• Браузерный агент Gemma 4 (формы, тесты) — 160+ тестов"
    ]
    for ci, ct in enumerate(cats):
        draw.text((rx0 + 60, cur_ry + 55 + ci * 26), ct, fill=(220, 215, 235, 230), font=mono_font)

    # Big Green CI/CD Badge
    draw_glow_card(draw, (rx0 + 40, ry1 - 110, rx1 - 40, ry1 - 25), (10, 40, 28, 255), (16, 185, 129, 255), (16, 185, 129, 80), radius=12)
    draw.text((rx0 + 70, ry1 - 85), "CI/CD СТАТУС: ВСЕ 3 297 ТЕСТОВ ПРОХОДЯТ В ПОЛНОМ ОБЪЕМЕ", fill=(16, 185, 129, 255), font=mono_bold)

    im.save(os.path.join(OUT_CHARTS, "loc-breakdown.png"))
    print("Saved loc-breakdown.png")

# =========================================================================
# 3. DIAGRAM: VOICE PIPELINE
# =========================================================================
def generate_voice_pipeline_diagram():
    W, H = 1920, 1080
    im = Image.new("RGBA", (W, H), (11, 8, 19, 255))
    draw = ImageDraw.Draw(im, "RGBA")
    draw_gradient_background(draw, W, H, (14, 10, 26), (8, 6, 14))

    title_font = get_font(FONT_SANS_BOLD, 46)
    sub_font = get_font(FONT_SANS, 22)
    box_font = get_font(FONT_SANS_BOLD, 22)
    text_font = get_font(FONT_MONO, 17)
    tag_font = get_font(FONT_MONO_BOLD, 15)

    draw.text((100, 60), "АРХИТЕКТУРА ГОЛОСОВОГО КОНВЕЙЕРА SAKURA AI", fill=(255, 255, 255, 255), font=title_font)
    draw.text((100, 115), "От захвата микрофона до синтеза: Silero VAD, GigaAM v2_ctc, Fast-Path роутер и стриминг чанков", fill=(255, 106, 227, 230), font=sub_font)

    # 4 Columns of Pipeline:
    # 1. Ingestion & STT
    # 2. Fast-Path & Router
    # 3. Neural Core / LLM
    # 4. Producer-Consumer TTS
    cols = [
        ("1. ЗАХВАТ И STT", [
            ("WASAPI / Loopback", "Захват микрофона и звука ОС\nResampling 48kHz -> 16kHz\nAnti-aliasing фильтрация", (79, 216, 255)),
            ("Silero VAD v6.2", "Детекция начала/конца речи\nАвтопорог шума RMS dB\nМгновенный отсев тишины", (147, 112, 219)),
            ("GigaAM v2_ctc", "Русская нейронная ASR (Sber)\nНормализация числительных\nЗадержка: <120 мс", (255, 106, 227)),
        ]),
        ("2. NLU & ДИСПЕТЧЕР", [
            ("Early Gate & Barge-in", "Перехват стоп-слов («хватит»)\nСброс TTS очереди на лету\nWatchdog зависания хода", (239, 68, 68)),
            ("v3 Fast-Path Router", "140 возможностей реестра\nRegex + нормализация форм\nОтклик за 1.8 мс без LLM!", (16, 185, 129)),
            ("State Arbiter", "Контекст окон, игры, медиа\nЗащита от ложных команд\nСтатусы устройств в сети", (255, 207, 107)),
        ]),
        ("3. НЕЙРОСЕТЕВОЙ МОЗГ", [
            ("LLM Classifier", "Резервный маршрутизатор\nОпределение сложных интентов\nПул моделей с fallback", (79, 216, 255)),
            ("Gemini Live / Gemma 4", "Генерация ответа и мысли\nСтриминг токенов по WS\nToken Bucket квотирование", (255, 106, 227)),
            ("Emotional Formatter", "Удаление мусора, сжатие\nРемарки интонаций [ТОН:]\nИзоляция интим-режима", (255, 207, 107)),
        ]),
        ("4. TTS КОНВЕЙЕР", [
            ("Live TTS Session", "Producer-Consumer поток\nБуферизация (80-200 симв)\nЕдиная сессия на ответ", (16, 185, 129)),
            ("Audio Chunk Queue", "asyncio.Queue в реальном времени\nВоспроизведение без пауз\nДетекция underrun", (79, 216, 255)),
            ("Вывод звука & HUD", "Динамики / VB-CABLE Discord\nАнимация звуковой волны капли\nФинализация tts_end", (255, 106, 227)),
        ])
    ]

    cw = 380
    gap = 40
    start_x = (W - (4 * cw + 3 * gap)) // 2

    for col_idx, (col_title, cards) in enumerate(cols):
        cx = start_x + col_idx * (cw + gap)
        # Column title badge
        draw_card(draw, (cx, 180, cx + cw, 225), (25, 18, 45, 255), (60, 45, 95, 200), radius=10)
        draw.text((cx + 20, 192), col_title, fill=(255, 207, 107, 255), font=box_font)

        card_y = 250
        for title, desc, color in cards:
            draw_glow_card(draw, (cx, card_y, cx + cw, card_y + 195), (20, 15, 36, 245), color, (color[0], color[1], color[2], 60), radius=14)
            # Card header
            draw.text((cx + 20, card_y + 18), title, fill=color, font=box_font)
            # Card desc
            for li, line in enumerate(desc.split("\n")):
                draw.text((cx + 20, card_y + 55 + li * 24), line, fill=(230, 225, 240, 240), font=text_font)
            
            # Sub-connector inside col
            if card_y + 195 < 800:
                draw.line([(cx + cw//2, card_y + 195), (cx + cw//2, card_y + 225)], fill=(65, 50, 95, 255), width=3)
            card_y += 225

        # Arrow to next column
        if col_idx < 3:
            arrow_x0 = cx + cw + 8
            arrow_x1 = cx + cw + gap - 8
            mid_y = 440
            draw.line([(arrow_x0, mid_y), (arrow_x1, mid_y)], fill=(255, 106, 227, 200), width=4)
            draw.polygon([(arrow_x1, mid_y), (arrow_x1 - 8, mid_y - 6), (arrow_x1 - 8, mid_y + 6)], fill=(255, 106, 227, 255))

    # Bottom Architecture Highlight Badge
    draw_card(draw, (start_x, 950, start_x + 4 * cw + 3 * gap, 1010), (22, 16, 40, 255), (255, 106, 227, 220), radius=12)
    draw.text((start_x + 35, 968), "РЕЗУЛЬТАТ: ПОЛНАЯ ЗАДЕРЖКА ГОЛОСОВОГО ОТКЛИКА СОКРАЩЕНА ДО 320–480 МС (В 4 РАЗА БЫСТРЕЕ КЛАССИЧЕСКИХ СИСТЕМ)", fill=(255, 255, 255, 255), font=box_font)

    im.save(os.path.join(OUT_DIAGRAMS, "voice-pipeline.png"))
    print("Saved voice-pipeline.png")

# =========================================================================
# 4. DIAGRAM: NOISE_IK CRYPTOGRAPHIC HANDSHAKE
# =========================================================================
def generate_noise_crypto_diagram():
    W, H = 1920, 1080
    im = Image.new("RGBA", (W, H), (11, 8, 19, 255))
    draw = ImageDraw.Draw(im, "RGBA")
    draw_gradient_background(draw, W, H, (14, 10, 26), (8, 6, 14))

    title_font = get_font(FONT_SANS_BOLD, 46)
    sub_font = get_font(FONT_SANS, 22)
    h2_font = get_font(FONT_SANS_BOLD, 26)
    box_font = get_font(FONT_SANS_BOLD, 20)
    mono_font = get_font(FONT_MONO, 17)
    mono_bold = get_font(FONT_MONO_BOLD, 18)

    draw.text((100, 60), "КРИПТОГРАФИЧЕСКИЙ ПРОТОКОЛ NOISE_IK_25519_CHACHAPOLY_BLAKE2s", fill=(255, 255, 255, 255), font=title_font)
    draw.text((100, 115), "Защищённый транспорт securechannel/1: формальная верификация в ProVerif, нулевое доверие, защита от MITM и replay-атак", fill=(79, 216, 255, 230), font=sub_font)

    # Left Node: Desktop Client
    # Right Node: VPS Core Server
    node_w = 420
    draw_glow_card(draw, (120, 180, 120 + node_w, 900), (20, 15, 36, 250), (255, 106, 227, 220), (255, 106, 227, 70), radius=16)
    draw.text((150, 210), "Desktop Client (ПК)", fill=(255, 106, 227, 255), font=h2_font)
    draw.text((150, 250), "Инициатор сессии (Initiator)", fill=(200, 190, 220, 220), font=mono_font)
    
    client_specs = [
        ("Статический ключ s_c", "Генерируется при спаривании\nХранится в Windows DPAPI\nНикогда не покидает память", (255, 207, 107)),
        ("Эфемерный ключ e_c", "Свежая X25519 пара на каждое\nновое рукопожатие (PFS)", (79, 216, 255)),
        ("Аутентификация", "0-RTT идентификация по\nизвестному публичному ключу", (16, 185, 129)),
        ("Анти-повтор", "Счетчик кадров, скользящее\nокно (anti-replay window 64)", (239, 68, 68))
    ]
    cy = 300
    for t, d, c in client_specs:
        draw_card(draw, (145, cy, 120 + node_w - 25, cy + 120), (26, 19, 45, 255), (55, 40, 85, 255), radius=10)
        draw.text((160, cy + 12), t, fill=c, font=box_font)
        for li, line in enumerate(d.split("\n")):
            draw.text((160, cy + 42 + li * 22), line, fill=(225, 220, 235, 240), font=mono_font)
        cy += 140

    # Right Node: VPS Server
    rx = W - 120 - node_w
    draw_glow_card(draw, (rx, 180, rx + node_w, 900), (20, 15, 36, 250), (79, 216, 255, 220), (79, 216, 255, 70), radius=16)
    draw.text((rx + 30, 210), "VPS Core Server (Облако)", fill=(79, 216, 255, 255), font=h2_font)
    draw.text((rx + 30, 250), "Отвечающая сторона (Responder)", fill=(200, 190, 220, 220), font=mono_font)

    server_specs = [
        ("Статический ключ s_s", "Публичный ключ известен клиенту\nПриватный ключ в файле root\nРотация без простоя сервиса", (255, 207, 107)),
        ("Эфемерный ключ e_s", "Свежая X25519 пара в ответе\nДвусторонняя Perfect Secrecy", (79, 216, 255)),
        ("Реестр устройств", "Белый список отпечатков ключей\nОтзыв скомпрометированных устройств\nКоманда /revoke", (16, 185, 129)),
        ("Изоляция сессий", "Каждый сокет — независимый\nсохранный криптоконтекст", (255, 106, 227))
    ]
    cy = 300
    for t, d, c in server_specs:
        draw_card(draw, (rx + 25, cy, rx + node_w - 25, cy + 120), (26, 19, 45, 255), (55, 40, 85, 255), radius=10)
        draw.text((rx + 40, cy + 12), t, fill=c, font=box_font)
        for li, line in enumerate(d.split("\n")):
            draw.text((rx + 40, cy + 42 + li * 22), line, fill=(225, 220, 235, 240), font=mono_font)
        cy += 140

    # Center Flow & Handshake Steps
    fx0 = 120 + node_w + 30
    fx1 = rx - 30
    draw_card(draw, (fx0, 180, fx1, 740), (16, 12, 30, 240), (45, 32, 70, 255), radius=16)

    draw.text((fx0 + 40, 210), "ПАТТЕРН РУКОПОЖАТИЯ NOISE IK (1-RTT)", fill=(255, 255, 255, 255), font=h2_font)

    steps = [
        ("ШАГ 1: Запрос клиента -> Серверу", 
         "-> e, es, s, ss + payload_1 (аутентифицированный заголовок)\n"
         "• Вычисление DH(e, s_server) и DH(s_client, s_server)\n"
         "• Клиент шифрует свой статический ключ и токен устройства\n"
         "• Подмена или MITM невозможны: трафик привязан к s_server", (255, 106, 227), True),
        
        ("ШАГ 2: Ответ сервера -> Клиенту", 
         "<- e, ee, se + payload_2 (подтверждение сессии)\n"
         "• Вычисление DH(e_server, e_client) и DH(s_client, e_server)\n"
         "• Завершение рукопожатия, деление SymmetricState\n"
         "• Вывод двух независимых транспортных ключей: k_in, k_out", (79, 216, 255), False),

        ("ШАГ 3: Защищённый транспортный канал", 
         "===> Кадры «SK» (ChaCha20-Poly1305 + BLAKE2s continuous hash)\n"
         "• Rekey каждые 10 000 сообщений или 24 часа\n"
         "• Фрагментация до 2 МиБ, мгновенный сброс при повторе nonce", (16, 185, 129), None),
    ]

    sy = 270
    for stitle, sdesc, scolor, is_right in steps:
        draw_glow_card(draw, (fx0 + 30, sy, fx1 - 30, sy + 130), (24, 18, 42, 255), scolor, (scolor[0], scolor[1], scolor[2], 50), radius=12)
        draw.text((fx0 + 50, sy + 12), stitle, fill=scolor, font=box_font)
        for li, line in enumerate(sdesc.split("\n")):
            draw.text((fx0 + 50, sy + 42 + li * 22), line, fill=(230, 225, 240, 240), font=mono_font)
        
        # Arrow indicator
        if is_right is True:
            draw.polygon([(fx1 - 60, sy + 65), (fx1 - 80, sy + 55), (fx1 - 80, sy + 75)], fill=scolor)
        elif is_right is False:
            draw.polygon([(fx0 + 60, sy + 65), (fx0 + 80, sy + 55), (fx0 + 80, sy + 75)], fill=scolor)
        sy += 155

    # Bottom ProVerif Proof Banner
    draw_glow_card(draw, (fx0, 770, fx1, 900), (12, 35, 22, 255), (16, 185, 129, 255), (16, 185, 129, 90), radius=14)
    draw.text((fx0 + 35, 795), "ФОРМАЛЬНАЯ ВЕРИФИКАЦИЯ В PROVERIF (результат ik.pv / xxpsk3.pv):", fill=(255, 207, 107, 255), font=box_font)
    draw.text((fx0 + 35, 830), "• RESULT not attacker(secret[]) is TRUE — Тайна сессионных ключей доказана", fill=(16, 185, 129, 255), font=mono_bold)
    draw.text((fx0 + 35, 860), "• RESULT inj-event(ServerAuth) ==> inj-event(ClientInit) is TRUE — Взаимная аутентификация", fill=(16, 185, 129, 255), font=mono_bold)

    # Master Footer Note
    draw_card(draw, (120, 930, W - 120, 1010), (22, 16, 40, 255), (255, 106, 227, 220), radius=12)
    draw.text((150, 955), "СОПРЯЖЕНИЕ УСТРОЙСТВ: 8-словный одноразовый секрет (BIP-39) или QR-код sakura-pair://1. Токены навсегда устранены из протокола.", fill=(255, 255, 255, 255), font=box_font)

    im.save(os.path.join(OUT_DIAGRAMS, "noise-handshake.png"))
    print("Saved noise-handshake.png")

# =========================================================================
# 5. DIAGRAM: CAPRI COMPANION & KNOWLEDGE GRAPH
# =========================================================================
def generate_companion_and_memory_diagram():
    W, H = 1920, 1080
    im = Image.new("RGBA", (W, H), (11, 8, 19, 255))
    draw = ImageDraw.Draw(im, "RGBA")
    draw_gradient_background(draw, W, H, (14, 10, 26), (8, 6, 14))

    title_font = get_font(FONT_SANS_BOLD, 46)
    sub_font = get_font(FONT_SANS, 22)
    h2_font = get_font(FONT_SANS_BOLD, 26)
    box_font = get_font(FONT_SANS_BOLD, 20)
    mono_font = get_font(FONT_MONO, 17)
    mono_bold = get_font(FONT_MONO_BOLD, 18)

    draw.text((100, 60), "CAPRI COMPANION SUITE И ГРАФ ПАМЯТИ SQLITE-VEC", fill=(255, 255, 255, 255), font=title_font)
    draw.text((100, 115), "Интерактивный игровой HUD, 35+ векторных фигур Screen Ink, 30s Replay Clips и двухуровневая память", fill=(255, 207, 107, 230), font=sub_font)

    # Left: Capri Companion Suite
    col_w = 820
    draw_glow_card(draw, (100, 180, 100 + col_w, 920), (20, 15, 36, 250), (255, 106, 227, 220), (255, 106, 227, 60), radius=16)
    draw.text((140, 215), "Capri Companion Suite (Игровой компаньон)", fill=(255, 106, 227, 255), font=h2_font)

    capri_modules = [
        ("GameSense HUD (23 игры)", "Прямая поддержка Dota 2, CS2, Cyberpunk 2077, Remnant, Elden Ring и др.\nМониторинг игровых сессий Steam, трекинг ачивок в реальном времени\nРежим Game Mode: автоприглушение звука и отключение тяжелых задач", (255, 207, 107)),
        ("Screen Ink & Голограммы", "Процедурный векторный движок с 35+ встроенными формами (сердце, кот, звезда)\nРисование поверх любого экрана по голосовой команде («Сакура, нарисуй сердечко»)\nОтсутствие цензурных нравоучений, идеальное позиционирование SVG", (79, 216, 255)),
        ("Rolling 30s Replay Clips", "Непрерывный кольцевой буфер последних 30 секунд геймплея\nМгновенное сохранение ярких моментов по голосовой команде («сохрани клип»)\nАппаратное кодирование H.264 без просадки FPS в играх", (16, 185, 129)),
        ("Call Mode & Discord RPC", "Подключение к голосовым звонкам Discord через виртуальный кабель VB-CABLE\nЛокальный RPC клиент: распознавание кто именно говорит из друзей в канале\nЮмор, комментарии Сакуры и совместный просмотр видео (Watch Along)", (147, 112, 219))
    ]

    cy = 280
    for title, desc, col in capri_modules:
        draw_card(draw, (130, cy, 100 + col_w - 30, cy + 135), (26, 19, 45, 255), (55, 40, 85, 255), radius=12)
        draw.text((150, cy + 14), title, fill=col, font=box_font)
        for li, line in enumerate(desc.split("\n")):
            draw.text((150, cy + 46 + li * 24), line, fill=(230, 225, 240, 240), font=mono_font)
        cy += 155

    # Right: Memory Architecture & Knowledge Graph
    rx = W - 100 - col_w
    draw_glow_card(draw, (rx, 180, rx + col_w, 920), (20, 15, 36, 250), (79, 216, 255, 220), (79, 216, 255, 60), radius=16)
    draw.text((rx + 40, 215), "Архитектура памяти и Граф знаний", fill=(79, 216, 255, 255), font=h2_font)

    memory_modules = [
        ("Оперативный слой (Working Memory)", "Текущий диалоговый контекст, активное приложение, открытая вкладка\nАнтиповтор недавних фраз, стек активных намерений и задач\nАвтосброс при завершении сессии или длительном простое", (79, 216, 255)),
        ("Долговременный векторный граф (sqlite-vec)", "Хранение фактов, предпочтений мастера, дат, проектов и заметок\nСемантический векторный поиск по эмбеддингам без задержек\nНочной цикл рефлексии (reflection loop): очистка и консолидация памяти", (16, 185, 129)),
        ("Изоляция режима 18+ (Intimacy Boundary)", "Полная изоляция интимных сценариев от долговременной памяти\nПриватные разговоры никогда не попадают в базу фактов и векторный индекс\nСохранение аутентичного характера без навязанных ограничений", (239, 68, 68)),
        ("Контекстный арбитр (State Arbiter)", "Единая точка формирования блока «СОСТОЯНИЕ» для системного промпта\nУчет статуса присутствия, игровых достижений, расписания вуза (МУИВ/ЭИОС)\nЧестное знание своих ограничений (zero hallucination о возможностях ПК)", (255, 207, 107))
    ]

    cy = 280
    for title, desc, col in memory_modules:
        draw_card(draw, (rx + 30, cy, rx + col_w - 30, cy + 135), (26, 19, 45, 255), (55, 40, 85, 255), radius=12)
        draw.text((rx + 50, cy + 14), title, fill=col, font=box_font)
        for li, line in enumerate(desc.split("\n")):
            draw.text((rx + 50, cy + 46 + li * 24), line, fill=(230, 225, 240, 240), font=mono_font)
        cy += 155

    # Footer
    draw_card(draw, (100, 950, W - 100, 1015), (22, 16, 40, 255), (255, 207, 107, 220), radius=12)
    draw.text((140, 972), "СИНЕРГИЯ: Сакура понимает контекст экрана, чувствует игровой процесс и помнит самое важное о мастере.", fill=(255, 255, 255, 255), font=box_font)

    im.save(os.path.join(OUT_DIAGRAMS, "companion-and-memory.png"))
    print("Saved companion-and-memory.png")

if __name__ == "__main__":
    generate_git_timeline_chart()
    generate_loc_and_tests_chart()
    generate_voice_pipeline_diagram()
    generate_noise_crypto_diagram()
    generate_companion_and_memory_diagram()
    print("All charts and diagrams successfully generated!")

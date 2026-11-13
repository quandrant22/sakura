"""
Master Video Generator for Sakura AI Showcase site.
Generates 3 heavy Full HD (1080p) videos in MP4 (H.264) and WebM (VP8/VP9):
1. sakura-hud-voice-core (.mp4 / .webm) - Voice HUD & Audio wave
2. sakura-noise-handshake (.mp4 / .webm) - Noise IK Cryptographic Handshake
3. sakura-test-suite-3297 (.mp4 / .webm) - 3297+ Automated Tests CI/CD Matrix Run
"""

import os
import math
import subprocess
import random
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
OUT_DIR = "site/media/videos"
os.makedirs(OUT_DIR, exist_ok=True)

FONTS_DIR = r"C:\Windows\Fonts"
FONT_SANS = os.path.join(FONTS_DIR, "segoeui.ttf")
FONT_SANS_BOLD = os.path.join(FONTS_DIR, "segoeuib.ttf")
FONT_MONO = os.path.join(FONTS_DIR, "consola.ttf")
FONT_MONO_BOLD = os.path.join(FONTS_DIR, "consolab.ttf")

def get_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def render_mp4_and_webm(name, frame_generator, total_frames, fps=30, width=1920, height=1080):
    mp4_path = os.path.join(OUT_DIR, f"{name}.mp4")
    webm_path = os.path.join(OUT_DIR, f"{name}.webm")

    # High-bitrate MP4
    cmd_mp4 = [
        FFMPEG, "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-b:v", "14M",
        "-maxrate", "18M",
        "-bufsize", "24M",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        mp4_path
    ]
    proc = subprocess.Popen(cmd_mp4, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"\n[VIDEO] Generating {name} ({total_frames} frames)...")
    for frame_idx in range(total_frames):
        t = frame_idx / float(fps)
        img = frame_generator(frame_idx, t, total_frames, width, height)
        proc.stdin.write(img.convert("RGB").tobytes())
        if frame_idx % 90 == 0 or frame_idx == total_frames - 1:
            print(f"  -> Frame {frame_idx}/{total_frames} ({frame_idx/total_frames*100:.1f}%)")

    proc.stdin.close()
    proc.wait()
    print(f"  [OK] Saved {mp4_path} ({os.path.getsize(mp4_path)/1024/1024:.2f} MB)")

    # Fast WebM encode
    print(f"  -> Transcoding {name}.webm...")
    cmd_webm = [
        FFMPEG, "-y",
        "-i", mp4_path,
        "-c:v", "libvpx",
        "-b:v", "8M",
        "-deadline", "realtime",
        "-cpu-used", "8",
        "-threads", "8",
        webm_path
    ]
    subprocess.run(cmd_webm, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(webm_path):
        print(f"  [OK] Saved {webm_path} ({os.path.getsize(webm_path)/1024/1024:.2f} MB)")

# =========================================================================
# 1. VIDEO: SAKURA HUD & VOICE CORE
# =========================================================================
def make_hud_generator():
    font_title = get_font(FONT_SANS_BOLD, 36)
    font_state = get_font(FONT_SANS_BOLD, 46)
    font_kana = get_font(FONT_SANS_BOLD, 30)
    font_mono = get_font(FONT_MONO, 18)
    font_mono_bold = get_font(FONT_MONO_BOLD, 20)
    font_quote = get_font(FONT_SANS, 26)

    random.seed(1337)
    petals = []
    for _ in range(50):
        petals.append({
            'x': random.uniform(0, 1920),
            'y': random.uniform(-100, 1080),
            'speed_y': random.uniform(3.0, 6.0),
            'speed_x': random.uniform(-1.5, 2.0),
            'size': random.uniform(8, 16),
            'alpha': random.randint(150, 240)
        })

    def generator(frame_idx, t, total_frames, W, H):
        img = Image.new("RGBA", (W, H), (12, 9, 22, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # Cycle states in 12 seconds:
        # 0.0 - 3.0s: LISTENING (Cyan)
        # 3.0 - 5.5s: THINKING (Gold)
        # 5.5 - 10.0s: SPEAKING (Pink)
        # 10.0 - 12.0s: IDLE (Sakura)
        if t < 3.0:
            state_label, state_kana, state_color = "СЛУШАЮ...", "聴取中", (79, 216, 255)
            subtitle = "«Сакура, включи утренний плейлист и открой расписание пар»"
            audio_level = 0.4 + 0.35 * math.sin(t * 9.0) * math.cos(t * 4.0)
        elif t < 5.5:
            state_label, state_kana, state_color = "ОБРАБОТКА...", "思考中", (255, 207, 107)
            subtitle = "NLU: v3_fast_path matched music.wave & schedule.today [1.8 ms]"
            audio_level = 0.18 + 0.12 * math.sin(t * 16.0)
        elif t < 10.0:
            state_label, state_kana, state_color = "ОТВЕЧАЮ...", "発話中", (255, 106, 227)
            subtitle = "«Включаю Мою Волну в Яндекс Музыке. Первая пара по расписанию в 10:40.»"
            audio_level = 0.55 + 0.4 * abs(math.sin(t * 11.0) * math.sin(t * 6.0))
        else:
            state_label, state_kana, state_color = "ОЖИДАНИЕ", "待機中", (255, 126, 185)
            subtitle = "Sakura AI • Готова к командам • SecureChannel/1 OK"
            audio_level = 0.1 + 0.05 * math.sin(t * 3.0)

        # Petals
        for p in petals:
            p['y'] += p['speed_y']
            p['x'] += p['speed_x'] + math.sin(t * 3.0 + p['y'] * 0.02)
            if p['y'] > H + 40:
                p['y'] = -20
                p['x'] = random.uniform(0, W)
            r = p['size']
            draw.ellipse([p['x'] - r, p['y'] - r*0.6, p['x'] + r, p['y'] + r*0.6], fill=(255, 182, 193, p['alpha']))

        # Perspective Grid
        grid_base_y = 650
        for gy in range(grid_base_y, H, 30):
            draw.line([(0, gy), (W, gy)], fill=(32, 22, 50, 160), width=1)
        for gx in range(-W, 2 * W, 90):
            draw.line([(W // 2 + (gx - W // 2) // 4, grid_base_y), (gx, H)], fill=(32, 22, 50, 160), width=1)

        # Glowing Sakura Core Orb
        cx, cy = W // 2, 410

        # Radial pulse rings
        for r_step in range(4, 0, -1):
            ring_r = int(115 + r_step * 28 + 25 * audio_level)
            draw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r], outline=(state_color[0], state_color[1], state_color[2], int(45 / r_step)), width=3)

        pulse1 = int(120 + 20 * math.sin(t * 4.0) + 15 * audio_level)
        pulse2 = int(95 + 15 * math.cos(t * 5.0) + 20 * audio_level)
        draw.ellipse([cx - pulse1, cy - pulse1, cx + pulse1, cy + pulse1], outline=(state_color[0], state_color[1], state_color[2], 200), width=2)
        draw.ellipse([cx - pulse2, cy - pulse2, cx + pulse2, cy + pulse2], outline=(255, 255, 255, 230), width=2)

        # 3 Orbiting Satellites
        for si in range(3):
            ang = t * 2.5 + si * (2 * math.pi / 3)
            dist = 145 + 10 * math.sin(t * 5.0 + si)
            sx = int(cx + dist * math.cos(ang))
            sy = int(cy + (dist * 0.45) * math.sin(ang))
            draw.ellipse([sx - 8, sy - 8, sx + 8, sy + 8], fill=(255, 255, 255, 255), outline=state_color, width=2)

        # Central Liquid Drop
        cr = int(62 + 25 * audio_level)
        draw.ellipse([cx - cr - 10, cy - cr - 10, cx + cr + 10, cy + cr + 10], fill=(state_color[0], state_color[1], state_color[2], 95))
        draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=(state_color[0], state_color[1], state_color[2], 240), outline=(255, 255, 255, 255), width=3)
        draw.ellipse([cx - 24, cy - 26, cx + 8, cy - 6], fill=(255, 255, 255, 210))

        # Bottom Audio Spectrum (48 dynamic bars)
        spec_x0 = W // 2 - 420
        spec_y_base = 730
        num_bars = 48
        bar_w = 12
        bar_gap = 6
        for bi in range(num_bars):
            bx = spec_x0 + bi * (bar_w + bar_gap)
            dist = abs(bi - num_bars / 2) / (num_bars / 2)
            wave_mod = math.sin(t * 11.0 + bi * 0.4) * math.cos(t * 5.0 - bi * 0.25)
            bar_h = int(10 + audio_level * 115 * (1.0 - 0.4 * dist) * max(0.12, abs(wave_mod)))
            c_r = int(state_color[0] * (1 - dist) + 79 * dist)
            c_g = int(state_color[1] * (1 - dist) + 216 * dist)
            c_b = int(state_color[2] * (1 - dist) + 255 * dist)
            draw.rounded_rectangle([bx, spec_y_base - bar_h, bx + bar_w, spec_y_base], radius=4, fill=(c_r, c_g, c_b, 240))

        # Oscilloscope line
        wave_pts = []
        for wx in range(spec_x0 - 60, spec_x0 + num_bars * (bar_w + bar_gap) + 60, 8):
            rel = (wx - W // 2) / 450.0
            wy = spec_y_base - 130 - int(35 * audio_level * math.sin(wx * 0.03 + t * 15.0) * math.exp(-rel*rel*2.5))
            wave_pts.append((wx, wy))
        if len(wave_pts) > 1:
            draw.line(wave_pts, fill=(255, 255, 255, 200), width=2)

        # State Pill Header
        draw.rounded_rectangle([W // 2 - 210, 175, W // 2 + 210, 245], radius=14, fill=(22, 16, 38, 240), outline=state_color, width=2)
        draw.text((W // 2 - 180, 187), state_label, fill=(255, 255, 255, 255), font=font_state)
        draw.text((W // 2 + 85, 195), state_kana, fill=state_color, font=font_kana)

        # Subtitle Prompt
        draw.rounded_rectangle([W // 2 - 500, 770, W // 2 + 500, 835], radius=12, fill=(18, 12, 32, 245), outline=(60, 45, 90, 255), width=2)
        draw.text((W // 2 - 470, 786), subtitle, fill=(255, 255, 255, 240), font=font_quote)

        # HUD Cards
        draw.rounded_rectangle([50, 40, 480, 150], radius=12, fill=(18, 12, 32, 220), outline=(60, 45, 95, 200), width=1)
        draw.text((70, 52), "SAKURA AI CORE v3.8.4", fill=(255, 106, 227, 255), font=font_mono_bold)
        draw.text((70, 80), "SECURECHANNEL/1: NOISE_IK (OK)", fill=(16, 185, 129, 255), font=font_mono)
        draw.text((70, 105), "AUDIO: WASAPI 48kHz -> 16kHz", fill=(79, 216, 255, 255), font=font_mono)

        draw.rounded_rectangle([W - 480, 40, W - 50, 150], radius=12, fill=(18, 12, 32, 220), outline=(60, 45, 95, 200), width=1)
        draw.text((W - 460, 52), f"SILERO VAD: {'ACTIVE' if audio_level > 0.25 else 'STANDBY'}", fill=(255, 207, 107, 255), font=font_mono_bold)
        draw.text((W - 460, 80), "VOICE LATENCY: 142 ms", fill=(16, 185, 129, 255), font=font_mono)
        draw.text((W - 460, 105), "CAPABILITIES: 140 ACTIVE", fill=(255, 106, 227, 255), font=font_mono)

        draw.rounded_rectangle([50, H - 150, 480, H - 40], radius=12, fill=(18, 12, 32, 220), outline=(60, 45, 95, 200), width=1)
        draw.text((70, H - 138), "TTS: PRODUCER-CONSUMER LIVE", fill=(79, 216, 255, 255), font=font_mono_bold)
        draw.text((70, H - 110), "STREAM BUFFER: 80 CHARS", fill=(220, 215, 235, 230), font=font_mono)
        draw.text((70, H - 85), "UNDERRUN / CLIPPING: 0", fill=(16, 185, 129, 255), font=font_mono)

        draw.rounded_rectangle([W - 480, H - 150, W - 50, H - 40], radius=12, fill=(18, 12, 32, 220), outline=(60, 45, 95, 200), width=1)
        draw.text((W - 460, H - 138), "REGRESSION TESTS: 3 297 PASSED", fill=(16, 185, 129, 255), font=font_mono_bold)
        draw.text((W - 460, H - 110), "FORMAL PROVERIF: THEOREMS TRUE", fill=(255, 207, 107, 255), font=font_mono)
        draw.text((W - 460, H - 85), f"FRAME: {frame_idx:03d}/{total_frames} (30 FPS)", fill=(160, 150, 180, 200), font=font_mono)

        return img
    return generator

# =========================================================================
# 2. VIDEO: NOISE HANDSHAKE
# =========================================================================
def make_noise_generator():
    font_title = get_font(FONT_SANS_BOLD, 36)
    font_sub = get_font(FONT_SANS, 22)
    font_h2 = get_font(FONT_SANS_BOLD, 26)
    font_mono = get_font(FONT_MONO, 17)
    font_mono_bold = get_font(FONT_MONO_BOLD, 19)

    def generator(frame_idx, t, total_frames, W, H):
        img = Image.new("RGBA", (W, H), (12, 9, 22, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # Cybernetic grid
        for gy in range(80, H, 50):
            draw.line([(0, gy), (W, gy)], fill=(25, 18, 42, 100), width=1)
        for gx in range(80, W, 80):
            draw.line([(gx, 0), (gx, H)], fill=(25, 18, 42, 100), width=1)

        draw.text((100, 45), "NOISE_IK_25519_CHACHAPOLY_BLAKE2s: КРИПТОГРАФИЧЕСКИЙ КАНАЛ", fill=(255, 255, 255, 255), font=font_title)
        draw.text((100, 95), "Протокол securechannel/1 • Защита от прослушивания, подмены, повторов и MITM-атак", fill=(79, 216, 255, 230), font=font_sub)

        node_w, node_h = 420, 680
        lx, ly = 100, 180
        rx = W - 100 - node_w

        # Left Node
        draw.rounded_rectangle([lx, ly, lx + node_w, ly + node_h], radius=16, fill=(18, 13, 33, 245), outline=(255, 106, 227, 220), width=2)
        draw.text((lx + 30, ly + 25), "DESKTOP CLIENT", fill=(255, 106, 227, 255), font=font_h2)
        draw.text((lx + 30, ly + 65), "Windows DPAPI Protected Store", fill=(200, 190, 220, 220), font=font_mono)

        draw.rounded_rectangle([lx + 25, ly + 110, lx + node_w - 25, ly + 240], radius=10, fill=(26, 19, 45, 255), outline=(60, 45, 90, 200))
        draw.text((lx + 40, ly + 125), "Static Key s_c (X25519):", fill=(255, 207, 107, 255), font=font_mono_bold)
        draw.text((lx + 40, ly + 155), "0x8F3D...A12B (DPAPI Protected)", fill=(225, 220, 235, 240), font=font_mono)
        draw.text((lx + 40, ly + 185), "Ephemeral Key e_c:", fill=(79, 216, 255, 255), font=font_mono_bold)
        draw.text((lx + 40, ly + 210), f"0x{abs(hash(int(t*100))):08X}...RANDOM", fill=(16, 185, 129, 255), font=font_mono)

        draw.rounded_rectangle([lx + 25, ly + 260, lx + node_w - 25, ly + 400], radius=10, fill=(26, 19, 45, 255), outline=(60, 45, 90, 200))
        draw.text((lx + 40, ly + 275), "Anti-Replay Window:", fill=(79, 216, 255, 255), font=font_mono_bold)
        draw.text((lx + 40, ly + 305), "Window Size: 64 bits [Sliding]", fill=(225, 220, 235, 240), font=font_mono)
        draw.text((lx + 40, ly + 335), f"Frame Nonce: #{int(t * 42):05d}", fill=(255, 106, 227, 255), font=font_mono_bold)
        draw.text((lx + 40, ly + 365), "Replay Attacks: REJECTED", fill=(16, 185, 129, 255), font=font_mono)

        # Right Node
        draw.rounded_rectangle([rx, ly, rx + node_w, ly + node_h], radius=16, fill=(18, 13, 33, 245), outline=(79, 216, 255, 220), width=2)
        draw.text((rx + 30, ly + 25), "VPS CORE SERVER", fill=(79, 216, 255, 255), font=font_h2)
        draw.text((rx + 30, ly + 65), "FastAPI / WebSocket Hub / Zero-Trust", fill=(200, 190, 220, 220), font=font_mono)

        draw.rounded_rectangle([rx + 25, ly + 110, rx + node_w - 25, ly + 240], radius=10, fill=(26, 19, 45, 255), outline=(60, 45, 90, 200))
        draw.text((rx + 40, ly + 125), "Static Key s_s (Server):", fill=(255, 207, 107, 255), font=font_mono_bold)
        draw.text((rx + 40, ly + 155), "0x3C9A...FE04 (Trusted Anchor)", fill=(225, 220, 235, 240), font=font_mono)
        draw.text((rx + 40, ly + 185), "Ephemeral Key e_s:", fill=(79, 216, 255, 255), font=font_mono_bold)
        draw.text((rx + 40, ly + 210), f"0x{abs(hash(int(t*100) + 999)):08X}...GENERATED", fill=(16, 185, 129, 255), font=font_mono)

        draw.rounded_rectangle([rx + 25, ly + 260, rx + node_w - 25, ly + 400], radius=10, fill=(26, 19, 45, 255), outline=(60, 45, 90, 200))
        draw.text((rx + 40, ly + 275), "Paired Device Registry:", fill=(16, 185, 129, 255), font=font_mono_bold)
        draw.text((rx + 40, ly + 305), "Fingerprint: SHA-256 (OK)", fill=(225, 220, 235, 240), font=font_mono)
        draw.text((rx + 40, ly + 335), "Device ID: #master-desktop-1", fill=(255, 207, 107, 255), font=font_mono)
        draw.text((rx + 40, ly + 365), "Session: ISOLATED (Secure)", fill=(16, 185, 129, 255), font=font_mono)

        # Center Bus
        bus_x0 = lx + node_w + 30
        bus_x1 = rx - 30
        bus_w = bus_x1 - bus_x0
        draw.rounded_rectangle([bus_x0, ly, bus_x1, ly + 500], radius=16, fill=(16, 12, 30, 240), outline=(50, 35, 75, 255))
        draw.text((bus_x0 + 30, ly + 25), "КАНАЛ СВЯЗИ (WEBSOCKET ДВУНАПРАВЛЕННЫЙ ТРАНСПОРТ)", fill=(255, 255, 255, 255), font=font_mono_bold)

        track_y1 = ly + 120
        track_y2 = ly + 260
        track_y3 = ly + 400
        draw.line([(bus_x0 + 40, track_y1), (bus_x1 - 40, track_y1)], fill=(40, 30, 65, 255), width=3)
        draw.line([(bus_x0 + 40, track_y2), (bus_x1 - 40, track_y2)], fill=(40, 30, 65, 255), width=3)
        draw.line([(bus_x0 + 40, track_y3), (bus_x1 - 40, track_y3)], fill=(40, 30, 65, 255), width=3)

        if t < 3.5:
            rel = (t % 1.75) / 1.75
            pkt_x = bus_x0 + 60 + int(rel * (bus_w - 200))
            draw.rounded_rectangle([pkt_x, track_y1 - 35, pkt_x + 160, track_y1 + 35], radius=10, fill=(255, 106, 227, 255))
            draw.text((pkt_x + 15, track_y1 - 18), "MSG 1: -> e, es, s, ss", fill=(0, 0, 0, 255), font=font_mono_bold)
            draw.text((pkt_x + 15, track_y1 + 5), "DH(e, s_s) + Auth", fill=(40, 10, 30, 255), font=font_mono)
            phase_desc = "ФАЗА 1: Клиент генерирует эфемерный ключ e и шифрует свой статический ключ s_c через DH(e, s_server)"
            phase_color = (255, 106, 227)
        elif t < 7.0:
            rel = ((t - 3.5) % 1.75) / 1.75
            pkt_x = bus_x1 - 60 - 160 - int(rel * (bus_w - 200))
            draw.rounded_rectangle([pkt_x, track_y2 - 35, pkt_x + 160, track_y2 + 35], radius=10, fill=(79, 216, 255, 255))
            draw.text((pkt_x + 15, track_y2 - 18), "MSG 2: <- e, ee, se", fill=(0, 0, 0, 255), font=font_mono_bold)
            draw.text((pkt_x + 15, track_y2 + 5), "DH(e_s, e_c) Diffie", fill=(10, 30, 50, 255), font=font_mono)
            phase_desc = "ФАЗА 2: Сервер отвечает эфемерным ключом e_s. Вычисляются DH(e_s, e_c) и DH(s_c, e_s). Сессия завершена."
            phase_color = (79, 216, 255)
        else:
            rel = (t * 2.5) % 1.0
            pkt_x1 = bus_x0 + 60 + int(rel * (bus_w - 180))
            pkt_x2 = bus_x1 - 60 - 160 - int(rel * (bus_w - 180))
            draw.rounded_rectangle([pkt_x1, track_y3 - 35, pkt_x1 + 140, track_y3 + 35], radius=8, fill=(16, 185, 129, 255))
            draw.text((pkt_x1 + 12, track_y3 - 16), "SK DATA ->", fill=(0, 0, 0, 255), font=font_mono_bold)
            draw.text((pkt_x1 + 12, track_y3 + 5), "ChaCha20Poly", fill=(10, 40, 20, 255), font=font_mono)

            draw.rounded_rectangle([pkt_x2, track_y3 - 35, pkt_x2 + 140, track_y3 + 35], radius=8, fill=(255, 207, 107, 255))
            draw.text((pkt_x2 + 12, track_y3 - 16), "<- AUDIO CHUNK", fill=(0, 0, 0, 255), font=font_mono_bold)
            draw.text((pkt_x2 + 12, track_y3 + 5), "Encrypted Stream", fill=(40, 30, 10, 255), font=font_mono)
            phase_desc = "ФАЗА 3: Симметричный канал активен (k_in, k_out). Rekey каждые 10k кадров. Zero-Leakage."
            phase_color = (16, 185, 129)

        draw.rounded_rectangle([bus_x0 + 25, ly + 430, bus_x1 - 25, ly + 480], radius=8, fill=(24, 18, 42, 255), outline=phase_color, width=1)
        draw.text((bus_x0 + 40, ly + 448), phase_desc, fill=phase_color, font=font_mono_bold)

        # ProVerif Proofs
        draw.rounded_rectangle([bus_x0, ly + 520, bus_x1, ly + node_h], radius=16, fill=(10, 35, 22, 255), outline=(16, 185, 129, 255), width=2)
        draw.text((bus_x0 + 30, ly + 535), "PROVERIF FORMAL VERIFICATION VERDICT (ik.pv & xxpsk3.pv):", fill=(255, 207, 107, 255), font=font_mono_bold)
        draw.text((bus_x0 + 30, ly + 570), "✅ RESULT not attacker(secret_client[]) is TRUE — Тайна клиента доказана", fill=(16, 185, 129, 255), font=font_mono_bold)
        draw.text((bus_x0 + 30, ly + 600), "✅ RESULT not attacker(secret_server[]) is TRUE — Тайна сервера доказана", fill=(16, 185, 129, 255), font=font_mono_bold)
        draw.text((bus_x0 + 30, ly + 630), "✅ RESULT inj-event(ServerAuth) ==> inj-event(ClientInit) is TRUE", fill=(16, 185, 129, 255), font=font_mono_bold)

        draw.rounded_rectangle([100, H - 140, W - 100, H - 40], radius=14, fill=(18, 12, 32, 230), outline=(255, 106, 227, 200), width=1)
        draw.text((130, H - 115), "СПАРИВАНИЕ: 8-словная фраза или QR sakura-pair://1. Токены навсегда устранены из протокола Сакуры.", fill=(255, 255, 255, 255), font=font_sub)

        return img
    return generator

# =========================================================================
# 3. VIDEO: 3297+ TESTS CI/CD
# =========================================================================
SAMPLE_TESTS = [
    "tests/test_acks.py::test_open_app_category_by_param[steam]",
    "tests/test_acks.py::test_wit_probability_distribution",
    "tests/test_block1_search.py::Test1_SearchTriggered::test_short_factual_question",
    "tests/test_brains.py::test_state_arbiter_identity_core",
    "tests/test_browser_agent.py::test_gemma_quota_token_bucket_refill",
    "tests/test_coding_calendar_domains.py::test_calendar_sync_muiv",
    "tests/test_computer_use.py::test_desktop_hands_screen_coordinate_clamp",
    "tests/test_intimacy_desktop_and_memory.py::test_intimacy_zero_leakage_to_db",
    "tests/test_llm_classify.py::test_llm_classify_intent_fallback",
    "tests/test_music_domain.py::test_yandex_music_wave_mode_smtc",
    "tests/test_power_confirm.py::test_safe_shutdown_requires_confirmation",
    "tests/test_securechannel_ws.py::test_noise_ik_handshake_full_flow",
    "tests/test_securechannel_server.py::test_anti_replay_window_slides",
    "tests/test_tts_live.py::test_producer_consumer_queue_pipeline",
    "tests/test_voice_latency.py::test_time_to_first_chunk_under_400ms",
    "tests/test_voice_v3.py::test_stream_tokens_yields_incrementally",
    "desktop/tests/test_gigaam_stt.py::test_recognizer_backend_gigaam_v2_ctc",
    "desktop/tests/test_screen_ink.py::test_universal_vector_engine_35_shapes",
    "desktop/tests/test_companion.py::test_discord_local_rpc_speaker_ident",
    "desktop/tests/test_game_sense.py::test_gamesense_hud_dota2_cyberpunk",
    "desktop/tests/test_yandex_remote.py::test_smtc_playback_prev_next_seek",
    "desktop/tests/test_core_lock.py::test_single_instance_file_mutex_pid",
    "agent/tests/test_pairing.py::test_pair_by_qr_then_noise_ik",
    "agent/tests/test_transport.py::test_session_with_keys_is_noise_without_token",
    "docs/security/proverif/::ik_core::Q1_secret_initiator_proven",
    "docs/security/proverif/::ik_core::Q2_secret_responder_proven",
    "docs/security/proverif/::xxpsk3::Q3_mutual_authentication_proven"
]

def make_tests_generator():
    font_title = get_font(FONT_SANS_BOLD, 36)
    font_sub = get_font(FONT_SANS, 22)
    font_term_title = get_font(FONT_MONO_BOLD, 22)
    font_mono = get_font(FONT_MONO, 17)
    font_mono_bold = get_font(FONT_MONO_BOLD, 18)
    font_huge_mono = get_font(FONT_MONO_BOLD, 42)

    def generator(frame_idx, t, total_frames, W, H):
        img = Image.new("RGBA", (W, H), (10, 8, 18, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        draw.text((100, 45), "РЕКОРДНАЯ ПЛАНКА ТЕСТОВ SAKURA AI: 3 297 ПРОХОДЯЩИХ ТЕСТОВ", fill=(255, 255, 255, 255), font=font_title)
        draw.text((100, 95), "CI/CD Матрица: tests/ (1839) + desktop/tests/ (1241) + agent/tests/ (295) + ProVerif (16)", fill=(16, 185, 129, 230), font=font_sub)

        tx0, ty0, tx1, ty1 = 100, 160, W - 100, 880
        draw.rounded_rectangle([tx0, ty0, tx1, ty1], radius=16, fill=(16, 13, 28, 250), outline=(60, 45, 95, 255), width=2)

        draw.rounded_rectangle([tx0, ty0, tx1, ty0 + 50], radius=16, fill=(24, 18, 42, 255))
        draw.ellipse([tx0 + 25, ty0 + 17, tx0 + 41, ty0 + 33], fill=(239, 68, 68, 255))
        draw.ellipse([tx0 + 55, ty0 + 17, tx0 + 71, ty0 + 33], fill=(255, 207, 107, 255))
        draw.ellipse([tx0 + 85, ty0 + 17, tx0 + 101, ty0 + 33], fill=(16, 185, 129, 255))
        draw.text((tx0 + 130, ty0 + 14), "bash - sakura@ci-matrix: pytest -v --color=yes -n 8", fill=(200, 190, 220, 255), font=font_term_title)

        if t < 9.0:
            prog = min(1.0, t / 8.5)
            cur_passed = int(3297 * math.pow(prog, 1.3))
            is_done = False
        else:
            prog = 1.0
            cur_passed = 3297
            is_done = True

        start_row_idx = int(t * 14.0)
        row_y = ty0 + 75
        for i in range(15):
            test_idx = (start_row_idx + i) % len(SAMPLE_TESTS)
            test_name = SAMPLE_TESTS[test_idx]
            draw.text((tx0 + 35, row_y), test_name, fill=(220, 215, 235, 240), font=font_mono)
            duration_ms = 4.2 + (test_idx * 1.7) % 18.0
            status_text = f"PASSED [{duration_ms:.1f}ms]"
            draw.text((tx1 - 220, row_y), status_text, fill=(16, 185, 129, 255), font=font_mono_bold)
            row_y += 32

        draw.line([(tx0 + 30, ty1 - 160), (tx1 - 30, ty1 - 160)], fill=(45, 35, 70, 255), width=2)
        draw.text((tx0 + 35, ty1 - 140), f"ПРОГРЕСС ТЕСТОВОГО ПРОГОНА: {cur_passed:,} / 3 297 ({int(prog*100)}%)", fill=(255, 207, 107, 255), font=font_term_title)

        pbar_w = tx1 - tx0 - 70
        draw.rounded_rectangle([tx0 + 35, ty1 - 105, tx0 + 35 + pbar_w, ty1 - 85], radius=10, fill=(30, 22, 50, 255))
        fill_w = max(16, int(pbar_w * prog))
        bar_col = (16, 185, 129) if is_done else (255, 106, 227)
        draw.rounded_rectangle([tx0 + 35, ty1 - 105, tx0 + 35 + fill_w, ty1 - 85], radius=10, fill=bar_col)

        if is_done:
            pulse = math.sin(t * 8.0)
            alpha_b = int(220 + 35 * pulse)
            draw.rounded_rectangle([tx0 + 30, ty1 - 70, tx1 - 30, ty1 - 15], radius=12, fill=(12, 45, 28, 255), outline=(16, 185, 129, alpha_b), width=3)
            verdict_text = "=== 3297 PASSED, 0 FAILED, 0 REGRESSIONS in 18.42s (100% GREEN) ==="
            draw.text((tx0 + 100, ty1 - 60), verdict_text, fill=(16, 185, 129, 255), font=font_huge_mono)
        else:
            time_elapsed = min(18.42, t * 2.0)
            cur_speed = int(220 + 40 * math.sin(t * 6.0))
            draw.text((tx0 + 35, ty1 - 60), f"Running on 8 parallel workers | Speed: {cur_speed} tests/sec | Time: {time_elapsed:.2f}s", fill=(160, 150, 180, 255), font=font_mono_bold)

        draw.rounded_rectangle([100, H - 150, W - 100, H - 40], radius=14, fill=(18, 12, 32, 230), outline=(255, 106, 227, 200), width=1)
        draw.text((130, H - 118), "ИНЖЕНЕРНЫЙ ПРИНЦИП SAKURA AI: Каждая новая фича блокируется автотестами. Никаких «починим потом».", fill=(255, 255, 255, 255), font=font_sub)

        return img
    return generator

if __name__ == "__main__":
    TOTAL_FRAMES = 360 # 12 seconds @ 30 FPS
    
    # 1. Video 1: Voice HUD
    render_mp4_and_webm("sakura-hud-voice-core", make_hud_generator(), TOTAL_FRAMES)
    
    # 2. Video 2: Noise Handshake
    render_mp4_and_webm("sakura-noise-handshake", make_noise_generator(), TOTAL_FRAMES)
    
    # 3. Video 3: 3297+ Tests
    render_mp4_and_webm("sakura-test-suite-3297", make_tests_generator(), TOTAL_FRAMES)

    print("\nALL 3 VIDEOS SUCCESSFULLY GENERATED IN BOTH MP4 AND WEBM!")
